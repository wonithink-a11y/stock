#!/usr/bin/env python
"""per_factor_precheck.py 후속 2건 — PBR이 거친 것과 같은 두 검증을 PER에
적용(사용자 지시 2026-08-28, "PER 검증부터"). 연도별 안정성(몰림 없음, 약한
신호)은 이미 확인됐다(per_factor_yearly_stability.py) - 남은 건 T1/T3
유동성 분해(PBR이 "대형주에서 반전"됐던 문제)와 TRAIN/VALID/TEST 시간분할
OOS(이 프로젝트 표준 검증).

per_factor_precheck.py의 데이터 로드·패널 구성 함수를 그대로 재사용 - 새
계산·API 호출 없음.

  python per_factor_t1t3_oos.py
"""
import json
import os

import numpy as np
import pandas as pd

from per_factor_precheck import (
    REPO_ROOT, load_valuation_panel, build_panel, monthly_rebalance_dates,
    run_backtest, decile_ic, START, END, TOP_N, COST_RT_BPS,
)
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.runner import _drop_suspension_rows

SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}


def bucket_stats(rets):
    rets = [r for r in rets if r is not None and not pd.isna(r)]
    if not rets:
        return {"count": 0, "meanReturn": None, "winRate": None}
    arr = np.array(rets)
    return {"count": len(arr), "meanReturn": round(float(arr.mean()), 4),
            "winRate": round(float((arr > 0).mean()), 4)}


def t1t3_decomposition(df):
    """전략이 실제로 고른(top-30, 유동성필터 없음) 종목들 내 상대 tercile 분해
    - run_pbr_t1t3_decomposition.py와 같은 방법론(이미 고정된 거래 집합의
    사후 진단, 상대 tercile을 필터로 쓸 때의 오염 문제와 다르다)."""
    picks = []
    for m, g in df.groupby("entry_date"):
        picks.append(g.sort_values("per", ascending=True).head(TOP_N))
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
    per_lookup = load_valuation_panel()
    tickers = sorted({t for t, _ in per_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="per-factor-precheck-v1")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, per_lookup)
    print(f"panel rows={len(df)}, months={df['entry_date'].nunique()}")

    print("\n=== T1/T3 유동성 분해 (top-30, 유동성필터 없음, 사후 진단) ===")
    t1t3 = t1t3_decomposition(df)
    print(json.dumps(t1t3, ensure_ascii=False, indent=2))

    print("\n=== TRAIN/VALID/TEST(60/15/25 월별 시간분할) OOS ===")
    splits = split_by_month(df)
    oos = {}
    for name, (sub, months) in splits.items():
        bt = run_backtest(sub, direction="low", liquidity_filter=None)
        ic = decile_ic(sub)
        oos[name] = {"months": f"{months[0]}~{months[-1]}" if months else None,
                     "nMonths": len(months), "backtest": bt, "decileIC": ic}
        print(f"  {name} ({oos[name]['months']}, {len(months)}mo): "
              f"cagr={bt['cagr']} maxDD={bt['maxDD']} | "
              f"decileIC spread={ic['meanSpread(D1-D10)']} t={ic['t']} (n={ic['nMonths']}mo)")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-per-factor-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "per-t1t3-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "context": "per_factor_precheck.py(decile IC t=1.90) 후속 - T1/T3 유동성 분해"
                       "(PBR 반전 패턴 재현 여부) + TRAIN/VALID/TEST OOS(이 프로젝트 표준 "
                       "검증, run_pbr_t1t3_decomposition.py·analyze_pead_quarterly_oos.py와 "
                       "같은 방법론).",
            "t1t3": t1t3, "oos": oos,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
