#!/usr/bin/env python
"""Flow Persistence — 외국인 당일 vs 5D vs 20D 누적 수급비율 비교.

연구 질문: 외국인 당일 수급보다 최근 여러 거래일의 지속 수급이 미래수익률과
더 강한 관계를 가지는가?

Feature:
  당일  : foreign_flow_ratio = foreign_net / total_amount          (Step 2, KEEP)
  5D    : foreign_flow_5d_ratio = sum(foreign_net,5) / sum(total_amount,5)
  20D   : foreign_flow_20d_ratio = sum(foreign_net,20) / sum(total_amount,20)
          (기존 컬럼 foreign_nb20_ratio와 정의 일치 확인 후 재사용)

Forward: T+5, T+20, T+60 (A2a adjusted close, PIT)
Quantile: cross-sectional 5분위 (Q1=최저, Q5=최고)
Split: TRAIN 2016-01~2022-06 / VALID 2022-07~2024-01 / TEST 2024-01~2026-08
"""
import os

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-persistence-2026-08.md")

FEATURES = {
    "foreign_flow_ratio": "당일 외국인 수급",
    "foreign_flow_5d_ratio": "5D 누적 외국인 수급",
    "foreign_flow_20d_ratio": "20D 누적 외국인 수급",
}
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

    # T+5 forward (parquet에 fwd_d5 없음, Step2와 동일하게 계산)
    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)

    # 당일 비율 (Step 2와 동일)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)

    # 5D 누적 비율 = sum(foreign_net,5) / sum(total_amount,5)
    # (foreign_nb_5d는 이미 5d rolling 합 — 정의 일치. 분모는 직접 계산)
    amt5 = df.groupby("ticker")["total_amount"].transform(lambda s: s.rolling(5, min_periods=1).sum())
    df["foreign_flow_5d_ratio"] = df["foreign_nb_5d"] / amt5.replace(0, np.nan)

    # 20D 누적 비율: 기존 컬럼 foreign_nb20_ratio = sum(net,20)/sum(amount,20) 재사용
    df["foreign_flow_20d_ratio"] = df["foreign_nb20_ratio"]

    # 기존 컬럼 정의 일치 검증: 20d 비율을 직접 계산해 기존값과 대조
    amt20 = df.groupby("ticker")["total_amount"].transform(lambda s: s.rolling(20, min_periods=1).sum())
    manual20 = df["foreign_nb_20d"] / amt20.replace(0, np.nan)
    diff = (manual20 - df["foreign_nb20_ratio"]).abs()
    print(f"  20D ratio 재사용 검증: 일치율(오차<1e-9) = {(diff < 1e-9).mean():.4f}, "
          f"max 오차 = {diff.max():.2e}")

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

    cache = {}
    def get_qdf(feat, fwd, period=None):
        key = (feat, fwd, period)
        if key in cache:
            return cache[key]
        sub = df if period is None else df[(df["date"] >= period[0]) & (df["date"] < period[1])]
        qdf, _ = compute_quintile_spread(sub, feat, fwd)
        cache[key] = qdf
        return qdf

    lines = []
    lines.append("# Flow Persistence — 외국인 당일 vs 5D vs 20D 누적 수급비율")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 수급 연구 데이터셋 (Step 2와 동일)")
    lines.append(f"> 기간: {df['date'].min().date()} ~ {df['date'].max().date()} | 종목: {df['ticker'].nunique()} | 관측치: {len(df):,}")
    lines.append("> 연구 질문: 외국인 당일 수급보다 최근 여러 거래일의 지속 수급이 더 강한 관계인가?")
    lines.append("")
    lines.append("## 1. 세 Feature 비교 (전체 기간, Q5-Q1 spread)")
    lines.append("")
    lines.append("| Feature | 5D Return | 20D Return | 60D Return |")
    lines.append("|---|---:|---:|---:|")
    for feat in FEATURES:
        cells = []
        for fwd in HORIZONS:
            qdf = get_qdf(feat, fwd)
            if qdf is None:
                cells.append("-")
                continue
            st = spread_stats(qdf)
            cells.append(f"{st['mean']:+.4f} (NW {st['nw_t']:+.2f})")
        lines.append(f"| {FEATURES[feat]} | {' | '.join(cells)} |")
    lines.append("")
    lines.append("> 행 간 비교: 같은 열(지평)에서 누적수급이 당일수급보다 spread/nw t가 큰지 본다.")
    lines.append("")

    # ── 2. 세부 quintile (전체) + spread 상세 ──
    lines.append("## 2. Feature별 Quintile 상세 (전체 기간)")
    lines.append("")
    for feat in FEATURES:
        lines.append(f"### {FEATURES[feat]}")
        lines.append("")
        lines.append("| Horizon | Q1 | Q2 | Q3 | Q4 | Q5 | Q5-Q1 | Mean | Std | t-stat | NW t-stat | Obs |")
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

    # ── 3. TRAIN/VALID/TEST ──
    lines.append("## 3. TRAIN / VALID / TEST (Q5-Q1 spread)")
    lines.append("")
    for feat in FEATURES:
        lines.append(f"### {FEATURES[feat]}")
        lines.append("")
        lines.append("| Horizon | Period | Q5-Q1 | t-stat | NW t-stat | Obs |")
        lines.append("|---|---:|---|---:|---:|---:|")
        for fwd, fwd_name in HORIZONS.items():
            for pname, pspan in SPLIT.items():
                qdf = get_qdf(feat, fwd, pspan)
                if qdf is None:
                    lines.append(f"| {fwd_name} | {pname} | - | - | - | 0 |")
                    continue
                st = spread_stats(qdf)
                lines.append(f"| {fwd_name} | {pname} | {st['mean']:+.4f} | {st['t_stat']:.3f} | {st['nw_t']:.3f} | {st['n_days']} |")
        lines.append("")

    # ── 4. 유동성 ──
    lines.append("## 4. 유동성 비교 — 전체 vs 거래대금 상위 30%")
    lines.append("")
    for feat in FEATURES:
        lines.append(f"### {FEATURES[feat]}")
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

    # ── 5. 판정 ──
    lines.append("## 5. 판정")
    lines.append("")
    lines.append("### OOS 안정성 요약 (TEST에서 방향 유지 여부)")
    lines.append("")
    summary = {}
    for feat in FEATURES:
        summary[feat] = {}
        for fwd, fwd_name in HORIZONS.items():
            qdf = get_qdf(feat, fwd, SPLIT["TEST"])
            if qdf is not None:
                summary[feat][fwd_name] = spread_stats(qdf)

    # 당일 vs 누적 TEST 비교
    for fwd_name in HORIZONS.values():
        daily = summary["foreign_flow_ratio"].get(fwd_name)
        f5 = summary["foreign_flow_5d_ratio"].get(fwd_name)
        f20 = summary["foreign_flow_20d_ratio"].get(fwd_name)
        def c(s):
            return f"{s['mean']:+.4f}(NW{s['nw_t']:+.2f})" if s else "-"
        lines.append(f"- **{fwd_name} TEST**: 당일={c(daily)} | 5D={c(f5)} | 20D={c(f20)}")
    lines.append("")

    lines.append("### 판정")
    lines.append("")
    # 5D/20D 누적이 당일(OOS)보다 안정적/강한가?
    n_cum_better = 0
    for fwd_name in HORIZONS.values():
        daily = summary["foreign_flow_ratio"].get(fwd_name)
        for cum in ("foreign_flow_5d_ratio", "foreign_flow_20d_ratio"):
            c = summary[cum].get(fwd_name)
            if daily and c:
                if abs(c["nw_t"]) > abs(daily["nw_t"]) and c["mean"] > 0:
                    n_cum_better += 1
    if n_cum_better >= 4:
        verdict = "KEEP — 누적수급이 당일보다 TEST에서 더 강하거나 안정적"
    elif n_cum_better >= 1:
        verdict = "SAME / WEAK — 누적수급이 당일과 비슷하거나 부분 개선, 뚜렷한 우위 없음"
    else:
        verdict = "REJECT — 누적수급이 당일보다 명확히 열화"
    lines.append(f"**외국인 누적수급(persistence): {verdict}**")
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved: {OUT}")

    # 콘솔 요약
    print("\n=== 당일 vs 누적 (전체 기간, NW t) ===")
    for feat in FEATURES:
        parts = []
        for fwd, fwd_name in HORIZONS.items():
            qdf = get_qdf(feat, fwd)
            st = spread_stats(qdf) if qdf is not None else None
            parts.append(f"{fwd_name}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {FEATURES[feat]:18s} | {' | '.join(parts)}")
    print("\n=== TEST 방향 ===")
    for feat in FEATURES:
        parts = []
        for fwd, fwd_name in HORIZONS.items():
            qdf = get_qdf(feat, fwd, SPLIT["TEST"])
            st = spread_stats(qdf) if qdf is not None else None
            parts.append(f"{fwd_name}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {FEATURES[feat]:18s} | {' | '.join(parts)}")


if __name__ == "__main__":
    main()
