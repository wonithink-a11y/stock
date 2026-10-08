#!/usr/bin/env python3
"""연말 대주주 매도 → 연초 반등 — 사전등록 findings/yearend-taxloss-preregistration-2026-10.md 그대로.

    python research/strategy-lab/yearend_taxloss.py --selftest
    python research/strategy-lab/yearend_taxloss.py      # → findings/yearend-taxloss-results-2026-10.{md,json}

귀무의 '무작위 위치'는 그해 D−8 에 만든 같은 두 그룹을, 같은 해 안 다른 위치(12-15 ~ 1-10 제외)의 같은 길이 구간에 적용한다(달력 위치만 바꾼다).
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

OUT = HERE / "findings" / "yearend-taxloss-results-2026-10"
SPAC = re.compile(r"스팩|기업인수목적")
LIQ, Q, SEED, REPS = 1e8, 0.30, 20261009, 10000
S_OFF, B_END = (-7, -2), 5


def window_rows(dates, y):
    """(S 행 범위, B 행 범위, 형성 행) — S = D−7..D−2, B = D−1..다음 해 5번째 거래일."""
    d = int(np.flatnonzero(dates.year == y).max())
    nxt = np.flatnonzero(dates.year == y + 1)
    if len(nxt) < B_END:
        return None
    return (d + S_OFF[0], d + S_OFF[1]), (d - 1, int(nxt[B_END - 1])), d - 8


def cum(R, a, b, cols):
    return np.prod(1 + np.nan_to_num(R[a:b + 1][:, cols], nan=0.0), axis=0) - 1


def groups(M, R, liq, r0, tick, names, market):
    ok = ~np.isnan(R[r0]) & (liq[r0] >= LIQ) & (M["MCAP"][r0] > 0)
    ok &= np.array([t[-1] == "0" and not SPAC.search(names.get(t, "")) for t in tick])
    kq = ok & np.array([market.get(t) == "KOSDAQ" for t in tick])
    kp_ = ok & np.array([market.get(t) == "KOSPI" for t in tick])
    cq, cp = M["MCAP"][r0], M["MCAP"][r0]
    small = np.flatnonzero(kq & (cq <= np.nanquantile(cq[kq], Q)))
    large = np.flatnonzero(kp_ & (cp >= np.nanquantile(cp[kp_], 1 - Q)))
    return small, large


def run():
    dates, tick, M, names, market = kp.build()
    R = kp.clean_returns(M["R"])
    liq = pd.DataFrame(M["VAL"].astype(float)).rolling(20, min_periods=10).mean().to_numpy()
    rng = np.random.default_rng(SEED)
    rows, nullS, nullB = [], np.zeros(REPS), np.zeros(REPS)
    years = [y for y in range(2010, 2026) if window_rows(dates, y)]
    for y in years:
        (sa, sb), (ba, bb), r0 = window_rows(dates, y)
        small, large = groups(M, R, liq, r0, tick, names, market)
        dS = cum(R, sa, sb, small).mean() - cum(R, sa, sb, large).mean()
        dB = cum(R, ba, bb, small).mean() - cum(R, ba, bb, large).mean()
        yr = np.flatnonzero(dates.year == y)
        md = dates[yr]
        allowed = yr[~(((md.month == 12) & (md.day >= 15)) | ((md.month == 1) & (md.day <= 10)))]
        for arr, L in ((nullS, sb - sa), (nullB, bb - ba)):
            st = rng.choice(allowed[allowed + L < len(dates)], REPS)
            csS = np.vstack([np.zeros((1, len(small))), np.cumsum(np.log1p(np.nan_to_num(R[:, small], nan=0.0)), axis=0)])
            csL = np.vstack([np.zeros((1, len(large))), np.cumsum(np.log1p(np.nan_to_num(R[:, large], nan=0.0)), axis=0)])
            arr += (np.exp(csS[st + L + 1] - csS[st]) - 1).mean(1) - (np.exp(csL[st + L + 1] - csL[st]) - 1).mean(1)
        rows.append(dict(year=y, S=float(dS), B=float(dB), n_small=len(small), n_large=len(large)))
    nullS /= len(years)
    nullB /= len(years)
    df = pd.DataFrame(rows)
    mS, mB = df["S"].mean(), df["B"].mean()
    pB, pS = float((nullB >= mB).mean()), float((nullS <= mS).mean())
    hitB, hitS = int((df["B"] > 0).sum()), int((df["S"] < 0).sum())
    ok = mB > np.percentile(nullB, 95) and mS < np.percentile(nullS, 5) and hitB >= 11 and hitS >= 11
    verdict = "CONFIRMED(기전 지지)" if ok else ("부분(반등만)" if mB > np.percentile(nullB, 95) and hitB >= 11 else "NONE")
    out = dict(verdict=verdict, mS=mS, mB=mB, pS=pS, pB=pB, hitS=hitS, hitB=hitB, nS95=[float(np.percentile(nullS, 5)), float(np.percentile(nullS, 95))],
               nB95=[float(np.percentile(nullB, 5)), float(np.percentile(nullB, 95))], years=rows,
               pre_post_2023={"2010~2022 B": float(df[df.year <= 2022]["B"].mean()), "2023~2025 B": float(df[df.year >= 2023]["B"].mean()),
                              "2010~2022 S": float(df[df.year <= 2022]["S"].mean()), "2023~2025 S": float(df[df.year >= 2023]["S"].mean())})
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    L = ["---", "track: kr", "factor: yearend-taxloss", "date: 2026-10-10", f"verdict: {'INFORMATION' if verdict != 'NONE' else 'NONE'}",
         "criteria_version: research-only (yearend-taxloss-preregistration-2026-10)",
         'conditions: ["KRX 일별 전종목 2010~2025 연말", "코스닥 소형 30% − 코스피 대형 30%", "매도 구간 D−7~D−2 · 반등 구간 D−1~다음 해 5번째 거래일", "같은 해 다른 위치 10,000회"]',
         "reason: >-", f"  신호: {verdict} · 반등 구간 평균 {mB * 100:+.2f}%p(p {pB:.3f}, {hitB}/16) · 매도 구간 {mS * 100:+.2f}%p(p {pS:.3f}, {hitS}/16 음). (스크립트 판정)", "---", "",
         "# 연말 대주주 매도 → 연초 반등 — 결과", "",
         f"| 구간 | 평균 차(코스닥 소형 − 코스피 대형) | 귀무 5·95백분위 | 한쪽 p | 예상 부호 해 |", "|---|---:|---|---:|---:|",
         f"| 매도 D−7~D−2 | {mS * 100:+.2f}%p | {out['nS95'][0] * 100:+.2f} · {out['nS95'][1] * 100:+.2f} | {pS:.3f} | {hitS}/16 음 |",
         f"| 반등 D−1~+5 | {mB * 100:+.2f}%p | {out['nB95'][0] * 100:+.2f} · {out['nB95'][1] * 100:+.2f} | {pB:.3f} | {hitB}/16 양 |", "",
         "| 해 | 매도 구간 | 반등 구간 | 소형 수 | 대형 수 |", "|---|---:|---:|---:|---:|"]
    L += [f"| {r['year']} | {r['S'] * 100:+.2f}%p | {r['B'] * 100:+.2f}%p | {r['n_small']} | {r['n_large']} |" for r in rows]
    L += ["", "2023 말 대주주 기준 상향(10억 → 50억) 앞뒤: " + " · ".join(f"{k} {v * 100:+.2f}%p" for k, v in out["pre_post_2023"].items())]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(verdict, "S", round(mS * 100, 2), pS, hitS, "B", round(mB * 100, 2), pB, hitB)
    return 0


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    dates = pd.bdate_range("2020-12-01", "2021-01-29")
    (sa, sb), (ba, bb), r0 = window_rows(dates, 2020)
    d = int(np.flatnonzero(dates.year == 2020).max())
    check("D = 12-31, S = D−7..D−2, B 끝 = 다음 해 5번째 거래일(1/7)", dates[d] == pd.Timestamp("2020-12-31") and (sa, sb) == (d - 7, d - 2) and dates[bb] == pd.Timestamp("2021-01-07"))
    R = np.array([[0.1, 0.0], [np.nan, 0.1]])
    check("누적(NaN = 0)", np.allclose(cum(R, 0, 1, np.array([0, 1])), [0.1, 0.1]))
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
