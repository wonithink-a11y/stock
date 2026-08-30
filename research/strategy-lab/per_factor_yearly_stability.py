#!/usr/bin/env python
"""per_factor_precheck.py 후속 - 저PER 팩터의 decile IC(D1-D10 스프레드,
t=1.90)가 특정 연도 하나에 몰린 착시인지, 전 기간 고르게 약한 신호인지
연도별로 쪼개서 확인한다(PBR·DD252 등에서 반복 써온 진단, 사용자 지시
2026-08-28).

per_factor_precheck.py의 데이터 로드·패널 구성 함수를 그대로 재사용 -
새 계산·API 호출 없음.
"""
import json

import pandas as pd

from per_factor_precheck import (
    REPO_ROOT, load_valuation_panel, build_panel, monthly_rebalance_dates,
    START, END,
)
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.runner import _drop_suspension_rows


def main():
    per_lookup = load_valuation_panel()
    tickers = sorted({t for t, _ in per_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="per-factor-precheck-v1")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, per_lookup)
    df["year"] = df["entry_date"].str[:4]

    print(f"전체 panel rows={len(df)}, 기간 {df['entry_date'].min()}~{df['entry_date'].max()}")

    yearly = {}
    for year, g in df.groupby("year"):
        spreads = []
        for m, gm in g.groupby("entry_date"):
            if len(gm) < 30:
                continue
            gm = gm.copy()
            gm["decile"] = pd.qcut(gm["per"].rank(method="first"), 10, labels=False) + 1
            d1 = gm[gm["decile"] == 1]["ret"].mean()
            d10 = gm[gm["decile"] == 10]["ret"].mean()
            if pd.notna(d1) and pd.notna(d10):
                spreads.append(d1 - d10)
        if not spreads:
            yearly[year] = {"nMonths": 0, "meanSpread": None, "t": None}
            continue
        sp = pd.Series(spreads)
        t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
        yearly[year] = {
            "nMonths": len(sp),
            "meanSpread": round(float(sp.mean()), 5),
            "t": round(float(t), 2) if t is not None else None,
        }

    print("\n연도별 decile IC (D1 저PER - D10 고PER):")
    neg_years, total_years = 0, 0
    for year in sorted(yearly):
        r = yearly[year]
        if r["meanSpread"] is not None:
            total_years += 1
            if r["meanSpread"] < 0:
                neg_years += 1
        print(f"  {year}: nMonths={r['nMonths']:>2} meanSpread={r['meanSpread']} t={r['t']}")

    print(f"\n음(-) 부호 연도: {neg_years}/{total_years}")

    out_path = "reports/2026-08-28-per-factor-precheck/per-yearly-stability.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"yearly": yearly, "negativeYears": neg_years, "totalYears": total_years},
                   f, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
