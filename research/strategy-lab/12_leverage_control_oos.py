#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""12_leverage_control_oos.py — 고부채 쏠림 통제(부채/EV 상위 1/3 제외) × PBR 잔차화 결합.

사전등록: findings/leverage-control-preregistration-2026-09.md (커밋 4ec0c469). 정의·판정은 그 문서가 단일 출처다.
11번(11_ev_value_family_oos.py)의 프레임·잔차화·결합·평가·게이트·판정 함수를 수정 없이 불러 쓴다.
새로 만든 것은 (1) 상위 1/3 부채/EV 제외, (2) 무작위 동수 제외 대조(질문 A)의 빠른 경로뿐이다.

  python 12_leverage_control_oos.py --selftest
  python 12_leverage_control_oos.py
"""
import argparse
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import factor_discovery_kr as fd  # noqa: E402


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m10 = _load("m10", "10_pbr_ey_resid_composite_oos.py")
m11 = _load("m11", "11_ev_value_family_oos.py")

OUT_DIR = os.path.join(HERE, "reports", "2026-09-21-leverage-control")
TARGET, SIGCOL, COST = m11.TARGET, m11.SIGCOL, m11.COST
CELLS = ["EBIT_EV", "FCF_EV", "GP_EV", "EY"]
DROP_ABOVE = 2 / 3                 # 상위 1/3 제외 — 사전등록의 유일한 임계값
BEAR_YEARS = ("2018", "2022", "2024")
N_PLACEBO = 500
N_FLOOR = 1000
SEED = 20260921


# ─────────────────────────── 프레임·표본 ───────────────────────────
def build_frame():
    panel = pd.read_parquet(m11.PANEL, columns=["ticker", "date", "sector", "liquid", "pbr", TARGET, "earnings_yield"])
    f, gate1 = m11.build_frame(panel=panel)
    f["EY"] = f.pop("earnings_yield")            # SIGCOL 이름과 겹치지 않게 미리 뺀다
    f["L"] = f["debt_eff"] / f["ev"]
    return f, gate1


def sample(f, cell):
    s = f[f[cell].notna() & f[TARGET].notna() & f["L"].notna()].copy()
    return s.rename(columns={cell: SIGCOL})


def keep_mask(s, side="low"):
    """월별 L 순위 백분위 기준. low = 상위 1/3 제외(개입), high = 상위 1/3 만(반대 대칭 점검)."""
    pct = s.groupby("date")["L"].rank(pct=True)
    return pct <= DROP_ABOVE if side == "low" else pct > DROP_ABOVE


# ─────────────────────────── 빠른 경로 ───────────────────────────
def month_arrays(s):
    """월별 원시 배열(원 행 순서 유지 — pandas rank(method='first') 의 tie 규칙과 맞춘다)."""
    ms = []
    for d, g in s.groupby("date", sort=True):
        ds = str(d)
        ms.append({"pbr": g["pbr"].to_numpy(float), "sig": g[SIGCOL].to_numpy(float), "ret": g[TARGET].to_numpy(float),
                   "train": fd.period_of(ds) == "TRAIN", "bear": ds[:4] in BEAR_YEARS, "date": ds})
    return ms


def fast_all(ms, idxs=None, sigs=None):
    """(dates, comp, pbr, train, bear) 월별 상위 10분위 gross. idxs = 월별 남길 인덱스, sigs = 월별 신호 대체값."""
    prep = []
    for i, m in enumerate(ms):
        ix = np.arange(len(m["pbr"])) if idxs is None else idxs[i]
        n = len(ix)
        if n < fd.MIN_NAMES:
            continue
        pr = rankdata(m["pbr"][ix])
        prc = pr - pr.mean()
        if prc.std() == 0:
            continue
        sg = m["sig"] if sigs is None else sigs[i]
        prep.append((m, pr, prc, float((prc ** 2).sum()), rankdata(sg[ix]), m["ret"][ix], n))
    slopes = [float(prc @ (xr - xr.mean()) / den) for m, pr, prc, den, xr, _, _ in prep if m["train"]]
    if len(slopes) < 3:
        return None
    beta = float(np.median(slopes))
    out = {"date": [], "comp": [], "pbr": [], "train": [], "bear": []}
    for m, pr, prc, den, xr, ret, n in prep:
        sp = 1 - pr / n
        rp = rankdata(xr - pr * beta) / n
        out["date"].append(m["date"])
        out["comp"].append(m11._top_mean(0.5 * sp + 0.5 * rp, ret, n))
        out["pbr"].append(m11._top_mean(sp, ret, n))
        out["train"].append(m["train"])
        out["bear"].append(m["bear"])
    return {k: np.array(v) for k, v in out.items()}


def gap_bp(r):
    b = r["bear"]
    return 1e4 * float((r["comp"][b] - r["pbr"][b]).mean())


def gap_pandas(scored):
    """pandas 경로(10 의 month_top)로 잰 G — selftest 대조·본 결과용."""
    c = {d: r for d, _, r, _ in m10.month_top(scored, "score_comp")}
    p = {d: r for d, _, r, _ in m10.month_top(scored, "score_pbr")}
    ds = [d for d in c if d in p and str(d)[:4] in BEAR_YEARS]
    return 1e4 * float(np.mean([c[d] - p[d] for d in ds])), len(ds)


def placebo_gaps(ms, k_by_month, g_u, rng, n):
    out = []
    for _ in range(n):
        idxs = [np.sort(rng.choice(len(m["pbr"]), size=min(k, len(m["pbr"])), replace=False)) for m, k in zip(ms, k_by_month)]
        r = fast_all(ms, idxs=idxs)
        out.append(gap_bp(r) - g_u)
    return np.array(out)


def restricted_floor(cell_ms, rng):
    """제한 표본에서 무작위 신호의 TRAIN ΔSharpe 최대값(네 셀 중) 분포 → p95."""
    base = {}
    for c, ms in cell_ms.items():
        r = fast_all(ms)
        t = r["train"]
        base[c] = m11._sharpe(r["pbr"][t] - COST)
    maxes = []
    for _ in range(N_FLOOR):
        best = -9.0
        for c, ms in cell_ms.items():
            sigs = [rng.permutation(m["sig"]) for m in ms]
            r = fast_all(ms, sigs=sigs)
            t = r["train"]
            best = max(best, m11._sharpe(r["comp"][t] - COST) - base[c])
        maxes.append(best)
    a = np.array(maxes)
    return {"p95": round(float(np.percentile(a, 95)), 4), "p50": round(float(np.percentile(a, 50)), 4),
            "p99": round(float(np.percentile(a, 99)), 4), "n": N_FLOOR, "seed": SEED}


# ─────────────────────────── 실행 ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    f, gate1 = build_frame()
    rng = np.random.default_rng(SEED)
    res = {"factor": "pbr-composite-leverage-control", "preregistration": "4ec0c469", "gate1": gate1, "cells": {}}
    S, SR, MSR, MSU = {}, {}, {}, {}
    for c in CELLS:
        s = sample(f, c)
        keep = keep_mask(s)
        S[c], SR[c] = s, s[keep].copy()
        MSU[c], MSR[c] = month_arrays(S[c]), month_arrays(SR[c])
        print(f"  {c}: 원 {len(s):,}행 → 제한 {len(SR[c]):,}행 ({len(SR[c]) / len(s):.1%})", flush=True)

    floor = restricted_floor(MSR, rng)
    res["restrictedFamilyFloor"] = floor
    print(f"제한 표본 가족 바닥선 p95={floor['p95']} (p50 {floor['p50']})", flush=True)

    n_pass = 0
    for c in CELLS:
        U, R = m11.add_scores(S[c]), m11.add_scores(SR[c])
        evU, evR = m11.evaluate(U), m11.evaluate(R)
        gU, nbU = gap_pandas(U)
        gR, nbR = gap_pandas(R)
        # 무작위 동수 제외 — 월별 남긴 수는 실제 개입과 같다
        kept = SR[c].groupby("date").size().reindex(sorted(S[c]["date"].unique())).fillna(0).astype(int).to_numpy()
        pl = placebo_gaps(MSU[c], kept, gU, rng, N_PLACEBO)
        dG = gR - gU
        p95 = float(np.percentile(pl, 95))
        m1 = bool(dG >= p95)
        n_pass += m1
        gt = m11.gates(evR, gate1)
        jd = m11.verdict(evR, gt, floor)
        # 반대 대칭(고부채 1/3 만) — 기록 전용
        H = m11.add_scores(S[c][keep_mask(S[c], "high")])
        gH, _ = gap_pandas(H)
        res["cells"][c] = {
            "nRowsFull": len(S[c]), "nRowsRestricted": len(SR[c]),
            "G_full_bp": round(gU, 1), "G_restricted_bp": round(gR, 1), "dG_bp": round(dG, 1), "bearMonths": nbR,
            "placebo": {"p05": round(float(np.percentile(pl, 5)), 1), "p50": round(float(np.percentile(pl, 50)), 1),
                        "p95": round(p95, 1), "share_ge_real": round(float((pl >= dG).mean()), 3)},
            "M1": m1, "gates": gt, "judgement": jd,
            "full": {k: evU[k] for k in ("nRows", "nMonths", "delta", "bear", "compTopProfile")},
            "restricted": {k: evR[k] for k in ("nRows", "nMonths", "delta", "bear", "compTopProfile")},
            "pbrOnly_bear_full": {y: v["pbr"] for y, v in evU["bear"].items()},
            "pbrOnly_bear_restricted": {y: v["pbr"] for y, v in evR["bear"].items()},
            "turnover": {"pbr": evR["PBR_only"]["turnover"], "comp": evR["COMP"]["turnover"]},
            "G_highLeverageOnly_bp": round(gH, 1),
        }
        d = evR["delta"]
        print(f"  {c}: G {gU:+.1f}→{gR:+.1f}bp (ΔG {dG:+.1f} · 무작위 p95 {p95:+.1f}) M1={m1} · 판정 {jd['verdict']} · "
              f"ΔSharpe T/V/T {d['TRAIN']['dSharpe']}/{d['VALID']['dSharpe']}/{d['TEST']['dSharpe']}", flush=True)
    res["mechanism"] = {"cellsPassingM1": n_pass, "verdict": "SUPPORTED" if n_pass >= 3 else "PARTIAL" if n_pass == 2 else "NOT SUPPORTED"}
    print(f"\n질문 A 기전: {res['mechanism']['verdict']} ({n_pass}/4 셀 M1 통과)", flush=True)
    res["executionTime_s"] = round(time.time() - t0, 1)
    p = os.path.join(OUT_DIR, "leverage-control.json")
    json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"저장: {p} ({res['executionTime_s']}s)", flush=True)


def selftest():
    f, gate1 = build_frame()
    s = sample(f, "EBIT_EV")
    assert s["L"].notna().all(), "표본에 L 결측이 있다"
    n_neg = int((s["L"] < 0).sum())   # 차입금 행 합이 음수인 종목이 있다(16행) — L 은 순위로만 쓰므로 무해, 기록만
    keep = keep_mask(s)
    frac = keep.groupby(s["date"]).mean()
    assert abs(frac.median() - 2 / 3) < 0.05, f"월별 남긴 비율 {frac.median():.3f}"
    sr = s[keep]
    hi = keep_mask(s, "high")
    assert (keep ^ hi).all(), "저/고 레버리지 분할이 서로 배타적이지 않다"
    # 빠른 경로 == pandas 경로 (제한 표본, 전 기간) — 무작위 대조를 믿을 근거
    R = m11.add_scores(sr)
    r = fast_all(month_arrays(sr))
    rc = {d: x for d, _, x, _ in m10.month_top(R, "score_comp")}
    rp = {d: x for d, _, x, _ in m10.month_top(R, "score_pbr")}
    ds = sorted(rc)
    assert list(r["date"]) == [str(d) for d in ds], "월 목록이 다르다"
    assert np.allclose(r["comp"], [rc[d] for d in ds]) and np.allclose(r["pbr"], [rp[d] for d in ds]), "빠른 경로가 pandas 와 다르다"
    g_fast, (g_pd, nb) = gap_bp(r), gap_pandas(R)
    assert abs(g_fast - g_pd) < 1e-6, (g_fast, g_pd)
    # 원 표본에서도 일치(ΔG 의 기준값이 두 경로에서 같다)
    U = m11.add_scores(s)
    assert abs(gap_bp(fast_all(month_arrays(s))) - gap_pandas(U)[0]) < 1e-6
    # 동수 무작위 제외는 실제 개입과 월별 같은 수를 남긴다
    ms = month_arrays(s)
    kept = s[keep].groupby("date").size().reindex(sorted(s["date"].unique())).fillna(0).astype(int).to_numpy()
    rng = np.random.default_rng(1)
    idx = [np.sort(rng.choice(len(m["pbr"]), size=k, replace=False)) for m, k in zip(ms, kept)]
    assert [len(i) for i in idx] == list(kept)
    print(f"selftest OK — L<0 {n_neg}행, 남긴 비율 중앙값 {frac.median():.3f}, 빠른 경로=pandas(G {g_pd:+.1f}bp, 하락장 {nb}개월), 무작위 제외 동수, 저/고 분할 배타")


if __name__ == "__main__":
    main()
