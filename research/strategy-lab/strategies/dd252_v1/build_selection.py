#!/usr/bin/env python
"""Offline builder for DD252 selection.json - cross-sectional ranking
(which 30 tickers are closest to their 252-day high this month, among
tickers with 273+ session history) computed once offline.

engine's Strategy contract (compute_features/generate_signals) only sees
one symbol at a time (strategies/base.py), so cross-sectional ranking
must be precomputed. Same pattern as lowmom60_v1/build_selection.py.

Signal: dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1
- higher (closer to 0) = better (near high)
- descending rank → top 30

Universe: A1A_A1B_MERGED (include_delisted=True) — same panel as
dd252_survivorship_study.py.

Monthly rebalance (first trading day of each month per TradingCalendar).

Holding: 120 trading days fixed per signal (staggered cohort approx:
continuousHoldOnRenewal=false so each monthly signal gets fresh 120-day clock).

  python build_selection.py [--end YYYY-MM-DD]
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
sys.path.insert(0, _STRATEGY_LAB_DIR)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
START = "2016-01-01"
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-03"
TOP_N = 30
HOLD_SESSIONS = 120
MIN_HISTORY = 273  # 252 + 21 (skip-1m) sessions needed for dd_252_skip1m


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    a2b = None  # will load via merged provider pattern if needed
    # Use A2aProvider for all (A2a + A2b merged) via mergedPriceProvider path
    # But for build_selection we load price bars directly: merged universe needs A2a + A2b
    # Use the same approach as dd252_survivorship_study.py: load A2a for all, then A2b for A1B tickers
    from engine.data.a2bProvider import A2bProvider  # noqa: E402

    print(f"Universe: {len(universe.tickers)} tickers (A1A_A1B_MERGED)")
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}
    a1a_tickers = set(universe.tickers) - a1b_tickers
    print(f"  A1A: {len(a1a_tickers)}, A1B: {len(a1b_tickers)}")

    # Load A2a for all tickers (A1A + A1B that have A2a coverage)
    all_tickers = set(universe.tickers)
    bars_raw = a2a.load(all_tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    # Load A2b for A1B tickers and merge (A2b overrides A2a for those tickers)
    if a1b_tickers:
        a2b_provider = A2bProvider(repo_root=REPO_ROOT)
        a2b_raw = a2b_provider.load(a1b_tickers, START, END, universe_hash=universe.universe_hash)
        for t, df in a2b_raw.items():
            if not df.empty:
                bars_by_ticker[t] = _drop_suspension_rows(df)

    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < MIN_HISTORY:
            continue
        close = bars["close"]
        idx = close.index.astype(str)
        # dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()  # 252-21+1 = 232 window
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            val = dd.iloc[i]
            if pd.isna(val):
                continue
            rows.append({"ticker": ticker, "asOf": t, "dd_252_skip1m": float(val)})

    panel = pd.DataFrame(rows)
    print(f"panel rows={len(panel)}")

    # Arm A baseline: NO liquidity filter (filter is Arm C)
    # Just require valid signal (>=273 sessions history already enforced by min_periods)
    eligible = panel.dropna(subset=["dd_252_skip1m"])
    print(f"eligible rows={len(eligible)}")

    # holdSessions: fixed 120 for each signal (staggered cohort approx)
    hold_sessions_by_date = {t: HOLD_SESSIONS for t in rebalance_dates}

    selection = {}
    monthly_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        if asOf not in hold_sessions_by_date:
            continue
        # higher dd_252_skip1m (closer to 0) first → descending
        top = g.sort_values("dd_252_skip1m", ascending=False).head(TOP_N)
        monthly_counts[asOf] = len(top)
        for ticker in top["ticker"]:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf]})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection.py",
            "sourcePanel": "computed in-process from A2a/A2b bars (dd_252_skip1m) - MERGED universe",
            "period": f"{START} ~ {END}",
            "holdSessions": HOLD_SESSIONS,
            "topN": TOP_N,
            "minHistorySessions": MIN_HISTORY,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(monthly_counts)} months)")


if __name__ == "__main__":
    main()