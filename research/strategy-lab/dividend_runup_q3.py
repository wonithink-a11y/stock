#!/usr/bin/env python3
"""고배당 연말 랠리 × 3분기 실적 (탐색·사후, 판정 없음).

11월 말 매수 시점(그해 11월 마지막 거래일)까지 공시된 3분기 보고서(DART fnlttMultiAcnt, 연결 우선·없으면 별도)만 쓴다.
물음 둘: ① 3분기 실적이 나쁜 종목이 연말 랠리에서 더 자주 손해 보나 ② 그해 배당 삭감을 미리 알려 주나.
결과를 보고 필터를 고르면 다중검정이다 — 앞(2016~2020)·뒤(2021~2025) 두 구간에서 같은 방향인 것만 '버틴다'로 적는다.

    python research/strategy-lab/dividend_runup_q3.py   # → findings/dividend-runup-q3-2026-10.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import krx_daily_panel as kp
from dividend_runup import window

SRC = HERE / "findings" / "dividend-runup-by-stock-2026-10.csv"
Q3 = HERE / "data" / "quarterly-multi" / "quarterly-multi-panel-11014.jsonl"
OUT = HERE / "findings" / "dividend-runup-q3-2026-10.md"


def yoy(cur, prev):
    """전년 동기 대비 분류. 적자 여부를 먼저 본다(비율이 뜻을 잃는다)."""
    if cur is None or prev is None:
        return "모름"
    if cur < 0 and prev >= 0:
        return "적자 전환"
    if cur < 0:
        return "적자 지속"
    if prev <= 0:
        return "흑자 전환"
    g = cur / prev - 1
    return "30% 넘게 감소" if g < -0.3 else "0~30% 감소" if g < 0 else "0~30% 증가" if g < 0.3 else "30% 넘게 증가"


def load_q3(buy_dates):
    best = {}
    for l in open(Q3, encoding="utf-8"):
        r = json.loads(l)
        y, t = r["year"], r["ticker"]
        if y not in buy_dates or r["availableFrom"] > buy_dates[y]:
            continue                                   # 11월 말 매수 뒤 공시 — 그때는 몰랐다
        k = (t, y)
        if k not in best or (best[k]["fsDiv"] != "CFS" and r["fsDiv"] == "CFS"):
            best[k] = r
    return best


def run():
    dates, *_ = kp.build()
    df = pd.read_csv(SRC, dtype={"ticker": str})
    df = df[df["tot0_net"].notna() & (df["year"] >= 2016)].copy()
    buy = {y: dates[window(dates, y)[0]].strftime("%Y%m%d") for y in df["year"].unique()}
    q = load_q3(buy)
    g = lambda r, acct, f: (r.get(acct) or {}).get(f) if r else None
    rs = [q.get((t, y)) for t, y in zip(df["ticker"], df["year"])]
    df["ni_q"] = [yoy(g(r, "net_income", "cur"), g(r, "net_income", "prev")) for r in rs]           # 3분기(7~9월) 순이익
    df["ni_9m"] = [yoy(g(r, "net_income", "cur_add"), g(r, "net_income", "prev_add")) for r in rs]   # 1~9월 누적 순이익
    df["op_9m"] = [yoy(g(r, "op_income", "cur_add"), g(r, "op_income", "prev_add")) for r in rs]     # 1~9월 누적 영업이익
    df["loss"] = df["tot0_net"] < 0
    df["cut"] = np.where(df["dps"].isna(), np.nan, (df["dps"] < df["dps_prev"] * 0.95).astype(float))
    order = ["적자 전환", "적자 지속", "30% 넘게 감소", "0~30% 감소", "0~30% 증가", "30% 넘게 증가", "흑자 전환", "모름"]
    pc = lambda v: "" if pd.isna(v) else f"{v * 100:+.1f}%"
    pr = lambda v: "" if pd.isna(v) else f"{v * 100:.0f}%"
    a, b = df["year"] <= 2020, df["year"] >= 2021
    L = ["---", "track: kr", "factor: dividend-runup-q3", "date: 2026-10-10", "verdict: EXPLORATORY", "reason: >-",
         "  탐색·사후(판정 없음). 11월 말까지 공시된 3분기 실적으로 연말 랠리 손실·배당 삭감을 미리 가를 수 있나.", "---", "",
         "# 고배당 연말 랠리 × 3분기 실적", "",
         f"대상 2016~2025 {len(df):,}건, 3분기 보고서를 11월 말 매수 전에 찾은 것 {sum(r is not None for r in rs):,}건. "
         f"전체 손실 비율 {df['loss'].mean():.0%} · 그해 배당 삭감(5% 넘게 줄임·끊음) 비율 {df['cut'].mean():.0%}.",
         "세후 합계 = 11월 말 매수 → 배당락일 종가 매도 + 실제 배당 × 0.846 − 0.335%. **사후 탐색** — 앞(2016~20)·뒤(2021~25) 같은 방향만 버틴다고 읽는다.", ""]
    for title, col in (("1~9월 누적 순이익, 전년 대비", "ni_9m"), ("3분기(7~9월) 순이익, 전년 대비", "ni_q"), ("1~9월 누적 영업이익, 전년 대비", "op_9m")):
        L += [f"## {title}", "", "| 구간 | 건수 | 손실 비율 | 세후 합계 평균 | 랠리 초과 | 배당 삭감 비율 | 손실 2016~20 / 2021~25 | 삭감 2016~20 / 2021~25 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for k in order:
            s = df[col] == k
            if s.sum() == 0:
                continue
            d = df[s]
            L.append(f"| {k} | {s.sum()} | {pr(d['loss'].mean())} | {pc(d['tot0_net'].mean())} | {pc(d['runup_ex'].mean())} | {pr(d['cut'].mean())} | "
                     f"{pr(df[s & a]['loss'].mean())} / {pr(df[s & b]['loss'].mean())} | {pr(df[s & a]['cut'].mean())} / {pr(df[s & b]['cut'].mean())} |")
        L.append("")
    # 묶음: 누적 순이익이 나빠진 쪽(적자 전환·적자 지속·30% 넘게 감소) vs 나머지(모름 제외)
    bad = df["ni_9m"].isin(["적자 전환", "적자 지속", "30% 넘게 감소"])
    known = df["ni_9m"] != "모름"
    L += ["## 묶어서 — 1~9월 누적 순이익이 크게 나빠진 종목(적자·30% 넘게 감소)을 빼면", "",
          "| 묶음 | 건수 | 손실 비율 | 세후 합계 평균 | 랠리 초과 | 배당 삭감 비율 |", "|---|---:|---:|---:|---:|---:|"]
    for nm, s in (("나빠짐", bad), ("나머지(실적 확인됨)", known & ~bad), ("전체", df.index == df.index)):
        d = df[s]
        L.append(f"| {nm} | {len(d)} | {pr(d['loss'].mean())} | {pc(d['tot0_net'].mean())} | {pc(d['runup_ex'].mean())} | {pr(d['cut'].mean())} |")
    L += ["", "| 해 | 나빠짐 손실 비율 | 나머지 손실 비율 | 나빠짐 세후 평균 | 나머지 세후 평균 |", "|---|---:|---:|---:|---:|"]
    for y, d in df.groupby("year"):
        x, z = d[bad.loc[d.index]], d[(known & ~bad).loc[d.index]]
        L.append(f"| {y} | {pr(x['loss'].mean())} ({len(x)}) | {pr(z['loss'].mean())} ({len(z)}) | {pc(x['tot0_net'].mean())} | {pc(z['tot0_net'].mean())} |")
    L += ["", "## 한계", "",
          "- 3분기 보고서는 11월 14일 전후 공시라 11월 말 매수 전에 대부분 보인다. 그 뒤 공시(정정·지연)는 '모름'으로 뺐다.",
          "- 배당 삭감은 다음 해 5월 KRX 연간 DPS 기준이다(분기·중간 배당 포함).",
          "- 2016~2025 10년이라 해마다 장세가 섞인다 — 해별 표에서 방향이 몇 해나 같은지 함께 본다.", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(run())
