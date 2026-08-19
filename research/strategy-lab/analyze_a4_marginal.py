#!/usr/bin/env python
"""A4 수급 feature 보완 분석 — marginal IC(다변량) · 개인축 상관관계 · 개인축 규모별 IC.

analyze_a4_research.py(2026-08-19, 다른 세션)가 남긴 3개 공백을 메운다:
  1. marginal IC — foreign_nb_20d·inst_nb_20d·indiv_nb_20d를 동시에 넣은 일별
     cross-sectional OLS(Fama-MacBeth 방식: 날짜별 회귀 → 계수 평균 + t검정).
     단변량 IC와 다르다 — 셋이 서로 상관돼 있으면 marginal 기여도가 달라질 수 있다.
  2. 개인축과 외국인/기관 20d의 상관관계 — 개인축을 추가해도 정보가 안 겹치는지.
  3. 개인축(indiv_nb_20d)의 규모(거래대금 3분위) 별 IC — 기존 분석은 외국인·기관만 봤다.

대상: research/strategy-lab/data/a4/a4-research-dataset.parquet (읽기 전용)
production 코드(lib/·config/)는 안 건드린다. 산출물은 이 디렉터리 안에만 쓴다.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-marginal-analysis.json")

FEATURES = ["foreign_nb_20d", "inst_nb_20d", "indiv_nb_20d"]
HORIZONS = {"fwd_d20": "20D", "fwd_d60": "60D", "fwd_d120": "120D"}


def compute_daily_ic(df, feature, fwd_col):
    ics = []
    for d, g in df.groupby("date"):
        g = g.dropna(subset=[feature, fwd_col])
        if len(g) < 30:
            continue
        r = spearmanr(g[feature], g[fwd_col])
        if not np.isnan(r.statistic):
            ics.append(r.statistic)
    return np.array(ics)


def fama_macbeth_daily(df, features, fwd_col):
    """날짜별로 fwd ~ features(표준화된 순위) OLS 회귀 → 계수 시계열 반환.
    순위(rank) 기반으로 하는 이유: 스케일이 서로 다른 세 feature를 동일 축으로 비교하려면
    cross-sectional IC와 같은 원리(그날 종목간 상대 순위)로 맞춰야 단변량 IC와 비교 가능하다."""
    coefs = {f: [] for f in features}
    n_used = 0
    for d, g in df.groupby("date"):
        g = g.dropna(subset=features + [fwd_col])
        if len(g) < 30:
            continue
        X = np.column_stack([rankdata(g[f].astype(float)) / len(g) for f in features])
        X = np.column_stack([np.ones(len(g)), X])
        y = g[fwd_col].astype(float).values
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        for i, f in enumerate(features):
            coefs[f].append(beta[i + 1])
        n_used += 1
    return coefs, n_used


def main():
    print("Loading parquet...")
    df = pd.read_parquet(DATA, columns=["ticker", "date", "foreign_nb_20d", "inst_nb_20d",
                                         "indiv_nb_20d", "total_amount", "fwd_d20", "fwd_d60", "fwd_d120"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"rows={len(df)} tickers={df['ticker'].nunique()}")

    results = {"config": {"period": [df["date"].min(), df["date"].max()], "nRows": len(df)}}

    # ── 1. Marginal IC (Fama-MacBeth) ──
    print("\n=== Marginal IC (foreign+inst+indiv 동시 회귀, 순위 기반) ===")
    marginal = {}
    for fwd, fwd_name in HORIZONS.items():
        coefs, n_used = fama_macbeth_daily(df, FEATURES, fwd)
        row = {}
        for f in FEATURES:
            arr = np.array(coefs[f])
            mean_c = float(arr.mean())
            std_c = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
            t = mean_c / (std_c / np.sqrt(len(arr))) if std_c > 0 else None
            row[f] = {"nDays": len(arr), "coefMean": round(mean_c, 5), "coefT": round(t, 3) if t else None}
            print(f"  {fwd_name} {f}: marginal_coef={mean_c:+.5f} (t={t:.2f})" if t else f"  {fwd_name} {f}: n/a")
        marginal[fwd] = row
    results["marginalIC"] = marginal

    # 비교용: 같은 기간 단변량 IC(순위 기반, analyze_a4_research.py와 동일 정의)
    print("\n=== 참고: 단변량 IC (marginal과 비교용) ===")
    univariate = {}
    for fwd, fwd_name in HORIZONS.items():
        row = {}
        for f in FEATURES:
            ics = compute_daily_ic(df, f, fwd)
            row[f] = round(float(ics.mean()), 5) if len(ics) else None
        univariate[fwd] = row
        print(f"  {fwd_name}: " + ", ".join(f"{f}={row[f]:+.5f}" for f in FEATURES if row[f] is not None))
    results["univariateIC_reference"] = univariate

    # ── 2. 개인축 vs 외국인/기관 20d 상관관계 (일별 cross-sectional, 평균) ──
    print("\n=== 개인축-외국인/기관 상관관계 (일별 순위 상관 평균) ===")
    corr = {}
    for other in ("foreign_nb_20d", "inst_nb_20d"):
        rs = []
        for d, g in df.groupby("date"):
            g = g.dropna(subset=["indiv_nb_20d", other])
            if len(g) < 30:
                continue
            r = spearmanr(g["indiv_nb_20d"], g[other])
            if not np.isnan(r.statistic):
                rs.append(r.statistic)
        arr = np.array(rs)
        corr[f"indiv_nb_20d_vs_{other}"] = {"nDays": len(arr), "corrMean": round(float(arr.mean()), 5),
                                            "corrStd": round(float(arr.std(ddof=1)), 5) if len(arr) > 1 else None}
        print(f"  indiv_nb_20d vs {other}: 평균상관={arr.mean():+.4f} (일별 표준편차={arr.std(ddof=1):.4f})")
    results["individualCorrelation"] = corr

    # ── 3. 개인축 규모별 IC (거래대금 3분위) ──
    print("\n=== 개인축 규모별 IC (total_amount 3분위, d60/d120) ===")
    df["size_tercile"] = df.groupby("date")["total_amount"].transform(
        lambda s: pd.qcut(rankdata(s.astype(float), method="ordinal"), 3, labels=[1, 2, 3]) if s.notna().sum() >= 3 else np.nan)
    size_ic = {}
    for fwd in ("fwd_d60", "fwd_d120"):
        row = {}
        for t in (1, 2, 3):
            sub = df[df["size_tercile"] == t]
            ics = compute_daily_ic(sub, "indiv_nb_20d", fwd)
            row[f"tercile{t}"] = {"nDays": int(len(ics)), "icMean": round(float(ics.mean()), 5) if len(ics) else None}
        size_ic[fwd] = row
        print(f"  {fwd}: " + ", ".join(f"T{t}:{row[f'tercile{t}']['icMean']}" for t in (1, 2, 3)))
    results["indiv_sizeIC"] = size_ic

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()
