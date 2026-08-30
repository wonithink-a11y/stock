#!/usr/bin/env python
"""MACD-KR-V1 SMOKE driver (STEP 2).

Implements and runs MACD(12,26,9) crossover, Long only, KOSPI+KOSDAQ daily,
with the listing-date PIT gate. Reuses the shared engine DATA layer, the shared
Portfolio accounting contract, CostModel and engine.metrics. It does NOT reuse
engine.executor.simulate_trade because the required exit (bearish crossover at
next open) is a dynamic state-machine exit, not the engine's fixed
STOP/TARGET/TIME_EXIT contract - see policy.json / report §14 (engine limits).

Exits on the equity side are pure crossover fills ("CROSSOVER"); there is no
stop/loss (the STEP-2 baseline defines no stop-loss/take-profit for MACD cross;
see report §15).

SMOKE scope only: a seeded 30-ticker A1A_ONLY subset. This is an implementation
validation, NOT a performance verdict (STEP-2 §17).

  python run_macd_kr_v1_smoke.py [--subset N] [--seed S] [--no-write]
"""
import argparse
import json
import os
import random
import sys
import time
from dataclasses import replace as _df_replace
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", ".."))  # for data/backfill relative loads

import pandas as pd
import numpy as np

from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.execution.contracts import Fill, Order  # noqa: E402
from engine.execution.executor import CostModel  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.signals.schema import RiskSpec  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from engine.metrics import metrics as M  # noqa: E402
from benchmarks.b0_buy_hold import compute_trades as bh_trades, compute_equity_curve as bh_curve  # noqa: E402

from strategies.macd_kr_v1 import rule as MACD_RULE  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

POLICY = MACD_RULE.PARAMS
RAW_START = POLICY["period"]["rawDataStart"]
PERF_START = POLICY["period"]["performanceStart"]
END = POLICY["period"]["end"]
FAST = POLICY["indicators"]["macd"]["fast"]
SLOW = POLICY["indicators"]["macd"]["slow"]
SIGNAL = POLICY["indicators"]["macd"]["signal"]

COST = CostModel(
    entry_cost_bps=POLICY["cost"]["entryCostBps"],
    exit_cost_bps=POLICY["cost"]["exitCostBps"],
    slippage_bps=POLICY["cost"]["slippageBps"],
)
PORT_CFG = PortfolioConfig(
    initial_capital=POLICY["portfolio"]["initialCapital"],
    max_positions=POLICY["portfolio"]["maxPositions"],
    equal_weight=POLICY["portfolio"]["equalWeight"],
    fractional_shares=POLICY["portfolio"]["fractionalShares"],
    tie_break=POLICY["portfolio"]["tieBreak"],
)


def load_listed_at(repo_root):
    """ticker -> listedAt (YYYY-MM-DD) from A1a current universe."""
    m = {}
    with open(os.path.join(repo_root, "data", "backfill", "universe", "a1a", "current.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            m[r["ticker"]] = r["listedAt"]
    return m


def build_events(symbol, features, calendar, listed_at):
    """Re-derive entry/exit fills (next-open) for a ticker. Returns list of
    (kind, fill_date, fill) where kind in ("ENTRY","EXIT"); and audit dict."""
    hist = features["macd_hist"]
    bull, bear = MACD_RULE.cross_series(hist)
    dates = list(features.index)

    audit = {"pre_listing_signals": 0, "bullish_cross_total": int(bull.sum()),
             "warmup_excluded": 0, "entry_count": 0, "exit_count": 0}
    long = False
    events = []

    for d in dates:
        ds = d.strftime("%Y-%m-%d")
        if ds < PERF_START:
            if bull.loc[d] or bear.loc[d]:
                audit["warmup_excluded"] += 1
            continue
        if not bull.loc[d] and not bear.loc[d]:
            continue
        if listed_at and ds < listed_at:
            audit["pre_listing_signals"] += 1
            continue

        if bull.loc[d] and not long:
            long = True
            nd = calendar.next_session(ds)
            if nd is None or nd not in features.index:
                long = False  # no forward bar -> cannot enter (end of data)
                continue
            order = Order(symbol=symbol, signal_date=ds, order_date=nd,
                          direction="LONG",
                          risk_spec=RiskSpec(stop_distance=0.0, reward_risk=0.0,
                                             max_holding_sessions=0))
            fill = Fill(order, nd, float(features.loc[nd, "open"]), "OPEN",
                        COST.entry_cost_bps, COST.slippage_bps)
            events.append(("ENTRY", nd, fill))
            audit["entry_count"] += 1
        elif bear.loc[d] and long:
            long = False
            nd = calendar.next_session(ds)
            if nd is None or nd not in features.index:
                continue
            order = Order(symbol=symbol, signal_date=ds, order_date=nd,
                          direction="LONG",
                          risk_spec=RiskSpec(stop_distance=0.0, reward_risk=0.0,
                                             max_holding_sessions=0))
            fill = Fill(order, nd, float(features.loc[nd, "open"]), "CROSSOVER",
                        COST.exit_cost_bps, COST.slippage_bps)
            events.append(("EXIT", nd, fill))
            audit["exit_count"] += 1

    return events, audit


def run_subset(subset, calendar, listed_at, features_by_ticker, master_dates):
    portfolio = Portfolio(PORT_CFG)
    events_by_date = {}
    audits = {}
    for symbol in subset:
        events, audit = build_events(symbol, features_by_ticker[symbol], calendar,
                                     listed_at.get(symbol))
        audits[symbol] = audit
        for kind, fd, fill in events:
            events_by_date.setdefault(fd, []).append((kind, fill))

    # chronological portfolio schedule (exits first, then entries - Portfolio contract)
    for date in sorted(events_by_date):
        items = events_by_date[date]
        exits = [(f.order.symbol, f, 0) for k, f in items if k == "EXIT"]
        # shares filled by portfolio.process_day's prior state; use stored shares
        # (only admitted positions have shares) - see share resolution below
        exits_adj = []
        for sym, f, _ in exits:
            if sym in portfolio.open_positions:
                exits_adj.append((sym, f, portfolio.open_positions[sym]["shares"]))
        entries = [(e.order, e) for k, e in items if k == "ENTRY"]
        portfolio.process_day(date, exits_adj, entries)

    return portfolio, audits


def compute_performance_equity(events_by_date, bars_by_ticker, calendar, perf_start, end, master_dates,
                               cost_multiplier=1.0):
    """Full daily MTM equity over performance window using Materialized events.
    Returns (curve, invested_by_day, open_marker).

    cost_multiplier scales the fill cost_bps (and slippage_bps) applied by the
    portfolio. Use 0.0 to build a gross (no-cost) equity curve for the same
    schedule; the net run keeps the default 1.0."""
    pf = Portfolio(PORT_CFG)
    last_close = {}
    curve = []
    invested = []
    closed_log = []

    # index closes per symbol for MTM
    closes_by_sym = {sym: bars["close"] for sym, bars in bars_by_ticker.items()}

    def _scaled(fill):
        if cost_multiplier == 1.0:
            return fill
        return _df_replace(fill, cost_bps=fill.cost_bps * cost_multiplier,
                           slippage_bps=fill.slippage_bps * cost_multiplier)

    for date in master_dates:
        ds = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
        # process this date's events (fills at this day's open)
        if ds in events_by_date:
            items = events_by_date[ds]
            exits = [(_scaled(f).order.symbol, _scaled(f), 0) for k, f in items if k == "EXIT"]
            exits_adj = []
            for sym, f, _ in exits:
                if sym in pf.open_positions:
                    exits_adj.append((sym, f, pf.open_positions[sym]["shares"]))
            entries = [(_scaled(e).order, _scaled(e)) for k, e in items if k == "ENTRY"]
            pf.process_day(ds, exits_adj, entries)
            new_closed = [p for p in pf.closed_positions
                          if p["exit_date"] == ds]
            closed_log.extend(new_closed)

        # mark to market open positions at today's close
        eq = pf.cash
        invested_val = 0.0
        for sym, pos in pf.open_positions.items():
            c = closes_by_sym.get(sym)
            px = last_close.get(sym)
            if c is not None and ds in c.index:
                px = float(c.loc[ds])
                last_close[sym] = px
            px = px if px is not None else pos["entry_fill"].fill_price
            mv = pos["shares"] * px
            eq += mv
            invested_val += mv
        for sym, pos in pf.open_positions.items():
            c = closes_by_sym.get(sym)
            if c is not None and ds in c.index:
                last_close[sym] = float(c.loc[ds])
        curve.append((ds, eq))
        invested.append(invested_val / eq if eq else 0.0)

    return pf, curve, invested, closed_log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=30)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    tk_sorted = sorted(universe.tickers)
    rng = random.Random(args.seed)
    subset = set(rng.sample(tk_sorted, min(args.subset, len(tk_sorted))))
    print(f"universe={len(universe.tickers)} (A1A_ONLY), smoke subset={len(subset)} (seed={args.seed})")

    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(subset, RAW_START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    suspension_dropped = sum(len(bars_raw[t]) - len(bars_by_ticker[t]) for t in bars_raw)

    calendar = TradingCalendar(repo_root=REPO_ROOT)
    master_dates = [d for d in calendar.days if PERF_START <= d <= END]
    master_ts = [pd.Timestamp(d) for d in master_dates]

    listed_at = load_listed_at(REPO_ROOT)

    features_by_ticker = {}
    no_data = 0
    for symbol in subset:
        bars = bars_by_ticker.get(symbol)
        if bars is None or bars.empty:
            no_data += 1
            continue
        features_by_ticker[symbol] = MACD_RULE.compute_features(bars)

    # ---- event construction ----
    events_by_date = {}
    audits = {}
    by_symbol_events = {}
    for symbol, features in features_by_ticker.items():
        events, audit = build_events(symbol, features, calendar, listed_at.get(symbol))
        by_symbol_events[symbol] = events
        audits[symbol] = audit
        for kind, fd, fill in events:
            events_by_date.setdefault(fd, []).append((kind, fill))

    pre_listing_sig = sum(a["pre_listing_signals"] for a in audits.values())
    total_bull = sum(a["bullish_cross_total"] for a in audits.values())
    total_entry = sum(a["entry_count"] for a in audits.values())
    total_exit = sum(a["exit_count"] for a in audits.values())

    # ---- portfolio + daily MTM equity (performance window) ----
    pf, curve, invested_by_day, closed_log = compute_performance_equity(
        events_by_date, bars_by_ticker, calendar, PERF_START, END, master_ts)

    # ---- gross (no-cost) equity curve: same schedule, zero costs ----
    _, gross_curve, _, _ = compute_performance_equity(
        events_by_date, bars_by_ticker, calendar, PERF_START, END, master_ts,
        cost_multiplier=0.0)
    gross_return = M.total_return(gross_curve)

    trades = [{
        "symbol": p["symbol"],
        "entry_date": p["entry_date"], "entry_price": p["entry"].fill_price,
        "exit_date": p["exit"].fill_date, "exit_price": p["exit"].fill_price,
        "exit_type": p["exit"].fill_type,
        "shares": p["shares"], "pnl": p["pnl"],
        "holding_sessions": (pd.Timestamp(p["exit"].fill_date) - pd.Timestamp(p["entry_date"])).days,
        "entry_cost_bps": p["entry"].cost_bps, "exit_cost_bps": p["exit"].cost_bps,
    } for p in pf.closed_positions]

    # metrics
    total_return = M.total_return(curve)
    cagr = M.cagr(curve)
    mdd = M.max_drawdown(curve)
    sharpe = M.sharpe(curve)
    sortino = M.sortino(curve)
    calmar = M.calmar(curve)
    ts = M.trade_stats([{"pnl": t["pnl"], "holding_sessions": t["holding_sessions"]} for t in trades])

    exposure = float(np.mean(invested_by_day)) if invested_by_day else 0.0
    gross_notional = sum(t["shares"] * t["entry_price"] for t in trades) + \
                     sum(t["shares"] * t["exit_price"] for t in trades)
    avg_equity = float(np.mean([e for _, e in curve])) if curve else PORT_CFG.initial_capital
    turnover = gross_notional / avg_equity if avg_equity else 0.0
    tx_cost = sum(t["shares"] * t["entry_price"] * t["entry_cost_bps"] / 10000
                  + t["shares"] * t["exit_price"] * t["exit_cost_bps"] / 10000 for t in trades)

    first_trade = trades[0]["entry_date"] if trades else None
    last_trade = trades[-1]["exit_date"] if trades else None
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]

    # ---- Equal-weight universe benchmark (daily rebalanced) ----
    ew_curve = compute_ew_benchmark(bars_by_ticker, master_ts, PERF_START, END)

    # ---- Buy & Hold benchmark ----
    bh_t, bh_alloc = bh_trades(bars_by_ticker, PORT_CFG.initial_capital,
                               COST.entry_cost_bps, COST.exit_cost_bps)
    bh_curve_result = bh_curve(bars_by_ticker, bh_t, bh_alloc, PORT_CFG.initial_capital, master_dates)

    result = {
        "experiment": "MACD-KR-V1",
        "step": "STEP 2 SMOKE",
        "description": "MACD(12,26,9) cross Long-only, next-open entry/exit; listing-date PIT gate; performance 2016-01-01+",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "macd": {"fast": FAST, "slow": SLOW, "signal": SIGNAL,
                 "emaMethod": "ewm(span, adjust=False)",
                 "referenceMatch": "macd_from_close_series (macd_information_content_study.py)"},
        "scope": {
            "market": "KOSPI + KOSDAQ",
            "timeframe": "Daily",
            "universeMode": "A1A_ONLY",
            "tickersRequested": len(subset),
            "tickersWithData": len(features_by_ticker),
            "tickersNoData": no_data,
            "rawDataStart": RAW_START, "performanceStart": PERF_START, "end": END,
            "suspensionRowsDropped": suspension_dropped,
            "seed": args.seed,
            "tickers": sorted(subset),
        },
        "pit": {
            "listingGate": "yes (A1a listedAt)",
            "listingAtAppliedTickers": len([s for s in subset if s in listed_at]),
            "preListingSignalsDropped": pre_listing_sig,
            "warmupSignalsExcluded": sum(a["warmup_excluded"] for a in audits.values()),
        },
        "signals": {
            "bullishCrossTotal": total_bull,
            "entryFills": total_entry,
            "exitFills": total_exit,
        },
        "trades": {
            "count": len(trades),
            "firstTrade": first_trade,
            "lastTrade": last_trade,
            "winning": len(wins),
            "losing": len(losses),
            "avgHoldingSessions": ts["avgHoldingPeriod"],
        },
        "metrics": {
            "grossReturn": gross_return,  # no-cost (cost_multiplier=0) equity curve
            "netTotalReturn": total_return,
            "cagr": cagr,
            "mdd": mdd,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "exposure": exposure,
            "turnover": turnover,
            "transactionCostKRW": tx_cost,
            "finalEquity": pf.cash + sum(pos["shares"] * _p
                                         for pos, _p in _mark(pf, closes_last(bars_by_ticker))),
            "winRate": ts["winRate"],
            "profitFactor": ts["profitFactor"],
            "avgWin": ts["avgWin"], "avgLoss": ts["avgLoss"],
            "expectancy": ts["expectancy"],
            "tradeStats": ts,
        },
        "benchmarks": {
            "equalWeight": {
                "desc": "daily-rebalanced equal-weight of subset (same A1A_ONLY universe window)",
                "totalReturn": M.total_return(ew_curve),
                "cagr": M.cagr(ew_curve),
                "mdd": M.max_drawdown(ew_curve),
                "sharpe": M.sharpe(ew_curve),
            },
            "buyAndHold": {
                "desc": "buy each ticker at first close, hold to last close (b0_buy_hold)",
                "totalReturn": M.total_return(bh_curve_result),
                "cagr": M.cagr(bh_curve_result),
                "mdd": M.max_drawdown(bh_curve_result),
                "sharpe": M.sharpe(bh_curve_result),
            },
            "randomControl": {"note": "deferred - not built into shared engine (STEP-2 11); follow-up experiment"},
        },
        "yearlyBreakdown": _yearly(trades),
        "invariantChecks": {
            "sameBarExecution": _samebar_check(trades),
            "shortPositions": 0,  # enforced by construction
            "leverage": 0.0,      # enforced by construction (cash-backed, no margin)
            "preListingPositions": 0,  # verified via PRE-listing signal suppression
        },
    }

    print("\n=== MACD-KR-V1 SMOKE ===")
    print(f"tickers={len(subset)} signals(bullish cross)={total_bull} entries={total_entry} exits={total_exit}")
    print(f"closed trades={len(trades)} first={first_trade} last={last_trade} winrate={ts['winRate']}")
    print(f"pre-listing signals dropped={pre_listing_sig}")
    print(f"totalReturn={total_return:.4f} grossReturn={gross_return:.4f} cagr={cagr:.4f} mdd={mdd:.4f} sharpe={sharpe:.4f} "
          f"exposure={exposure:.2f} turnover={turnover:.2f}")
    print(f"tx cost KRW={tx_cost:,.0f}")
    print(f"EW bench totalReturn={M.total_return(ew_curve):.4f}  BH totalReturn={M.total_return(bh_curve_result):.4f}")
    print(f"elapsed={time.time()-t0:.1f}s")

    # write results
    report_dir = os.path.join(HERE, "findings", "macd-kr-v1-smoke")
    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, "smoke_result.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2, default=str)
    print("saved:", json_path)

    # save trades detail
    with open(os.path.join(report_dir, "all_trades.json"), "w", encoding="utf-8") as fh:
        json.dump(trades, fh, ensure_ascii=False, indent=2, default=str)
    print("saved trades:", os.path.join(report_dir, "all_trades.json"))


def _mark(pf, last_closes):
    return [(pos, last_closes.get(sym, pos["entry_fill"].fill_price))
            for sym, pos in pf.open_positions.items()]


def closes_last(bars_by_ticker):
    return {sym: float(df["close"].iloc[-1]) for sym, df in bars_by_ticker.items() if not df.empty}


def _samebar_check(trades):
    for t in trades:
        if t["entry_date"] >= t["exit_date"]:
            return {"violations": 1, "detail": t}
    return {"violations": 0}


def _yearly(trades):
    y = Counter()
    for t in trades:
        yy = t["exit_date"][:4]
        y[yy] += t["pnl"]
    return dict(sorted(y.items()))


def compute_ew_benchmark(bars_by_ticker, master_ts, perf_start, end):
    """Daily equal-weight (equal-weight-on-available) index over the same subset,
    close-to-close returns, compounding from 100. Suspension days carry the prior
    close (no return). Starts on the first master date >= perf_start."""
    dates = []
    rets = []
    last_close = {}
    for ts in master_ts:
        ds = ts.strftime("%Y-%m-%d")
        day_rets = []
        for sym, df in bars_by_ticker.items():
            if df.empty or ds not in df.index:
                continue
            px = float(df.loc[ds, "close"])
            if sym in last_close and last_close[sym] and last_close[sym] > 0:
                day_rets.append(px / last_close[sym] - 1.0)
            last_close[sym] = px
        if day_rets:
            dates.append(ds)
            rets.append(sum(day_rets) / len(day_rets))
    # compound
    curve = []
    eq = 100.0
    curve.append((dates[0], eq))
    for i in range(1, len(dates)):
        eq *= (1 + rets[i])
        curve.append((dates[i], eq))
    return curve


if __name__ == "__main__":
    main()
