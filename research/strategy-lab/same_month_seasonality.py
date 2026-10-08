#!/usr/bin/env python3
"""같은 달 계절성(Heston·Sadka) — 사전등록 findings/same-month-seasonality-preregistration-2026-10.md 그대로.

    python research/strategy-lab/same_month_seasonality.py --selftest
    python research/strategy-lab/same_month_seasonality.py      # → findings/same-month-seasonality-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "same-month-seasonality-results-2026-10"
SPAC = re.compile(r"스팩|기업인수목적")
LIQ, Q, YEARS, MIN_Y, COST = 1e8, 0.10, 5, 3, 0.00335
SEED, REPS = 20261009, 1000
WINDOWS = {"TRAIN": (2013, 2017), "VALID": (2018, 2021), "TEST": (2022, 2026)}


def monthly_matrix(dates, tick, M, names):
    """(월 목록, 월 수익 MR[보유월, 종목], 적격 E[형성월, 종목])."""
    R = kp.clean_returns(M["R"])
    per = dates.to_period("M")
    me = pd.Series(np.arange(len(dates))).groupby(per).max()
    months = list(me.index)
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(np.log1p(np.nan_to_num(R, nan=0.0)), axis=0)])
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    col_ok = np.array([t[-1] == "0" and not SPAC.search(names.get(t, "")) for t in tick])
    traded = ~np.isnan(R)
    MR = np.full((len(months), R.shape[1]), np.nan)
    E = np.zeros((len(months), R.shape[1]), bool)
    for i, m in enumerate(months):
        r1 = me[m]
        r0 = me[months[i - 1]] if i > 0 else -1
        alive = traded[r0 + 1:r1 + 1].any(0)
        MR[i] = np.where(alive, np.exp(cs[r1 + 1] - cs[r0 + 1]) - 1, np.nan)
        E[i] = col_ok & traded[r1] & (liq[r1] >= LIQ)
    return months, MR, E


def signal(MR, i):
    lags = [MR[i - 12 * k] for k in range(1, YEARS + 1) if i - 12 * k >= 0]
    if len(lags) < MIN_Y:
        return None
    A = np.vstack(lags)
    s = np.nanmean(A, axis=0)
    s[np.sum(~np.isnan(A), axis=0) < MIN_Y] = np.nan
    return s


def other_signal(MR, i):
    lo = max(i - 12 * YEARS, 0)
    rows = [k for k in range(lo, i) if (i - k) % 12 != 0]
    if len(rows) < 24:
        return None
    A = MR[rows]
    s = np.nanmean(A, axis=0)
    s[np.sum(~np.isnan(A), axis=0) < 24] = np.nan
    return s


def run():
    dates, tick, M, names, market = kp.build()
    months, MR, E = monthly_matrix(dates, tick, M, names)
    rng = np.random.default_rng(SEED)
    rows, prev, null = [], set(), np.zeros(REPS)
    ntr = 0
    for i in range(1, len(months)):
        hm = months[i]
        if hm.year < 2013 or hm > pd.Period("2026-09", "M"):
            continue
        s, so = signal(MR, i), other_signal(MR, i)
        if s is None:
            continue
        ok = E[i - 1] & np.isfinite(s) & np.isfinite(MR[i])
        idx = np.flatnonzero(ok)
        if len(idx) < 100:
            continue
        k = max(int(round(len(idx) * Q)), 1)
        order = idx[np.argsort(s[idx])]
        top, bot = order[-k:], order[:k]
        cur = set(top.tolist())
        to = 1.0 if not prev else len(cur - prev) / k
        prev = cur
        ew = MR[i, idx].mean()
        r = dict(month=str(hm), top=MR[i, top].mean() - ew, bot=MR[i, bot].mean() - ew, to=to, n=len(idx))
        if so is not None:
            oko = idx[np.isfinite(so[idx])]
            ko = max(int(round(len(oko) * Q)), 1)
            r["other_top"] = MR[i, oko[np.argsort(so[oko])[-ko:]]].mean() - MR[i, oko].mean() if len(oko) >= 100 else np.nan
        rows.append(r)
        if WINDOWS["TRAIN"][0] <= hm.year <= WINDOWS["TRAIN"][1]:
            x = MR[i, idx]
            pick = np.argsort(rng.random((REPS, len(idx))), axis=1)[:, :k]
            null += x[pick].mean(1) - ew
            ntr += 1
    df = pd.DataFrame(rows)
    df["year"] = df["month"].str[:4].astype(int)
    df["net"] = df["top"] - df["to"] * COST
    floor = float(np.percentile(null / max(ntr, 1), 95))
    bw = {w: dict(months=int(((df.year >= a) & (df.year <= b)).sum()), ex=float(df.loc[(df.year >= a) & (df.year <= b), "top"].mean()),
                  net=float(df.loc[(df.year >= a) & (df.year <= b), "net"].mean()), spread=float((df["top"] - df["bot"])[(df.year >= a) & (df.year <= b)].mean()),
                  other=float(df.loc[(df.year >= a) & (df.year <= b), "other_top"].mean()) if "other_top" in df else np.nan,
                  to=float(df.loc[(df.year >= a) & (df.year <= b), "to"].mean())) for w, (a, b) in WINDOWS.items()}
    info = bw["TRAIN"]["ex"] >= floor and bw["VALID"]["ex"] > 0 and bw["TEST"]["ex"] > 0
    econ = info and bw["VALID"]["net"] > 0 and bw["TEST"]["net"] > 0
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    years = df.groupby("year")["top"].sum().round(4).to_dict()
    out = dict(verdict=verdict, floor=floor, by_win=bw, years={int(a): float(b) for a, b in years.items()}, n_univ=float(df["n"].mean()))
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    bp = lambda x: f"{x * 1e4:+.0f}bp"
    L = ["---", "track: kr", "factor: same-month-seasonality", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (same-month-seasonality-preregistration-2026-10)",
         'conditions: ["KRX 전종목 2010~2026 월 수익", "과거 5년 같은 달 평균 상위 10% 등가중", "무작위 포트폴리오 1,000회 95백분위", "비용 회전율 × 33.5bp"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. (스크립트 판정, 바닥선 {bp(floor)}/월)", "---", "",
         "# 같은 달 계절성(Heston·Sadka) — 결과", "", f"유니버스 평균 {out['n_univ']:.0f}종목/월.", "",
         "| 구간 | 달 | 상위 10% 월평균 초과 | 비용 후 | 상위 − 하위 | 대조(다른 달 평균 상위 10%) | 월 회전율 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for w, r in bw.items():
        L.append(f"| {w} | {r['months']} | {bp(r['ex'])} | {bp(r['net'])} | {bp(r['spread'])} | {bp(r['other'])} | {r['to']:.2f} |")
    L += ["", f"판정: **{verdict}** (TRAIN 바닥선 {bp(floor)}).", "", "연도별 상위 10% 초과 합: " + " · ".join(f"{y} {v * 100:+.1f}%" for y, v in out["years"].items())]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, {w: (bp(r["ex"]), bp(r["net"]), bp(r["spread"]), bp(r["other"])) for w, r in bw.items()}, "floor", bp(floor))
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    MR = np.zeros((61, 2))
    MR[[12, 24, 36, 48], 0] = 0.1                    # 종목 0 은 같은 달(60 기준 12개월 간격)에 강했다
    s = signal(MR, 60)
    check("같은 달 평균: 종목 0 = 0.08(5개 중 4개 0.1), 종목 1 = 0", abs(s[0] - 0.08) < 1e-12 and s[1] == 0)
    so = other_signal(MR, 60)
    check("다른 달 평균은 같은 달을 뺀다", so is not None and abs(so[0]) < 1e-12)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
