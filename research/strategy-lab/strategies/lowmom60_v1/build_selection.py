#!/usr/bin/env python
"""Offline builder for selection.json - the (ticker -> [rebalance dates
selected]) table rule.py loads at import time.

Same reason as strategies/pbr_value_v1/build_selection.py: cross-sectional
ranking (which 30 tickers have the lowest 60D momentum this month, among
tickers with turnover20 >= 1억원) cannot be computed inside
generate_signals(symbol, features), which only sees one symbol at a time
(engine contract, strategies/base.py). This script does the cross-sectional
pass once, offline.

Same panel construction, same liquidity threshold, same top-N as the
validated precheck (lowmom60_institutional_eligible_precheck_v2_absolute.py,
high_liquidity_absoluteThreshold CAGR +13.90%, decile IC t=5.24 in
absolute_liquidity_decile_check.py) - this "Candidate C" (LOWMOM60 + absolute
liquidity filter) is what was actually validated. ChatGPT's Candidate A/B
(LOWMOM60 + a real institutional/foreign 20D net-buy filter, A4 data) were
never given a concrete filter design anywhere in this project's history and
are out of scope here (2026-08-24 decision).

  python build_selection.py
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/lowmom60_v1
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # .../research/strategy-lab
sys.path.insert(0, _STRATEGY_LAB_DIR)

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
START = "2016-01-01"
# Monthly live refresh: `python build_selection.py --end 2026-09-02` after
# data/backfill/price/a2a has been refreshed through that date (A2a is
# workflow_dispatch-only, not a standing daily feed). Same pattern as
# pbr_value_v1/build_selection.py; this strategy needs no separate JS
# valuation-panel step since it's price/volume-only.
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-14"
TOP_N = 30
MIN_TURNOVER = 100_000_000.0
MOM_WINDOW = 60


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
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash="lowmom60-v1-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        mom60 = close / close.shift(MOM_WINDOW) - 1
        turnover20 = (close * vol).rolling(20).mean()
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            m = mom60.iloc[i]
            tv = turnover20.iloc[i]
            if pd.isna(m) or pd.isna(tv):
                continue
            rows.append({"ticker": ticker, "asOf": t, "mom60": float(m), "turnover20": float(tv)})
    panel = pd.DataFrame(rows)
    print(f"panel rows={len(panel)}")

    eligible = panel[panel["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (turnover20>={MIN_TURNOVER:,.0f}) rows={len(eligible)}")

    # holdSessions: exact "sessions until the next rebalance date's next
    # tradable session" (entry_date counted as session 1) - same convention as
    # pbr_value_v1/build_selection.py, replacing that strategy's fixed
    # 21-session approximation which measurably cost it CAGR (2026-08-21
    # finding, +3.52% actual vs +7.06% precheck before the fix).
    hold_sessions_by_date = {}
    for k, t in enumerate(rebalance_dates[:-1]):
        entry_date = calendar.next_session(t)
        next_rebal = rebalance_dates[k + 1]
        exit_target = calendar.next_session(next_rebal)
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if rebalance_dates:
        last_t = rebalance_dates[-1]
        hold_sessions_by_date.setdefault(last_t, 21)  # last month only, no next rebalance date to bound it

    selection = {}
    monthly_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        if asOf not in hold_sessions_by_date:
            continue
        # lowest momentum first ("저모멘텀") - ascending on mom60
        bottom = g.sort_values("mom60", ascending=True).head(TOP_N)
        monthly_counts[asOf] = len(bottom)
        for ticker in bottom["ticker"]:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf]})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection.py",
            "sourcePanel": "computed in-process from A2a bars (mom60, turnover20) - no external panel file",
            "period": f"{START} ~ {END}",
            "momWindow": MOM_WINDOW,
            "topN": TOP_N,
            "minTurnover": MIN_TURNOVER,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(monthly_counts)} months)")


if __name__ == "__main__":
    main()
