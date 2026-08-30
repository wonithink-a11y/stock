"""Independent verification driver for strategies/crypto/*/rule.py (OpenCode-
authored, not run through the standard engine yet - runner.py hard-asserts
universe mode in (A1A_ONLY, A1A_A1B_MERGED) and these use CRYPTO_FIXED, and
rule.PARAMS is a dataclass not a dict so params["cost"]["entryCostBps"] etc.
would crash anyway). This script reuses the engine's execution/portfolio/
metrics primitives directly (unmodified) with a synthetic all-days calendar
(crypto trades 24/7, unlike KRX's TradingCalendar) and calls each rule.py's
*_main() wrapper functions directly (the correctly-shaped compute_features(bars)/
generate_signals(symbol, features)/risk_spec_for(row) - the plain-named
functions require an extra `params` arg nothing in this project's calling
convention would ever supply).

Daily equity-curve pattern mirrors pbr_vs_ew_monthly_mtm.py's proven
mark-to-market approach (snapshotting portfolio.equity() at each date instead
of relying on realized-PnL-at-exit, which distorts long-held positions), but
snapshots every day (not just month-end) - crypto has no monthly rebalance
concept here, and daily gives a proper Sharpe under engine/metrics' own
252-day annualization convention.
"""
import bisect
import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
os.chdir(str(REPO))

import pandas as pd  # noqa: E402

from engine.execution.executor import CostModel, build_order, simulate_trade  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.metrics import metrics as M  # noqa: E402

DATA_DIR = REPO / "data" / "crypto" / "daily"


class AllDaysCalendar:
    def __init__(self, days):
        self.days = sorted(days)

    def next_session(self, date):
        i = bisect.bisect_right(self.days, date)
        return self.days[i] if i < len(self.days) else None

    def next_n_sessions(self, start, n):
        lo = bisect.bisect_left(self.days, start)
        return self.days[lo:lo + n]


def load_strategy_module(strategy_id):
    path = REPO / "strategies" / "crypto" / strategy_id / "rule.py"
    spec = importlib.util.spec_from_file_location(f"strategies.crypto.{strategy_id}.rule", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_bars(symbols, start, end):
    bars = {}
    for s in symbols:
        df = pd.read_parquet(DATA_DIR / f"{s}.parquet")
        bars[s] = df.loc[start:end]
    return bars


def build_close_lookup(bars_by_symbol):
    lookup = {}
    for sym, df in bars_by_symbol.items():
        idx = df.index.strftime("%Y-%m-%d")
        lookup[sym] = dict(zip(idx, df["close"].values))
    return lookup


def run_backtest(strategy_id, start, end):
    mod = load_strategy_module(strategy_id)
    policy = json.loads((REPO / "strategies" / "crypto" / strategy_id / "policy.json").read_text(encoding="utf-8"))
    symbols = policy["universe"]["symbols"]

    bars_by_symbol = load_bars(symbols, start, end)
    all_days = set()
    for df in bars_by_symbol.values():
        all_days.update(df.index.strftime("%Y-%m-%d").tolist())
    calendar = AllDaysCalendar(all_days)

    cost_model = CostModel(
        entry_cost_bps=policy["cost"]["entryCostBps"],
        exit_cost_bps=policy["cost"]["exitCostBps"],
        slippage_bps=policy["cost"]["slippageBps"],
    )
    portfolio_cfg = PortfolioConfig(
        initial_capital=policy["portfolio"]["initialCapital"],
        max_positions=policy["portfolio"]["maxPositions"],
        equal_weight=policy["portfolio"]["equalWeight"],
        fractional_shares=policy["portfolio"]["fractionalShares"],
        tie_break=policy["portfolio"]["tieBreak"],
    )

    all_signals = []
    features_by_symbol = {}
    diag = {"executionErrors": 0, "invalidSignal": 0, "noNextSession": 0,
            "noBarOnEntry": 0, "ranOutOfBars": 0, "overlapsDropped": 0}
    for symbol, bars in bars_by_symbol.items():
        try:
            features = mod.compute_features_main(bars)
        except Exception as e:
            diag["executionErrors"] += 1
            print(f"  [ERROR] compute_features failed for {symbol}: {e}")
            continue
        features_by_symbol[symbol] = features
        all_signals.extend(mod.generate_signals_main(symbol, features))

    resolved = []
    for sig in all_signals:
        features = features_by_symbol[sig.symbol]
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index:
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
        bars = bars_by_symbol[sig.symbol]
        if pd.Timestamp(order.order_date) not in bars.index:
            diag["noBarOnEntry"] += 1
            continue
        result = simulate_trade(order, bars, calendar, cost_model)
        if result is None:
            diag["ranOutOfBars"] += 1
            continue
        entry_fill, exit_fill = result
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec))

    diag["rawSignalCount"] = len(all_signals)

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

    portfolio = Portfolio(portfolio_cfg)
    close_lookup = build_close_lookup(bars_by_symbol)

    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    all_days_sorted = sorted(all_days)
    equity_curve = [(all_days_sorted[0], portfolio_cfg.initial_capital)]

    for date in all_days_sorted:
        exits_today, same_bar_exit_candidates = [], []
        exit_symbols_queued = set()
        for item in by_exit_date.get(date, []):
            _, order, entry_fill, exit_fill, _ = item
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])

        closes_today = {sym: close_lookup.get(sym, {}).get(date)
                         for sym in portfolio.open_positions if close_lookup.get(sym, {}).get(date) is not None}
        equity_curve.append((date, portfolio.equity(closes_today)))

    trades = [{"pnl": p["pnl"], "holding_sessions": 0} for p in portfolio.closed_positions]

    return {
        "strategyId": strategy_id,
        "diag": diag,
        "cagr": M.cagr(equity_curve),
        "totalReturn": M.total_return(equity_curve),
        "maxDrawdown": M.max_drawdown(equity_curve),
        "sharpe": M.sharpe(equity_curve),
        "sortino": M.sortino(equity_curve),
        "calmar": M.calmar(equity_curve),
        "tradeStats": M.trade_stats(trades),
        "finalEquity": equity_curve[-1][1],
        "closedPositions": len(portfolio.closed_positions),
        "openPositionsAtEnd": len(portfolio.open_positions),
    }, equity_curve


def buy_hold_benchmark(symbols, start, end, initial_capital=100_000_000):
    bars_by_symbol = load_bars(symbols, start, end)
    close_lookup = build_close_lookup(bars_by_symbol)
    all_days = sorted(set().union(*[set(v.keys()) for v in close_lookup.values()]))
    per_symbol_capital = initial_capital / len(symbols)
    shares = {}
    equity_curve = []
    for date in all_days:
        for sym in symbols:
            if sym not in shares and date in close_lookup.get(sym, {}):
                shares[sym] = per_symbol_capital / close_lookup[sym][date]
        total = sum(shares.get(sym, 0) * close_lookup.get(sym, {}).get(date, 0) for sym in symbols)
        equity_curve.append((date, total))
    return equity_curve


def fmt_pct(x):
    return "N/A" if x is None else f"{x*100:+.2f}%"


def fmt_num(x, nd=3):
    return "N/A" if x is None else f"{x:.{nd}f}"


if __name__ == "__main__":
    START, END = "2023-05-21", "2026-08-27"
    STRATEGIES = ["donchian_atr_v1", "trend_momentum_v1", "vol_regime_v1"]
    UNIVERSE = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA"]

    print(f"\n{'='*70}\n검증 기간: {START} ~ {END} ({UNIVERSE})\n{'='*70}\n")

    print("--- 벤치마크: 동일비중 buy&hold (5종목, 리밸런싱 없음) ---")
    bh_curve = buy_hold_benchmark(UNIVERSE, START, END)
    print(f"  CAGR={fmt_pct(M.cagr(bh_curve))}  MDD={fmt_pct(M.max_drawdown(bh_curve))}  "
          f"Sharpe={fmt_num(M.sharpe(bh_curve))}  총수익={fmt_pct(M.total_return(bh_curve))}")

    results_all = {}
    for sid in STRATEGIES:
        print(f"\n--- {sid} ---")
        try:
            res, curve = run_backtest(sid, START, END)
        except Exception as e:
            import traceback
            print(f"  [실행 실패] {e}")
            traceback.print_exc()
            continue
        results_all[sid] = res
        d = res["diag"]
        print(f"  신호 {d['rawSignalCount']}건 -> 체결가능 {d.get('portfolioEligibleTradeCount', 0)}건 "
              f"(무효신호 {d['invalidSignal']}, 다음세션없음 {d['noNextSession']}, "
              f"진입일봉없음 {d['noBarOnEntry']}, 봉소진 {d['ranOutOfBars']}, 중복겹침제외 {d['overlapsDropped']})")
        print(f"  포트폴리오 반영 청산 {res['closedPositions']}건, 종료시점 보유 {res['openPositionsAtEnd']}건")
        ts = res["tradeStats"]
        print(f"  CAGR={fmt_pct(res['cagr'])}  MDD={fmt_pct(res['maxDrawdown'])}  "
              f"Sharpe={fmt_num(res['sharpe'])}  Sortino={fmt_num(res['sortino'])}  Calmar={fmt_num(res['calmar'])}")
        print(f"  승률={fmt_pct(ts['winRate'])}  손익비={fmt_num(ts['profitFactor'])}  "
              f"거래수={ts['tradeCount']}  기대값={fmt_num(ts['expectancy'], 0)}원/건")
        print(f"  최종자산={res['finalEquity']:,.0f}원 (초기 100,000,000원)")

    print(f"\n{'='*70}\n요약 비교 (vs 동일비중 buy&hold)\n{'='*70}")
    bh_cagr = M.cagr(bh_curve)
    print(f"  {'전략':<20} {'CAGR':>10} {'vs BH':>10} {'MDD':>10} {'Sharpe':>8} {'거래수':>6}")
    print(f"  {'buy&hold(벤치마크)':<20} {fmt_pct(bh_cagr):>10} {'vs-BH':>10} {fmt_pct(M.max_drawdown(bh_curve)):>10} {fmt_num(M.sharpe(bh_curve)):>8}")
    for sid, res in results_all.items():
        gap = (res["cagr"] - bh_cagr) if (res["cagr"] is not None and bh_cagr is not None) else None
        gap_str = f"{gap*100:+.2f}%p" if gap is not None else "N/A"
        print(f"  {sid:<20} {fmt_pct(res['cagr']):>10} {gap_str:>10} {fmt_pct(res['maxDrawdown']):>10} "
              f"{fmt_num(res['sharpe']):>8} {res['tradeStats']['tradeCount']:>6}")
