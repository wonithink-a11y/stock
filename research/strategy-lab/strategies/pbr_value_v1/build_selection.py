#!/usr/bin/env python
"""Offline builder for selection.json - the (ticker -> [rebalance dates selected])
table that rule.py loads at import time.

Cross-sectional ranking (which 30 tickers have the lowest PBR this month, among
tickers with turnover20 >= 1억원) cannot be computed inside generate_signals(symbol,
features), which only sees one symbol at a time (engine contract, strategies/
base.py). So this script does the cross-sectional pass once, offline, and writes
the result as a flat per-ticker signal-date list - rule.py then only has to do a
per-symbol membership lookup, which fits the existing contract with zero engine
changes.

Same panel, same liquidity threshold, same top-N as the validated precheck
(research/strategy-lab/a5_valuation_factor_precheck_v2_absolute.py,
lowPBR_high_liquidity_absoluteThreshold CAGR +7.06%, decile IC t=6.30 in
absolute_liquidity_decile_check.py) - this script does not re-derive the design,
it turns the already-validated design into a Strategy Lab-loadable artifact.

  python build_selection.py
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/pbr_value_v1
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # .../research/strategy-lab
sys.path.insert(0, _STRATEGY_LAB_DIR)

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))  # .../research/strategy-lab -> research -> REPO_ROOT
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
# 월별 라이브 리프레시 시 `python build_selection.py --end 2026-09-02`처럼
# CLI로 넘긴다 - 그 전에 scripts/build-a5-valuation-panel.js --end로 같은
# 날짜까지 valuation-panel.jsonl을 먼저 확장해야 한다. 로직은 무변경.
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-14"
TOP_N = 30
MIN_TURNOVER = 100_000_000.0


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
    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-value-v1-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    turnover_rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        turnover20 = (close * vol).rolling(20).mean()
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            tv = turnover20.iloc[i]
            if pd.isna(tv):
                continue
            turnover_rows.append({"ticker": ticker, "asOf": t, "turnover20": float(tv)})
    turnover_df = pd.DataFrame(turnover_rows)
    print(f"turnover rows={len(turnover_df)}")

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (pbr>0 & turnover20>={MIN_TURNOVER:,.0f}) rows={len(eligible)}")

    # holdSessions: 정확히 "다음 리밸런싱일 다음 거래일까지" 세션수(entry_date를
    # 세션 1로 셈, executor.py의 TIME_EXIT 규칙과 맞춤) - 고정 21일 근사 대신
    # 매 리밸런싱일마다 실제 거래일수를 반영한다(19~23일로 흔들리는 걸 정확히
    # 잡기 위함, 2026-08-21 사용자 확인 후 근사 대체).
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
        hold_sessions_by_date.setdefault(last_t, 21)  # 다음 리밸런싱일이 없는 마지막 달만 고정근사 유지

    selection = {}
    monthly_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        if asOf not in hold_sessions_by_date:
            continue
        top = g.sort_values("pbr", ascending=True).head(TOP_N)
        monthly_counts[asOf] = len(top)
        for ticker in top["ticker"]:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf]})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection.py",
            "sourcePanel": os.path.relpath(VALUATION_PANEL, REPO_ROOT),
            "period": f"{START} ~ {END}",
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
