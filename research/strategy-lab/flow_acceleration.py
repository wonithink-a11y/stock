#!/usr/bin/env python
"""Flow Acceleration — 외국인 수급의 '절대 수준'이 아니라 '평소 대비 변화' 검증.

질문: 외국인이 평소보다 갑자기 강하게 순매수하기 시작한 종목에서 향후 수익률이 더 좋아지는가?

Feature:
  foreign_flow_acceleration = foreign_flow_1d_ratio - foreign_flow_20d_ratio
                            = (foreign_net / total_amount) - (foreign_nb20_ratio)
  (기존 A4에 동일 의미 컬럼 없음 → 정의대로 계산. 1d ratio = 당일 비율(Step2와 동일),
   20d ratio = foreign_nb20_ratio(Step3에서 정의 일치 검증 완료))

비교 feature:
  1. 당일 foreign_flow_ratio (Step 2)
  2. 5D cumulative (foreign_flow_5d_ratio, Step 3)
  3. foreign_flow_acceleration (본 단계)

Forward: T+5, T+20, T+60 (A2a adjusted close, PIT)
Quantile: cross-sectional 5분위 (Q1=가장 약해짐, Q5=가장 강해짐)
Split: TRAIN 2016-01~2022-06 / VALID 2022-07~2024-01 / TEST 2024-01~2026-08
"""
import os

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-acceleration-2026-08.md")

HORIZONS = {"fwd_d5": "5D", "fwd_d20": "20D", "fwd_d60": "60D"}
N_QUINTILE = 5

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-07-01"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def load_data():
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    # T+5 forward (A4에 fwd_d5 없음 → Step2와 동일하게 계산)
    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)

    # 당일 비율 (Step 2)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)

    # 5D 누적 비율 (Step 3) — 재사용 비교 대상
    amt5 = df.groupby("ticker")["total_amount"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    df["foreign_flow_5d_ratio"] = df["foreign_nb_5d"] / amt5.replace(0, np.nan)

    # 20D 누적 비율 = foreign_nb20_ratio (Step3에서 동일 정의 확인)
    # acceleration = 1D ratio - 20D ratio
    df["foreign_flow_acceleration"] = df["foreign_flow_ratio"] - df["foreign_nb20_ratio"]

    # 유동성 pct rank
    df["amount_pct"] = df.groupby("date")["total_amount"].rank(pct=True)
    return df


def compute_quintile_spread(df, feat, fwd_col, n_quintile=5):
    sub = df.dropna(subset=[feat, fwd_col]).copy()
    if len(sub) == 0:
        return None, None
    ranks = sub.groupby("date")[feat].rank(method="first")
    counts = sub.groupby("date")[feat].transform("count")
    sub["q"] = np.ceil(ranks / counts * n_quintile).astype(int).clip(1, n_quintile)
    qmean = sub.groupby(["date", "q"])[fwd_col].mean().unstack()
    cols = [c for c in range(1, n_quintile + 1) if c in qmean.columns]
    qmean = qmean[cols]
    qmean["spread"] = qmean[n_quintile] - qmean[1]
    qdf = qmean.reset_index().set_index("date").dropna(subset=["spread"])
    return qdf, sub


def newey_west_tstat(series):
    x = series.dropna().values
    n = len(x)
    if n < 3:
        return np.nan
    lags = int(np.floor(4 * (n / 100) ** (2 / 9)))
    mean = x.mean()
    demeaned = x - mean
    gamma0 = np.mean(demeaned ** 2)
    nw_var = gamma0
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        gamma_l = np.mean(demeaned[l:] * demeaned[:-l])
        nw_var += 2 * w * gamma_l
    se = np.sqrt(nw_var / n)
    return mean / se if se > 0 else np.nan


def spread_stats(qdf):
    s = qdf["spread"].dropna()
    n = len(s)
    mean = s.mean()
    std = s.std(ddof=1)
    t_stat = mean / (std / np.sqrt(n)) if std > 0 and n > 1 else np.nan
    return {
        "mean": float(mean),
        "t_stat": float(t_stat) if not np.isnan(t_stat) else np.nan,
        "nw_t": newey_west_tstat(s),
        "n_days": int(n),
    }


def main():
    print("Loading data...")
    df = load_data()
    feat = "foreign_flow_acceleration"

    cache = {}
    def get_qdf(f, fwd, period=None):
        key = (f, fwd, period)
        if key in cache:
            return cache[key]
        sub = df if period is None else df[(df["date"] >= period[0]) & (df["date"] < period[1])]
        qdf, _ = compute_quintile_spread(sub, f, fwd)
        cache[key] = qdf
        return qdf

    lines = []
    lines.append("# Flow Acceleration — 외국인 수급 '수준' vs '평소 대비 변화'")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 수급 연구 데이터셋 (Step 2/3과 동일)")
    lines.append(f"> 기간: {df['date'].min().date()} ~ {df['date'].max().date()} | 종목: {df['ticker'].nunique()} | 관측치: {len(df):,}")
    lines.append("> 질문: 외국인이 평소보다 갑자기 강하게 순매수하기 시작한 종목에서 향후 수익률이 더 좋아지는가?")
    lines.append("")
    lines.append("## 0. Feature 정의")
    lines.append("")
    lines.append("```")
    lines.append("foreign_flow_acceleration = foreign_flow_1d_ratio - foreign_flow_20d_ratio")
    lines.append("                          = (foreign_net/total_amount) - foreign_nb20_ratio")
    lines.append("```")
    lines.append("")
    lines.append("> 기존 A4에 동일 의미 컬럼 없음(확인) → 정의대로 계산. 1D ratio는 당일 비율(Step2와 동일),")
    lines.append("> 20D ratio는 foreign_nb20_ratio 재사용(Step3에서 정의 일치 검증 완료).")
    lines.append("")

    # ── 1. 전 feature 비교 (전체 기간, Q5-Q1 spread) ──
    lines.append("## 1. 세 Feature 비교 (전체 기간, Q5-Q1 spread)")
    lines.append("")
    lines.append("| Feature | 5D Return | 20D Return | 60D Return |")
    lines.append("|---|---:|---:|---:|")
    cmp_feats = {
        "foreign_flow_ratio": "당일 외국인 수급 (수준)",
        "foreign_flow_5d_ratio": "5D 누적 외국인 수급",
        feat: "foreign_flow_acceleration (변화)",
    }
    for f in cmp_feats:
        cells = []
        for fwd in HORIZONS:
            qdf = get_qdf(f, fwd)
            if qdf is None:
                cells.append("-")
                continue
            st = spread_stats(qdf)
            cells.append(f"{st['mean']:+.4f} (NW {st['nw_t']:+.2f})")
        lines.append(f"| {cmp_feats[f]} | {' | '.join(cells)} |")
    lines.append("")

    # ── 2. Acceleration quintile 상세 (전체) ──
    lines.append("## 2. foreign_flow_acceleration Quintile 상세 (전체 기간)")
    lines.append("")
    lines.append("| Horizon | Q1(약해짐) | Q2 | Q3 | Q4 | Q5(강해짐) | Q5-Q1 | Mean | Std | t-stat | NW t-stat | Obs |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for fwd, fwd_name in HORIZONS.items():
        qdf = get_qdf(feat, fwd)
        if qdf is None:
            lines.append(f"| {fwd_name} | - | - | - | - | - | - | - | - | - | - | 0 |")
            continue
        st = spread_stats(qdf)
        qv = [float(qdf[q].mean()) for q in range(1, N_QUINTILE + 1)]
        lines.append(
            f"| {fwd_name} | {qv[0]:.4f} | {qv[1]:.4f} | {qv[2]:.4f} | {qv[3]:.4f} | {qv[4]:.4f} "
            f"| {st['mean']:+.4f} | {st['mean']:+.6f} | {qdf['spread'].std(ddof=1):.6f} "
            f"| {st['t_stat']:.3f} | {st['nw_t']:.3f} | {st['n_days']} |"
        )
    lines.append("")

    # ── 3. Acceleration TRAIN/VALID/TEST ──
    lines.append("## 3. foreign_flow_acceleration TRAIN / VALID / TEST")
    lines.append("")
    lines.append("| Horizon | Period | Q5-Q1 | t-stat | NW t-stat | 방향 | Obs |")
    lines.append("|---|---:|---|---:|---:|---:|---:|")
    for fwd, fwd_name in HORIZONS.items():
        for pname, pspan in SPLIT.items():
            qdf = get_qdf(feat, fwd, pspan)
            if qdf is None:
                lines.append(f"| {fwd_name} | {pname} | - | - | - | - | 0 |")
                continue
            st = spread_stats(qdf)
            direction = "+" if st["mean"] > 0 else "-"
            lines.append(f"| {fwd_name} | {pname} | {st['mean']:+.4f} | {st['t_stat']:.3f} | {st['nw_t']:.3f} | {direction} | {st['n_days']} |")
    lines.append("")

    # ── 4. 세 feature의 TEST 비교 (nw t) ──
    lines.append("## 4. 세 Feature TEST 비교 (OOS, Q5-Q1 spread)")
    lines.append("")
    lines.append("| Feature | 5D Return | 20D Return | 60D Return |")
    lines.append("|---|---:|---:|---:|")
    for f in cmp_feats:
        cells = []
        for fwd in HORIZONS:
            qdf = get_qdf(f, fwd, SPLIT["TEST"])
            if qdf is None:
                cells.append("-")
                continue
            st = spread_stats(qdf)
            cells.append(f"{st['mean']:+.4f} (NW {st['nw_t']:+.2f})")
        lines.append(f"| {cmp_feats[f]} | {' | '.join(cells)} |")
    lines.append("")

    # ── 5. 유동성 ──
    lines.append("## 5. 유동성 비교 — 전체 vs 거래대금 상위 30% (acceleration)")
    lines.append("")
    lines.append("| Universe | Horizon | Q5-Q1 | NW t-stat | Obs |")
    lines.append("|---|---:|---|---:|---:|")
    df_top = df[df["amount_pct"] >= 0.70]
    for univ_name, sub in (("All", df), ("Top 30%", df_top)):
        for fwd, fwd_name in HORIZONS.items():
            qdf, _ = compute_quintile_spread(sub, feat, fwd)
            if qdf is None:
                lines.append(f"| {univ_name} | {fwd_name} | - | - | 0 |")
                continue
            st = spread_stats(qdf)
            lines.append(f"| {univ_name} | {fwd_name} | {st['mean']:+.4f} | {st['nw_t']:.3f} | {st['n_days']} |")
    lines.append("")

    # ── 6. 판정 ──
    lines.append("## 6. 판정")
    lines.append("")
    acc = {}
    for fwd in HORIZONS:
        acc[fwd] = spread_stats(get_qdf(feat, fwd, SPLIT["TEST"])) if get_qdf(feat, fwd, SPLIT["TEST"]) is not None else None
        if get_qdf(feat, fwd, SPLIT["TEST"]) is None:
            # falls through
            pass

    # dir consistency across TRAIN/VALID/TEST
    dirs = {}
    for fwd in HORIZONS:
        ds = []
        for pname in SPLIT:
            qdf = get_qdf(feat, fwd, SPLIT[pname])
            ds.append((pname, spread_stats(qdf)["mean"] > 0 if qdf is not None else None))
        dirs[fwd] = ds
    lines.append("**방향 일관성(acceleration)**:")
    for fwd_name, ds in dirs.items():
        parts = [f"{p}={'+' if (m is True) else ('-' if m is False else '?')}" for p, m in ds]
        lines.append(f"- {fwd_name}: {' | '.join(parts)}")
    lines.append("")

    # verdict: does acceleration beat daily (수준) in OOS?
    lines.append("**가설 비교 — '수준' vs '변화' (TEST NW t)**:")
    lines.append("")
    lines.append("| Horizon | 당일(수준) NW | acceleration NW | 개선? |")
    lines.append("|---|---:|---:|---|")
    n_better = 0
    for fwd, fwd_name in HORIZONS.items():
        dq = get_qdf("foreign_flow_ratio", fwd, SPLIT["TEST"])
        aq = get_qdf(feat, fwd, SPLIT["TEST"])
        dnw = spread_stats(dq)["nw_t"] if dq is not None else np.nan
        anw = spread_stats(aq)["nw_t"] if aq is not None else np.nan
        better = (abs(anw) > abs(dnw)) and anw > 0
        if better:
            n_better += 1
        lines.append(f"| {fwd_name} | {dnw:+.2f} | {anw:+.2f} | {'YES' if better else 'no'} |")
    lines.append("")

    if n_better >= 2:
        verdict = "KEEP — acceleration이 OOS에서 당일(수준)보다 정보력 개선"
    elif n_better >= 1:
        verdict = "WEAK — 관계는 존재하나 당일(수준) 대비 뚜렷한 개선 없음"
    else:
        verdict = "REJECT — acceleration이 TEST에서 당일(수준)보다 열화/무의미"
    lines.append(f"**외국인 수급 acceleration: {verdict}**")
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved: {OUT}")

    print("\n=== 전체 기간 (NW t) ===")
    for f in cmp_feats:
        parts = []
        for fwd, fwd_name in HORIZONS.items():
            qdf = get_qdf(f, fwd)
            st = spread_stats(qdf) if qdf is not None else None
            parts.append(f"{fwd_name}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {cmp_feats[f]:34s} | {' | '.join(parts)}")
    print("\n=== TEST (NW t) ===")
    for f in cmp_feats:
        parts = []
        for fwd, fwd_name in HORIZONS.items():
            qdf = get_qdf(f, fwd, SPLIT["TEST"])
            st = spread_stats(qdf) if qdf is not None else None
            parts.append(f"{fwd_name}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {cmp_feats[f]:34s} | {' | '.join(parts)}")
    print("\n=== Acceleration TRAIN/VALID/TEST (NW t) ===")
    for fwd, fwd_name in HORIZONS.items():
        parts = []
        for pname in SPLIT:
            qdf = get_qdf(feat, fwd, SPLIT[pname])
            st = spread_stats(qdf) if qdf is not None else None
            parts.append(f"{pname}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {fwd_name:4s} | {' | '.join(parts)}")


if __name__ == "__main__":
    main()
