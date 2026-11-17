#!/usr/bin/env python3
"""극저가 소형주 회피 — 홀드아웃(2010~2015) 확인. 사전등록 findings/kr-penny-avoid-preregistration-2026-11.md

    python research/strategy-lab/kr_penny_avoid.py            # 결과 JSON + 요약 (1분 안팎)
    python research/strategy-lab/kr_penny_avoid.py --selftest

A = 월말 종가 < 1,000원 ∧ 시총 하위 3/5분위. D = EW(A) − EW(유니버스 − A), 방향 D < 0. 바닥선 = 같은 달 소형 풀에서 |A| 개 무작위 순열(단측). 기록 전용.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
HOLD = HERE / "data" / "krx-pbr-history" / "daily"
DISC = HERE / "data" / "krx-daily-ext"
OUT_JSON = HERE / "findings" / "kr-penny-avoid-results.json"
BREAK, MIN_V20, PRICE, NPERM, NBOOT, SEED, ALPHA, ALPHA_INFO, COST_BP = 30.5, 5e8, 1000, 2000, 2000, 20261117, 0.05 / 12, 0.05, 33.5
SPAC = re.compile(r"스팩|기업인수목적")
SETS = {"홀드아웃(판정)": (HOLD, "2010-02", "2015-12"), "발견 표본(기록)": (DISC, "2016-03", "2026-09")}


def load_panel(dirs: list[Path], first: str, last: str) -> pd.DataFrame:
    cols = ["BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "FLUC_RT", "MKTCAP", "ACC_TRDVAL"]
    d = pd.concat((pd.read_parquet(f, columns=cols) for p in dirs for f in sorted(glob.glob(str(p / "*.parquet")))), ignore_index=True)
    d["date"] = pd.to_datetime(d.BAS_DD)
    spac = d.groupby("ISU_CD").ISU_NM.agg(lambda s: any(SPAC.search(str(x)) for x in s.unique()))
    d = d[d.ISU_CD.str.endswith("0") & ~d.ISU_CD.map(spac)].sort_values(["ISU_CD", "date"]).reset_index(drop=True)
    fl = pd.to_numeric(d.FLUC_RT, errors="coerce").fillna(0.0)
    d["brk"] = (fl.abs() > BREAK).astype(int)
    d["r"] = np.where(d.brk == 1, 0.0, fl / 100)
    d.loc[~d.duplicated("ISU_CD"), "r"] = 0.0
    g = d.groupby("ISU_CD")
    d["idx"] = (1 + d.r).groupby(d.ISU_CD).cumprod()
    d["bcs"] = g.brk.cumsum()
    d["v20"] = g.ACC_TRDVAL.transform(lambda s: s.rolling(20, min_periods=15).mean())
    d["ym"] = d.date.dt.to_period("M")
    mmax = d.groupby("ym").date.max()
    me = d.groupby(["ISU_CD", "ym"]).tail(1).assign(mlast=lambda x: x.ym.map(mmax))
    f = me[(me.date == me.mlast) & (me.v20 >= MIN_V20) & (me.MKTCAP > 0) & (me.ym >= pd.Period(first)) & (me.ym <= pd.Period(last))]
    nxt = me.set_index(["ISU_CD", "ym"])[["idx", "bcs"]].rename(columns={"idx": "idxN", "bcs": "bcsN"})
    f = f.assign(ymN=f.ym + 1).join(nxt, on=["ISU_CD", "ymN"])
    f = f[f.idxN.isna() | ((f.bcsN - f.bcs) == 0)].copy()
    f["R"] = np.where(f.idxN.isna(), 0.0, f.idxN / f.idx - 1)
    return f[["ym", "ISU_CD", "MKTCAP", "TDD_CLSPRC", "R"]].rename(columns={"ISU_CD": "isu", "MKTCAP": "cap", "TDD_CLSPRC": "close"})


def analyze(panel: pd.DataFrame, rng, price=PRICE, nperm=NPERM, with_perm=True):
    months, D, G, DTO, skipped, groups = [], [], [], [], 0, []
    prevA: set = set()
    for ym, g in panel.groupby("ym"):
        if len(g) < 100:
            continue
        q = pd.qcut(g.cap.rank(method="first"), 5, labels=False).to_numpy()
        small = q <= 2
        R, isu, close = g.R.to_numpy(), g.isu.to_numpy(), g.close.to_numpy()
        A = small & (close < price)
        nA, nU = int(A.sum()), len(g)
        curA = set(isu[A])
        if nA < 5:
            skipped += 1
            prevA = curA
            continue
        months.append(str(ym))
        D.append(R[A].mean() - R[~A].mean())
        G.append(R[~A].mean() - R.mean())
        DTO.append(len(curA ^ prevA) / nU if prevA else np.nan)
        groups.append((R[small], nA, float(R.sum()), nU))
        prevA = curA
    D, G, DTO = np.array(D), np.array(G), np.array(DTO)
    perm = None
    if with_perm:
        perm = np.zeros((nperm, len(months)))
        for j, (rp, nA, sumU, nU) in enumerate(groups):
            P = rng.permuted(np.tile(rp, (nperm, 1)), axis=1)[:, :nA]
            perm[:, j] = P.mean(1) - (sumU - P.sum(1)) / (nU - nA)
    return dict(months=months, D=D, G=G, DTO=DTO, perm=perm, skipped=skipped, nA=[x[1] for x in groups], nU=[x[3] for x in groups])


def summarize(res, rng) -> dict:
    D, G, DTO, m = res["D"], res["G"], res["DTO"], res["months"]
    n = len(D)
    h = n // 2
    bs = [np.mean(rng.choice(D, n)) for _ in range(NBOOT)]
    net = G - COST_BP / 1e4 * np.nan_to_num(DTO, nan=0.0)
    out = dict(months=n, skipped=res["skipped"], meanA=round(float(np.mean(res["nA"])), 1), meanU=round(float(np.mean(res["nU"])), 0),
               dBp=round(float(D.mean()) * 1e4, 1), ci95Bp=[round(float(np.percentile(bs, 2.5)) * 1e4, 1), round(float(np.percentile(bs, 97.5)) * 1e4, 1)],
               first=round(float(D[:h].mean()) * 1e4, 1), second=round(float(D[h:].mean()) * 1e4, 1), neg=round(float((D < 0).mean() * 100)),
               gainBp=round(float(G.mean()) * 1e4, 1), turnover=round(float(np.nanmean(DTO)), 4), netBp=round(float(net.mean()) * 1e4, 1),
               breakevenBp=round(float(G.mean() / max(np.nanmean(DTO), 1e-9)) * 1e4, 0))
    if res["perm"] is not None:
        out["permP"] = round(float((1 + np.sum(res["perm"].mean(1) <= D.mean())) / (1 + len(res["perm"]))), 4)
    return out


def verdict(s) -> tuple[str, str]:
    if s["dBp"] < 0 and s["permP"] <= ALPHA and s["first"] < 0 and s["second"] < 0:
        sig = "신호 있음"
    elif s["dBp"] < 0 and s["permP"] <= ALPHA_INFO:
        sig = "INFORMATION"
    else:
        sig = "REJECT"
    econ = ("통과" if s["netBp"] > 0 else "미달") if sig != "REJECT" else "해당 없음"
    return sig, econ


def selftest() -> int:
    ok = 0
    rng = np.random.default_rng(1)

    def make(effect):
        rows = []
        for ym in pd.period_range("2010-02", "2011-12", freq="M"):
            n = 500
            cap = rng.lognormal(10, 1, n)
            close = np.exp(0.5 * np.log(cap) + rng.normal(0, 0.8, n)) * 4
            A = (close < 1000) & (pd.qcut(pd.Series(cap).rank(method="first"), 5, labels=False).to_numpy() <= 2)
            R = rng.normal(0, 0.08, n) + effect * A
            rows.append(pd.DataFrame(dict(ym=ym, isu=[f"{i:06d}" for i in range(n)], cap=cap, close=close, R=R)))
        return pd.concat(rows, ignore_index=True)

    pan = make(-0.03)
    res = analyze(pan, np.random.default_rng(2), nperm=400)
    s = summarize(res, np.random.default_rng(3))
    assert s["dBp"] < -200 and s["permP"] <= 0.01 and verdict(s)[0] == "신호 있음", s; ok += 1          # 심은 −3% 는 잡힌다
    null = analyze(make(0.0), np.random.default_rng(4), nperm=400)
    sn = summarize(null, np.random.default_rng(5))
    assert abs(sn["dBp"]) < 100 and verdict(sn)[0] != "신호 있음", sn; ok += 1                             # 심지 않으면 안 잡힌다
    assert res["DTO"][0] != res["DTO"][0] and abs(res["DTO"][1] - 0.5) < 0.1, res["DTO"][:3]; ok += 1       # 첫 달 NaN, 달마다 독립으로 뽑은 합성 A 는 멤버십 대칭차 ≈ 0.5
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    out = {}
    panels = {}
    for nm, (p, a, b) in SETS.items():
        panels[nm] = load_panel([p], a, b)
        rng = np.random.default_rng(SEED)
        res = analyze(panels[nm], rng)
        s = summarize(res, rng)
        sig, econ = verdict(s)
        out[nm] = dict(summary=s, signal=sig, economics=econ, monthlyDbp={m: round(float(x) * 1e4, 1) for m, x in zip(res["months"], res["D"])})
        print(f"{nm}: {s} → 신호 {sig} · 경제성 {econ}")
    # 반도체 제외(진단), 합친 198개월(기록), 가격 문턱 민감도(기록, 판정 불사용)
    sys.path.insert(0, str(HERE))
    import diag_regime_semis as sm
    semi = set(sm.semi_set(pd.read_parquet(HERE / "data" / "factor-panel" / "kr-monthly-v1.parquet")))
    hold = panels["홀드아웃(판정)"]
    ex = summarize(analyze(hold[~hold.isu.isin(semi)], np.random.default_rng(SEED + 1), with_perm=True), np.random.default_rng(SEED + 1))
    out["반도체 제외(홀드아웃, 진단)"] = ex
    print("반도체 제외(홀드아웃):", ex)
    both = pd.concat([hold, panels["발견 표본(기록)"]], ignore_index=True)
    sb = summarize(analyze(both, np.random.default_rng(SEED + 2)), np.random.default_rng(SEED + 2))
    out["합친 표본(기록)"] = sb
    print("합친:", sb)
    sens = {}
    for thr in (500, 2000):
        sens[f"{thr}원"] = {nm: summarize(analyze(panels[nm], np.random.default_rng(SEED + 3), price=thr, with_perm=False), np.random.default_rng(SEED + 3))["dBp"] for nm in panels}
    out["가격 문턱 민감도(기록, 판정 불사용) D bp"] = sens
    print("민감도:", sens)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
