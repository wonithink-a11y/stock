#!/usr/bin/env python
"""Flow Basic Effect — 당일 기관/외국인 수급비율 → 미래수익률 quintile 분석.

Feature:
  A: institution_flow_ratio = inst_net / total_amount
  B: foreign_flow_ratio = foreign_net / total_amount

Forward returns: T+5, T+20, T+60 (A2a adjusted close 기준, PIT)
Quintile: cross-sectional (날짜별 5분위)
Split: TRAIN 2016-01~2022-06 / VALID 2022-07~2024-01 / TEST 2024-01~2026-08
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr
from statsmodels.stats.sandwich_covariance import cov_hac

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-basic-effect-2026-08.md")

FEATURES = {
    "institution_flow_ratio": "Institution",
    "foreign_flow_ratio": "Foreign",
}
HORIZONS = {"fwd_d5": "5D", "fwd_d20": "20D", "fwd_d60": "60D"}
N_QUINTILE = 5

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-06-30"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def load_data():
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])

    # fwd_d5 계산: 종목별 날짜순 정렬 후 5행 뒤 close / 현재 close - 1
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)

    # Feature 계산
    df["institution_flow_ratio"] = df["inst_net"] / df["total_amount"].replace(0, np.nan)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)

    # total_amount 기반 유동성 pct rank
    df["amount_pct"] = df.groupby("date")["total_amount"].rank(pct=True)

    return df


def compute_quintile_spread(df, feat, fwd_col, n_quintile=5):
    """각 날짜별 quintile forward return + Q5-Q1 spread 시계열.

    Vectorized: date별 feature 순위 → 5분위. lambda qcut 대신 groupby.rank 사용.
    """
    sub = df.dropna(subset=[feat, fwd_col]).copy()
    if len(sub) == 0:
        return None, None

    # date 내 ordinal rank (1..N) → quintile (1..5)
    ranks = sub.groupby("date")[feat].rank(method="first")
    counts = sub.groupby("date")[feat].transform("count")
    sub["q"] = np.ceil(ranks / counts * n_quintile).astype(int).clip(1, n_quintile)

    # quintile별 평균을 date별로
    qmean = sub.groupby(["date", "q"])[fwd_col].mean().unstack()  # date x q
    qmean = qmean[[c for c in range(1, n_quintile + 1) if c in qmean.columns]]
    qmean["spread"] = qmean[n_quintile] - qmean[1]

    qdf = qmean.reset_index().set_index("date")
    qdf = qdf.dropna(subset=["spread"])
    return qdf, sub


def newey_west_tstat(series, lags=None):
    """Newey-West HAC t-stat for time-series mean."""
    x = series.dropna().values
    n = len(x)
    if n < 3:
        return np.nan, np.nan
    if lags is None:
        lags = int(np.floor(4 * (n / 100) ** (2 / 9)))
    mean = x.mean()
    demeaned = x - mean
    # Newey-West variance
    gamma0 = np.mean(demeaned ** 2)
    nw_var = gamma0
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)  # Bartlett kernel
        gamma_l = np.mean(demeaned[l:] * demeaned[:-l])
        nw_var += 2 * w * gamma_l
    se = np.sqrt(nw_var / n)
    t = mean / se if se > 0 else np.nan
    return mean / se if se > 0 else np.nan, se


def spread_stats(qdf):
    """Q5-Q1 spread에 대한 statistics."""
    s = qdf["spread"].dropna()
    n = len(s)
    mean = s.mean()
    std = s.std(ddof=1)
    t_stat = mean / (std / np.sqrt(n)) if std > 0 and n > 1 else np.nan
    nw_t, nw_se = newey_west_tstat(s)
    return {
        "mean": round(float(mean), 6),
        "std": round(float(std), 6),
        "t_stat": round(float(t_stat), 3) if not np.isnan(t_stat) else None,
        "nw_t_stat": round(float(nw_t), 3) if not np.isnan(nw_t) else None,
        "n_days": int(n),
    }


def quintile_means_table(qdf, n_quintile=5):
    """Quintile별 평균 수익률 테이블 (qdf columns = integer 1..n + spread)."""
    result = {}
    for q in range(1, n_quintile + 1):
        if q in qdf.columns:
            result[f"Q{q}"] = round(float(qdf[q].mean()), 6)
    result["Q5-Q1"] = round(float(qdf["spread"].mean()), 6)
    return result


def main():
    print("Loading data...")
    df = load_data()
    print(f"  rows={len(df)} tickers={df['ticker'].nunique()} "
          f"period={df['date'].min().date()}~{df['date'].max().date()}")
    print(f"  fwd_d5 coverage: {df['fwd_d5'].notna().mean():.1%}")

    results = {
        "period": [str(df["date"].min().date()), str(df["date"].max().date())],
        "nRows": len(df),
        "nTickers": int(df["ticker"].nunique()),
    }

    lines = []
    lines.append("# Flow Basic Effect — 당일 기관/외국인 수급비율 → 미래수익률")
    lines.append("")
    lines.append(f"> 분석 일시: 2026-08-28 | 데이터: A4 수급 연구 데이터셋")
    lines.append(f"> 기간: {df['date'].min().date()} ~ {df['date'].max().date()}")
    lines.append(f"> 종목 수: {df['ticker'].nunique()} | 관측치: {len(df):,}")
    lines.append(f"> Feature: institution_flow_ratio = inst_net / total_amount")
    lines.append(f"> Feature: foreign_flow_ratio = foreign_net / total_amount")
    lines.append(f"> Forward: T+5, T+20, T+60 (A2a adjusted close)")
    lines.append(f"> Quintile: cross-sectional 5분위 (Q1=최저, Q5=최고)")
    lines.append("")

    # ─── 전체 기간 결과 ───
    lines.append("## 1. Quintile Forward Return (전체 기간)")
    lines.append("")

    # 테이블 헤더
    header = "| Feature | Horizon | Q1 | Q2 | Q3 | Q4 | Q5 | Q5-Q1 | Mean | Std | t-stat | NW t-stat | Obs |"
    sep =    "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.append(header)
    lines.append(sep)

    for feat_key, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            qdf, sub = compute_quintile_spread(df, feat_key, fwd)
            if qdf is None:
                lines.append(f"| {feat_name} | {fwd_name} | - | - | - | - | - | - | - | - | - | - | 0 |")
                continue
            qt = quintile_means_table(qdf)
            stats = spread_stats(qdf)
            lines.append(
                f"| {feat_name} | {fwd_name} "
                f"| {qt['Q1']:.4f} | {qt['Q2']:.4f} | {qt['Q3']:.4f} | {qt['Q4']:.4f} | {qt['Q5']:.4f} "
                f"| {qt['Q5-Q1']:+.4f} "
                f"| {stats['mean']:+.6f} | {stats['std']:.6f} "
                f"| {stats['t_stat']:.3f} | {stats['nw_t_stat']:.3f} | {stats['n_days']} |"
            )
    lines.append("")

    # ─── 2. 시간 안정성 (TRAIN/VALID/TEST) ───
    lines.append("## 2. 시간 안정성 — Q5-Q1 Spread by Period")
    lines.append("")
    header2 = "| Feature | Horizon | Period | Q5-Q1 | t-stat | NW t-stat | Obs |"
    sep2 =    "|---|---:|---|---:|---:|---:|---:|"
    lines.append(header2)
    lines.append(sep2)

    split_results = {}
    for feat_key, feat_name in FEATURES.items():
        split_results[feat_key] = {}
        for fwd, fwd_name in HORIZONS.items():
            for period_name, (start, end) in SPLIT.items():
                mask = (df["date"] >= start) & (df["date"] < end)
                sub_df = df[mask]
                qdf, _ = compute_quintile_spread(sub_df, feat_key, fwd)
                if qdf is None:
                    lines.append(f"| {feat_name} | {fwd_name} | {period_name} | - | - | - | 0 |")
                    continue
                stats = spread_stats(qdf)
                direction = "+" if stats["mean"] > 0 else "-"
                lines.append(
                    f"| {feat_name} | {fwd_name} | {period_name} "
                    f"| {stats['mean']:+.6f} | {stats['t_stat']:.3f} | {stats['nw_t_stat']:.3f} | {stats['n_days']} |"
                )
                split_results[feat_key][f"{fwd_name}_{period_name}"] = stats
    lines.append("")

    # ─── 3. 방향 일관성 판정 ───
    lines.append("## 3. 방향 일관성")
    lines.append("")
    for feat_key, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            key = f"{fwd_name}"
            means = {}
            for period_name in SPLIT:
                k = f"{fwd_name}_{period_name}"
                if k in split_results[feat_key]:
                    means[period_name] = split_results[feat_key][k]["mean"]
            if len(means) == 3:
                all_pos = all(v > 0 for v in means.values())
                all_neg = all(v < 0 for v in means.values())
                train_dir = "POS" if means.get("TRAIN", 0) > 0 else "NEG"
                valid_dir = "POS" if means.get("VALID", 0) > 0 else "NEG"
                test_dir = "POS" if means.get("TEST", 0) > 0 else "NEG"
                consistent = (all_pos or all_neg)
                verdict = "CONSISTENT" if consistent else "INCONSISTENT"
                lines.append(f"- **{feat_name} {fwd_name}**: TRAIN={means['TRAIN']:+.4f}({train_dir}) "
                             f"VALID={means['VALID']:+.4f}({valid_dir}) "
                             f"TEST={means['TEST']:+.4f}({test_dir}) → **{verdict}**")
    lines.append("")

    # ─── 4. 유동성 확인 ───
    lines.append("## 4. 유동성 비교 — 전체 vs 상위 30%")
    lines.append("")
    header4 = "| Feature | Horizon | Universe | Q5-Q1 | NW t-stat | Obs |"
    sep4 =    "|---|---:|---|---:|---:|---:|"
    lines.append(header4)
    lines.append(sep4)

    df_top30 = df[df["amount_pct"] >= 0.70].copy()
    print(f"\n  Top 30% universe: {len(df_top30):,} rows ({len(df_top30)/len(df):.1%})")

    for feat_key, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            # 전체
            qdf_all, _ = compute_quintile_spread(df, feat_key, fwd)
            if qdf_all is not None:
                s_all = spread_stats(qdf_all)
                lines.append(f"| {feat_name} | {fwd_name} | All | {s_all['mean']:+.6f} | {s_all['nw_t_stat']:.3f} | {s_all['n_days']} |")
            # 상위 30%
            qdf_top, _ = compute_quintile_spread(df_top30, feat_key, fwd)
            if qdf_top is not None:
                s_top = spread_stats(qdf_top)
                lines.append(f"| {feat_name} | {fwd_name} | Top 30% | {s_top['mean']:+.6f} | {s_top['nw_t_stat']:.3f} | {s_top['n_days']} |")
    lines.append("")

    # ─── 5. 판정 ───
    lines.append("## 5. 판정")
    lines.append("")
    for feat_key, feat_name in FEATURES.items():
        all_consistent = True
        any_significant = False
        for fwd, fwd_name in HORIZONS.items():
            means = {}
            for period_name in SPLIT:
                k = f"{fwd_name}_{period_name}"
                if k in split_results[feat_key]:
                    means[period_name] = split_results[feat_key][k]["mean"]
            if len(means) == 3:
                consistent = all(v > 0 for v in means.values()) or all(v < 0 for v in means.values())
                if not consistent:
                    all_consistent = False
                # NW t-stat > 2 in at least one period
                for period_name in SPLIT:
                    k = f"{fwd_name}_{period_name}"
                    if k in split_results[feat_key]:
                        nw = split_results[feat_key][k].get("nw_t_stat")
                        if nw and abs(nw) > 2:
                            any_significant = True

        if all_consistent and any_significant:
            verdict = "KEEP"
        elif any_significant:
            verdict = "WEAK"
        else:
            verdict = "REJECT"
        lines.append(f"**{feat_name}**: {verdict}")
        if not all_consistent:
            lines.append(f"  - 방향 비일관: OOS에서 부호 반전 존재")
        if not any_significant:
            lines.append(f"  - 어떤 구간에서NW t-stat > 2에 도달하지 못함")
        lines.append("")

    # ─── 6. 부록: 결측률 ───
    lines.append("## 6. 부록 — Feature 결측률")
    lines.append("")
    for feat_key, feat_name in FEATURES.items():
        miss = df[feat_key].isna().mean()
        lines.append(f"- {feat_name}: {miss:.2%}")
    for fwd, fwd_name in HORIZONS.items():
        miss = df[fwd].isna().mean()
        lines.append(f"- {fwd_name}: {miss:.2%}")
    lines.append("")

    # 파일 쓰기
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved: {OUT}")

    # 콘솔 출력: 핵심 테이블
    print("\n=== Quintile Spread Summary (전체 기간) ===")
    for feat_key, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            qdf, _ = compute_quintile_spread(df, feat_key, fwd)
            if qdf is not None:
                qt = quintile_means_table(qdf)
                stats = spread_stats(qdf)
                print(f"  {feat_name:12s} {fwd_name:4s} Q5-Q1={qt['Q5-Q1']:+.4f} "
                      f"NW_t={stats['nw_t_stat']:+.3f} n={stats['n_days']}")

    print("\n=== Split Analysis ===")
    for feat_key, feat_name in FEATURES.items():
        for fwd, fwd_name in HORIZONS.items():
            parts = []
            for period_name in SPLIT:
                k = f"{fwd_name}_{period_name}"
                if k in split_results[feat_key]:
                    s = split_results[feat_key][k]
                    parts.append(f"{period_name}={s['mean']:+.4f}(NW {s['nw_t_stat']:+.3f})")
            print(f"  {feat_name:12s} {fwd_name:4s} {' | '.join(parts)}")


if __name__ == "__main__":
    main()
