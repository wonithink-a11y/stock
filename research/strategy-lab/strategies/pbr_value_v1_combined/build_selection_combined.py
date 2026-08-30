#!/usr/bin/env python
"""Offline builder for pbr_value_v1_combined's selection.json - dropout
(회전율 제한) + MAX(복권효과) 제외 두 실험을 함께 적용한 조합.

build_selection_maxexcl.py와 완전히 같은 로직(MAX5 상위 20% 대체 없이 제외)
이되, BASELINE_SELECTION만 pbr_value_v1/selection.json 대신
pbr_value_v1_dropout/selection.json을 가리킨다 - dropout이 이미 만든 매달
보유 목록(회전율 제한 적용됨) 위에 MAX 제외를 한 겹 더 씌우는 것. 두 필터
모두 "이미 정해진 보유 후보에서 사후적으로 뺀다"는 같은 형태라 순서를 바꿔도
(MAX 제외 먼저 → dropout 나중) 의미가 달라지지 않는다는 점은 아니다 - dropout은
"전월 보유"를 매달 참조하므로, 만약 MAX제외를 먼저 적용해 dropout의 held
후보 자체가 줄어들면 dropout의 교체 로직(nDrop 예산)이 이번 조합과 다르게
움직인다. 이 스크립트는 "dropout이 이미 굳힌 보유목록에서 MAX만 추가로
빼기"만 하므로 두 실험이 각각 독립적으로 검증한 selection.json을 그대로
재사용하고, dropout 자체의 월별 교체 로직에는 손대지 않는다.

  python build_selection_combined.py
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/pbr_value_v1_combined
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # .../research/strategy-lab
sys.path.insert(0, _STRATEGY_LAB_DIR)

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
BASELINE_SELECTION = os.path.join(REPO_ROOT, "research", "strategy-lab", "strategies",
                                   "pbr_value_v1_dropout", "selection.json")
MIN_TURNOVER = 100_000_000.0
MAX_WINDOW = 21
MAX_TOP_N = 5
EXCLUSION_PERCENTILE = 0.8


def max5(daily_returns_window):
    top5 = sorted(daily_returns_window, reverse=True)[:MAX_TOP_N]
    return sum(top5) / len(top5) if top5 else None


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
    with open(BASELINE_SELECTION, encoding="utf-8") as f:
        baseline = json.load(f)
    START, END = baseline["period"].split(" ~ ")
    baseline_by_month = {}
    for ticker, entries in baseline["selection"].items():
        for e in entries:
            baseline_by_month.setdefault(e["date"], {})[ticker] = e["holdSessions"]
    print(f"baseline(dropout): {len(baseline['selection'])} tickers, {len(baseline_by_month)} months")

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-value-v1-combined-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    turnover_rows, max5_rows = [], []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        daily_ret = close.pct_change()
        turnover20 = (close * vol).rolling(20).mean()
        rolling_max5 = daily_ret.rolling(MAX_WINDOW).apply(
            lambda w: max5(list(w)), raw=False)
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            tv = turnover20.iloc[i]
            m5 = rolling_max5.iloc[i]
            if pd.isna(tv):
                continue
            turnover_rows.append({"ticker": ticker, "asOf": t, "turnover20": float(tv)})
            if not pd.isna(m5):
                max5_rows.append({"ticker": ticker, "asOf": t, "max5": float(m5)})
    turnover_df = pd.DataFrame(turnover_rows)
    max5_df = pd.DataFrame(max5_rows)
    print(f"turnover rows={len(turnover_df)}, max5 rows={len(max5_df)}")

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER]
    eligible = eligible.merge(max5_df, on=["ticker", "asOf"], how="left")
    print(f"eligible (pbr>0 & turnover20>={MIN_TURNOVER:,.0f}) rows={len(eligible)}, "
          f"of which max5 available={eligible['max5'].notna().sum()}")

    threshold_by_month = eligible.dropna(subset=["max5"]).groupby("asOf")["max5"].quantile(EXCLUSION_PERCENTILE)
    max5_lookup = {(r["ticker"], r["asOf"]): r["max5"] for _, r in max5_df.iterrows()}

    selection = {}
    monthly_kept = {}
    monthly_excluded = {}

    for asOf, holdings in baseline_by_month.items():
        threshold = threshold_by_month.get(asOf)
        kept_count, excluded_count = 0, 0
        for ticker, hold_sessions in holdings.items():
            m5 = max5_lookup.get((ticker, asOf))
            excluded = threshold is not None and m5 is not None and m5 >= threshold
            if excluded:
                excluded_count += 1
                continue
            kept_count += 1
            selection.setdefault(ticker, []).append({"date": asOf, "holdSessions": hold_sessions})
        monthly_kept[asOf] = kept_count
        monthly_excluded[asOf] = excluded_count

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    total_excluded = sum(monthly_excluded.values())
    total_baseline_slots = sum(len(h) for h in baseline_by_month.values())
    print(f"제외된 (ticker,month) 슬롯: {total_excluded}/{total_baseline_slots} "
          f"({total_excluded/total_baseline_slots:.1%})")
    print(f"월평균 보유종목수: dropout={total_baseline_slots/len(baseline_by_month):.1f} -> "
          f"combined={sum(monthly_kept.values())/len(monthly_kept):.1f}")

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_combined.py",
            "basedOnSelection": os.path.relpath(BASELINE_SELECTION, REPO_ROOT),
            "sourcePanel": os.path.relpath(VALUATION_PANEL, REPO_ROOT),
            "period": f"{START} ~ {END}",
            "maxWindow": MAX_WINDOW,
            "maxTopN": MAX_TOP_N,
            "exclusionPercentile": EXCLUSION_PERCENTILE,
            "rebalanceMonths": len(baseline_by_month),
            "avgSelectedPerMonthDropout": round(total_baseline_slots / len(baseline_by_month), 1),
            "avgSelectedPerMonthCombined": round(sum(monthly_kept.values()) / len(monthly_kept), 1),
            "totalExcludedSlots": total_excluded,
            "totalBaselineSlots": total_baseline_slots,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(baseline_by_month)} months)")


if __name__ == "__main__":
    main()
