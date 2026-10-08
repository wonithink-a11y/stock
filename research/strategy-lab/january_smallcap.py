#!/usr/bin/env python3
"""1월 소형주 효과 — 사전등록 findings/january-smallcap-preregistration-2026-10.md 그대로.

    python research/strategy-lab/january_smallcap.py --selftest
    python research/strategy-lab/january_smallcap.py      # → findings/january-smallcap-results-2026-10.{md,json}
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

OUT = HERE / "findings" / "january-smallcap-results-2026-10"
SPAC = re.compile(r"스팩|기업인수목적")
LIQ, Q, COST = 1e8, 0.10, 0.00335
SEED, REPS = 20261009, 10000
WINDOWS = {"TRAIN": (2011, 2016), "VALID": (2017, 2020), "TEST": (2021, 2026)}


def monthly(dates, tick, M, names):
    R = M["R"].astype(float)
    per = dates.to_period("M")
    me = pd.Series(np.arange(len(dates))).groupby(per).max()
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    col_ok = np.array([t[-1] == "0" and not SPAC.search(names.get(t, "")) for t in tick])
    tr = ~np.isnan(R)
    fr = np.where(tr.any(0), tr.argmax(0), -1)
    first_day = np.zeros_like(tr)
    first_day[fr[fr >= 0], np.flatnonzero(fr >= 0)] = True
    anomaly = (R > 1.0) & ~first_day                 # 개정 1: 하루 +100% 초과 = 자료 이상
    logR = np.log1p(np.nan_to_num(np.where(anomaly, 0.0, R), nan=0.0))
    cs = np.vstack([np.zeros((1, R.shape[1])), np.cumsum(logR, axis=0)])
    rows = []
    months = list(me.index)
    for a, b in zip(months[:-1], months[1:]):
        r0, r1 = me[a], me[b]
        ok = col_ok & ~np.isnan(R[r0]) & (liq[r0] >= LIQ) & (M["MCAP"][r0] > 0)
        nxt = np.exp(cs[r1 + 1] - cs[r0 + 1]) - 1
        alive = (~np.isnan(R[r0 + 1:r1 + 1])).any(0)
        ok &= alive & ~anomaly[r0 + 1:r1 + 1].any(0)
        idx = np.flatnonzero(ok)
        if len(idx) < 100:
            continue
        cap = M["MCAP"][r0, idx]
        lo, hi = np.quantile(cap, [Q, 1 - Q])
        small, large = idx[cap <= lo], idx[cap >= hi]
        rows.append((b, nxt[small].mean(), nxt[large].mean(), nxt[idx].mean(), len(idx)))
    df = pd.DataFrame(rows, columns=["month", "small", "large", "ew", "n"])
    df["spread"] = df["small"] - df["large"]
    df["year"] = df["month"].map(lambda p: p.year)
    df["mon"] = df["month"].map(lambda p: p.month)
    return df


def D_stat(df):
    j = df["mon"] == 1
    return float(df.loc[j, "spread"].mean() - df.loc[~j, "spread"].mean())


def perm_p(df, rng):
    years = sorted(df["year"].unique())
    obs = D_stat(df)
    by = {y: df[df["year"] == y] for y in years}
    cnt = 0
    for _ in range(REPS):
        jan, oth = [], []
        for y, g in by.items():
            if len(g) < 2:
                continue
            k = rng.integers(len(g))
            jan.append(g["spread"].iloc[k])
            oth.extend(np.delete(g["spread"].to_numpy(), k))
        cnt += (np.mean(jan) - np.mean(oth)) >= obs
    return cnt / REPS


def run():
    dates, tick, M, names, market = kp.build()
    df = monthly(dates, tick, M, names)
    rng = np.random.default_rng(SEED)
    p = perm_p(df, rng)
    win = {}
    for w, (a, b) in WINDOWS.items():
        g = df[(df["year"] >= a) & (df["year"] <= b)]
        jan = g[g["mon"] == 1]
        win[w] = dict(D=D_stat(g), jan_spread=float(jan["spread"].mean()), jan_small_ex=float((jan["small"] - jan["ew"]).mean() - 2 * COST), n_jan=len(jan))
    info = p < 0.05 and all(win[w]["D"] > 0 for w in WINDOWS)
    econ = info and all(win[w]["jan_small_ex"] > 0 for w in ("VALID", "TEST"))
    verdict = "ECONOMIC" if econ else ("INFORMATION" if info else "REJECT")
    bymon = df.groupby("mon").agg(spread=("spread", "mean"), small_ex=("small", "mean"), ew=("ew", "mean")).reset_index()
    bymon["small_ex"] = bymon["small_ex"] - bymon["ew"]
    jan_years = df[df["mon"] == 1][["year", "spread"]].values.tolist()
    out = dict(verdict=verdict, p=p, D=D_stat(df), win=win, bymon=bymon.to_dict("records"), jan_years=jan_years, n_univ=float(df["n"].mean()))
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    L = ["---", "track: kr", "factor: january-smallcap", "date: 2026-10-09", f"verdict: {verdict}", "criteria_version: research-only (january-smallcap-preregistration-2026-10)",
         'conditions: ["KRX 일별 전종목 2010~2026 시가총액 10분위", "D = 1월 (소형−대형) − 다른 달", "해마다 무작위 달 순열 10,000회"]',
         "reason: >-", f"  신호: {'있음' if verdict != 'REJECT' else '없음'} · 경제성: {'통과' if verdict == 'ECONOMIC' else '미달'}. D = {out['D'] * 100:+.2f}%p, 순열 p = {p:.3f}. (스크립트 판정)", "---", "",
         "# 1월 소형주 효과 — 결과", "", f"유니버스 평균 {out['n_univ']:.0f}종목/월.", "", "| 구간 | 1월 수 | D(1월 − 다른 달) | 1월 소형−대형 | 1월 소형 − 등가중(비용 후) |", "|---|---:|---:|---:|---:|"]
    for w, r in win.items():
        L.append(f"| {w} | {r['n_jan']} | {r['D'] * 100:+.2f}%p | {r['jan_spread'] * 100:+.2f}% | {r['jan_small_ex'] * 100:+.2f}% |")
    L += ["", "## 기록 — 달별 평균(전체)", "", "| 달 | 소형 − 대형 | 소형 − 등가중 |", "|---:|---:|---:|"]
    L += [f"| {int(r['mon'])} | {r['spread'] * 100:+.2f}% | {r['small_ex'] * 100:+.2f}% |" for r in out["bymon"]]
    L += ["", "1월 연도별 소형 − 대형: " + " · ".join(f"{int(y)} {s * 100:+.1f}%" for y, s in jan_years)]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, "D", round(out["D"] * 100, 2), "p", p, {w: round(r["D"] * 100, 2) for w, r in win.items()})
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    df = pd.DataFrame({"year": np.repeat([2011, 2012], 12), "mon": list(range(1, 13)) * 2, "spread": [0.05] + [0.0] * 11 + [0.03] + [0.0] * 11})
    check("D = 1월 평균 0.04 − 다른 달 0", abs(D_stat(df) - 0.04) < 1e-12)
    check("순열 p 는 작다(해마다 1월만 양)", perm_p(df, np.random.default_rng(0)) < 0.05)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
