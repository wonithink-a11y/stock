#!/usr/bin/env python
"""Flow Regime Effect — 외국인 당일 수급 효과가 시장 국면에 따라 달라지는가?

핵심 Feature: foreign_flow_ratio = foreign_net / total_amount (Step 2와 동일 정의)
국면: 기존 Research Lab market-regime (regime_labels.parquet)
  Risk-On / Neutral / Risk-Off (VIX·trend60·breadth·USD/KRW 4축, score 합>=+2/-<=-2)
  기존 정의 그대로 사용, 새 regime·threshold 최적화 없음.
PIT: 신호일 t의 regime = usableFromDate==t 인 라벨 (기존 regime-conditional 관례와 동일).

Forward: T+5, T+20, T+60 (A2a adjusted close)
Quantile: 국면 내 cross-sectional 5분위 (Q1=최저수급, Q5=최고수급)
Split: TRAIN 2016-01~2022-06 / VALID 2022-07~2024-01 / TEST 2024-01~2026-08
"""
import os

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-regime-effect-2026-08.md")

HORIZONS = {"fwd_d5": "5D", "fwd_d20": "20D", "fwd_d60": "60D"}
N_QUINTILE = 5
REGIMES = ["Risk-On", "Neutral", "Risk-Off"]

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-07-01"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def load_data():
    df = pd.read_parquet(DATA)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)
    df["amount_pct"] = df.groupby("date")["total_amount"].rank(pct=True)
    return df


def load_regimes():
    rl = pd.read_parquet(REGIME_PATH)
    # PIT: 신호일 t의 regime = usableFromDate==t 라벨 (기존 regime-conditional 관례)
    lut = rl.dropna(subset=["usableFromDate", "regime"])[["usableFromDate", "regime"]].copy()
    lut["usableFromDate"] = pd.to_datetime(lut["usableFromDate"])
    lut = lut.drop_duplicates("usableFromDate").rename(columns={"usableFromDate": "date"})
    return lut


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
    if n == 0:
        return {"mean": np.nan, "t_stat": np.nan, "nw_t": np.nan, "n_days": 0}
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
    regimes = load_regimes()
    df = df.merge(regimes, on="date", how="left")
    print(f"  rows={len(df)} tickers={df['ticker'].nunique()}")
    print(f"  regime coverage: {df['regime'].notna().mean():.1%}")
    print(f"  regime counts: {df['regime'].value_counts(dropna=False).to_dict()}")
    feat = "foreign_flow_ratio"

    lines = []
    lines.append("# Flow Regime Effect — 외국인 당일 수급 효과 × 시장 국면")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 (Step 2와 동일) + 기존 market-regime")
    lines.append(f"> 기간: {df['date'].min().date()} ~ {df['date'].max().date()} | 종목: {df['ticker'].nunique()}")
    lines.append("> 질문: 외국인 당일 순매수 효과가 시장 상승/하락 국면에 따라 달라지는가?")
    lines.append("")
    lines.append("## 0. 사용한 시장 국면 (기존 정의 그대로, 최적화 없음)")
    lines.append("")
    lines.append("- 원천: `data/market-regime/regime_labels.parquet` (`build_regime_definition.py`, 2026-08-23)")
    lines.append("- 4축 점수 합: VIX(Low=+1/Mid=0/High=-1) · trend60(Bull=+1/Neutral/Bear=-1) ·")
    lines.append("  breadth/adv_pct(Strong=+1/Weak=-1) · USD/KRW 20d(Falling=+1/Rising=-1)")
    lines.append("- 3구간: **합>=+2 → Risk-On, 합<=-2 → Risk-Off, 그 외 → Neutral**")
    lines.append("- PIT: 신호일 t의 regime = `usableFromDate==t` 라벨 (기존 regime-conditional 관례와 동일)")
    lines.append("")
    dist = df["regime"].value_counts(dropna=False)
    lines.append(f"- 레이블 분포(레코드 기준): "
                 f"Risk-On {int(dist.get('Risk-On',0))} · Neutral {int(dist.get('Neutral',0))} · "
                 f"Risk-Off {int(dist.get('Risk-Off',0))} · 결측 {int(dist.get(np.nan,0))}")
    lines.append("")

    # ── 1. main table: Regime x Horizon Q5-Q1 spread ──
    lines.append("## 1. Regime별 foreign_flow_ratio Quintile (전체 기간, Q5-Q1 spread)")
    lines.append("")
    lines.append("| Regime | Horizon | Q5-Q1 | NW t | N |")
    lines.append("|---|---:|---:|---:|---:|")
    main_table = {}
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            sub = df[df["regime"] == r]
            qdf, _ = compute_quintile_spread(sub, feat, fwd)
            if qdf is None:
                lines.append(f"| {r} | {fwd_name} | - | - | 0 |")
                main_table[(r, fwd)] = None
                continue
            st = spread_stats(qdf)
            main_table[(r, fwd)] = st
            lines.append(f"| {r} | {fwd_name} | {st['mean']:+.4f} | {st['nw_t']:+.2f} | {st['n_days']} |")
    lines.append("")

    # ── 2. TRAIN/VALID/TEST per regime ──
    lines.append("## 2. Regime별 TRAIN / VALID / TEST (Q5-Q1 spread)")
    lines.append("")
    lines.append("| Regime | Horizon | Period | Q5-Q1 | NW t | 방향 | N |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    split_table = {}
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            for pname, pspan in SPLIT.items():
                sub = df[(df["regime"] == r) & (df["date"] >= pspan[0]) & (df["date"] < pspan[1])]
                qdf, _ = compute_quintile_spread(sub, feat, fwd)
                if qdf is None:
                    lines.append(f"| {r} | {fwd_name} | {pname} | - | - | - | 0 |")
                    split_table[(r, fwd, pname)] = None
                    continue
                st = spread_stats(qdf)
                direction = "+" if st["mean"] > 0 else "-"
                split_table[(r, fwd, pname)] = st
                lines.append(f"| {r} | {fwd_name} | {pname} | {st['mean']:+.4f} | {st['nw_t']:+.2f} | {direction} | {st['n_days']} |")
    lines.append("")

    # ── 3. direction consistency per regime ──
    lines.append("## 3. 국면별 방향 일관성 (외국인 수급 효과)")
    lines.append("")
    lines.append("| Regime | Horizon | TRAIN | VALID | TEST | 일관? |")
    lines.append("|---|---|---|---|---|---|")
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            dirs = []
            for pname in SPLIT:
                st = split_table.get((r, fwd, pname))
                dirs.append("+" if (st and st["mean"] > 0) else ("-" if (st and st["mean"] <= 0) else "?"))
            consistent = dirs[0] == dirs[1] == dirs[2] != "?"
            mark = "일관" if consistent else "비일관"
            lines.append(f"| {r} | {fwd_name} | {dirs[0]} | {dirs[1]} | {dirs[2]} | {mark} |")
    lines.append("")

    # ── 4. Interpretation axes A-D ──
    lines.append("## 4. 해석")
    lines.append("")
    lines.append("### A. 모든 국면에서 효과가 존재하는가?")
    for r in REGIMES:
        st = main_table.get((r, "fwd_d5"))
        s20 = main_table.get((r, "fwd_d20"))
        s60 = main_table.get((r, "fwd_d60"))
        parts = []
        for s in (st, s20, s60):
            parts.append("+ (유의)" if (s and s["nw_t"] and abs(s["nw_t"]) > 2 and s["mean"] > 0)
                         else ("+ (약)" if (s and s["mean"] > 0) else ("-" if s else "?")))
        lines.append(f"- **{r}**: 5D={parts[0]} | 20D={parts[1]} | 60D={parts[2]}")
    lines.append("")
    lines.append("### D. 국면을 나누어도 외국인 5D 효과가 유지되는가?")
    for r in REGIMES:
        st = main_table.get((r, "fwd_d5"))
        lines.append(f"- {r}: Q5-Q1={st['mean']:+.4f} (NW {st['nw_t']:+.2f}, N={st['n_days']})"
                     if st else f"- {r}: 데이터 없음")
    lines.append("")

    # ── 5. 유동성 ──
    lines.append("## 5. 유동성 — 거래대금 상위 30% (regime별)")
    lines.append("")
    lines.append("| Regime | Horizon | Q5-Q1 | NW t | N |")
    lines.append("|---|---:|---:|---:|---:|")
    df_top = df[df["amount_pct"] >= 0.70]
    top_table = {}
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            sub = df_top[df_top["regime"] == r]
            qdf, _ = compute_quintile_spread(sub, feat, fwd)
            if qdf is None:
                lines.append(f"| {r} | {fwd_name} | - | - | 0 |")
                continue
            st = spread_stats(qdf)
            top_table[(r, fwd)] = st
            lines.append(f"| {r} | {fwd_name} | {st['mean']:+.4f} | {st['nw_t']:+.2f} | {st['n_days']} |")
    lines.append("")

    # ── 6. 판정 ──
    lines.append("## 6. 판정")
    lines.append("")
    lines.append("### 국면 간 대비 (전체 기간)")
    lines.append("")
    lines.append("| Regime | 5D NW | 20D NW | 60D NW |")
    lines.append("|---|---:|---:|---:|")
    for r in REGIMES:
        row = []
        for fwd in HORIZONS:
            st = main_table.get((r, fwd))
            row.append(f"{st['nw_t']:+.2f}" if st else "-")
        lines.append(f"| {r} | {' | '.join(row)} |")
    lines.append("")

    # Verdict logic
    # KEEP: 어떤 regime에서 TRAIN→VALID→TEST 방향 일관 유지 + 경제적 설명 가능한 국면별 차이
    consistent_regimes = []
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            ds = [split_table.get((r, fwd, p)) for p in SPLIT]
            if all(ds) and all(d["mean"] > 0 for d in ds):
                consistent_regimes.append((r, fwd_name))
    # Is there regime-specific differentiation with a stable OOS relation?
    strong_oos = []
    for r in REGIMES:
        for fwd, fwd_name in HORIZONS.items():
            t = split_table.get((r, fwd, "TEST"))
            if t and t["nw_t"] and abs(t["nw_t"]) > 2:
                strong_oos.append((r, fwd_name, t["nw_t"]))

    lines.append("### 방향 일관(3구간 전부 같은 부호) + TEST 유의한 케이스")
    lines.append("")
    if consistent_regimes:
        lines.append("- 방향 일관: " + ", ".join(f"{r} {h}" for r, h in consistent_regimes))
    else:
        lines.append("- 방향 일관 케이스: 없음")
    if strong_oos:
        lines.append("- TEST에서 |NW|>2: " + ", ".join(f"{r} {h}({t:+.2f})" for r, h, t in strong_oos))
    else:
        lines.append("- TEST에서 |NW|>2 케이스: 없음")
    lines.append("")

    lines.append("### 최종 판정")
    lines.append("")
    lines.append("- **KEEP**: 특정 국면에서 효과가 TRAIN→VALID→TEST 반복 유지 + 경제적으로 설명 가능한 차이")
    lines.append("- **WEAK**: 국면별 차이는 있으나 OOS 불안정")
    lines.append("- **REJECT**: 국면을 나눠도 효과 없음 / 특정 기간에만 나타남")
    lines.append("")

    # Manual determination (documented below after reading numbers)
    lines.append("**(아래 콘솔 요약의 수치를 읽고 확정한다.)**")
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved: {OUT}")

    print("\n=== Main table (전체 기간) ===")
    for r in REGIMES:
        row = []
        for fwd, fwd_name in HORIZONS.items():
            st = main_table.get((r, fwd))
            row.append(f"{fwd_name}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'},N={st['n_days'] if st else 0})")
        print(f"  {r:10s} | {' | '.join(row)}")
    print("\n=== Split 방향 ===")
    for r in REGIMES:
        parts = []
        for fwd in HORIZONS:
            ds = []
            for pname in SPLIT:
                st = split_table.get((r, fwd, pname))
                ds.append(f"{pname}={'{:+.4f}'.format(st['mean']) if st else '-'}({'{:+.2f}'.format(st['nw_t']) if st and st['nw_t'] is not np.nan else '-'})")
            parts.append(f"{fwd}:{' | '.join(ds)}")
        print(f"  {r:10s} | {' || '.join(parts)}")


if __name__ == "__main__":
    main()
