#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""11_ev_value_family_oos.py — EV 가치 계열(EBIT/EV · FCF/EV · GP/EV) × PBR 잔차화 결합.

사전등록: findings/a3e-ev-value-family-preregistration-2026-09.md (커밋 6b9c2b52, 정오표 40990a48).
정의·판정 기준은 그 문서가 단일 출처다 — 여기서 값을 바꾸지 않는다.

10_pbr_ey_resid_composite_oos.py 의 함수(add_residual_columns · month_top · strategy_block ·
annual_breakdown)를 **수정 없이 불러 쓴다.** 신호 열을 'earnings_yield' 로 이름만 바꿔 넣으면
선례와 같은 TRAIN-고정 직교화가 그대로 돈다(복사본이 갈라지는 것을 막는다).

  python 11_ev_value_family_oos.py --selftest   # 게이트·PIT·빠른 경로 일치 검사
  python 11_ev_value_family_oos.py              # 전체 실행 → reports/2026-09-21-a3e-ev-value-family/
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import a3e_account_map as M  # noqa: E402
import factor_discovery_kr as fd  # noqa: E402


def _load_10():
    spec = importlib.util.spec_from_file_location("m10", os.path.join(HERE, "10_pbr_ey_resid_composite_oos.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m10 = _load_10()

PANEL = m10.PANEL
A3E = os.path.join(HERE, "data", "fundamentals-ext", "annual-ext-panel.jsonl")
OUT_DIR = os.path.join(HERE, "reports", "2026-09-21-a3e-ev-value-family")
TARGET = "fwd1m"
SIGCOL = "earnings_yield"          # 10 의 add_residual_columns 가 읽는 이름 — 셀 신호를 이 이름으로 넣는다
FIN = re.compile(r"금융|보험|은행|저축|신탁|집합투자|증권|상품 중개")
STALE_DAYS = 500
N_NULL = 1000
SEED = 20260921
CELLS = ["EBIT_EV", "FCF_EV", "GP_EV"]
BEAR_YEARS = ["2018", "2022", "2024"]
COST = 30 / 10000


# ─────────────────────────── 데이터 ───────────────────────────
def load_a3e():
    rows = []
    for l in open(A3E, encoding="utf-8"):
        r = json.loads(l)
        x = M.extract(r)
        rows.append({
            "ticker": r["ticker"], "af": pd.Timestamp(fd.normd(r["availableFrom"])), "fsDiv": r["fsDiv"],
            "equity": x.get("equity"), "cash": x.get("cash"), "op_income": x.get("op_income"),
            "cfo": x.get("cfo"), "capex_ppe": x.get("capex_ppe"), "gross_profit": x.get("gross_profit"),
            "debt_eff": x.get("debt_eff"), "debt_zero_assumed": bool(x.get("debt_zero_assumed")),
        })
    return pd.DataFrame(rows).sort_values("af").reset_index(drop=True)


def build_frame(a3e=None, panel=None):
    """(종목, 월) 프레임 + EV·셀 신호. 게이트 (1)에 쓸 EV 통계를 함께 돌려준다."""
    a3e = (load_a3e() if a3e is None else a3e).sort_values("af").reset_index(drop=True)
    p = pd.read_parquet(PANEL, columns=["ticker", "date", "sector", "liquid", "pbr", TARGET]) if panel is None else panel.copy()
    listed = p["liquid"] & p["pbr"].notna() & (p["pbr"] > 0)
    p = p[listed & ~p["sector"].fillna("").str.contains(FIN)].copy()
    p["dt"] = pd.to_datetime(p["date"])
    p = p.sort_values("dt")
    f = pd.merge_asof(p, a3e, left_on="dt", right_on="af", by="ticker", direction="backward",
                      tolerance=pd.Timedelta(days=STALE_DAYS))
    f["mcap"] = np.where(f["equity"] > 0, f["pbr"] * f["equity"], np.nan)
    f["ev"] = f["mcap"] + f["debt_eff"] - f["cash"]
    has_inputs = f[["mcap", "debt_eff", "cash"]].notna().all(axis=1)
    gate1 = {"nInputs": int(has_inputs.sum()), "evPositive": int((f.loc[has_inputs, "ev"] > 0).sum())}
    gate1["rate"] = gate1["evPositive"] / gate1["nInputs"] if gate1["nInputs"] else None
    f.loc[~(f["ev"] > 0), "ev"] = np.nan
    f["EBIT_EV"] = f["op_income"] / f["ev"]
    f["FCF_EV"] = (f["cfo"] - f["capex_ppe"]) / f["ev"]
    f["GP_EV"] = f["gross_profit"] / f["ev"]
    return f, gate1


def cell_sample(f, cell):
    s = f[f[cell].notna() & f[TARGET].notna()].copy()
    return s.rename(columns={cell: SIGCOL})


def add_scores(s):
    """10 의 add_residual_columns 를 그대로 호출 — 신호 = SIGCOL, 통제 = pbr."""
    r = m10.add_residual_columns(s, ["pbr"])
    r = r.dropna(subset=["ey_res_pbr_fixed"]).copy()
    g = r.groupby("date")
    r["score_pbr"] = 1 - g["pbr"].rank(pct=True)
    r["score_res"] = g["ey_res_pbr_fixed"].rank(pct=True)
    r["score_raw"] = g[SIGCOL].rank(pct=True)
    r["score_comp"] = 0.5 * r["score_pbr"] + 0.5 * r["score_res"]
    return r


# ─────────────────────────── 평가 ───────────────────────────
def turnover(recs):
    seq = [names for _, names, _, _ in recs]
    v = [1 - len(a & b) / len(b) for a, b in zip(seq[:-1], seq[1:]) if b]
    return round(float(np.mean(v)), 4) if v else None


def ttest(x):
    x = np.asarray(x, float)
    if len(x) < 3 or x.std(ddof=1) == 0:
        return None
    return round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 3)


def concat_stats(gross_by_date, dates, cost_bps):
    nets = [gross_by_date[d] - cost_bps / 10000 for d in dates]
    return fd.port_stats(nets)


def evaluate(panel):
    """한 셀 표본(add_scores 결과)의 세 변형 + 대조 통계."""
    ew = panel.groupby("date")[TARGET].mean().sort_index()
    out = {"nRows": len(panel), "nTickers": int(panel["ticker"].nunique()), "nMonths": int(panel["date"].nunique()),
           "avgNamesPerMonth": round(float(panel.groupby("date").size().mean()), 1)}
    recs = {}
    for label, col in [("PBR_only", "score_pbr"), ("RES_only", "score_res"), ("COMP", "score_comp"), ("RAW_only", "score_raw")]:
        rc = m10.month_top(panel, col)
        recs[label] = rc
        blk = m10.strategy_block(panel, col, rc, ew)
        blk["annual"] = m10.annual_breakdown(rc, ew)
        blk["turnover"] = turnover(rc)
        out[label] = blk
    # 짝 비교 — 같은 월끼리
    g = {k: {d: r for d, _, r, _ in recs[k]} for k in ("PBR_only", "COMP")}
    dates = sorted(set(g["PBR_only"]) & set(g["COMP"]))
    per = {p: [d for d in dates if fd.period_of(str(d)) == p] for p in ("TRAIN", "VALID", "TEST")}
    per["OOS"] = per["VALID"] + per["TEST"]
    delta = {}
    for p, ds in per.items():
        a = fd.port_stats([g["COMP"][d] - COST for d in ds]) if ds else {}
        b = fd.port_stats([g["PBR_only"][d] - COST for d in ds]) if ds else {}
        delta[p] = {"nMonths": len(ds), "compSharpe": a.get("sharpe"), "pbrSharpe": b.get("sharpe"),
                    "dSharpe": None if not a or not b or a.get("sharpe") is None or b.get("sharpe") is None
                    else round(a["sharpe"] - b["sharpe"], 3),
                    "compCagr": a.get("cagr"), "pbrCagr": b.get("cagr"), "compMdd": a.get("mdd"), "pbrMdd": b.get("mdd"),
                    "meanGrossDiffBp": round(1e4 * float(np.mean([g["COMP"][d] - g["PBR_only"][d] for d in ds])), 1) if ds else None}
    oos_ds = per["OOS"]
    for c in (30, 50, 65):
        delta[f"OOS_cagr_net{c}"] = {"comp": concat_stats(g["COMP"], oos_ds, c).get("cagr"),
                                     "pbr": concat_stats(g["PBR_only"], oos_ds, c).get("cagr")}
    delta["OOS_excess_t"] = ttest([g["COMP"][d] - g["PBR_only"][d] for d in oos_ds])
    out["delta"] = delta
    # 하락장 연도
    ann_c, ann_p = out["COMP"]["annual"], out["PBR_only"]["annual"]
    bear = {}
    for y in BEAR_YEARS:
        if y in ann_c and y in ann_p:
            bear[y] = {"bench": ann_c[y]["benchCagr"], "comp": ann_c[y]["cagr"], "pbr": ann_p[y]["cagr"],
                       "compBeatsPbr": ann_c[y]["cagr"] > ann_p[y]["cagr"], "benchNegative": (ann_c[y]["benchCagr"] or 0) < 0}
    out["bear"] = bear
    # 상관·구성(기록 전용)
    rc = [(d, m10.monthly_spearman(gg["score_pbr"], gg["score_res"])) for d, gg in panel.groupby("date")]
    out["rankCorr_pbr_res"] = m10.summarize_ic([(d, v) for d, v in rc if v is not None])
    rr = [(d, m10.monthly_spearman(gg["score_pbr"], gg["score_raw"])) for d, gg in panel.groupby("date")]
    out["rankCorr_pbr_raw"] = m10.summarize_ic([(d, v) for d, v in rr if v is not None])
    top = pd.concat([t for _, _, _, t in recs["COMP"]])
    out["compTopProfile"] = {"meanDebtToEv": round(float((top["debt_eff"] / top["ev"]).mean()), 3),
                             "medianMcapBn": round(float(top["mcap"].median() / 1e9), 1),
                             "universeMedianMcapBn": round(float(panel["mcap"].median() / 1e9), 1),
                             "universeMeanDebtToEv": round(float((panel["debt_eff"] / panel["ev"]).mean()), 3)}
    # 상위 1개 연도의 초과수익 집중도(COMP − 벤치)
    ex = {y: v["excess"] for y, v in ann_c.items() if v["excess"] is not None}
    pos = {y: e for y, e in ex.items() if e > 0}
    out["topYearShareOfPositiveExcess"] = round(max(pos.values()) / sum(pos.values()), 3) if pos else None
    return out


# ─────────────────────── 난수 바닥선 (빠른 경로) ───────────────────────
def null_months(panel):
    """TRAIN 월별 배열. 난수 바닥선은 TRAIN ΔSharpe 만 쓰므로 TRAIN 월만 만든다."""
    ms = []
    for d, g in panel.groupby("date", sort=True):
        if fd.period_of(str(d)) != "TRAIN" or len(g) < fd.MIN_NAMES:
            continue
        pr = g["pbr"].rank().to_numpy(float)
        prc = pr - pr.mean()
        if prc.std() == 0:
            continue
        ms.append({"pr": pr, "prc": prc, "den": float((prc ** 2).sum()), "xr": g[SIGCOL].rank().to_numpy(float),
                   "sp": g["score_pbr"].to_numpy(float), "ret": g[TARGET].to_numpy(float), "n": len(g)})
    return ms


def _top_mean(score, ret, n):
    order = np.argsort(score, kind="stable")          # pandas rank(method='first') 와 같은 tie 규칙
    ordinal = np.empty(n)
    ordinal[order] = np.arange(1, n + 1)
    return float(ret[ordinal > 1 + 0.9 * (n - 1)].mean())   # qcut(…, 10) 의 상위 구간과 같다


def _sharpe(nets):
    a = np.asarray(nets, float)
    return float(a.mean() / a.std(ddof=1) * np.sqrt(12)) if a.std(ddof=1) > 0 else 0.0


def fast_gross(ms, xr_list=None):
    """(COMP 월별 gross, PBR 월별 gross). xr_list=None 이면 실제 신호 순위."""
    xs = [m["xr"] for m in ms] if xr_list is None else xr_list
    slopes = [float(m["prc"] @ (x - x.mean()) / m["den"]) for m, x in zip(ms, xs)]
    if len(slopes) < 3:
        return None, None
    beta = float(np.median(slopes))
    comp, pbr = [], []
    for m, x in zip(ms, xs):
        rp = rankdata(x - m["pr"] * beta) / m["n"]
        comp.append(_top_mean(0.5 * m["sp"] + 0.5 * rp, m["ret"], m["n"]))
        pbr.append(_top_mean(m["sp"], m["ret"], m["n"]))
    return comp, pbr


def family_floor(cell_months, rng):
    """세 셀 무작위 신호의 TRAIN ΔSharpe 최대값 분포 → 95번째 백분위."""
    base = {c: _sharpe([r - COST for r in fast_gross(ms)[1]]) for c, ms in cell_months.items()}
    maxes = []
    for _ in range(N_NULL):
        best = -9.0
        for c, ms in cell_months.items():
            xs = [rng.permutation(m["xr"]) for m in ms]
            comp, _ = fast_gross(ms, xs)
            best = max(best, _sharpe([r - COST for r in comp]) - base[c])
        maxes.append(best)
    a = np.array(maxes)
    return {"p95": round(float(np.percentile(a, 95)), 4), "p50": round(float(np.percentile(a, 50)), 4),
            "p99": round(float(np.percentile(a, 99)), 4), "n": N_NULL, "seed": SEED}


# ─────────────────────────── 판정 ───────────────────────────
def gates(cell_eval, gate1):
    g = {"g1_evPositiveRate": None if gate1["rate"] is None else round(gate1["rate"], 4)}
    g["g1_pass"] = bool(gate1["rate"] is not None and gate1["rate"] >= 0.90)
    d = cell_eval["delta"]
    g["g2_months"] = {p: d[p]["nMonths"] for p in ("TRAIN", "VALID", "TEST")}
    g["g2_pass"] = all(v >= 12 for v in g["g2_months"].values())
    corr = cell_eval["rankCorr_pbr_res"]["mean"]
    g["g3_rankCorr"] = corr
    g["g3_pass"] = bool(corr is not None and abs(corr) < 0.3)
    g["pass"] = g["g1_pass"] and g["g2_pass"] and g["g3_pass"]
    return g


def verdict(cell_eval, gate, floor):
    if not gate["pass"]:
        return {"verdict": "UNTESTABLE", "why": "정합 게이트 실패"}
    d = cell_eval["delta"]
    ds = {p: d[p]["dSharpe"] for p in ("TRAIN", "VALID", "TEST")}
    if any(v is None for v in ds.values()):
        return {"verdict": "UNTESTABLE", "why": "구간 Sharpe 없음"}
    info = ds["TRAIN"] >= floor["p95"] and ds["VALID"] > 0 and ds["TEST"] > 0
    o30, o50 = d["OOS_cagr_net30"], d["OOS_cagr_net50"]
    econ = info and o30["comp"] > o30["pbr"] and o50["comp"] > o50["pbr"]
    wins = sum(1 for v in cell_eval["bear"].values() if v["compBeatsPbr"])
    t = d["OOS_excess_t"]
    robust = econ and wins >= 2 and t is not None and t >= 2
    v = "ROBUST" if robust else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "information": bool(info), "economic": bool(econ), "robust": bool(robust),
            "dSharpe": ds, "floorP95": floor["p95"], "bearWins": wins, "oosExcessT": t}


# ─────────────────────────── 실행 ───────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    f, gate1 = build_frame()
    excluded = sorted({s for s in pd.read_parquet(PANEL, columns=["sector"])["sector"].dropna().unique() if FIN.search(s)})
    print(f"프레임 {len(f):,}행 · EV>0 비율 {gate1['rate']:.3f} ({gate1['evPositive']}/{gate1['nInputs']})", flush=True)
    res = {"factor": "a3e-ev-value-family", "mapVersion": M.MAP_VERSION, "preregistration": "6b9c2b52 + 40990a48",
           "excludedFinancialSectors": excluded, "gate1": gate1, "cells": {}, "sensitivity": {}}

    scored, months = {}, {}
    for c in CELLS:
        scored[c] = add_scores(cell_sample(f, c))
        months[c] = null_months(scored[c])
        print(f"  {c}: {len(scored[c]):,}행 · TRAIN 월 {len(months[c])}", flush=True)
    floor = family_floor(months, np.random.default_rng(SEED))
    res["familyFloor"] = floor
    print(f"가족 난수 바닥선 p95={floor['p95']} (p50 {floor['p50']}, p99 {floor['p99']})", flush=True)

    for c in CELLS:
        ev = evaluate(scored[c])
        gt = gates(ev, gate1)
        ev["gates"] = gt
        ev["judgement"] = verdict(ev, gt, floor)
        res["cells"][c] = ev
        d = ev["delta"]
        print(f"  {c}: {ev['judgement']['verdict']} · ΔSharpe T/V/T {d['TRAIN']['dSharpe']}/{d['VALID']['dSharpe']}/{d['TEST']['dSharpe']} "
              f"· 하락장 {sum(v['compBeatsPbr'] for v in ev['bear'].values())}/3 · OOS t {d['OOS_excess_t']} · 게이트 {gt['pass']}", flush=True)

    # 기록 전용 민감도 — 판정에 쓰지 않는다
    for name, mask in [("debtCapturedOnly", ~f["debt_zero_assumed"].fillna(False).astype(bool)),
                       ("cfsOnly", f["fsDiv"] == "CFS")]:
        res["sensitivity"][name] = {}
        for c in CELLS:
            sub = add_scores(cell_sample(f[mask], c))
            e = evaluate(sub)
            res["sensitivity"][name][c] = {"nRows": e["nRows"], "dSharpe": {p: e["delta"][p]["dSharpe"] for p in ("TRAIN", "VALID", "TEST")},
                                           "oosExcessT": e["delta"]["OOS_excess_t"],
                                           "bearWins": sum(v["compBeatsPbr"] for v in e["bear"].values())}
            print(f"  [{name}] {c}: ΔSharpe {res['sensitivity'][name][c]['dSharpe']} 하락장 {res['sensitivity'][name][c]['bearWins']}/3", flush=True)

    # 셀 잔차끼리의 순위 상관(기록 전용)
    cols = {c: scored[c].set_index(["date", "ticker"])["score_res"].rename(c) for c in CELLS}
    j = pd.concat(cols.values(), axis=1, join="inner").reset_index()
    pair = {}
    for x, y in [("EBIT_EV", "FCF_EV"), ("EBIT_EV", "GP_EV"), ("FCF_EV", "GP_EV")]:
        v = [m10.monthly_spearman(g[x], g[y]) for _, g in j.groupby("date")]
        pair[f"{x}~{y}"] = round(float(np.nanmean([q for q in v if q is not None])), 3)
    res["residualRankCorrAmongCells"] = pair
    res["executionTime_s"] = round(time.time() - t0, 1)
    p = os.path.join(OUT_DIR, "a3e-ev-value-family.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    print(f"저장: {p} ({res['executionTime_s']}s)", flush=True)


# ─────────────────────────── selftest ───────────────────────────
def selftest():
    # (1) 정의 검사 — 합성 프레임으로 EV·셀 산식·PIT·금융 제외
    a3e = pd.DataFrame([
        {"ticker": "A", "af": pd.Timestamp("2020-03-20"), "fsDiv": "CFS", "equity": 100.0, "cash": 10.0, "op_income": 20.0,
         "cfo": 30.0, "capex_ppe": 5.0, "gross_profit": 50.0, "debt_eff": 40.0, "debt_zero_assumed": False},
        {"ticker": "A", "af": pd.Timestamp("2021-03-20"), "fsDiv": "CFS", "equity": 200.0, "cash": 10.0, "op_income": 1.0,
         "cfo": 1.0, "capex_ppe": 1.0, "gross_profit": 1.0, "debt_eff": 0.0, "debt_zero_assumed": True},
        {"ticker": "B", "af": pd.Timestamp("2019-01-01"), "fsDiv": "CFS", "equity": 100.0, "cash": 0.0, "op_income": 5.0,
         "cfo": 5.0, "capex_ppe": 1.0, "gross_profit": 5.0, "debt_eff": 0.0, "debt_zero_assumed": False},
    ])
    panel = pd.DataFrame([
        {"ticker": "A", "date": "2020-03-19", "sector": "반도체 제조업", "liquid": True, "pbr": 2.0, TARGET: 0.01},   # 접수 전 → 미정의
        {"ticker": "A", "date": "2020-04-01", "sector": "반도체 제조업", "liquid": True, "pbr": 2.0, TARGET: 0.01},   # 2020 레코드
        {"ticker": "A", "date": "2021-04-01", "sector": "반도체 제조업", "liquid": True, "pbr": 1.0, TARGET: 0.01},   # 2021 레코드
        {"ticker": "B", "date": "2021-06-01", "sector": "반도체 제조업", "liquid": True, "pbr": 1.0, TARGET: 0.01},   # 900일 지남 → 미정의
        {"ticker": "A", "date": "2020-04-01", "sector": "은행 및 저축기관", "liquid": True, "pbr": 1.0, TARGET: 0.01},  # 금융 제외
    ])
    f, g1 = build_frame(a3e, panel)
    assert len(f) == 4, "금융업 1행이 제외돼야 한다"
    r = f[(f.ticker == "A") & (f.date == "2020-04-01")].iloc[0]
    assert r["mcap"] == 200.0 and r["ev"] == 230.0, (r["mcap"], r["ev"])   # 2.0×100 + 40 − 10
    assert abs(r["EBIT_EV"] - 20 / 230) < 1e-12 and abs(r["FCF_EV"] - 25 / 230) < 1e-12 and abs(r["GP_EV"] - 50 / 230) < 1e-12
    pre = f[f.date == "2020-03-19"].iloc[0]
    assert np.isnan(pre["equity"]), "공시 전 달에 미래 레코드가 붙었다(PIT 위반)"
    r21 = f[(f.ticker == "A") & (f.date == "2021-04-01")].iloc[0]
    assert r21["equity"] == 200.0, "가장 늦은 접수일 레코드를 골라야 한다"
    assert np.isnan(f[f.ticker == "B"].iloc[0]["equity"]), "500일 넘은 레코드는 미정의여야 한다"
    print("selftest 1/3 OK — 산식·PIT·500일·금융 제외")

    # (2) 실데이터: 빠른 경로 == 10 의 pandas 경로, 그리고 실제 신호의 게이트 성질
    f, gate1 = build_frame()
    assert gate1["rate"] is not None
    assert (f["af"].isna() | (f["af"] <= f["dt"])).all(), "접수일이 패널 날짜보다 늦은 행이 있다(PIT 위반)"
    assert ((f["dt"] - f["af"]).dropna() <= pd.Timedelta(days=STALE_DAYS)).all()
    s = add_scores(cell_sample(f, "EBIT_EV"))
    ms = null_months(s)
    comp_fast, pbr_fast = fast_gross(ms)
    rc = {lab: {d: r for d, _, r, _ in m10.month_top(s, col)} for lab, col in [("c", "score_comp"), ("p", "score_pbr")]}
    train_dates = sorted(d for d in rc["c"] if fd.period_of(str(d)) == "TRAIN")
    assert len(train_dates) == len(ms) and len(ms) > 20
    assert np.allclose(comp_fast, [rc["c"][d] for d in train_dates]) and np.allclose(pbr_fast, [rc["p"][d] for d in train_dates]), \
        "빠른 난수 경로가 pandas 경로와 다르다 — 바닥선을 믿을 수 없다"
    print(f"selftest 2/3 OK — 빠른 경로가 pandas 와 일치(TRAIN {len(ms)}개월), PIT 위반 0")

    # (3) 잔차 상관·점수 범위
    assert s["score_comp"].between(0, 1).all()
    corr = s[["score_pbr", "score_res"]].corr(method="spearman").iloc[0, 1]
    assert abs(corr) < 0.3, corr
    print(f"selftest 3/3 OK — {len(s):,}행, score_comp∈[0,1], corr(pbr, 잔차)={corr:.3f}, EV>0 비율 {gate1['rate']:.3f}")


if __name__ == "__main__":
    main()
