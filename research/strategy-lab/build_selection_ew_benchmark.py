#!/usr/bin/env python
"""진단전용 - strategies/ew_benchmark_liquid_v1/selection.json 생성. pbr_value_v1의
build_selection.py와 완전히 동일한 유니버스·유동성 임계값·리밸런싱 스케줄이지만
PBR 랭킹 없이 그 달 turnover20>=1억원 적격종목 전부를 선택한다 - "전체 유니버스
EW" 벤치마크. 원본 pbr_value_v1/build_selection.py·selection.json은 안 건드린다.

  python build_selection_ew_benchmark.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
MIN_TURNOVER = 100_000_000.0
OUT_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "strategies",
                         "ew_benchmark_liquid_v1", "selection.json")


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
    # same ticker universe as pbr_value_v1 (tickers with a valid pbr value) -
    # "동일 유니버스" per the user's request, not the full A1a universe.
    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0]
    tickers = sorted(val["ticker"].unique())

    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-value-v1-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    hold_sessions_by_date = {}
    for k, t in enumerate(rebalance_dates[:-1]):
        entry_date = calendar.next_session(t)
        next_rebal = rebalance_dates[k + 1]
        exit_target = calendar.next_session(next_rebal)
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if rebalance_dates:
        hold_sessions_by_date.setdefault(rebalance_dates[-1], 21)

    selection = {}
    monthly_counts = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        turnover20 = (close * vol).rolling(20).mean()
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            if t not in hold_sessions_by_date:
                continue
            i = pos.get(t)
            if i is None:
                continue
            tv = turnover20.iloc[i]
            if pd.isna(tv) or tv < MIN_TURNOVER:
                continue
            selection.setdefault(ticker, []).append(
                {"date": t, "holdSessions": hold_sessions_by_date[t]})
            monthly_counts[t] = monthly_counts.get(t, 0) + 1

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_ew_benchmark.py (diag only)",
            "sourcePanel": os.path.relpath(VALUATION_PANEL, REPO_ROOT),
            "period": f"{START} ~ {END}", "minTurnover": MIN_TURNOVER,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "maxSelectedPerMonth": max(monthly_counts.values()) if monthly_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT_PATH} ({len(selection)} tickers, {len(monthly_counts)} months, "
          f"max/month={max(monthly_counts.values()) if monthly_counts else None})")


if __name__ == "__main__":
    main()
