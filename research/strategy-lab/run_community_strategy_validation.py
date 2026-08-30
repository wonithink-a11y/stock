"""Community/GitHub-based crypto chart strategies 1-6 validation runner.

Reuses the Crypto Strategy Lab infrastructure (engine.execution CostModel /
build_order / simulate_trade, engine.portfolio Portfolio, engine.metrics,
60/15/25 TRAIN/VALID/TEST split) without modifying any existing file.

New code here (not engine edits):
  - 6 new strategy modules under strategies/crypto/* (bb_squeeze_v1,
    bb_squeeze_vol_v1, bb_breakout_trend_v1, rsi2_mr_v1, supertrend_macd_v1,
    price_action_v1)
  - multi-timeframe daily->lower-TF alignment that is leak-free by construction
    (a daily candle becomes usable only AFTER that daily candle has closed;
    see inject_daily_trend)
  - a dynamic exit simulator for the RSI(2) mean-reversion strategy (S4),
    since the engine's static STOP/TARGET model cannot express an
    indicator-based exit; it reuses the exact same cost/slippage/fill
    conventions as engine.simulate_trade.

Conventions (all matched to the existing lab):
  - universe: 7 coins (KRW-BTC/ETH/SOL/XRP/ADA/DOGE/DOT)
  - cost: 5 bps entry + 5 bps exit + 5 bps slippage (run_crypto_backtest.py
    default); the sensitivity sweep scales these bps by a multiplier
  - portfolio: equal weight, max 5 concurrent positions, tie-break
    ticker_ascending, same-day cash reuse banned (engine Portfolio)
  - capital 10B KRW so every coin is buyable under the engine's integer-share
    sizing; percentage metrics (CAGR/Sharpe/WinRate) are capital-invariant
  - split: 60/15/25 by session time
  - entry: signal confirmed at bar close -> next session open (engine
    next_session); no lookahead
  - indicator features are computed once over FULL bars per symbol and sliced
    to each period, so every period retains real warmup history
"""
import bisect
import importlib.util
import json
import os
import sys
import warnings
warnings.filterwarnings("ignore")
from collections import defaultdict, OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from engine.execution.executor import CostModel, build_order, simulate_trade  # noqa: E402
from engine.execution.contracts import Fill  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.metrics import metrics as M  # noqa: E402

DATA_DIR = REPO / "data" / "crypto"
OUT_DIR = REPO / "findings" / "crypto-community-strategies"
FINDINGS_MD = REPO / "findings" / "crypto-community-strategies-1-6-2026-08.md"

UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA",
            "KRW-DOGE", "KRW-DOT"]
BASE_ENTRY, BASE_EXIT, BASE_SLIP = 5.0, 5.0, 5.0
INITIAL_CAPITAL = 10_000_000_000.0
MAX_POSITIONS = 5

EXISTING = ["donchian_atr_v1", "trend_momentum_v1", "vol_regime_v1"]
NEW = ["bb_squeeze_v1", "bb_squeeze_vol_v1", "bb_breakout_trend_v1",
       "rsi2_mr_v1", "supertrend_macd_v1", "price_action_v1"]


class AllDaysCalendar:
    """24/7 crypto calendar: every bar timestamp is a tradable session."""
    def __init__(self, days):
        self.days = sorted(pd.Timestamp(d) for d in days)

    def next_session(self, date):
        i = bisect.bisect_right(self.days, pd.Timestamp(date))
        return self.days[i] if i < len(self.days) else None

    def next_n_sessions(self, start, n):
        lo = bisect.bisect_left(self.days, pd.Timestamp(start))
        return self.days[lo:lo + n]


def load_strategy_module(strategy_id):
    path = REPO / "strategies" / "crypto" / strategy_id / "rule.py"
    spec = importlib.util.spec_from_file_location(
        f"strategies.crypto.{strategy_id}.rule", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_bars(timeframe):
    bars = {}
    sub = "daily" if timeframe == "D" else "4h"
    for s in UNIVERSE:
        df = pd.read_parquet(DATA_DIR / sub / f"{s}.parquet")
        df = df[~df.index.duplicated(keep="last")].sort_index()
        bars[s] = df
    return bars


def inject_daily_trend(ltf_bars, daily_bars):
    """Daily-confirmed trend columns reindexed onto the lower-TF frame.

    A daily candle labeled D is only usable on lower-TF bars whose session time
    is >= (D + 1 day) 00:00 - i.e. after that daily candle has fully closed.
    The shifted-index + forward-fill makes the alignment leak-free.
    """
    daily = daily_bars.copy()
    d_sma = daily["close"].rolling(200).mean()
    src = pd.DataFrame({
        "d_close": daily["close"].values,
        "d_sma200": d_sma.values,
        "d_trend_up": (daily["close"] > d_sma).values,
    }, index=daily.index + pd.Timedelta(days=1))
    src = src[~src.index.duplicated(keep="last")]
    grid = src.index.union(ltf_bars.index).unique().sort_values()
    out = pd.DataFrame(index=ltf_bars.index)
    for c in src.columns:
        out[c] = src[c].reindex(grid).ffill().reindex(ltf_bars.index)
    return out


def build_close_lookup(bars_by_symbol):
    return {sym: df["close"].to_dict() for sym, df in bars_by_symbol.items()}


def simulate_rsi_exit(order, bars, features, calendar, cost_model, exit_rsi,
                      max_holding):
    """Dynamic indicator-based exit for mean-reversion (S4)."""
    if order.order_date not in bars.index:
        return None
    entry_price = bars.loc[order.order_date, "open"] * (1 + cost_model.slippage_bps / 10000)
    entry_fill = Fill(order, order.order_date, float(entry_price), "OPEN",
                      cost_model.entry_cost_bps, cost_model.slippage_bps)

    window = calendar.next_n_sessions(order.order_date, max_holding)
    exit_fill = None
    for day in window:
        if day not in bars.index:
            continue
        if day not in features.index:
            continue
        rsi_now = features.loc[day, "rsi"]
        if pd.isna(rsi_now):
            continue
        if float(rsi_now) >= exit_rsi:
            px = float(bars.loc[day, "close"]) * (1 - cost_model.slippage_bps / 10000)
            exit_fill = Fill(order, day, px, "EXIT_RULE", cost_model.exit_cost_bps,
                             cost_model.slippage_bps)
            break

    if exit_fill is None and window:
        last_day = window[-1]
        if last_day in bars.index:
            px = float(bars.loc[last_day, "close"]) * (1 - cost_model.slippage_bps / 10000)
            exit_fill = Fill(order, last_day, px, "TIME_EXIT",
                             cost_model.exit_cost_bps, cost_model.slippage_bps)

    if exit_fill is None:
        return None
    return entry_fill, exit_fill


def split_periods(ts_list):
    ts_list = sorted(ts_list)
    n = len(ts_list)
    i_tr = int(n * 0.6)
    i_va = int(n * 0.75)
    return {
        "FULL": (ts_list[0], ts_list[-1]),
        "TRAIN": (ts_list[0], ts_list[i_tr - 1]),
        "VALID": (ts_list[i_tr], ts_list[i_va - 1]),
        "TEST": (ts_list[i_va], ts_list[-1]),
    }


def run_backtest(mod, bars_by_symbol, feats_by_symbol, period_ts, close_lookup,
                 cost_model, symbols):
    """Single-symbol-set portfolio backtest over [start, end].

    Returns a dict with the equity curve, portfolio, trades, diagnostics.
    Features are pre-computed on FULL bars (warmup preserved); bars are sliced
    to the period for fills so positions never fabricate bars past the period.
    """
    start, end = period_ts
    lookup_bars = {}
    for sym in symbols:
        df = bars_by_symbol[sym]
        mask = (df.index >= start) & (df.index <= end)
        lookup_bars[sym] = df[mask]

    all_days = sorted({ts for df in lookup_bars.values() for ts in df.index})
    if not all_days:
        return None
    calendar = AllDaysCalendar(all_days)

    diag = {"rawSignalCount": 0, "invalidSignal": 0, "noNextSession": 0,
            "noBarOnEntry": 0, "ranOutOfBars": 0, "overlapsDropped": 0,
            "portfolioEligibleTradeCount": 0}

    all_signals = []
    for sym in symbols:
        all_signals.extend(mod.generate_signals_main(sym, feats_by_symbol[sym]))

    resolved = []
    for sig in all_signals:
        diag["rawSignalCount"] += 1
        features = feats_by_symbol[sig.symbol]
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index or not (start <= ts <= end):
            diag["invalidSignal"] += 1
            continue
        row = features.loc[ts]
        if pd.isna(row.get("atr", 0.0)):
            diag["invalidSignal"] += 1
            continue
        risk_spec = mod.risk_spec_for_main(row)
        order = build_order(sig, risk_spec, calendar)
        if order is None:
            diag["noNextSession"] += 1
            continue

        bars = lookup_bars[sig.symbol]
        if order.order_date not in bars.index:
            diag["noBarOnEntry"] += 1
            continue

        exit_rule = (sig.metadata or {}).get("exit_rule")
        if exit_rule == "rsi2_ge70":
            result = simulate_rsi_exit(order, bars, features, calendar, cost_model,
                                       float(sig.metadata.get("exit_rsi_min", 70.0)),
                                       order.risk_spec.max_holding_sessions)
        else:
            result = simulate_trade(order, bars, calendar, cost_model)
        if result is None:
            diag["ranOutOfBars"] += 1
            continue
        entry_fill, exit_fill = result
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec))

    diag["resolvedTradeCount"] = len(resolved)

    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit = {}
    deduped = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date < last_exit:
            diag["overlapsDropped"] += 1
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped
    diag["portfolioEligibleTradeCount"] = len(resolved)

    cfg = PortfolioConfig(initial_capital=INITIAL_CAPITAL, max_positions=MAX_POSITIONS,
                          equal_weight=True, fractional_shares=True,
                          tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    period_close = {sym: close_lookup.get(sym, {}) for sym in symbols}

    by_entry_date, by_exit_date = defaultdict(list), defaultdict(list)
    for item in resolved:
        _, order, entry_fill, exit_fill, _ = item
        by_entry_date[order.order_date].append(item)
        by_exit_date[exit_fill.fill_date].append(item)

    equity_curve = [(all_days[0], cfg.initial_capital)]
    exposure_days = 0
    exit_type_counts = defaultdict(int)
    for date in all_days:
        exits_today, same_bar_exit_candidates = [], []
        exit_symbols_queued = set()
        for item in by_exit_date.get(date, []):
            _, order, entry_fill, exit_fill, _ = item
            exit_type_counts[exit_fill.fill_type] += 1
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                exits_today.append((order.symbol, exit_fill, portfolio.open_positions[order.symbol]["shares"]))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)

        if same_bar_exit_candidates:
            admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if admitted:
                portfolio.process_day(date, admitted, [])

        if portfolio.open_positions:
            exposure_days += 1
        closes_today = {sym: period_close[sym].get(date)
                        for sym in portfolio.open_positions
                        if period_close[sym].get(date) is not None}
        equity_curve.append((date, portfolio.equity(closes_today)))

    return {
        "equity_curve": equity_curve,
        "portfolio": portfolio,
        "closed_positions": portfolio.closed_positions,
        "diag": diag,
        "exit_type_counts": dict(exit_type_counts),
        "lookup_bars": lookup_bars,
        "all_days": all_days,
        "exposure_days": exposure_days,
    }


def cagr_ts(curve):
    if len(curve) < 2:
        return None
    t0, e0 = pd.Timestamp(curve[0][0]), curve[0][1]
    t1, e1 = pd.Timestamp(curve[-1][0]), curve[-1][1]
    years = (t1 - t0).total_seconds() / (365.25 * 86400)
    if years <= 0 or e0 <= 0:
        return None
    return (e1 / e0) ** (1 / years) - 1


def calmar_ts(curve):
    c = cagr_ts(curve)
    mdd = M.max_drawdown(curve)
    return None if (c is None or not mdd) else c / abs(mdd)


def sharpe_annualized(rets, bars_per_year):
    if len(rets) < 2:
        return None
    mean = np.mean(rets)
    std = np.std(rets, ddof=1)
    return None if std == 0 else mean / std * np.sqrt(bars_per_year)


def equity_returns(curve):
    eq = [v for _, v in curve]
    return [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1] > 0]


def annual_returns(curve):
    if not curve:
        return {}
    s = pd.Series([v for _, v in curve], index=pd.to_datetime([c[0] for c in curve]))
    yearly = s.resample("YE").last()
    out = {}
    prev = None
    for ts, v in yearly.items():
        if prev is not None:
            out[str(ts.year)] = round(float(v / prev - 1), 4)
        prev = v
    return out


def compute_metrics(result, bars_per_year, label_ts=False):
    """Result dict from run_backtest -> metric dict (capital-invariant)."""
    curve = result["equity_curve"]
    portfolio = result["portfolio"]
    metrics = {
        "totalReturn": M.total_return(curve),
        "cagr": cagr_ts(curve),
        "maxDrawdown": M.max_drawdown(curve),
        "sharpe252": M.sharpe(curve, annualization=252) if not label_ts else None,
        "sortino252": M.sortino(curve, annualization=252) if not label_ts else None,
        "calmar": calmar_ts(curve),
    }
    rets = equity_returns(curve)
    metrics["sharpe_ann"] = sharpe_annualized(rets, bars_per_year)
    metrics["sortino_ann"] = None
    if len(rets) >= 2:
        mean = np.mean(rets)
        dd = [min(r, 0.0) for r in rets]
        dstd = np.sqrt(np.mean(np.square(dd)))
        if dstd > 0:
            metrics["sortino_ann"] = mean / dstd * np.sqrt(bars_per_year)

    trades = []
    for p in portfolio.closed_positions:
        entry_ts = pd.Timestamp(p["entry_date"])
        exit_ts = pd.Timestamp(p["exit_date"])
        trades.append({
            "pnl": p["pnl"],
            "entry": entry_ts,
            "exit": exit_ts,
            "symbol": p["symbol"],
            "shares": p["shares"],
            "entry_price": p["entry"].fill_price,
            "exit_price": p["exit"].fill_price,
            "entry_date": p["entry_date"],
            "exit_date": p["exit_date"],
            "exit_type": p["exit"].fill_type,
            "holding_sessions": sessions_between(p["entry_date"], p["exit_date"], result["all_days"]),
        })

    tstats = M.trade_stats(trades)
    avg_eq = np.mean([v for _, v in curve]) if len(curve) else None
    notional = sum(p["entry"].fill_price * p["shares"] + p["exit"].fill_price * p["shares"]
                   for p in portfolio.closed_positions)
    turnover = (notional / avg_eq) if avg_eq else None

    metrics.update({
        "tradeCount": tstats["tradeCount"],
        "winRate": tstats["winRate"],
        "profitFactor": tstats["profitFactor"],
        "expectancy": tstats["expectancy"],
        "avgWin": tstats["avgWin"],
        "avgLoss": tstats["avgLoss"],
        "avgHoldingSessions": tstats["avgHoldingPeriod"],
        "turnover": turnover,
        "exposure": (result["exposure_days"] / len(result["all_days"])) if len(result["all_days"]) else None,
        "closedPositionCount": len(portfolio.closed_positions),
        "openPositionsAtEnd": len(portfolio.open_positions),
        "annualReturns": annual_returns(curve),
        "finalEquity": curve[-1][1] if curve else None,
        "exitTypeCounts": result["exit_type_counts"],
        "diag": result["diag"],
    })
    return metrics, trades


def sessions_between(s, e, all_days):
    """Number of calendar sessions between two timestamps (inclusive-ish)."""
    ts_s, ts_e = pd.Timestamp(s), pd.Timestamp(e)
    total = sum(1 for d in all_days if ts_s <= d <= ts_e)
    return total


def buy_hold_benchmark(bars_by_symbol, period_ts, symbols, timeframe):
    start, end = period_ts
    curves = {}
    for sym in symbols:
        df = bars_by_symbol[sym]
        df = df[(df.index >= start) & (df.index <= end)]
        if len(df) == 0:
            continue
        curves[sym] = df["close"].to_dict()
    all_days = sorted({ts for c in curves.values() for ts in c})
    if not all_days:
        return None
    per_cap = INITIAL_CAPITAL / len(symbols)
    shares = {}
    curve = []
    for date in all_days:
        for sym in symbols:
            if sym not in shares and date in curves.get(sym, {}):
                shares[sym] = per_cap / curves[sym][date]
        total = sum(shares.get(sym, 0) * curves.get(sym, {}).get(date, 0) for sym in symbols)
        curve.append((date, total))
    return curve


def per_asset_decomposition(trades, symbols):
    out = {}
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["symbol"]].append(t)
    for sym in symbols:
        ts = by_sym.get(sym, [])
        wins = [t["pnl"] for t in ts if t["pnl"] > 0]
        losses = [t["pnl"] for t in ts if t["pnl"] <= 0]
        n = len(ts)
        out[sym] = {
            "trades": n,
            "winRate": len(wins) / n if n else None,
            "netPnl": float(sum(t["pnl"] for t in ts)),
            "grossProfit": float(sum(wins)) if wins else 0.0,
            "grossLoss": float(-sum(losses)) if losses else 0.0,
        }
    return out


def correlation_matrix(name_order, curves_by_name):
    """Pearson correlation of strategy return series over aligned index."""
    rets = OrderedDict()
    index_set = None
    for name in name_order:
        curve = curves_by_name.get(name)
        if not curve:
            continue
        s = pd.Series([v for _, v in curve], index=[pd.Timestamp(c[0]) for c in curve])
        r = s.pct_change()
        rets[name] = r
        index_set = r.index if index_set is None else index_set.union(r.index)
    names = list(rets.keys())
    frame = pd.DataFrame({n: rets[n].reindex(index_set) for n in names})
    corr = frame.corr()
    return corr, names


def build_configs():
    """Strategy run configurations. Arms toggled by mutating module PARAMS."""
    configs = []
    # Daily (primary OOS period = full 3.3y)
    for sid in (EXISTING + NEW):
        cfg = {"strategy": sid, "timeframe": "D", "overrides": {}}
        if sid == "bb_breakout_trend_v1":
            cfg["overrides"] = {"use_daily_trend": False}
            a = dict(cfg, label="bb_breakout_trend_A")
            b = dict(cfg, label="bb_breakout_trend_B")
            b["overrides"] = {"use_daily_trend": True}
            configs.append(a)
            configs.append(b)
        else:
            configs.append(cfg)
    # 4H (supplementary; S3 MTF & S4 are inherently 4H)
    for sid in NEW:
        cfg = {"strategy": sid, "timeframe": "4H", "overrides": {},
               "inject_daily": sid in ("bb_breakout_trend_v1", "rsi2_mr_v1")}
        if sid == "bb_breakout_trend_v1":
            a = dict(cfg, label="bb_breakout_trend_A", overrides={"use_daily_trend": False})
            b = dict(cfg, label="bb_breakout_trend_B", overrides={"use_daily_trend": True})
            configs.append(a)
            configs.append(b)
        else:
            configs.append(cfg)
    return configs


def apply_overrides(mod, overrides):
    for k, v in overrides.items():
        setattr(mod.PARAMS, k, v)


def feature_occurrence(feats_by_sym):
    """Feature frequency analysis for price_action_v1 (S6) on the FULL period."""
    cols = ["f_body", "f_loc", "f_range", "f_high", "f_vol"]
    occ = {}
    for col in cols:
        n_true, n_valid = 0, 0
        for sym, f in feats_by_sym.items():
            v = f[col].dropna()
            n_valid += int(v.size)
            n_true += int(v.sum())
        occ[col] = {"true": n_true, "valid": n_valid,
                    "rate": (n_true / n_valid) if n_valid else None}
    return occ


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    daily_bars = load_bars("D")
    h4_bars = load_bars("4H")
    daily_close = build_close_lookup(daily_bars)
    h4_close = build_close_lookup(h4_bars)

    ts_daily = sorted({ts for df in daily_bars.values() for ts in df.index})
    ts_h4 = sorted({ts for df in h4_bars.values() for ts in df.index})
    splits_d = split_periods(ts_daily)
    splits_h = split_periods(ts_h4)

    # ---- feature/benchmark setup ----
    module_cache = {}
    features_cache = {}

    all_results = {}
    daily_equity_curves = {}
    h4_equity_curves = {}
    benchmarks = {"D": {}, "4H": {}}
    feature_occ = {}

    for tf, bars, close in (("D", daily_bars, daily_close), ("4H", h4_bars, h4_close)):
        splits = splits_d if tf == "D" else splits_h
        bh = {}
        for period, prange in splits.items():
            bh[period] = buy_hold_benchmark(bars, prange, UNIVERSE, tf)
        benchmarks[tf] = bh

    for cfg in build_configs():
        sid = cfg["strategy"]
        tf = cfg["timeframe"]
        label = cfg.get("label", sid)
        uid = f"{label}:{tf}"
        overrides = cfg.get("overrides", {})
        inject = cfg.get("inject_daily", False)

        key = (sid, tf, inject, json.dumps(overrides, sort_keys=True))
        if key not in module_cache:
            mod = load_strategy_module(sid)
            apply_overrides(mod, overrides)
            # precompute features once on FULL bars
            feats = {}
            for sym in UNIVERSE:
                bars = (h4_bars if tf == "4H" else daily_bars)[sym]
                fb = bars.copy()
                if inject and tf == "4H":
                    daily_trend = inject_daily_trend(fb, daily_bars[sym])
                    for c in daily_trend.columns:
                        fb[c] = daily_trend[c]
                feats[sym] = mod.compute_features_main(fb)
            module_cache[key] = (mod, feats)
        else:
            mod, feats = module_cache[key]

        bars_by_sym = h4_bars if tf == "4H" else daily_bars
        close_by_sym = h4_close if tf == "4H" else daily_close
        splits = splits_h if tf == "4H" else splits_d
        bars_per_year = 365 * 6 if tf == "4H" else 365

        entry = {
            "strategy": sid, "label": label, "uid": uid, "timeframe": tf,
            "overrides": overrides, "inject_daily": inject,
        }
        period_results = {}
        full_res = None
        for period, prange in splits.items():
            cost = CostModel(entry_cost_bps=BASE_ENTRY, exit_cost_bps=BASE_EXIT,
                             slippage_bps=BASE_SLIP)
            res = run_backtest(mod, bars_by_sym, feats, prange, close_by_sym, cost, UNIVERSE)
            if res is None:
                period_results[period] = {"metrics": None, "trades": []}
                continue
            m, trades = compute_metrics(res, bars_per_year, label_ts=(tf == "4H"))
            period_results[period] = {"metrics": m, "trades": trades}
            if period == "FULL":
                full_res = res
        all_results[uid] = {"config": entry, "periods": period_results}

        # persist FULL equity curve for correlation / report
        curve_store = daily_equity_curves if tf == "D" else h4_equity_curves
        curve_store[uid] = full_res["equity_curve"] if full_res is not None else []

        # per-asset decomposition on FULL
        pa = per_asset_decomposition(period_results["FULL"]["trades"], UNIVERSE)
        all_results[uid]["per_asset"] = pa

        # cost sensitivity: re-run FULL at multipliers 0/2/4
        sens = {}
        for mult in (0.0, 2.0, 4.0):
            c = CostModel(BASE_ENTRY * mult, BASE_EXIT * mult, BASE_SLIP * mult)
            r = run_backtest(mod, bars_by_sym, feats, splits["FULL"], close_by_sym, c, UNIVERSE)
            if r is None:
                sens[str(mult)] = None
                continue
            sm, _ = compute_metrics(r, bars_per_year, label_ts=(tf == "4H"))
            sens[str(mult)] = sm
        all_results[uid]["cost_sensitivity"] = sens

        fm = period_results["FULL"]["metrics"]
        if fm is None:
            print(f"[done] {label:<28} {tf:>3}  NO TRADES period=[FULL]")
        else:
            fm = {k: (v if v is not None else 0.0) for k, v in fm.items()}
            print(f"[done] {label:<28} {tf:>3} "
                  f"CAGR={fm['cagr'] * 100:.2f}%  MDD={fm['maxDrawdown'] * 100:.2f}%  "
                  f"Sharpe={fm['sharpe_ann']:.2f}  Win%={fm['winRate'] * 100:.1f}  "
                  f"N={fm['tradeCount']}")

        # S6 feature occurrence
        if sid == "price_action_v1":
            feature_occ[uid] = {"timeframe": tf, "features": feature_occurrence(feats)}

    # ---- correlations ----
    corr_d, names_d = correlation_matrix(
        [f"{cfg.get('label', cfg['strategy'])}:{cfg['timeframe']}"
         for cfg in build_configs() if cfg["timeframe"] == "D"],
        daily_equity_curves)
    corr_h, names_h = correlation_matrix(
        [f"{cfg.get('label', cfg['strategy'])}:{cfg['timeframe']}"
         for cfg in build_configs() if cfg["timeframe"] == "4H"],
        h4_equity_curves)

    payload = {
        "universe": UNIVERSE,
        "cost": {"entry_bps": BASE_ENTRY, "exit_bps": BASE_EXIT, "slippage_bps": BASE_SLIP},
        "capital": INITIAL_CAPITAL,
        "max_positions": MAX_POSITIONS,
        "daily_range": [str(ts_daily[0]), str(ts_daily[-1])],
        "h4_range": [str(ts_h4[0]), str(ts_h4[-1])],
        "splits_daily": {k: [str(v[0]), str(v[1])] for k, v in splits_d.items()},
        "splits_4h": {k: [str(v[0]), str(v[1])] for k, v in splits_h.items()},
        "benchmarks": {tf: {p: _curve_to_metrics(c) for p, c in bh.items()}
                       for tf, bh in benchmarks.items()},
        "strategies": all_results,
        "corr_daily_full": corr_d.to_dict(),
        "corr_4h_full": corr_h.to_dict(),
        "feature_occurrence": feature_occ,
    }

    with open(OUT_DIR / "results.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {OUT_DIR / 'results.json'}")
    return payload


def _curve_to_metrics(curve):
    if curve is None or len(curve) < 2:
        return None
    return {
        "cagr": cagr_ts(curve),
        "totalReturn": M.total_return(curve),
        "maxDrawdown": M.max_drawdown(curve),
        "sharpe_ann": sharpe_annualized(equity_returns(curve), 365),
    }


if __name__ == "__main__":
    payload = main()

    def _fmt(m, k, scale=1.0, digits=2):
        v = m.get(k)
        if v is None:
            return "   n/a  "
        return f"{v * scale:>{digits * 3 + 5}.{digits}f}"

    print("\n==================== FULL PERIOD SUMMARY (DAILY) ====================")
    print(f"{'strategy':<36} {'CAGR':>9} {'MDD':>9} {'Sharpe':>8} {'Win%':>6} {'Trds':>5}")
    for uid, data in payload["strategies"].items():
        if data["config"]["timeframe"] != "D":
            continue
        name = data["config"]["label"]
        m = data["periods"]["FULL"]["metrics"]
        if m is None:
            print(f"{name:<36} NO TRADES")
            continue
        print(f"{name:<36} {_fmt(m, 'cagr', 100, 1):>9} {_fmt(m, 'maxDrawdown', 100, 1):>9} "
              f"{_fmt(m, 'sharpe_ann'):>8} {_fmt(m, 'winRate', 100, 1):>6} "
              f"{_fmt(m, 'tradeCount', 1, 0):>5}")
    print("\n==================== FULL PERIOD SUMMARY (4H) ====================")
    print(f"{'strategy':<36} {'CAGR':>9} {'MDD':>9} {'Sharpe':>8} {'Win%':>6} {'Trds':>5}")
    for uid, data in payload["strategies"].items():
        if data["config"]["timeframe"] != "4H":
            continue
        name = data["config"]["label"]
        m = data["periods"]["FULL"]["metrics"]
        if m is None:
            print(f"{name:<36} NO TRADES")
            continue
        print(f"{name:<36} {_fmt(m, 'cagr', 100, 1):>9} {_fmt(m, 'maxDrawdown', 100, 1):>9} "
              f"{_fmt(m, 'sharpe_ann'):>8} {_fmt(m, 'winRate', 100, 1):>6} "
              f"{_fmt(m, 'tradeCount', 1, 0):>5}")
    print("\nBenchmarks (equal-weight buy & hold)")
    for tf in ("D", "4H"):
        for period, bm in payload["benchmarks"][tf].items():
            if bm is None:
                print(f"  {tf} {period:<6}: no data")
                continue
            print(f"  {tf} {period:<6}: CAGR={bm['cagr'] * 100:>7.1f}%  "
                  f"MDD={bm['maxDrawdown'] * 100:>7.1f}%  Sharpe={bm['sharpe_ann']:>5.2f}")