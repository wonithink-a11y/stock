#!/usr/bin/env python3
"""고배당 연말 랠리 — 손해 본 경우의 공통점 (탐색·사후, 판정 없음).

dividend_runup_by_stock.py 의 표(3,051건)에 **11월 말 매수 시점에 알 수 있는 값**만 붙여 손실(세후 합계 < 0) 비율을 나눠 본다.
결과를 보고 필터를 고르면 다중검정이다 — 앞 절반(2010~2017)에서 보이고 뒤 절반(2018~2025)에서도 같은 방향인 것만 '버틴다'고 적는다.

    python research/strategy-lab/dividend_runup_loss_profile.py   # → findings/dividend-runup-loss-profile-2026-10.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dividend_capture as dc
import krx_daily_panel as kp
from dividend_runup import window

SRC = HERE / "findings" / "dividend-runup-by-stock-2026-10.csv"
OUT = HERE / "findings" / "dividend-runup-loss-profile-2026-10.md"


def features(df):
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.nan_to_num(np.nanmean(R, axis=1))))]
    ti = {t: j for j, t in enumerate(tick)}
    m20, m60, m250 = [], [], []
    for y, t in zip(df["year"], df["ticker"]):
        s, _ = window(dates, y)
        j = ti[t]
        f = lambda k: float(np.exp(cs[s + 1, j] - cs[s + 1 - k, j]) - np.exp(ew_cs[s + 1] - ew_cs[s + 1 - k]))   # 시장 대비
        m20.append(f(20)); m60.append(f(60)); m250.append(f(250))
    df["m20"], df["m60"], df["m250"] = m20, m60, m250
    # 직전 해 배당 증감: y 년 11월 DPS(=직전 사업연도) vs y−1 년 11월 DPS
    prev = {}
    for y in sorted(df["year"].unique()):
        f = dc.PBR / f"{y - 1}-11.parquet"
        if f.exists():
            prev[y] = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")["DPS"].to_dict()
    df["dps_pp"] = [prev.get(y, {}).get(t) for y, t in zip(df["year"], df["ticker"])]
    g = df["dps_prev"] / df["dps_pp"].replace(0, np.nan) - 1
    df["dps_chg"] = np.select([df["dps_pp"].isna(), df["dps_pp"] == 0, g < -0.05, g > 0.05], ["모름", "새로 배당", "줄임", "늘림"], "유지")
    # 작년 랠리 초과(같은 종목이 작년에도 뽑혔을 때만)
    last = df.set_index(["ticker", "year"])["runup_ex"].to_dict()
    df["prev_runup_ex"] = [last.get((t, y - 1)) for t, y in zip(df["ticker"], df["year"])]
    return df


def bucket_table(df, col, cuts=None, labels=None):
    x = pd.cut(df[col], cuts, labels=labels) if cuts is not None else df[col]
    rows = []
    for k, g in df.groupby(x, observed=True):
        a, b = g[g["year"] <= 2017], g[g["year"] >= 2018]
        rows.append((str(k), len(g), (g["loss"]).mean(), g["tot0_net"].mean(), g["runup_ex"].mean(),
                     a["loss"].mean() if len(a) else np.nan, b["loss"].mean() if len(b) else np.nan))
    return rows


def run():
    df = pd.read_csv(SRC, dtype={"ticker": str})
    df = df[df["tot0_net"].notna()].copy()
    df["loss"] = df["tot0_net"] < 0
    df = features(df)
    base = df["loss"].mean()
    pc = lambda v: "" if pd.isna(v) else f"{v * 100:+.1f}%"
    pr = lambda v: "" if pd.isna(v) else f"{v * 100:.0f}%"
    L = ["---", "track: kr", "factor: dividend-runup-loss-profile", "date: 2026-10-10", "verdict: EXPLORATORY", "reason: >-",
         "  탐색·사후(판정 없음). 11월 말 매수 → 배당락일 매도에서 세후 손실이 난 경우를 매수 시점 정보로 나눠 봄.", "---", "",
         "# 고배당 연말 랠리 — 손해 본 경우의 공통점", "",
         f"대상 {len(df):,}건 중 세후 손실 {df['loss'].sum():,}건(**{base:.0%}**). 세후 합계 = 11월 말 매수 → 배당락일 종가 매도 + 실제 배당 × 0.846 − 0.335%.",
         "**사후 탐색이다** — 앞 절반(2010~2017)과 뒤 절반(2018~2025) 손실 비율이 같은 방향이어야 '버틴다'로 읽는다.", "",
         "## 1. 해마다 손실 비율", "", "| 해 | 건수 | 손실 비율 | 세후 합계 평균 | 시장(등가중) 같은 기간 |", "|---|---:|---:|---:|---:|"]
    for y, g in df.groupby("year"):
        L.append(f"| {y} | {len(g)} | {pr(g['loss'].mean())} | {pc(g['tot0_net'].mean())} | {pc((g['runup'] - g['runup_ex']).mean())} |")
    specs = [
        ("11월 말 배당률(DIV)", "div_nov", [3, 4, 5, 7, 100], ["3~4%", "4~5%", "5~7%", "7% 이상"]),
        ("시총 순위(11월 말)", "mcap_rank", [0, 200, 500, 1000, 5000], ["1~200", "201~500", "501~1000", "1000 밖"]),
        ("11월까지 1개월 시장 대비", "m20", [-9, -0.1, -0.03, 0.03, 0.1, 9], ["−10%↓", "−10~−3%", "−3~+3%", "+3~+10%", "+10%↑"]),
        ("11월까지 3개월 시장 대비", "m60", [-9, -0.15, -0.05, 0.05, 0.15, 9], ["−15%↓", "−15~−5%", "−5~+5%", "+5~+15%", "+15%↑"]),
        ("11월까지 1년 시장 대비", "m250", [-9, -0.3, -0.1, 0.1, 0.3, 9], ["−30%↓", "−30~−10%", "−10~+10%", "+10~+30%", "+30%↑"]),
        ("작년 랠리 초과(작년에도 뽑힌 종목)", "prev_runup_ex", [-9, -0.03, 0, 0.03, 9], ["−3%↓", "−3~0%", "0~+3%", "+3%↑"]),
    ]
    for title, col, cuts, labels in specs:
        L += ["", f"## {title}", "", "| 구간 | 건수 | 손실 비율 | 세후 합계 평균 | 랠리 초과 | 손실 비율 2010~17 | 2018~25 |", "|---|---:|---:|---:|---:|---:|---:|"]
        L += [f"| {k} | {n} | {pr(l)} | {pc(m)} | {pc(r)} | {pr(a)} | {pr(b)} |" for k, n, l, m, r, a, b in bucket_table(df, col, cuts, labels)]
    for title, col in (("시장", "market"), ("직전 해 배당 증감(작년 11월 DPS 대비)", "dps_chg")):
        L += ["", f"## {title}", "", "| 구간 | 건수 | 손실 비율 | 세후 합계 평균 | 랠리 초과 | 손실 비율 2010~17 | 2018~25 |", "|---|---:|---:|---:|---:|---:|---:|"]
        L += [f"| {k} | {n} | {pr(l)} | {pc(m)} | {pc(r)} | {pr(a)} | {pr(b)} |" for k, n, l, m, r, a, b in bucket_table(df, col)]
    # 사후에만 알 수 있는 것(참고): 실제 배당이 11월 추정보다 줄었나
    df["cut_after"] = np.where(df["yield_act"].isna(), "모름", np.where(df["dps"] < df["dps_prev"] * 0.95, "올해 배당 줄임/끊음", "유지·늘림"))
    L += ["", "## 참고 — 매수 뒤에야 알 수 있는 것: 그해 실제 배당을 줄였나", "", "| 구간 | 건수 | 손실 비율 | 세후 합계 평균 | 랠리 초과 | 손실 비율 2010~17 | 2018~25 |", "|---|---:|---:|---:|---:|---:|---:|"]
    L += [f"| {k} | {n} | {pr(l)} | {pc(m)} | {pc(r)} | {pr(a)} | {pr(b)} |" for k, n, l, m, r, a, b in bucket_table(df, "cut_after")]
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(run())
