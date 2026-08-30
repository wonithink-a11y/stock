#!/usr/bin/env python
"""Flow × Price Confirmation — 외국인 강매수 종목에서 당일 가격 반응에 따른 미래수익률 차이.

질문: 외국인이 강하게 순매수한 종목 중에서도, 당일 가격이 아직 안 오른 종목과
이미 크게 오른 종목의 미래수익률이 다른가?

2×2 표:
  행: Foreign flow (Bottom 20% / Top 20%)
  열: daily_return (Price Bottom 50% / Top 50%)
  | A | B |   (Foreign Bottom)
  | C | D |   (Foreign Top)

핵심 비교:
  C = 외국인 강매수 + 당일 가격 약세
  D = 외국인 강매수 + 당일 가격 강세
  C - D (외국인 Top 20% 내부에서 price bottom vs top)

Forward: T+5, T+20, T+60 (A2a adjusted close)
Split: TRAIN 2016-01~2022-06 / VALID 2022-07~2024-01 / TEST 2024-01~2026-08
"""
import os

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-price-confirmation-2026-08.md")

HORIZONS = {"fwd_d5": "5D", "fwd_d20": "20D", "fwd_d60": "60D"}

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
    # 당일 수익률
    df["daily_return"] = df.groupby("ticker")["close"].transform(lambda s: s / s.shift(1) - 1)
    df["amount_pct"] = df.groupby("date")["total_amount"].rank(pct=True)
    return df


def compute_2x2(df, fwd_col, flow_frac=(0.20, 0.80), price_frac=0.50):
    """각 날짜별 Foreign Bottom/Top 20% × Price Bottom/Top 50% 셀 평균 미래수익률.

    returns: dict of daily Series (index=date) per cell, plus C-D inside top.
    """
    sub = df.dropna(subset=["foreign_flow_ratio", "daily_return", fwd_col]).copy()
    if len(sub) == 0:
        return None

    # foreign flow: date 내 pct rank
    sub["f_rank"] = sub.groupby("date")["foreign_flow_ratio"].rank(pct=True)
    # daily return: date 내 pct rank
    sub["p_rank"] = sub.groupby("date")["daily_return"].rank(pct=True)

    sub["fgrp"] = np.where(sub["f_rank"] < flow_frac[0], "Bottom",
                  np.where(sub["f_rank"] > flow_frac[1], "Top", "Mid"))
    sub["pgrp"] = np.where(sub["p_rank"] < price_frac, "Pbottom", "Ptop")

    # 셀별 일별 평균 미래수익률
    cells = {}
    for fg in ("Bottom", "Top"):
        for pg in ("Pbottom", "Ptop"):
            key = (fg, pg)
            g = sub[sub["fgrp"] == fg]
            g = g[g["pgrp"] == pg]
            cells[key] = g.groupby("date")[fwd_col].mean()

    # C - D (외국인 top 내부에서 price bottom - top)
    top = sub[sub["fgrp"] == "Top"]
    c_series = top[top["pgrp"] == "Pbottom"].groupby("date")[fwd_col].mean()
    d_series = top[top["pgrp"] == "Ptop"].groupby("date")[fwd_col].mean()
    cd = c_series.sub(d_series)

    return {"cells": cells, "C_minus_D": cd, "n_cells": {k: int(v.notna().sum()) for k, v in cells.items()}}


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


def series_stats(s):
    s = s.dropna()
    n = len(s)
    if n == 0:
        return {"mean": np.nan, "t_stat": np.nan, "nw_t": np.nan, "n_days": 0}
    mean = s.mean()
    std = s.std(ddof=1)
    t = mean / (std / np.sqrt(n)) if std > 0 and n > 1 else np.nan
    return {"mean": float(mean), "t_stat": float(t) if not np.isnan(t) else np.nan,
            "nw_t": newey_west_tstat(s), "n_days": int(n)}


def main():
    print("Loading data...")
    df = load_data()
    print(f"  rows={len(df)} tickers={df['ticker'].nunique()}")

    cache = {}
    def get_2x2(fwd, period=None):
        key = (fwd, period)
        if key in cache:
            return cache[key]
        sub = df if period is None else df[(df["date"] >= period[0]) & (df["date"] < period[1])]
        res = compute_2x2(sub, fwd)
        cache[key] = res
        return res

    lines = []
    lines.append("# Flow × Price Confirmation — 외국인 강매수 × 당일 가격 반응")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 + A2a (Step 2와 동일)")
    lines.append(f"> 기간: {df['date'].min().date()} ~ {df['date'].max().date()} | 종목: {df['ticker'].nunique()}")
    lines.append("> 질문: 외국인이 강하게 순매수한 종목 중, 당일 가격이 아직 안 오른 종목과 이미 크게 오른 종목의 미래수익률이 다른가?")
    lines.append("")
    lines.append("## 0. 방법")
    lines.append("")
    lines.append("- foreign_flow_ratio = foreign_net / total_amount (Step 2와 동일)")
    lines.append("- daily_return = close[t]/close[t-1] - 1 (A2a adjusted)")
    lines.append("- 매일: foreign flow Bottom 20% / Top 20%, 그 안에서 daily_return Bottom 50% / Top 50% → 2×2")
    lines.append("")
    lines.append("| | Price Bottom 50% | Price Top 50% |")
    lines.append("|---|---:|---:|")
    lines.append("| Foreign Bottom 20% | A | B |")
    lines.append("| Foreign Top 20% | C | D |")
    lines.append("")
    lines.append("> C−D: 외국인 Top 20% 내부에서 가격 약세 − 강세. C>D면 '외국인이 사는데 가격은 아직 안 오른 종목이 더 좋다'.")
    lines.append("")

    # ── 1. 전체 기간 2×2 ──
    lines.append("## 1. 전체 기간 2×2 (셀별 평균 미래수익률)")
    lines.append("")
    for fwd, fwd_name in HORIZONS.items():
        res = get_2x2(fwd)
        if res is None:
            continue
        lines.append(f"### {fwd_name} Forward")
        lines.append("")
        lines.append(f"| | Price Bottom 50% | Price Top 50% |")
        lines.append(f"|---|---:|---:|")
        a = series_stats(res["cells"]["Bottom", "Pbottom"])
        b = series_stats(res["cells"]["Bottom", "Ptop"])
        c = series_stats(res["cells"]["Top", "Pbottom"])
        d = series_stats(res["cells"]["Top", "Ptop"])
        lines.append(f"| Foreign Bottom 20% | A={a['mean']:+.4f} (N={a['n_days']}) | B={b['mean']:+.4f} (N={b['n_days']}) |")
        lines.append(f"| Foreign Top 20% | C={c['mean']:+.4f} (N={c['n_days']}) | D={d['mean']:+.4f} (N={d['n_days']}) |")
        lines.append("")
    lines.append("")

    # ── 2. C-D across horizons (전체) ──
    lines.append("## 2. 외국인 Top 20% 내부 — Price Bottom vs Top (C−D)")
    lines.append("")
    lines.append("| Horizon | C−D (Bottom−Top) | t-stat | NW t | N |")
    lines.append("|---|---:|---:|---:|---:|")
    cd_table = {}
    for fwd, fwd_name in HORIZONS.items():
        res = get_2x2(fwd)
        st = series_stats(res["C_minus_D"]) if res is not None else None
        cd_table[fwd] = st
        if st is None:
            lines.append(f"| {fwd_name} | - | - | - | 0 |")
        else:
            lines.append(f"| {fwd_name} | {st['mean']:+.4f} | {st['t_stat']:+.3f} | {st['nw_t']:+.3f} | {st['n_days']} |")
    lines.append("")

    # ── 3. TRAIN/VALID/TEST C-D ──
    lines.append("## 3. C−D by TRAIN / VALID / TEST")
    lines.append("")
    lines.append("| Horizon | Period | C−D | t-stat | NW t | 방향 | N |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    cd_split = {}
    for fwd, fwd_name in HORIZONS.items():
        for pname, pspan in SPLIT.items():
            res = get_2x2(fwd, pspan)
            st = series_stats(res["C_minus_D"]) if res is not None else None
            cd_split[(fwd, pname)] = st
            if st is None:
                lines.append(f"| {fwd_name} | {pname} | - | - | - | - | 0 |")
            else:
                d = "+" if st["mean"] > 0 else "-"
                lines.append(f"| {fwd_name} | {pname} | {st['mean']:+.4f} | {st['t_stat']:+.3f} | {st['nw_t']:+.3f} | {d} | {st['n_days']} |")
    lines.append("")

    # ── 4. 방향 일관성 ──
    lines.append("## 4. C−D 방향 일관성")
    lines.append("")
    lines.append("| Horizon | TRAIN | VALID | TEST | 일관? |")
    lines.append("|---|---|---|---|---|")
    for fwd, fwd_name in HORIZONS.items():
        dirs = []
        for pname in SPLIT:
            st = cd_split.get((fwd, pname))
            dirs.append("+" if (st and st["mean"] > 0) else ("-" if (st and st["mean"] <= 0) else "?"))
        consistent = dirs[0] == dirs[1] == dirs[2] != "?"
        lines.append(f"| {fwd_name} | {dirs[0]} | {dirs[1]} | {dirs[2]} | {'일관' if consistent else '비일관'} |")
    lines.append("")

    # ── 5. 유동성 ──
    lines.append("## 5. 유동성 — 거래대금 상위 30% (C−D)")
    lines.append("")
    lines.append("| Horizon | Universe | C−D | NW t | N |")
    lines.append("|---|---:|---:|---:|---:|")
    df_top = df[df["amount_pct"] >= 0.70]
    for fwd, fwd_name in HORIZONS.items():
        res_all = get_2x2(fwd)
        if res_all is not None:
            st = series_stats(res_all["C_minus_D"])
            lines.append(f"| {fwd_name} | All | {st['mean']:+.4f} | {st['nw_t']:+.3f} | {st['n_days']} |")
        res_top = compute_2x2(df_top, fwd)
        if res_top is not None:
            st = series_stats(res_top["C_minus_D"])
            lines.append(f"| {fwd_name} | Top 30% | {st['mean']:+.4f} | {st['nw_t']:+.3f} | {st['n_days']} |")
    lines.append("")

    # ── 6. 판정 ──
    lines.append("## 6. 판정")
    lines.append("")
    for fwd, fwd_name in HORIZONS.items():
        parts = []
        for pname in SPLIT:
            st = cd_split.get((fwd, pname))
            parts.append(f"{pname}={'{:+.4f}'.format(st['mean']) if st else '-'}"
                         f"(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'},N={st['n_days'] if st else 0})")
        lines.append(f"- **{fwd_name} C−D**: {' | '.join(parts)}")
    lines.append("")
    lines.append("### 최종 판정")
    lines.append("")
    # 결정: 외국인 top 내부에서 price bottom이 top보다 안정적으로 높은가?
    # 각 horizon에서 TRAIN/VALID/TEST C-D 부호가 모두 양인지
    verdict_lines = []
    n_horizon_keep = 0
    for fwd, fwd_name in HORIZONS.items():
        means = [cd_split.get((fwd, p)) for p in SPLIT]
        if all(m and m["mean"] > 0 for m in means):
            verdict_lines.append(f"- {fwd_name}: C−D TRAIN/VALID/TEST 전부 양(+) → '가격 미반응 강매수'가 더 좋다, 방향 일관")
            n_horizon_keep += 1
        elif all(m and m["mean"] <= 0 for m in means):
            verdict_lines.append(f"- {fwd_name}: C−D TRAIN/VALID/TEST 전부 음(-) → 방향 반대(가격 반응 종목이 더 좋다)")
        else:
            verdict_lines.append(f"- {fwd_name}: C−D 방향이 구간 간 비일관")
    lines.extend(verdict_lines)
    lines.append("")
    if n_horizon_keep >= 2:
        lines.append("**KEEP**: 외국인 Top 20% 내부에서 가격 Bottom 50%가 Top 50%보다 여러 지평에서 TRAIN→VALID→TEST 안정적으로 높음")
    elif n_horizon_keep >= 1:
        lines.append("**WEAK**: 차이는 있으나(OOS 일부 유지) 지평 전반으로 안정적이지 않음")
    else:
        lines.append("**REJECT**: C−D가 없거나 TEST에서 방향 반전 — 가격 반응 구분의 예측력 없음")
    lines.append("")
    lines.append("(위는 자동 요약. 구체적 수치에 대한 최종 판단은 하단 콘솔 요약 참고.)")
    lines.append("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nSaved: {OUT}")

    print("\n=== 전체기간 2×2 (Q5-Q1... 여기선 셀 평균) ===")
    for fwd, fwd_name in HORIZONS.items():
        res = get_2x2(fwd)
        if res is None:
            continue
        a = series_stats(res["cells"]["Bottom", "Pbottom"])
        b = series_stats(res["cells"]["Bottom", "Ptop"])
        c = series_stats(res["cells"]["Top", "Pbottom"])
        d = series_stats(res["cells"]["Top", "Ptop"])
        print(f"  {fwd_name}: A={a['mean']:+.4f} B={b['mean']:+.4f} | C={c['mean']:+.4f} D={d['mean']:+.4f} | C-D={c['mean']-d['mean']:+.4f}")
    print("\n=== C-D by split ===")
    for fwd, fwd_name in HORIZONS.items():
        parts = []
        for pname in SPLIT:
            st = cd_split.get((fwd, pname))
            parts.append(f"{pname}={'{:+.4f}'.format(st['mean']) if st else '-'}(NW {'{:+.2f}'.format(st['nw_t']) if st else '-'})")
        print(f"  {fwd_name:5s} | {' | '.join(parts)}")


if __name__ == "__main__":
    main()
