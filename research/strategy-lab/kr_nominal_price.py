#!/usr/bin/env python3
"""한국 명목 주가 이상현상. 사전등록 findings/kr-nominal-price-preregistration-2026-11.md

    python research/strategy-lab/kr_nominal_price.py            # 결과 JSON + 요약 (수 분 이내)
    python research/strategy-lab/kr_nominal_price.py --selftest

월말 시총 5분위 안에서 명목 종가 3분위: 저가 − 고가 다음 달 수익 스프레드(시총 중립). 바닥선 = 같은 시총 분위 안 가격 라벨 순열. 기록 전용.
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
DATA = HERE / "data" / "krx-daily-ext"
OUT_JSON = HERE / "findings" / "kr-nominal-price-results.json"
BREAK, MIN_V20, NPERM, NBOOT, SEED, ALPHA, ALPHA_INFO, COST_BP = 30.5, 5e8, 2000, 2000, 20261117, 0.05 / 12, 0.05, 33.5
PERIODS = {"TRAIN": ("2016-04", "2020-12"), "VALID": ("2021-01", "2023-12"), "TEST": ("2024-01", "2026-10")}
ERAS = {"2016~23": ("2016-04", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", "2026-10")}
SPAC = re.compile(r"스팩|기업인수목적")


def load_panel() -> tuple[pd.DataFrame, str]:
    cols = ["BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC", "FLUC_RT", "MKTCAP", "ACC_TRDVAL"]
    d = pd.concat((pd.read_parquet(f, columns=cols) for f in sorted(glob.glob(str(DATA / "*.parquet")))), ignore_index=True)
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
    mlast = d.groupby("ym").date.transform("max")
    me = d.groupby(["ISU_CD", "ym"]).tail(1).assign(mlast=lambda x: x.ym.map(d.groupby("ym").date.max()))
    first = me[(me.date == me.mlast) & (me.v20 >= MIN_V20) & (me.MKTCAP > 0) & (me.ym >= pd.Period("2016-03")) & (me.ym <= pd.Period("2026-09"))]
    nxt = me.set_index(["ISU_CD", "ym"])[["idx", "bcs"]].rename(columns={"idx": "idxN", "bcs": "bcsN"})
    first = first.assign(ymN=first.ym + 1).join(nxt, on=["ISU_CD", "ymN"])
    gone = first.idxN.isna()                                                       # 다음 달 행이 없음 = 직후 폐지 → 마지막 종가 청산(0%)
    ok = gone | ((first.bcsN - first.bcs) == 0)
    first = first[ok].copy()
    first["R"] = np.where(first.idxN.isna(), 0.0, first.idxN / first.idx - 1)
    first["gone"] = first.idxN.isna()
    return first[["ym", "ISU_CD", "MKTCAP", "TDD_CLSPRC", "R", "gone"]].rename(columns={"ISU_CD": "isu", "MKTCAP": "cap", "TDD_CLSPRC": "close"}), str(d.date.max().date())


def cells(g: pd.DataFrame):
    """한 달 단면 → 시총 5분위 × 가격 3분위 라벨(0=저, 1=중, 2=고)."""
    q = pd.qcut(g.cap.rank(method="first"), 5, labels=False)
    p = g.groupby(q).close.transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False))
    return q.to_numpy(), p.to_numpy()


def analyze(panel: pd.DataFrame, rng, nperm=NPERM, with_perm=True):
    months, S, L, TAU, PERM, G = [], [], [], [], [], []
    prev_low = {}
    for ym, g in panel.groupby("ym"):
        if len(g) < 100:
            continue
        q, p = cells(g)
        R = g.R.to_numpy()
        isu = g.isu.to_numpy()
        s_q, l_q, t_q, groups = [], [], [], []
        low_now = {}
        for k in range(5):
            m = q == k
            rl, rh, ra = R[m & (p == 0)], R[m & (p == 2)], R[m]
            s_q.append(rl.mean() - rh.mean())
            l_q.append(rl.mean() - ra.mean())
            low_now[k] = set(isu[m & (p == 0)])
            if k in prev_low and low_now[k]:
                t_q.append(len(low_now[k] - prev_low[k]) / len(low_now[k]))
            groups.append((ra, int((m & (p == 0)).sum()), int((m & (p == 2)).sum())))
        prev_low = low_now
        months.append(str(ym)); S.append(np.mean(s_q)); L.append(np.mean(l_q)); TAU.append(np.mean(t_q) if t_q else np.nan); G.append(groups)
    S, L, TAU = np.array(S), np.array(L), np.array(TAU)
    if with_perm:
        sp = np.zeros((nperm, len(months)))
        for j, groups in enumerate(G):
            acc = np.zeros(nperm)
            for ra, nl, nh in groups:
                P = rng.permuted(np.tile(ra, (nperm, 1)), axis=1)
                acc += P[:, :nl].mean(1) - P[:, -nh:].mean(1)
            sp[:, j] = acc / 5
        PERM = sp
    return dict(months=months, S=S, L=L, TAU=TAU, perm=PERM if with_perm else None)


def mask(months, a, b):
    return np.array([a <= m <= b for m in months])


def summarize(res, rng) -> dict:
    months, S, L, TAU = res["months"], res["S"], res["L"], res["TAU"]
    # 수익 월 = 형성 월 + 1: 구간 경계는 수익 월 기준이라 형성 월 문자열에 1개월을 더해 비교한다
    ret_m = [str(pd.Period(m) + 1) for m in months]
    out = {}
    for nm, (a, b) in {"전 기간": ("2016-04", "2026-10"), **PERIODS, **ERAS}.items():
        mk = mask(ret_m, a, b)
        if mk.sum() < 6:
            out[nm] = None
            continue
        x, l, t = S[mk], L[mk], TAU[mk]
        bs = [np.mean(rng.choice(x, len(x))) for _ in range(NBOOT)]
        row = dict(n=int(mk.sum()), spreadBp=round(float(x.mean()) * 1e4, 1), ci95Bp=[round(float(np.percentile(bs, 2.5)) * 1e4, 1), round(float(np.percentile(bs, 97.5)) * 1e4, 1)],
                   pos=round(float((x > 0).mean() * 100)), longExcessBp=round(float(l.mean()) * 1e4, 1), turnover=round(float(np.nanmean(t)), 3),
                   netBp=round(float((l - COST_BP / 1e4 * t).mean()) * 1e4, 1))
        if nm == "전 기간" and res["perm"] is not None:
            obs = abs(x.mean())
            pm = np.abs(res["perm"][:, mk].mean(1))
            row["permP2"] = round(float((1 + np.sum(pm >= obs)) / (1 + len(pm))), 4)
        out[nm] = row
    return out


def verdict(summ) -> tuple[str, str]:
    full = summ["전 기간"]
    signs = [np.sign(summ[k]["spreadBp"]) for k in PERIODS]
    same = len(set(signs)) == 1 and signs[0] != 0
    if full["permP2"] <= ALPHA and same:
        sig = "신호 있음(저가 우위)" if full["spreadBp"] > 0 else "신호 있음(고가 우위)"
    elif full["permP2"] <= ALPHA_INFO:
        sig = "INFORMATION"
    else:
        sig = "REJECT"
    econ = "해당 없음"
    if sig == "신호 있음(저가 우위)":
        econ = "통과" if full["netBp"] > 0 and summ["TEST"]["netBp"] > 0 else "미달"
    return sig, econ


def selftest() -> int:
    ok = 0
    rng = np.random.default_rng(1)
    rows = []
    for k, ym in enumerate(pd.period_range("2016-03", "2018-02", freq="M")):
        n = 600
        cap = rng.lognormal(10, 1, n)
        close = np.exp(0.7 * np.log(cap) + rng.normal(0, 0.5, n)) * 100                  # 가격-시총 상관 강함
        R = rng.normal(0.0, 0.08, n) + 0.02 * (np.argsort(np.argsort(close)) < n / 3)     # 저가 1/3 에 +2% 심기(시총과 무관하지 않음에 유의)
        rows.append(pd.DataFrame(dict(ym=ym, isu=[f"{i:06d}" for i in range(n)], cap=cap, close=close, R=R, gone=False)))
    panel = pd.concat(rows, ignore_index=True)
    res = analyze(panel, np.random.default_rng(2), nperm=400)
    assert res["S"].mean() > 0.003 and len(res["months"]) == 24, res["S"].mean(); ok += 1       # 심은 효과(전체 저가 1/3 에 +2%) 가 시총 중립 뒤에도 남는다(작은 시총 분위에 집중돼 약해짐)
    null = panel.assign(R=np.random.default_rng(3).normal(0, 0.08, len(panel)))
    r0 = analyze(null, np.random.default_rng(4), nperm=400)
    assert abs(r0["S"].mean()) < 0.01; ok += 1
    r0["months"] = res["months"]
    ps = [(r0["perm"][:, :].mean(1) >= abs(r0["S"].mean())).mean(), (res["perm"].mean(1) >= res["S"].mean()).mean()]
    assert ps[1] == 0.0 and ps[0] > 0.0; ok += 1                                                  # 순열 바닥선: 심은 쪽만 극단
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    panel, end = load_panel()
    print("자료 끝", end, "형성 월", panel.ym.nunique(), "행", len(panel), "직후 폐지 청산", int(panel.gone.sum()))
    rng = np.random.default_rng(SEED)
    res = analyze(panel, rng)
    summ = summarize(res, rng)
    sig, econ = verdict(summ)
    print(f"전 기간 스프레드 {summ['전 기간']} → 신호 {sig} · 경제성 {econ}")
    for nm, row in summ.items():
        print(f"  {nm}: {row}")
    out = dict(result=summ, signal=sig, economics=econ, monthlySpreadBp={m: round(float(s) * 1e4, 1) for m, s in zip(res["months"], res["S"])})
    # 반도체 제외(진단 전용)
    sys.path.insert(0, str(HERE))
    import diag_regime_semis as sm
    semi = set(sm.semi_set(pd.read_parquet(HERE / "data" / "factor-panel" / "kr-monthly-v1.parquet")))
    rx = analyze(panel[~panel.isu.isin(semi)], np.random.default_rng(SEED + 1), with_perm=False)
    out["반도체 제외(진단)"] = summarize(rx, np.random.default_rng(SEED + 1))
    print("반도체 제외:", {k: (v["spreadBp"], v["ci95Bp"]) for k, v in out["반도체 제외(진단)"].items() if v})
    # 기록 전용: 시총 중립 없이, 시총 분위별, 가격 구간별
    rec = {}
    def simple(g):
        p = pd.qcut(g.close.rank(method="first"), 3, labels=False)
        return g.R[p == 0].mean() - g.R[p == 2].mean()
    un = panel.groupby("ym").apply(simple)
    rec["시총 비중립 저−고 월 평균 bp"] = round(float(un.mean()) * 1e4, 1)
    bins = pd.cut(panel.close, [0, 1000, 5000, 20000, 1e12], labels=["<1천", "1천~5천", "5천~2만", "≥2만"])
    rec["가격 구간별 월 평균 수익(%)"] = {str(k): round(float(v) * 100, 2) for k, v in panel.groupby(bins, observed=True).R.mean().items()}
    sizeq = {}
    for k in range(5):
        vals = []
        for ym, g in panel.groupby("ym"):
            if len(g) < 100:
                continue
            q, p = cells(g)
            m = q == k
            vals.append(g.R.to_numpy()[m & (p == 0)].mean() - g.R.to_numpy()[m & (p == 2)].mean())
        sizeq[f"시총 {k + 1}분위(1=최소)"] = round(float(np.mean(vals)) * 1e4, 1)
    rec["시총 분위별 스프레드 bp"] = sizeq
    out["기록전용"] = rec
    print("기록:", rec)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
