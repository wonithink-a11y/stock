#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""13_quality_family_oos.py — A3e 품질 계열(GP/A · 발생액 · 자산성장), 1단계 단독 → 2단계 PBR 잔차화 결합.

사전등록: findings/a3e-quality-family-preregistration-2026-09.md (커밋 1dbf541a). 정의·판정은 그 문서가 단일 출처다.
10번(잔차화·월별 상위 10분위·연도표)과 11번(평가·게이트·판정·가족 난수 바닥선) 함수를 수정 없이 불러 쓴다.
새로 만든 것은 세 축의 정의(a3e 프레임)와 1단계(단독 상위 10분위 vs 같은 표본 EW) 판정뿐이다.

  python 13_quality_family_oos.py --selftest
  python 13_quality_family_oos.py
"""
import argparse
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import a3e_account_map as M  # noqa: E402
import factor_discovery_kr as fd  # noqa: E402


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m10 = _load("m10", "10_pbr_ey_resid_composite_oos.py")
m11 = _load("m11", "11_ev_value_family_oos.py")

OUT_DIR = os.path.join(HERE, "reports", "2026-09-21-quality-family")
TARGET, SIGCOL, COST = m11.TARGET, m11.SIGCOL, m11.COST
AXES = ["GPA", "ACCR", "AGR"]
BEAR_YEARS = ("2018", "2022", "2024")
N_FLOOR = 1000
SEED = 20260921
GATE1_NA = {"rate": 1.0, "nInputs": 0, "evPositive": 0}     # EV>0 게이트는 품질 축에 해당 없음


# ─────────────────────────── 프레임 ───────────────────────────
def load_a3e():
    rows = []
    for l in open(m11.A3E, encoding="utf-8"):
        r = json.loads(l)
        x = M.extract(r)
        rows.append({"ticker": r["ticker"], "fy": int(r["fiscalYear"]), "af": pd.Timestamp(fd.normd(r["availableFrom"])),
                     "fsDiv": r["fsDiv"], "assets": x.get("assets"), "equity": x.get("equity"), "cash": x.get("cash"),
                     "gross_profit": x.get("gross_profit"), "net_income": x.get("net_income"), "cfo": x.get("cfo"),
                     "debt_eff": x.get("debt_eff")})
    return pd.DataFrame(rows)


def add_axes(a):
    """레코드별 세 축 계산. AGR 은 같은 종목의 fy−1 레코드이고 fsDiv 가 같을 때만."""
    a = a.sort_values(["ticker", "fy", "af"]).reset_index(drop=True)
    g = a.groupby("ticker")
    same = (g["fy"].shift() == a["fy"] - 1) & (g["fsDiv"].shift() == a["fsDiv"]) & (g["assets"].shift() > 0)
    prev = g["assets"].shift().where(same)
    ok = a["assets"] > 0
    a["GPA"] = (a["gross_profit"] / a["assets"]).where(ok)
    a["ACCR"] = ((a["cfo"] - a["net_income"]) / a["assets"]).where(ok)     # 발생액의 부호를 뒤집은 것(높을수록 좋음)
    a["AGR"] = (-(a["assets"] / prev - 1)).where(ok & prev.notna())         # 자산이 덜 늘수록 좋음
    return a.sort_values("af").reset_index(drop=True)


def build_frame(a3e=None, panel=None):
    a = add_axes(load_a3e() if a3e is None else a3e)
    if panel is None:
        panel = pd.read_parquet(m11.PANEL, columns=["ticker", "date", "sector", "liquid", "pbr", TARGET, "roe", "op_margin"])
    p = panel[panel["liquid"] & panel["pbr"].notna() & (panel["pbr"] > 0)].copy()
    p = p[~p["sector"].fillna("").str.contains(m11.FIN)].copy()
    p["dt"] = pd.to_datetime(p["date"])
    p = p.sort_values("dt")
    f = pd.merge_asof(p, a, left_on="dt", right_on="af", by="ticker", direction="backward",
                      tolerance=pd.Timedelta(days=m11.STALE_DAYS))
    f["mcap"] = np.where(f["equity"] > 0, f["pbr"] * f["equity"], np.nan)
    ev = f["mcap"] + f["debt_eff"] - f["cash"]
    f["ev"] = ev.where(ev > 0)
    return f


def sample(f, axis):
    return f[f[axis].notna() & f[TARGET].notna()].copy().rename(columns={axis: SIGCOL})


# ─────────────────────────── 1단계: 단독 vs EW ───────────────────────────
def standalone(s, reverse=False):
    p = s.copy()
    p["score_raw"] = p.groupby("date")[SIGCOL].rank(pct=True)
    if reverse:
        p["score_raw"] = 1 - p["score_raw"]
    ew = p.groupby("date")[TARGET].mean().sort_index()
    recs = m10.month_top(p, "score_raw")
    gross = {d: r for d, _, r, _ in recs}
    dates = sorted(gross)
    per = {k: [d for d in dates if fd.period_of(str(d)) == k] for k in ("TRAIN", "VALID", "TEST")}
    per["OOS"] = per["VALID"] + per["TEST"]
    out = {"nRows": len(p), "nTickers": int(p["ticker"].nunique()), "avgNames": round(float(p.groupby("date").size().mean()), 1)}
    for k, ds in per.items():
        top = fd.port_stats([gross[d] - COST for d in ds]) if ds else {}
        bm = fd.port_stats([float(ew.loc[d]) for d in ds]) if ds else {}
        out[k] = {"nMonths": len(ds), "meanExcessBp": round(1e4 * float(np.mean([gross[d] - ew.loc[d] for d in ds])), 1) if ds else None,
                  "topSharpe": top.get("sharpe"), "topCagr": top.get("cagr"), "topMdd": top.get("mdd"),
                  "ewSharpe": bm.get("sharpe"), "ewCagr": bm.get("cagr")}
    out["oosExcessT"] = m11.ttest([gross[d] - ew.loc[d] for d in per["OOS"]])
    out["annual"] = m10.annual_breakdown(recs, ew)
    out["bear"] = {y: {"ew": out["annual"][y]["benchCagr"], "top": out["annual"][y]["cagr"],
                       "topBeatsEw": out["annual"][y]["cagr"] >= out["annual"][y]["benchCagr"]}
                   for y in BEAR_YEARS if y in out["annual"]}
    out["turnover"] = m11.turnover(recs)
    ex = {y: v["excess"] for y, v in out["annual"].items() if v["excess"] is not None}
    pos = {y: e for y, e in ex.items() if e > 0}
    out["topYearShare"] = round(max(pos.values()) / sum(pos.values()), 3) if pos else None
    return out


def stage1_months(s):
    ms = []
    for d, g in s.groupby("date", sort=True):
        if fd.period_of(str(d)) == "TRAIN" and len(g) >= fd.MIN_NAMES and g[SIGCOL].nunique() > 1:
            ms.append((g[SIGCOL].to_numpy(float), g[TARGET].to_numpy(float)))
    return ms


def fast_train_excess_bp(ms, sigs=None):
    v = [m11._top_mean(x if sigs is None else sigs[i], r, len(x)) - r.mean() for i, (x, r) in enumerate(ms)]
    return 1e4 * float(np.mean(v))


def floor1(axis_ms, rng):
    maxes = []
    for _ in range(N_FLOOR):
        maxes.append(max(fast_train_excess_bp(ms, [rng.permutation(x) for x, _ in ms]) for ms in axis_ms.values()))
    a = np.array(maxes)
    return {"p95": round(float(np.percentile(a, 95)), 2), "p50": round(float(np.percentile(a, 50)), 2),
            "p99": round(float(np.percentile(a, 99)), 2), "n": N_FLOOR, "seed": SEED}


def verdict1(st, floor):
    months_ok = all(st[p]["nMonths"] >= 12 for p in ("TRAIN", "VALID", "TEST"))
    if not months_ok:
        return {"verdict": "UNTESTABLE", "why": "구간 월수 < 12"}
    ex = {p: st[p]["meanExcessBp"] for p in ("TRAIN", "VALID", "TEST")}
    info = ex["TRAIN"] >= floor["p95"] and ex["VALID"] > 0 and ex["TEST"] > 0
    econ = info and st["OOS"]["topCagr"] > st["OOS"]["ewCagr"]
    wins = sum(1 for v in st["bear"].values() if v["topBeatsEw"])
    t = st["oosExcessT"]
    robust = econ and wins >= 2 and t is not None and t >= 2
    v = "ROBUST" if robust else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "information": bool(info), "economic": bool(econ), "robust": bool(robust),
            "excessBp": ex, "floorP95": floor["p95"], "bearWins": wins, "oosExcessT": t}


# ─────────────────────────── 실행 ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    f = build_frame()
    rng = np.random.default_rng(SEED)
    S = {a: sample(f, a) for a in AXES}
    res = {"factor": "a3e-quality-family", "preregistration": "1dbf541a", "stage1": {}, "stage2": {}, "recordOnly": {}}
    for a in AXES:
        print(f"  {a}: {len(S[a]):,}행 · {S[a]['ticker'].nunique()}종목", flush=True)

    fl1 = floor1({a: stage1_months(S[a]) for a in AXES}, rng)
    res["stage1Floor"] = fl1
    print(f"1단계 가족 난수 바닥선 p95={fl1['p95']}bp (p50 {fl1['p50']})", flush=True)
    advance = []
    for a in AXES:
        st = standalone(S[a])
        st["judgement"] = verdict1(st, fl1)
        res["stage1"][a] = st
        j = st["judgement"]
        print(f"  [1단계] {a}: {j['verdict']} · 초과 T/V/T {st['TRAIN']['meanExcessBp']}/{st['VALID']['meanExcessBp']}/{st['TEST']['meanExcessBp']}bp "
              f"· 하락장 {j.get('bearWins')}/3 · OOS t {st['oosExcessT']}", flush=True)
        if j.get("information"):
            advance.append(a)
    res["advance"] = advance

    # 2단계 바닥선은 진입 여부와 무관하게 세 축 기준으로 만든다(사전등록 §3)
    scored = {a: m11.add_scores(S[a]) for a in AXES}
    fl2 = m11.family_floor({a: m11.null_months(scored[a]) for a in AXES}, np.random.default_rng(SEED + 1))
    res["stage2Floor"] = fl2
    print(f"2단계 가족 난수 바닥선 p95={fl2['p95']} (Sharpe 차)", flush=True)
    for a in advance:
        ev = m11.evaluate(scored[a])
        gt = m11.gates(ev, GATE1_NA)
        ev["gates"] = gt
        ev["judgement"] = m11.verdict(ev, gt, fl2)
        res["stage2"][a] = ev
        d = ev["delta"]
        print(f"  [2단계] {a}: {ev['judgement']['verdict']} · ΔSharpe T/V/T {d['TRAIN']['dSharpe']}/{d['VALID']['dSharpe']}/{d['TEST']['dSharpe']} "
              f"· 하락장 {sum(v['compBeatsPbr'] for v in ev['bear'].values())}/3", flush=True)
    if not advance:
        print("  1단계를 통과한 축이 없어 2단계를 실행하지 않는다 — 품질 계열 단독 정보 없음으로 종결.", flush=True)

    # 기록 전용
    ro = res["recordOnly"]
    ro["reversedTop"] = {a: {p: standalone(S[a], reverse=True)[p]["meanExcessBp"] for p in ("TRAIN", "VALID", "TEST")} for a in AXES}
    ro["cfsOnly"] = {a: {p: standalone(S[a][S[a]["fsDiv"] == "CFS"])[p]["meanExcessBp"] for p in ("TRAIN", "VALID", "TEST")} for a in AXES}
    j = f.dropna(subset=AXES + ["pbr"]).copy()
    corr = {}
    for x, y in [("GPA", "ACCR"), ("GPA", "AGR"), ("ACCR", "AGR"), ("GPA", "pbr"), ("ACCR", "pbr"), ("AGR", "pbr")]:
        v = [m10.monthly_spearman(g[x], g[y]) for _, g in j.groupby("date")]
        corr[f"{x}~{y}"] = round(float(np.nanmean([q for q in v if q is not None])), 3)
    for x in AXES:
        for y in ("roe", "op_margin"):
            jj = f.dropna(subset=[x, y])
            v = [m10.monthly_spearman(g[x], g[y]) for _, g in jj.groupby("date")]
            corr[f"{x}~{y}"] = round(float(np.nanmean([q for q in v if q is not None])), 3)
    ro["rankCorr"] = corr
    res["executionTime_s"] = round(time.time() - t0, 1)
    p = os.path.join(OUT_DIR, "quality-family.json")
    json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(f"저장: {p} ({res['executionTime_s']}s)", flush=True)


# ─────────────────────────── selftest ───────────────────────────
def selftest():
    T = pd.Timestamp
    a3e = pd.DataFrame([
        {"ticker": "A", "fy": 2019, "af": T("2020-03-20"), "fsDiv": "CFS", "assets": 100.0, "equity": 50.0, "cash": 5.0, "gross_profit": 30.0, "net_income": 8.0, "cfo": 12.0, "debt_eff": 10.0},
        {"ticker": "A", "fy": 2020, "af": T("2021-03-20"), "fsDiv": "CFS", "assets": 120.0, "equity": 60.0, "cash": 5.0, "gross_profit": 48.0, "net_income": 10.0, "cfo": 6.0, "debt_eff": 10.0},
        {"ticker": "A", "fy": 2021, "af": T("2022-03-20"), "fsDiv": "OFS", "assets": 150.0, "equity": 60.0, "cash": 5.0, "gross_profit": 45.0, "net_income": 10.0, "cfo": 6.0, "debt_eff": 10.0},  # fsDiv 전환
        {"ticker": "B", "fy": 2018, "af": T("2019-03-20"), "fsDiv": "CFS", "assets": 100.0, "equity": 50.0, "cash": 5.0, "gross_profit": 30.0, "net_income": 8.0, "cfo": 12.0, "debt_eff": 10.0},
        {"ticker": "B", "fy": 2020, "af": T("2021-03-20"), "fsDiv": "CFS", "assets": 130.0, "equity": 50.0, "cash": 5.0, "gross_profit": 30.0, "net_income": 8.0, "cfo": 12.0, "debt_eff": 10.0},  # fy 공백
    ])
    a = add_axes(a3e).set_index(["ticker", "fy"])
    assert abs(a.loc[("A", 2020), "GPA"] - 48 / 120) < 1e-12
    assert abs(a.loc[("A", 2020), "ACCR"] - (6 - 10) / 120) < 1e-12, "ACCR = (CFO−순이익)/자산 이어야 한다(높을수록 좋음)"
    assert abs(a.loc[("A", 2020), "AGR"] - (-(120 / 100 - 1))) < 1e-12, "AGR = −자산성장"
    assert np.isnan(a.loc[("A", 2019), "AGR"]), "전년 레코드가 없으면 AGR 미정의"
    assert np.isnan(a.loc[("A", 2021), "AGR"]), "연결↔별도 전환은 AGR 미정의(가짜 성장 차단)"
    assert np.isnan(a.loc[("B", 2020), "AGR"]), "fiscalYear 공백이면 AGR 미정의"
    assert a.loc[("A", 2021), "GPA"] == 45 / 150, "GPA 는 fsDiv 전환과 무관"
    panel = pd.DataFrame([
        {"ticker": "A", "date": "2021-03-19", "sector": "반도체 제조업", "liquid": True, "pbr": 1.0, TARGET: 0.01, "roe": 0.1, "op_margin": 0.1},
        {"ticker": "A", "date": "2021-04-01", "sector": "반도체 제조업", "liquid": True, "pbr": 1.0, TARGET: 0.01, "roe": 0.1, "op_margin": 0.1},
        {"ticker": "A", "date": "2021-04-01", "sector": "보험업", "liquid": True, "pbr": 1.0, TARGET: 0.01, "roe": 0.1, "op_margin": 0.1},
    ])
    f = build_frame(a3e, panel)
    assert len(f) == 2, "금융업 제외"
    assert abs(f[f.date == "2021-04-01"].iloc[0]["GPA"] - 48 / 120) < 1e-12, "가장 늦은 접수일(2021-03-20) 레코드여야 한다"
    assert abs(f[f.date == "2021-03-19"].iloc[0]["GPA"] - 30 / 100) < 1e-12, "접수 전 달에는 직전 연도 레코드(미래 누수 없음)"
    print("selftest 1/2 OK — 세 축 부호·정의, fsDiv 전환·fy 공백 차단, PIT, 금융 제외")

    ff = build_frame()
    assert (ff["af"].isna() | (ff["af"] <= ff["dt"])).all(), "접수일이 패널 날짜보다 늦다(PIT 위반)"
    a_all = add_axes(load_a3e())
    dup = int(a_all.duplicated(["ticker", "fy"]).sum())
    assert dup < 50, f"(ticker, fy) 중복 {dup}건 — 종목 매핑 점검 필요"
    s = sample(ff, "GPA")
    ms = stage1_months(s)
    p = s.copy()
    p["score_raw"] = p.groupby("date")[SIGCOL].rank(pct=True)
    recs = {d: r for d, _, r, _ in m10.month_top(p, "score_raw")}
    ew = p.groupby("date")[TARGET].mean()
    tr = [1e4 * (recs[d] - ew.loc[d]) for d in sorted(recs) if fd.period_of(str(d)) == "TRAIN"]
    assert len(tr) == len(ms) > 20 and abs(fast_train_excess_bp(ms) - float(np.mean(tr))) < 1e-6, "빠른 경로가 pandas 와 다르다"
    cov = {x: round(float(ff[x].notna().mean()), 3) for x in AXES}
    print(f"selftest 2/2 OK — PIT 위반 0, (ticker,fy) 중복 {dup}건, 빠른 경로=pandas(TRAIN {len(ms)}개월), 축 커버리지 {cov}")


if __name__ == "__main__":
    main()
