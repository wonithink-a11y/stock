#!/usr/bin/env python3
"""국내 지수 ETF 의 종가 괴리(종가 ÷ NAV − 1) → 다음 날 '기초지수 대비' 수익 — 탐색(EXPLORATORY, 판정 없음).

질문: 종가가 NAV 보다 싸게 끝난 ETF 는 다음 날 기초지수보다 더 오르는가(괴리 수렴)? 수렴 폭이 왕복 비용을 넘는가?
설계(실행 전 고정): 국내 기초지수 ETF(기초지수명에 해외·선물·채권·금리·달러·원유·금·은·커버드·레버리지·인버스가 없는 것),
전일 거래대금 ≥ 1억, 괴리 구간 [<−1%, −1~−0.5%, −0.5~−0.2%, ±0.2%, 0.2~0.5%, 0.5~1%, >1%], 다음 날 초과 = 종가 수익 − 기초지수 수익.
구간 TRAIN 2010~2016 · VALID 2017~2020 · TEST 2021~. 비용 비교선 = ETF 왕복 5bp(+호가 1틱은 별도 기록).

    python research/strategy-lab/etf_nav_gap_explore.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import etf_timing_lab as e

OUT = HERE / "findings" / "etf-nav-gap-explore-2026-10"
EXCL = re.compile(r"해외|미국|중국|일본|유로|글로벌|선물|채권|국고|금리|달러|원유|골드|금$|은$|커버드|레버리지|인버스|2X|S&P|NASDAQ|MSCI|China|Japan|Euro|Gold|Treasury|Bond|Futures", re.I)
BINS = [-np.inf, -0.01, -0.005, -0.002, 0.002, 0.005, 0.01, np.inf]
LABELS = ["<−1%", "−1~−0.5%", "−0.5~−0.2%", "±0.2%", "0.2~0.5%", "0.5~1%", ">1%"]
WINDOWS = {"TRAIN": (2010, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}


def main():
    p = e.load_panel()
    p = p[p["idx_name"].notna() & ~p["idx_name"].astype(str).str.contains(EXCL) & ~p["name"].astype(str).str.contains(EXCL)]
    p = p[(p["close"] > 0) & (p["nav"] > 0) & (p["idx"] > 0)].sort_values(["code", "date"])
    g = p.groupby("code")
    p["gap"] = p["close"] / p["nav"] - 1
    p["val_prev_ok"] = p["val"] >= 1e8
    p["nxt_ex"] = (g["close"].shift(-1) / p["close"] - 1) - (g["idx"].shift(-1) / p["idx"] - 1)
    p["nxt_gap_chg"] = g["gap"].shift(-1) - p["gap"]
    p = p[p["val_prev_ok"] & p["nxt_ex"].notna() & (p["nxt_ex"].abs() < 0.2)]
    p["bin"] = pd.cut(p["gap"], BINS, labels=LABELS)
    p["win"] = p["date"].dt.year.map(lambda y: next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None))
    tab = p.groupby(["bin", "win"], observed=True)["nxt_ex"].agg(["count", "mean", "median"]).unstack("win")
    out = {"n_etf": int(p["code"].nunique()), "rows": int(len(p)), "table": {}}
    L = ["---", "track: kr", "factor: etf-nav-gap-explore", "date: 2026-10-09", "verdict: EXPLORATORY", "criteria_version: research-only (탐색, 판정 없음)",
         "reason: >-", "  국내 지수 ETF 의 종가 괴리(종가÷NAV−1) 구간별 다음 날 기초지수 대비 초과. 설계는 스크립트 머리말(실행 전 커밋).", "---", "",
         "# 국내 지수 ETF 종가 괴리 → 다음 날 기초지수 대비 수익 — 탐색", "",
         f"ETF {out['n_etf']}종 · {out['rows']:,}행(전일 거래대금 ≥ 1억). 값 = 다음 날 (ETF 종가 수익 − 기초지수 수익), bp.", "",
         "| 괴리 구간 | TRAIN 건수 | TRAIN 평균 | VALID 건수 | VALID 평균 | TEST 건수 | TEST 평균 | TEST 중앙 |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for b in LABELS:
        if b not in tab.index:
            continue
        r = tab.loc[b]
        cell = lambda stat, w: r.get((stat, w), np.nan)
        L.append(f"| {b} | {cell('count','TRAIN'):,.0f} | {cell('mean','TRAIN') * 1e4:+.1f} | {cell('count','VALID'):,.0f} | {cell('mean','VALID') * 1e4:+.1f} | "
                 f"{cell('count','TEST'):,.0f} | {cell('mean','TEST') * 1e4:+.1f} | {cell('median','TEST') * 1e4:+.1f} |")
        out["table"][b] = {w: dict(n=float(cell("count", w)), mean_bp=float(cell("mean", w) * 1e4)) for w in WINDOWS}
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[11:]))


if __name__ == "__main__" and len(sys.argv) == 1:
    main()


# ── 사후 기록(첫 실행 뒤 추가, 판정 불사용): 국내 지수 허용 목록 · 다음 날 분배락 제외 · 매일 괴리 ≤ −0.5% 등가중 1일 보유 ──
DOMESTIC = re.compile(r"코스피|코스닥|KRX|FnGuide|WISE|MKF|에프앤가이드|DeepSearch|삼성그룹|코리아|Korea|KEDI|iSelect")
FOREIGN = re.compile(r"대만|금현물|은현물|Silver|Gold|TSMC|Tesla|BYD|Global|China|중국|차이나|미국|글로벌|채권|국고|레버리지|인버스|선물|커버드|Hang|CSI|Nifty|VN30|STAR|FactSet|Bloomberg|FTSE|MSCI|S&P|NASDAQ", re.I)


def strategy(th=-0.005, liq=1e9, cost=3.54e-4):
    p = e.load_panel()
    nm = p["idx_name"].astype(str)
    p = p[nm.str.contains(DOMESTIC) & ~nm.str.contains(FOREIGN) & ~p["name"].astype(str).str.contains(FOREIGN)]
    p = p[(p["close"] > 0) & (p["nav"] > 0) & (p["idx"] > 0)].sort_values(["code", "date"]).copy()
    g = p.groupby("code")
    p["gap"] = p["close"] / p["nav"] - 1
    p["dist_next"] = ((g["idx"].shift(-1) / p["idx"] - 1) - (g["nav"].shift(-1) / p["nav"] - 1)) > 0.002
    p["nxt_ex"] = (g["close"].shift(-1) / p["close"] - 1) - (g["idx"].shift(-1) / p["idx"] - 1)
    p = p[(p["val"] >= liq) & p["nxt_ex"].notna() & (p["nxt_ex"].abs() < 0.2)]
    sig = p[(p["gap"] <= th) & ~p["dist_next"]]
    daily = sig.groupby("date")["nxt_ex"].mean()
    yr = daily.groupby(daily.index.year).agg(["count", "mean"])
    L = ["", "## 사후 기록 — 국내 지수 ETF 만(허용 목록), 다음 날 분배락 제외, 매일 괴리 ≤ −0.5% 등가중 1일 보유", "",
         f"ETF {p['code'].nunique()}종 · 신호 {len(sig):,}건 · 신호일 {len(daily):,}일. 일평균 초과(다음 날 ETF 종가 수익 − 기초지수 수익) "
         f"{daily.mean() * 1e4:+.1f}bp · 비용 {cost * 1e4:.2f}bp 후 {(daily.mean() - cost) * 1e4:+.1f}bp · 중앙 {daily.median() * 1e4:+.1f}bp.", "",
         "| 연도 | 신호일 | 일평균 초과(bp) |", "|---|---:|---:|"]
    L += [f"| {y} | {int(r['count'])} | {r['mean'] * 1e4:+.1f} |" for y, r in yr.iterrows()]
    L += ["", "신호가 많은 ETF: " + " · ".join(f"{k} {v}" for k, v in sig.groupby("name").size().sort_values(ascending=False).head(8).items())]
    return "\n".join(L) + "\n"


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--strategy":
    txt = strategy()
    with open(OUT.with_suffix(".md"), "a", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)
