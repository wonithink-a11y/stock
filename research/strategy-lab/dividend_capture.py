#!/usr/bin/env python3
"""연말 배당락 배당 포착 — 사전등록 findings/dividend-capture-preregistration-2026-10.md 그대로.

    python research/strategy-lab/dividend_capture.py --selftest
    python research/strategy-lab/dividend_capture.py      # → findings/dividend-capture-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import krx_daily_panel as kp

OUT = HERE / "findings" / "dividend-capture-results-2026-10"
PBR = HERE / "data" / "krx-pbr-history" / "pbr"
SPAC = re.compile(r"스팩|기업인수목적")
DIV_MIN, TAX, COST, LIQ = 3.0, 0.154, 0.00335, 1e8
SEED, REPS = 20261009, 1000
WINDOWS = {"TRAIN": (2010, 2015), "VALID": (2016, 2019), "TEST": (2020, 2022), "REC": (2023, 2025)}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def capture(rx, div):
    return rx + div / 100 * (1 - TAX) - COST


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    ti = {t: j for j, t in enumerate(tick)}
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    traded = ~np.isnan(R)
    rng = np.random.default_rng(SEED)
    ev = []
    for y in range(2010, 2026):
        f = PBR / f"{y}-11.parquet"
        if not f.exists():
            continue
        dv = pd.read_parquet(f).drop_duplicates("ticker").set_index("ticker")["DIV"]
        yr = np.flatnonzero(dates.year == y)
        D = int(yr.max())
        X = D - 1
        normal = yr[~np.isin(dates[yr].month, [11, 12])]
        for t, d in dv.items():
            j = ti.get(t)
            if j is None or not (d >= DIV_MIN) or t[-1] != "0" or SPAC.search(names.get(t, "")):
                continue
            if not (traded[X - 1, j] and traded[X, j]) or not (liq[X - 1, j] >= LIQ):
                continue
            cand = normal[traded[normal, j]]
            if len(cand) < 50:
                continue
            ev.append(dict(year=y, t=t, div=float(d), rx=float(R[X, j]), rnull=R[rng.choice(cand, REPS), j]))
    df = pd.DataFrame(ev)
    df["win"] = df["year"].map(win_of)
    df["cap"] = capture(df["rx"], df["div"])
    df["drop"] = -df["rx"] / (df["div"] / 100)
    res = {}
    for w in WINDOWS:
        d = df[df["win"] == w]
        if d.empty:
            continue
        rn = np.vstack(d["rnull"].to_numpy())
        G = (d["rx"].to_numpy()[:, None] - rn).mean(0) + d["div"].mean() / 100 * (1 - TAX) - COST
        res[w] = dict(n=len(d), cap=float(d["cap"].mean()), cap_med=float(d["cap"].median()), win=float((d["cap"] > 0).mean()), drop=float(d["drop"].median()),
                      div=float(d["div"].mean()), G=float(G.mean()), G1=float(np.percentile(G, 1)), rx=float(d["rx"].mean()))
    j = df[df["win"].isin(["TRAIN", "VALID", "TEST"])]
    rn = np.vstack(j["rnull"].to_numpy())
    Gall = (j["rx"].to_numpy()[:, None] - rn).mean(0) + j["div"].mean() / 100 * (1 - TAX) - COST
    info = np.percentile(Gall, 1) > 0 and all(res[w]["G"] > 0 for w in ("TRAIN", "VALID", "TEST"))
    verdict = "INFORMATION" if info else "NONE"
    buckets = {k: dict(n=int(s.sum()), drop=float(df.loc[s, "drop"].median()), cap=float(df.loc[s, "cap"].mean()))
               for k, s in (("DIV 3~5%", (df["div"] < 5) & (df["year"] <= 2022)), ("DIV ≥5%", (df["div"] >= 5) & (df["year"] <= 2022)))}
    years = df.groupby("year").agg(n=("cap", "size"), cap=("cap", "mean"), drop=("drop", "median")).round(4).reset_index().to_dict("records")
    out = dict(verdict=verdict, G_all=float(Gall.mean()), G_all_p1=float(np.percentile(Gall, 1)), res=res, buckets=buckets, years=years)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.2f}%"
    L = ["---", "track: kr", "factor: dividend-capture", "date: 2026-10-09", f"verdict: {verdict}", "criteria_version: research-only (dividend-capture-preregistration-2026-10)",
         'conditions: ["KRX 11월 말 DIV ≥ 3% 보통주, 연말 배당락일 X = 마지막 거래일 전날", "포착 = R_X + DIV × (1 − 15.4%) − 33.5bp", "보통날 무작위 1,000회 대비 G"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'NONE' else '없음'}. G(배당락일 − 보통날 + 세후 배당 − 비용) 전체 {pc(out['G_all'])}, 1백분위 {pc(out['G_all_p1'])}. (스크립트 판정)", "---", "",
         "# 연말 배당락 배당 포착 — 결과", "", "| 구간 | 사건 | 평균 DIV | 배당락일 수익 | 낙폭 비율(중앙) | 포착 손익 평균 | 중앙 | 양 비율 | G | G 1백분위 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for w, r in res.items():
        L.append(f"| {w} | {r['n']} | {r['div']:.2f}% | {pc(r['rx'])} | {r['drop']:.2f} | {pc(r['cap'])} | {pc(r['cap_med'])} | {r['win']:.0%} | {pc(r['G'])} | {pc(r['G1'])} |")
    L += ["", "## 기록", "", "- DIV 구간(2010~2022): " + " · ".join(f"{k} {v['n']}건 낙폭 비율 {v['drop']:.2f} 포착 {pc(v['cap'])}" for k, v in buckets.items()),
          "- 연도별: " + " · ".join(f"{int(r['year'])} {pc(r['cap'])}(낙폭 {r['drop']:.2f}, {int(r['n'])}건)" for r in years)]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, pc(out["G_all"]), pc(out["G_all_p1"]), {w: (r["n"], pc(r["cap"]), round(r["drop"], 2), pc(r["G"])) for w, r in res.items()})
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    check("배당 5%, 배당락 −4% → −0.04 + 0.05×0.846 − 0.00335 = −0.00105", abs(capture(-0.04, 5.0) - (-0.04 + 0.0423 - 0.00335)) < 1e-12)
    check("구간", win_of(2012) == "TRAIN" and win_of(2024) == "REC")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
