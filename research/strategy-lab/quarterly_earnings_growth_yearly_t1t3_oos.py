#!/usr/bin/env python
"""quarterly_earnings_growth_factor_precheck.py(decile IC t=3.13, 이번 세션
최고 수치) 후속 - 채택 판단 전 이 프로젝트 표준 3종 검증을 전부 통과하는지
확인. PER·Lynch PEG가 바로 이 단계(특히 OOS)에서 무너졌으므로 신중하게
본다.

  1) 연도별 안정성 - PBR(2022 98.6%)·DD252(2026 104%) 같은 단일연도 쏠림 확인
  2) T1/T3 유동성 사후분해 - PBR 대형주 반전 패턴 재현 여부
  3) TRAIN/VALID/TEST(60/15/25 시간분할) OOS - 이 프로젝트 표준 채택 기준

quarterly_earnings_growth_factor_precheck.py의 데이터 로드·패널 구성을
그대로 재사용 - 새 계산·API 호출 없음.

  python quarterly_earnings_growth_yearly_t1t3_oos.py
"""
import json
import os

import numpy as np
import pandas as pd

from quarterly_earnings_growth_factor_precheck import (
    REPO_ROOT, load_growth_events, build_panel, monthly_rebalance_dates,
    run_backtest, decile_ic, START, END, TOP_N, COST_RT_BPS,
)
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.runner import _drop_suspension_rows

SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}


def yearly_stability(df):
    df = df.copy()
    df["year"] = df["entry_date"].str[:4]
    yearly = {}
    for year, g in df.groupby("year"):
        spreads = []
        for m, gm in g.groupby("entry_date"):
            if len(gm) < 30:
                continue
            gm = gm.copy()
            gm["decile"] = pd.qcut(gm["growth"].rank(method="first"), 10, labels=False) + 1
            d1 = gm[gm["decile"] == 1]["ret"].mean()
            d10 = gm[gm["decile"] == 10]["ret"].mean()
            if pd.notna(d1) and pd.notna(d10):
                spreads.append(d10 - d1)
        if not spreads:
            yearly[year] = {"nMonths": 0, "meanSpread": None, "t": None}
            continue
        sp = pd.Series(spreads)
        t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
        yearly[year] = {"nMonths": len(sp), "meanSpread": round(float(sp.mean()), 5),
                         "t": round(float(t), 2) if t is not None else None}
    return yearly


def bucket_stats(rets):
    rets = [r for r in rets if r is not None and not pd.isna(r)]
    if not rets:
        return {"count": 0, "meanReturn": None, "winRate": None}
    arr = np.array(rets)
    return {"count": len(arr), "meanReturn": round(float(arr.mean()), 4),
            "winRate": round(float((arr > 0).mean()), 4)}


def t1t3_decomposition(df):
    picks = []
    for m, g in df.groupby("entry_date"):
        picks.append(g.sort_values("growth", ascending=False).head(TOP_N))
    picked = pd.concat(picks)
    tvs = sorted(picked["turnover20"])
    n = len(tvs)
    lo_cut, hi_cut = tvs[n // 3], tvs[(2 * n) // 3]
    t1 = picked[picked["turnover20"] <= lo_cut]["ret"] - COST_RT_BPS / 1e4
    t3 = picked[picked["turnover20"] >= hi_cut]["ret"] - COST_RT_BPS / 1e4
    return {
        "totalPicks": len(picked),
        "relTercile_t1_bottom33pct_liquidity": bucket_stats(t1.tolist()),
        "relTercile_t3_top33pct_liquidity": bucket_stats(t3.tolist()),
    }


def split_by_month(df, fractions=SPLIT_FRACTIONS):
    months = sorted(df["entry_date"].unique())
    n = len(months)
    n_train = int(round(n * fractions["TRAIN"]))
    n_valid = int(round(n * fractions["VALID"]))
    train_m = set(months[:n_train])
    valid_m = set(months[n_train:n_train + n_valid])
    test_m = set(months[n_train + n_valid:])
    return {
        "TRAIN": (df[df["entry_date"].isin(train_m)], sorted(train_m)),
        "VALID": (df[df["entry_date"].isin(valid_m)], sorted(valid_m)),
        "TEST": (df[df["entry_date"].isin(test_m)], sorted(test_m)),
    }


def main():
    by_ticker = load_growth_events()
    tickers = sorted(by_ticker.keys())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="qtr-earnings-growth-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, by_ticker)
    print(f"panel rows={len(df)}, months={df['entry_date'].nunique()}")

    print("\n=== ① 연도별 안정성 (D10-D1 스프레드) ===")
    yearly = yearly_stability(df)
    neg_years = sum(1 for y in yearly.values() if y["meanSpread"] is not None and y["meanSpread"] < 0)
    total_years = sum(1 for y in yearly.values() if y["meanSpread"] is not None)
    for y in sorted(yearly):
        r = yearly[y]
        print(f"  {y}: nMonths={r['nMonths']:>2} meanSpread={r['meanSpread']} t={r['t']}")
    print(f"음(-) 부호 연도: {neg_years}/{total_years}")

    print("\n=== ② T1/T3 유동성 사후분해 (top-30 고성장, 유동성필터 없음) ===")
    t1t3 = t1t3_decomposition(df)
    print(json.dumps(t1t3, ensure_ascii=False, indent=2))

    print("\n=== ③ TRAIN/VALID/TEST(60/15/25 월별 시간분할) OOS ===")
    splits = split_by_month(df)
    oos = {}
    for name, (sub, months) in splits.items():
        bt = run_backtest(sub, direction="high", liquidity_filter=None)
        ic = decile_ic(sub)
        oos[name] = {"months": f"{months[0]}~{months[-1]}" if months else None,
                     "nMonths": len(months), "backtest": bt, "decileIC": ic}
        print(f"  {name} ({oos[name]['months']}, {len(months)}mo): "
              f"cagr={bt['cagr']} maxDD={bt['maxDD']} | "
              f"decileIC spread={ic['meanSpread(D10-D1)']} t={ic['t']} (n={ic['nMonths']}mo)")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-quarterly-earnings-growth-precheck")
    out_path = os.path.join(out_dir, "quarterly-earnings-growth-yearly-t1t3-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "context": "quarterly_earnings_growth_factor_precheck.py(decile IC t=3.13) 후속 - "
                       "연도별 안정성 + T1/T3 유동성 사후분해 + TRAIN/VALID/TEST OOS.",
            "yearlyStability": {"yearly": yearly, "negativeYears": neg_years, "totalYears": total_years},
            "t1t3": t1t3, "oos": oos,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
