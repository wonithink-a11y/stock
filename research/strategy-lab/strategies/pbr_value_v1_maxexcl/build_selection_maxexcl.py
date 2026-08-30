#!/usr/bin/env python
"""Offline builder for pbr_value_v1_maxexcl's selection.json - a MAX(lottery
effect) exclusion counterfactual layered on top of pbr_value_v1's *existing*
selection.json (not re-derived from scratch, to avoid any drift between two
independently-computed top-30 rankings).

Why exclusion, not a scalar overlay (findings/
github-literature-return-enhancement-candidates-2026-08.md): MAX is a
per-stock characteristic (which names look like lottery tickets this month),
not a market-wide timing signal. pbr_exposure_overlay_vs_baseline_mtm.py's
exposure_frac scalar mechanic exists for macro-regime timing (same
composition, different weight on the whole curve) - it doesn't fit "drop
these specific names" at all. This script instead changes composition
directly: for each rebalance month, compute MAX5 (mean of the top-5 daily
returns over the trailing 21 sessions, Nartea/Wu/Liu 2014's definition) for
every ticker in that month's *eligible* universe (same turnover20>=1억 &
pbr>0 pool build_selection.py used - needed as the percentile reference, not
just the 30 already picked, so "top 20%" means top 20% of the market, the
standard academic MAX-quintile sort). Any of pbr_value_v1's 30 selected
names whose MAX5 falls in that eligible pool's top 20% get dropped - no
replacement. Some months end up holding fewer than 30 names; that's the
counterfactual itself ("what if we just hadn't bought the lottery-like
picks"), not a bug.

  python build_selection_maxexcl.py
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/pbr_value_v1_maxexcl
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
                                   "pbr_value_v1", "selection.json")
MIN_TURNOVER = 100_000_000.0
MAX_WINDOW = 21  # Nartea/Wu/Liu(2014)의 MAX5 정의 - 최근 21거래일 중 상위 5일 평균수익
MAX_TOP_N = 5
EXCLUSION_PERCENTILE = 0.8  # 그 달 적격 유니버스 내 MAX5 상위 20%(80th pct 이상) 제외


def max5(daily_returns_window):
    top5 = sorted(daily_returns_window, reverse=True)[:MAX_TOP_N]
    return sum(top5) / len(top5) if top5 else None


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("상위5 평균 - 균일 리턴", max5([0.01] * 10) == 0.01)
    check("상위5 평균 - 내림차순 상위만 반영", abs(max5([0.05, 0.04, 0.03, 0.02, 0.01, -0.9]) - 0.03) < 1e-9)
    check("표본이 5개 미만이면 있는 만큼 평균", abs(max5([0.02, 0.01]) - 0.015) < 1e-9)
    check("빈 리스트는 None", max5([]) is None)

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print(f"\n통과 {sum(c for _, c in checks)} · 실패 {sum(not c for _, c in checks)}")
    return 0 if ok else 1


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
    print(f"baseline: {len(baseline['selection'])} tickers, {len(baseline_by_month)} months")

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-value-v1-maxexcl-selection")
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
    print(f"월평균 보유종목수: baseline={total_baseline_slots/len(baseline_by_month):.1f} -> "
          f"maxexcl={sum(monthly_kept.values())/len(monthly_kept):.1f}")

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_maxexcl.py",
            "basedOnSelection": os.path.relpath(BASELINE_SELECTION, REPO_ROOT),
            "sourcePanel": os.path.relpath(VALUATION_PANEL, REPO_ROOT),
            "period": f"{START} ~ {END}",
            "maxWindow": MAX_WINDOW,
            "maxTopN": MAX_TOP_N,
            "exclusionPercentile": EXCLUSION_PERCENTILE,
            "rebalanceMonths": len(baseline_by_month),
            "avgSelectedPerMonthBaseline": round(total_baseline_slots / len(baseline_by_month), 1),
            "avgSelectedPerMonthMaxExcl": round(sum(monthly_kept.values()) / len(monthly_kept), 1),
            "totalExcludedSlots": total_excluded,
            "totalBaselineSlots": total_baseline_slots,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(baseline_by_month)} months)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
