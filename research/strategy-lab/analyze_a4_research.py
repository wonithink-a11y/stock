#!/usr/bin/env python
"""A4 수급 feature 분석 — IC/Rank IC, decile forward return, 조합, 연도별, 결측률, 규모별.

대상: research/strategy-lab/data/a4/a4-research-dataset.parquet (5.3M 행, 2,558종목)
기준: cross-sectional (하루에 종목들 간 순위 비교) — 날짜별로 feature 값을 종목 간
순위로 변환해 그 날짜의 forward return과 상관을 계산.

주의:
  - 전량 panel이라 상장 시점 편향/2008~2015 부재. 기간은 2016-01~2026-08.
  - cross-sectional IC는 feature 값 자체가 아니라 '그날 종목들 간 순위'와 forward return의
    Spearman 상관. Rank IC = 일별 IC의 평균 (분산 = 일별 IC의 표준편차).
  - decile은 날짜별 10분위 (10 = 가장 많은 순매수). n 표본 표기.
  - 과최적화 방지: threshold·가중치 조합은 이 스크립트에서 확정하지 않는다 — 방향성만 확인.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-analysis-results.json")

FEATURES = {
    "foreign_nb_5d": "외국인 순매수 5d 합",
    "foreign_nb_20d": "외국인 순매수 20d 합",
    "inst_nb_5d": "기관 순매수 5d 합",
    "inst_nb_20d": "기관 순매수 20d 합",
    "indiv_nb_5d": "개인 순매수 5d 합",
    "indiv_nb_20d": "개인 순매수 20d 합",
    "foreign_nb20_ratio": "외국인 20d 순매수/거래대금",
    "inst_nb20_ratio": "기관 20d 순매수/거래대금",
}
HORIZONS = {"fwd_d20": "20D", "fwd_d60": "60D", "fwd_d120": "120D"}
N_DECILE = 10


def compute_daily_ic(df, feature, fwd_col):
    """일별 cross-sectional Spearman: feature 순위 vs forward return."""
    ics = []
    for d, g in df.groupby("date"):
        g = g.dropna(subset=[feature, fwd_col])
        if len(g) < 30:
            continue
        r = spearmanr(g[feature], g[fwd_col])
        if not np.isnan(r.statistic):
            ics.append(r.statistic)
    return np.array(ics)


def main():
    print("Loading parquet...")
    df = pd.read_parquet(DATA)
    df = df.sort_values("date").reset_index(drop=True)
    print(f"rows={len(df)} tickers={df['ticker'].nunique()} period={df['date'].min()}~{df['date'].max()}")

    results = {"config": {"period": [df["date"].min(), df["date"].max()],
                          "nRows": len(df), "nTickers": int(df["ticker"].nunique()),
                          "note": "과최적화 방지: threshold 미확정, 방향성만 확인"}}

    # ── 1. IC / Rank IC (전체 기간, 일별 평균) ──
    print("\n=== IC / Rank IC (cross-sectional Spearman, 일별 평균) ===")
    ic_table = {}
    for feat, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            ics = compute_daily_ic(df, feat, fwd)
            if len(ics) == 0:
                ic_table[f"{feat}|{fwd}"] = {"nDays": 0, "icMean": None, "icStd": None, "icT": None}
                continue
            mean_ic = float(ics.mean())
            std_ic = float(ics.std(ddof=1)) if len(ics) > 1 else 0.0
            t = mean_ic / (std_ic / np.sqrt(len(ics))) if std_ic > 0 else None
            ic_table[f"{feat}|{fwd}"] = {"nDays": int(len(ics)), "icMean": round(mean_ic, 5),
                                         "icStd": round(std_ic, 5), "icT": round(t, 3) if t else None}
            print(f"  {feat_name} vs {fwd_name}: IC={mean_ic:+.5f} (t={t:.2f}, nDays={len(ics)})")
    results["ic"] = ic_table

    # ── 2. Decile forward return (날짜별 10분위, 10=최다 순매수) ──
    print("\n=== Decile forward return (10 = 최다 순매수) ===")
    decile_table = {}
    for feat in FEATURES:
        rows = []
        dg = df.dropna(subset=[feat])
        for fwd in HORIZONS:
            sub = dg.dropna(subset=[fwd])
            # 날짜별 rank → decile (0..9)
            dec = sub.groupby("date")[feat].transform(lambda s: pd.qcut(rankdata(s.astype(float), method="ordinal"),
                                                                        N_DECILE, labels=False))
            tmp = sub.copy()
            tmp["decile"] = dec.astype(int) + 1
            agg = tmp.groupby("decile")[fwd].agg(["count", "mean", "median"])
            rows.append({"horizon": HORIZONS[fwd],
                         "decileMean": {int(i): round(float(agg.loc[i, "mean"]), 5) for i in range(1, N_DECILE + 1)},
                         "decileMedian": {int(i): round(float(agg.loc[i, "median"]), 5) for i in range(1, N_DECILE + 1)},
                         "n": {int(i): int(agg.loc[i, "count"]) for i in range(1, N_DECILE + 1)}})
        decile_table[feat] = rows
    # 요약: d60만 인쇄
    for feat in FEATURES:
        for entry in decile_table[feat]:
            if entry["horizon"] == "60D":
                dm = entry["decileMean"]
                print(f"  {feat}: d60 mean D1={dm[1]:+.4f} D5={dm[5]:+.4f} D10={dm[10]:+.4f}")
    results["decile"] = decile_table

    # ── 3. 연도별 IC (외국인/기관/개인 20d vs d60) ──
    print("\n=== 연도별 IC (20d feature vs d60) ===")
    yearly_ic = {}
    for feat in ("foreign_nb_20d", "inst_nb_20d", "indiv_nb_20d", "foreign_nb20_ratio", "inst_nb20_ratio"):
        by_year = {}
        df["year"] = df["date"].str[:4]
        for y, gy in df.groupby("year"):
            ics = compute_daily_ic(gy, feat, "fwd_d60")
            by_year[y] = {"nDays": int(len(ics)),
                          "icMean": round(float(ics.mean()), 5) if len(ics) else None,
                          "icStd": round(float(ics.std(ddof=1)), 5) if len(ics) > 1 else None}
        yearly_ic[feat] = by_year
        print(f"  {feat}: " + ", ".join(f"{y}:{v['icMean']}" for y, v in by_year.items()))
    results["yearlyIC"] = yearly_ic

    # ── 4. 규모별 (거래대금 3분위 proxy) IC ──
    print("\n=== 규모별 IC (total_amount 3분위, d60) ===")
    size_ic = {}
    df["size_tercile"] = df.groupby("date")["total_amount"].transform(
        lambda s: pd.qcut(rankdata(s.astype(float), method="ordinal"), 3, labels=[1, 2, 3]) if s.notna().sum() >= 3 else np.nan)
    for feat in ("foreign_nb_20d", "inst_nb_20d", "foreign_nb20_ratio"):
        row = {}
        for t in (1, 2, 3):
            sub = df[df["size_tercile"] == t]
            ics = compute_daily_ic(sub, feat, "fwd_d60")
            row[f"tercile{t}"] = {"nDays": int(len(ics)), "icMean": round(float(ics.mean()), 5) if len(ics) else None}
        size_ic[feat] = row
        print(f"  {feat}: " + ", ".join(f"T{t}:{row[f'tercile{t}']['icMean']}" for t in (1, 2, 3)))
    results["sizeIC"] = size_ic

    # ── 5. 결측률 ──
    print("\n=== 결측률 (전체 panel) ===")
    missing = {}
    for col in list(FEATURES) + list(HORIZONS) + ["close", "total_amount"]:
        if col in df.columns:
            missing[col] = round(float(df[col].isna().mean()), 5)
    results["missingRate"] = missing
    print(json.dumps(missing, indent=2))

    # ── 6. 조합: 외국인 & 기관 동시 순매수 vs 동시 순매도 ──
    print("\n=== 조합: foreign 20d & inst 20d 동시 순매수/순매도 (d60) ===")
    d = df.dropna(subset=["foreign_nb_20d", "inst_nb_20d", "fwd_d60"])
    both_buy = d[(d["foreign_nb_20d"] > 0) & (d["inst_nb_20d"] > 0)]
    both_sell = d[(d["foreign_nb_20d"] < 0) & (d["inst_nb_20d"] < 0)]
    f_only = d[(d["foreign_nb_20d"] > 0) & (d["inst_nb_20d"] < 0)]
    i_only = d[(d["foreign_nb_20d"] < 0) & (d["inst_nb_20d"] > 0)]
    combo = {
        "bothBuy": {"n": int(len(both_buy)), "meanD60": round(float(both_buy["fwd_d60"].mean()), 5),
                    "winRate": round(float((both_buy["fwd_d60"] > 0).mean()), 4)},
        "bothSell": {"n": int(len(both_sell)), "meanD60": round(float(both_sell["fwd_d60"].mean()), 5),
                     "winRate": round(float((both_sell["fwd_d60"] > 0).mean()), 4)},
        "foreignOnly": {"n": int(len(f_only)), "meanD60": round(float(f_only["fwd_d60"].mean()), 5)},
        "instOnly": {"n": int(len(i_only)), "meanD60": round(float(i_only["fwd_d60"].mean()), 5)},
    }
    results["combo"] = combo
    print(json.dumps(combo, indent=2, ensure_ascii=False))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {OUT}")


if __name__ == "__main__":
    main()