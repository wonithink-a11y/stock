#!/usr/bin/env python
"""quarterly_earnings_growth_factor_precheck.py 후속 - OOS에서 나온 "TEST
(2024~2026)에서만 강해진다"는 편중이 매크로 국면(불장) 때문인지 확인.
DD252(analyze_dd252_arm_a_decomposition.py)가 이미 쓴 것과 동일한 방법론
(KOSPI 연간수익률 ±10% 기준 불장/약세장/횡보장 분류, classify_regime_by_year
그대로 재사용)을 이 팩터의 월별 decile 스프레드(D10-D1)에 적용한다.

quarterly_earnings_growth_factor_precheck.py의 데이터 로드·패널 구성을
그대로 재사용 - 새 계산·API 호출 없음.

  python quarterly_earnings_growth_regime_decomposition.py
"""
import json
import os

import numpy as np
import pandas as pd

from quarterly_earnings_growth_factor_precheck import (
    REPO_ROOT, load_growth_events, build_panel, monthly_rebalance_dates,
    START, END,
)
from analyze_dd252_arm_a_decomposition import classify_regime_by_year, KOSPI_PATH
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.runner import _drop_suspension_rows


def monthly_spread_series(df):
    """월별 (date, D10-D1 스프레드) - yearly_t1t3_oos.py의 decile_ic()와 같은
    계산이지만 집계 전 개별 월값을 그대로 반환한다."""
    out = []
    for m, g in df.groupby("entry_date"):
        if len(g) < 30:
            continue
        g = g.copy()
        g["decile"] = pd.qcut(g["growth"].rank(method="first"), 10, labels=False) + 1
        d1 = g[g["decile"] == 1]["ret"].mean()
        d10 = g[g["decile"] == 10]["ret"].mean()
        if pd.notna(d1) and pd.notna(d10):
            out.append((m, float(d10 - d1)))
    return sorted(out)


def main():
    by_ticker = load_growth_events()
    tickers = sorted(by_ticker.keys())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="qtr-earnings-growth-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, by_ticker)
    print(f"panel rows={len(df)}")

    spreads = monthly_spread_series(df)
    print(f"monthly spread series: {len(spreads)} months")

    regime_by_year = classify_regime_by_year(KOSPI_PATH)
    print("\n연도별 KOSPI 국면:", {y: r["regime"] for y, r in sorted(regime_by_year.items())})

    bucket = {}
    for m, sp in spreads:
        year = int(m[:4])
        regime = regime_by_year.get(year, {}).get("regime", "unknown")
        b = bucket.setdefault(regime, {"logSum": 0.0, "months": 0, "years": set()})
        b["logSum"] += float(np.log1p(sp))
        b["months"] += 1
        b["years"].add(year)

    total_log = sum(b["logSum"] for b in bucket.values())
    print(f"\n전체 로그초과분 합: {total_log:.4f}")
    print("\n=== 국면별 성과(D10-D1 스프레드, 로그합) ===")
    summary = {}
    for regime, b in sorted(bucket.items(), key=lambda kv: -kv[1]["logSum"]):
        share = b["logSum"] / total_log if total_log else None
        print(f"  {regime:>9}: years={sorted(b['years'])} months={b['months']} "
              f"logSum={b['logSum']:+.4f} share={share:+.1%}" if share is not None else
              f"  {regime:>9}: years={sorted(b['years'])} months={b['months']} logSum={b['logSum']:+.4f}")
        summary[regime] = {"years": sorted(b["years"]), "months": b["months"],
                           "logSum": round(b["logSum"], 4),
                           "shareOfTotal": round(share, 4) if share is not None else None}

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-quarterly-earnings-growth-precheck")
    out_path = os.path.join(out_dir, "quarterly-earnings-growth-regime-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "context": "quarterly_earnings_growth_factor_precheck.py 후속 - OOS TEST(2024~2026)"
                       "편중이 KOSPI 불장 국면 때문인지 확인. DD252와 동일 방법론"
                       "(classify_regime_by_year, KOSPI 연간 ±10%).",
            "regimeByYear": {str(y): r for y, r in regime_by_year.items()},
            "totalLogSum": round(total_log, 4), "regimeSummary": summary,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
