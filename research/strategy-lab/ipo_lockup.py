#!/usr/bin/env python3
"""신규 상장주 보호예수 해제일 — 사전등록 findings/ipo-lockup-preregistration-2026-10.md 그대로.

    python research/strategy-lab/ipo_lockup.py --selftest
    python research/strategy-lab/ipo_lockup.py      # → findings/ipo-lockup-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "ipo-lockup-results-2026-10"
SPAC = re.compile(r"스팩|기업인수목적")
MONTHS, POST, PRE, LO, HI, EXCL = (1, 3, 6), 5, 10, 20, 200, 10
COST = 0.002354
SEED, REPS, BOOT, BLOCK = 20261009, 1000, 2000, 6
WINDOWS = {"TRAIN": (2010, 2017), "VALID": (2018, 2021), "TEST": (2022, 2026)}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def cum(r):
    return float(np.prod(1 + np.nan_to_num(r, nan=0.0)) - 1)


def unlock_rows(dates, first_row):
    L = dates[first_row]
    out = {}
    for k in MONTHS:
        u = int(np.searchsorted(dates, L + pd.DateOffset(months=k)))
        if u < len(dates):
            out[k] = u
    return out


def run():
    dates, tick, M, names, market = kp.build()
    R = M["R"].astype(float)
    T = len(dates)
    traded = ~np.isnan(R)
    first = np.where(traded.any(0), traded.argmax(0), -1)
    ew = np.nanmean(R, axis=1)
    ew = np.nan_to_num(ew)
    rng = np.random.default_rng(SEED)
    ev = []
    pools = {}
    for j, t in enumerate(tick):
        f = first[j]
        if f <= 0 or t[-1] != "0" or SPAC.search(names.get(t, "")) or dates[f] < pd.Timestamp("2010-02-01"):
            continue
        U = unlock_rows(dates, f)
        lastrow = np.flatnonzero(traded[:, j])[-1]
        excl = set()
        for k, u in U.items():
            if u + POST >= T or u > lastrow:
                continue
            ex = cum(R[u:u + POST + 1, j]) - cum(ew[u:u + POST + 1])
            pre = cum(R[u - PRE:u, j]) - cum(ew[u - PRE:u])
            ev.append(dict(t=t, k=k, u=u, date=dates[u], ex=ex, pre=pre, first_ret=float(R[f, j]) if np.isfinite(R[f, j]) else np.nan, market=market.get(t, "")))
            excl.update(range(u - EXCL, u + EXCL + 1))
        cand = [u for u in range(f + LO, min(f + HI, lastrow - POST, T - POST - 1)) if u not in excl]
        if cand:
            pools[t] = (np.array(cand), j)
    df = pd.DataFrame(ev)
    df["win"] = df["date"].dt.year.map(win_of)
    df["mi"] = (df["date"].dt.year - 2010) * 12 + df["date"].dt.month - 1
    res = {}
    for k in MONTHS:
        d = df[df["k"] == k]
        null = np.zeros(REPS)
        cnt = 0
        for _, r in d.iterrows():
            if r["t"] not in pools:
                continue
            cand, j = pools[r["t"]]
            us = rng.choice(cand, REPS)
            null += np.array([cum(R[u:u + POST + 1, j]) - cum(ew[u:u + POST + 1]) for u in us])
            cnt += 1
        null /= max(cnt, 1)
        mm = d.groupby("mi")["ex"].mean().sort_index()
        nb = int(np.ceil(len(mm) / BLOCK))
        st = rng.integers(0, max(len(mm) - BLOCK + 1, 1), (BOOT, nb))
        idx = np.minimum((st[:, :, None] + np.arange(BLOCK)).reshape(BOOT, -1)[:, : len(mm)], len(mm) - 1)
        boot = mm.to_numpy()[idx].mean(1)
        ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
        bw = {w: dict(n=int((d["win"] == w).sum()), ex=float(d.loc[d["win"] == w, "ex"].mean()), pre=float(d.loc[d["win"] == w, "pre"].mean())) for w in WINDOWS}
        lo, hi = np.percentile(null, [1, 99])
        m = float(d["ex"].mean())
        v = "REVERSE" if (m < lo and all(bw[w]["ex"] < 0 for w in WINDOWS) and ci[1] < 0) else (
            "INFORMATION" if (m > hi and all(bw[w]["ex"] > 0 for w in WINDOWS) and ci[0] > 0) else "NONE")
        econ = v == "REVERSE" and all(-bw[w]["ex"] > COST for w in ("VALID", "TEST"))
        fr_med = d["first_ret"].median()
        res[f"U{k}"] = dict(n=len(d), mean=m, median=float(d["ex"].median()), win=float((d["ex"] > 0).mean()), pre=float(d["pre"].mean()), ci=ci,
                            null_1=float(lo), null_99=float(hi), null_mean=float(null.mean()), by_win=bw, verdict=v, avoid_economic=bool(econ),
                            by_market={mk: float(d.loc[d["market"] == mk, "ex"].mean()) for mk in ("KOSPI", "KOSDAQ")},
                            by_first={"첫날 상위 절반": float(d.loc[d["first_ret"] > fr_med, "ex"].mean()), "첫날 하위 절반": float(d.loc[d["first_ret"] <= fr_med, "ex"].mean())})
    years = df.groupby(df["date"].dt.year)["t"].nunique().to_dict()
    out = dict(res=res, n_ipo=int(df["t"].nunique()), years={int(a): int(b) for a, b in years.items()}, dates=[str(dates[0].date()), str(dates[-1].date())])
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for k, r in res.items():
        print(k, r["verdict"], r["n"], round(r["mean"] * 100, 2), {w: round(r["by_win"][w]["ex"] * 100, 2) for w in WINDOWS}, "pre", round(r["pre"] * 100, 2))
    return 0


def pc(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.2f}%"


def render(o):
    v = {k: r["verdict"] for k, r in o["res"].items()}
    pos = [k for k, x in v.items() if x != "NONE"]
    L = ["---", "track: kr", "factor: ipo-lockup", "date: 2026-10-09",
         f"verdict: {'REVERSE' if 'REVERSE' in v.values() else ('INFORMATION' if 'INFORMATION' in v.values() else 'NONE')}",
         "criteria_version: research-only (ipo-lockup-preregistration-2026-10)",
         'conditions: ["KRX 일별 전종목 2010~2026, 첫 등장일 = 상장일(폐지 포함)", "해제일 = 상장 + 1·3·6개월 뒤 첫 거래일", "해제일 ~ +5거래일 초과(전종목 등가중 대비)", "같은 종목 무작위 날짜 1,000회 1·99백분위"]',
         "reason: >-", f"  신호: {'있음(' + '·'.join(f'{k} {v[k]}' for k in pos) + ')' if pos else '없음'} · 경제성(회피): {'통과' if any(r['avoid_economic'] for r in o['res'].values()) else '미달'}. (스크립트 판정)",
         "---", "", "# 신규 상장주 보호예수 해제일 — 결과", "", f"자료 {o['dates'][0]} ~ {o['dates'][1]} · 신규 상장 보통주 {o['n_ipo']}종목.", "",
         "| 칸 | 사건 | 6일 초과 평균 [블록 95%] | 중앙 | 승률 | 해제 전 10일 초과 | 귀무 평균 · 1/99백분위 | TRAIN | VALID | TEST | 판정 |", "|---|---:|---|---:|---:|---:|---|---:|---:|---:|---|"]
    for k, r in o["res"].items():
        L.append(f"| {k} | {r['n']} | {pc(r['mean'])} [{pc(r['ci'][0])}, {pc(r['ci'][1])}] | {pc(r['median'])} | {r['win']:.0%} | {pc(r['pre'])} | {pc(r['null_mean'])} · {pc(r['null_1'])}/{pc(r['null_99'])} | "
                 + " | ".join(f"{pc(r['by_win'][w]['ex'])}({r['by_win'][w]['n']})" for w in WINDOWS) + f" | **{r['verdict']}** |")
    L += ["", "## 기록", ""]
    for k, r in o["res"].items():
        L.append(f"- {k}: 시장별 " + " · ".join(f"{m} {pc(x)}" for m, x in r["by_market"].items()) + " / 상장 첫날 수익별 " + " · ".join(f"{m} {pc(x)}" for m, x in r["by_first"].items()))
    L.append("- 연도별 신규 상장(해제 사건이 있는 종목): " + " · ".join(f"{y} {n}" for y, n in o["years"].items()))
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    u = unlock_rows(dates, 10)                       # 2020-01-15 상장
    check("1개월 = 2/17(2/15 토 → 월), 3·6개월", dates[u[1]] == pd.Timestamp("2020-02-17") and dates[u[3]] == pd.Timestamp("2020-04-15") and dates[u[6]] == pd.Timestamp("2020-07-15"))
    check("누적 수익(NaN = 0)", abs(cum(np.array([0.1, np.nan, -0.1])) - (1.1 * 0.9 - 1)) < 1e-12)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
