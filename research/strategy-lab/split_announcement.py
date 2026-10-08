#!/usr/bin/env python3
"""액면분할·병합 공시 뒤 60거래일 — 사전등록 findings/split-announcement-preregistration-2026-10.md 그대로.

    python research/strategy-lab/split_announcement.py --selftest
    python research/strategy-lab/split_announcement.py      # → findings/split-announcement-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import krx_daily_panel as kp

OUT = HERE / "findings" / "split-announcement-results-2026-10"
A3D = ROOT / "data" / "backfill" / "fundamentals" / "a3d"
H, HS, EXCL, DEDUP_D, MIN_N, COST = 60, (20, 60, 120), 120, 365, 20, 0.00335
SEED, REPS = 20261009, 1000
WINDOWS = {"TRAIN": (2000, 2019), "VALID": (2020, 2022), "TEST": (2023, 2026)}
CELLS = {"SPLIT": "split", "REV": "reverseOrConsolidation"}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def load_events(cat):
    rows = []
    for line in gzip.open(A3D / f"{CELLS[cat]}.jsonl.gz", "rt", encoding="utf-8"):
        r = json.loads(line)
        if r.get("ticker") and r.get("disclosureDate"):
            rows.append((r["ticker"], pd.Timestamp(r["disclosureDate"])))
    df = pd.DataFrame(rows, columns=["ticker", "date"]).sort_values(["ticker", "date"])
    keep, last = [], {}
    for t, d in df.itertuples(index=False):
        if t not in last or (d - last[t]).days > DEDUP_D:
            keep.append((t, d))
            last[t] = d
    return keep


def excess(R, ew_cs, cs, e, h, j):
    return float(np.exp(cs[e + h + 1, j] - cs[e + 1, j]) - 1 - (np.exp(ew_cs[e + h + 1] - ew_cs[e + 1]) - 1))


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    ti = {t: j for j, t in enumerate(tick)}
    T = len(dates)
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    ew = np.nan_to_num(np.nanmean(R, axis=1))
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(ew))]
    traded = ~np.isnan(R)
    rng = np.random.default_rng(SEED)
    res = {}
    for cat in CELLS:
        ev = []
        for t, d in load_events(cat):
            j = ti.get(t)
            if j is None:
                continue
            e = int(np.searchsorted(dates, d, side="right"))       # 공시일 다음 거래일 = 진입(종가)
            if e + max(HS) + 1 >= T or not traded[e, j]:
                continue
            day0 = float(R[e - 1, j]) if e >= 1 and dates[e - 1] == d and traded[e - 1, j] else np.nan
            ev.append(dict(t=t, j=j, e=e, date=d, win=win_of(d.year), day0=day0, day1=float(R[e, j]),
                           **{f"x{h}": excess(R, ew_cs, cs, e, h, j) for h in HS}))
        df = pd.DataFrame(ev)
        null = np.zeros(REPS)
        cnt = 0
        for r in df.itertuples():
            a, b = WINDOWS[r.win]
            cand = np.flatnonzero(traded[:, r.j] & (dates.year >= a) & (dates.year <= b))
            cand = cand[(np.abs(cand - r.e) > EXCL) & (cand + H + 1 < T)]
            if len(cand) == 0:
                continue
            us = rng.choice(cand, REPS)
            null += np.exp(cs[us + H + 1, r.j] - cs[us + 1, r.j]) - 1 - (np.exp(ew_cs[us + H + 1] - ew_cs[us + 1]) - 1)
            cnt += 1
        null /= max(cnt, 1)
        bw = {w: dict(n=int((df["win"] == w).sum()), x60=float(df.loc[df["win"] == w, "x60"].mean())) for w in WINDOWS}
        m = float(df["x60"].mean())
        lo, hi = np.percentile(null, [1, 99])
        enough = all(bw[w]["n"] >= MIN_N for w in WINDOWS)
        if cat == "SPLIT":
            v = "INFORMATION" if enough and m > hi and all(bw[w]["x60"] > 0 for w in WINDOWS) else "NONE"
        else:
            v = "REVERSE" if enough and m < lo and all(bw[w]["x60"] < 0 for w in WINDOWS) else "NONE"
        res[cat] = dict(n=len(df), verdict=v, mean60=m, median60=float(df["x60"].median()), win60=float((df["x60"] > 0).mean()),
                        null=[float(lo), float(null.mean()), float(hi)], by_win=bw, x20=float(df["x20"].mean()), x120=float(df["x120"].mean()),
                        day0=float(df["day0"].mean()), day1=float(df["day1"].mean()), enough=enough)
    out = dict(res=res)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: "" if x is None or not np.isfinite(x) else f"{x * 100:+.2f}%"
    L = ["---", "track: kr", "factor: split-announcement", "date: 2026-10-10",
         f"verdict: {'INFORMATION' if res['SPLIT']['verdict'] != 'NONE' else ('REVERSE' if res['REV']['verdict'] != 'NONE' else 'NONE')}",
         "criteria_version: research-only (split-announcement-preregistration-2026-10)",
         'conditions: ["A3d 액면분할·병합 공시일 + KRX 일별 전종목 FLUC_RT", "공시 다음 날 종가 진입 60거래일 초과(전종목 등가중 대비)", "같은 종목 다른 날짜 1,000회 1·99백분위"]',
         "reason: >-", "  " + " · ".join(f"{k} {r['verdict']}(60일 초과 {pc(r['mean60'])}, {r['n']}건)" for k, r in res.items()) + ". (스크립트 판정)", "---", "",
         "# 액면분할·병합 공시 뒤 60거래일 — 결과", "",
         "| 칸 | 사건 | 공시일 수익 | 다음 날 | 20일 초과 | 60일 초과 평균 | 중앙 | 승률 | 120일 초과 | 귀무 1·평균·99 | TRAIN | VALID | TEST | 판정 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|"]
    for k, r in res.items():
        L.append(f"| {k} | {r['n']} | {pc(r['day0'])} | {pc(r['day1'])} | {pc(r['x20'])} | {pc(r['mean60'])} | {pc(r['median60'])} | {r['win60']:.0%} | {pc(r['x120'])} | "
                 f"{pc(r['null'][0])} · {pc(r['null'][1])} · {pc(r['null'][2])} | " + " | ".join(f"{pc(r['by_win'][w]['x60'])}({r['by_win'][w]['n']})" for w in WINDOWS) + f" | **{r['verdict']}** |")
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    for k, r in res.items():
        print(k, r["verdict"], r["n"], round(r["mean60"] * 100, 2), {w: (r["by_win"][w]["n"], round(r["by_win"][w]["x60"] * 100, 2)) for w in WINDOWS}, [round(x * 100, 2) for x in r["null"]])
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    R = np.array([[0.0], [0.1], [0.1], [0.0]])
    cs = np.vstack([np.zeros((1, 1)), np.cumsum(np.log1p(R), axis=0)])
    ew_cs = np.r_[0.0, np.cumsum(np.log1p(np.zeros(4)))]
    check("진입 e=0 종가 → 2일 뒤 = 1.1×1.1 − 1", abs(excess(R, ew_cs, cs, 0, 2, 0) - 0.21) < 1e-12)
    check("구간 나누기", win_of(2019) == "TRAIN" and win_of(2021) == "VALID" and win_of(2024) == "TEST")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
