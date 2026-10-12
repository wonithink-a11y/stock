#!/usr/bin/env python3
"""급락 뒤 횡보 국면의 업종 고르기 — 사전등록 findings/sideways-regime-sector-preregistration-2026-10.md (커밋 c38b60d3) 그대로.

    python research/strategy-lab/sideways_regime_sector.py --selftest
    python research/strategy-lab/sideways_regime_sector.py            # → findings/sideways-regime-sector-results-2026-10.{md,json}

업종지수·배당은 kospi_sector_momentum.load(), KOSPI 는 data/kospi-sector-idx/1001.parquet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kospi_sector_momentum as ksm  # noqa: E402

OUT = HERE / "findings" / "sideways-regime-sector-results-2026-10"
K, COST, STRESS, MIN_SECT = 3, 0.0010, 0.00335, 6
DD, DD_WIN, HI_WIN, HI_MIN = 0.85, 126, 252, 120
RANGE, RANGE_WIN, VOL_WIN = 0.15, 40, 60
N_NULL, SEED, ALPHA, MIN_ERA = 10000, 20261012, 0.05 / 3, 24
JUDGE_END = "2026-07-31"
ERAS = {"1990~2009": (1990, 2009), "2010~2026-07": (2010, 2026)}
PERIODS = {"1990~2009": (1990, 2009), "2010~2023": (2010, 2023), "2024~": (2024, 2030)}
CRISIS = [("1997-11-01", "1998-12-31"), ("2008-01-01", "2008-12-31")]
CELLS = {"M": "40일 수익 상위 3(주도 지속)", "R": "40일 수익 하위 3(소외 되돌림)", "L": "60일 변동성 하위 3(저변동)"}


def regime(P: pd.Series) -> pd.DataFrame:
    dd = P / P.rolling(HI_WIN, min_periods=HI_MIN).max()
    A = dd.rolling(DD_WIN, min_periods=1).min() <= DD
    B = (P.rolling(RANGE_WIN).max() / P.rolling(RANGE_WIN).min() - 1) <= RANGE
    return pd.DataFrame({"A": A, "B": B})


def build(C, Y, R, cell, mode="AB", cost=COST, use_dy=True):
    """mode: AB(국면 달) · notAB(국면 아닌 달) · B(횡보만). 행 = 보유한 달."""
    cal = C.index
    Cf = C.ffill()
    look = max(RANGE_WIN, VOL_WIN)
    ends = [d for d in ksm.month_ends(cal) if cal.get_loc(d) + 1 < len(cal) and cal.get_loc(d) >= look]
    rows, prev, prev_k = [], None, None
    for k in range(len(ends) - 1):
        s, s2 = ends[k], ends[k + 1]
        rg = R.loc[:s]
        if rg.empty:
            continue
        a, b = bool(rg["A"].iloc[-1]), bool(rg["B"].iloc[-1])
        on = {"AB": a and b, "notAB": not (a and b), "B": b}[mode]
        if not on:
            continue
        i = cal.get_loc(s)
        e, e2 = cal[i + 1], cal[cal.get_loc(s2) + 1]
        rs = (C.iloc[i] / C.iloc[i - RANGE_WIN] - 1).dropna()
        vol = C.iloc[i - VOL_WIN:i + 1].pct_change(fill_method=None).std()
        ce, ce2 = C.loc[e], Cf.loc[e2]
        ret = {}
        for tk in rs.index:
            if np.isfinite(ce[tk]) and np.isfinite(ce2[tk]) and np.isfinite(vol.get(tk, np.nan)):
                dy = Y.at[s, tk] if use_dy else 0.0
                dy = float(dy) if np.isfinite(dy) and dy > 0 else 0.0
                ret[tk] = float(ce2[tk] / ce[tk] - 1 + dy / 100 / 12)
        if len(ret) < MIN_SECT:
            continue
        key = {"M": lambda t: (-rs[t], t), "R": lambda t: (rs[t], t), "L": lambda t: (vol[t], t)}[cell]
        picks = sorted(ret, key=key)[:K]
        to = len(set(picks) - set(prev)) / K if prev is not None and prev_k == k - 1 else 1.0
        top, ew = float(np.mean([ret[t] for t in picks])), float(np.mean(list(ret.values())))
        rows.append(dict(signal=s, year=s.year, picks=picks, ret=ret, top=top, ew=ew, turnover=to, X=top - ew - cost * to))
        prev, prev_k = picks, k
    return rows


def mean(rows, f="X"):
    return float(np.mean([r[f] if f != "gross" else r["top"] - r["ew"] for r in rows])) if rows else float("nan")


def judge_cell(J):
    mx, pv, nm = ksm.null_p(J, n=N_NULL, seed=SEED) if J else (float("nan"), 1.0, float("nan"))
    eras = {k: [r for r in J if a <= r["year"] <= b] for k, (a, b) in ERAS.items()}
    era_x = {k: mean(v) for k, v in eras.items()}
    era_n = {k: len(v) for k, v in eras.items()}
    sup = mx > 0 and pv < ALPHA and all(v > 0 for v in era_x.values()) and all(n >= MIN_ERA for n in era_n.values())
    v = "SUPPORTED" if sup else ("REJECT" if not mx > 0 else "INCONCLUSIVE")
    return dict(verdict=v, months=len(J), mean_X=mx, p=pv, null_mean=nm, era_X=era_x, era_n=era_n)


def run():
    C, Y = ksm.load()
    P = pd.read_parquet(ksm.D / "1001.parquet")["close"].astype(float)
    R = regime(P)
    end = pd.Timestamp(JUDGE_END)
    out = {"data": f"{C.index.min().date()}~{C.index.max().date()} · KOSPI ~{P.index.max().date()}", "cells": {}}
    for c in CELLS:
        rows = build(C, Y, R, c)
        J = [r for r in rows if r["signal"] <= end]
        res = judge_cell(J)
        res["gross"] = mean(J, "gross")
        res["turnover"] = mean(J, "turnover")
        res["breakeven_bp"] = res["gross"] / res["turnover"] * 1e4 if res["turnover"] else float("nan")
        res["periods"] = {k: dict(n=len(x), X=mean(x), gross=mean(x, "gross"))
                          for k, (a, b) in PERIODS.items() if (x := [r for r in J if a <= r["year"] <= b])}
        st = [r for r in build(C, Y, R, c, cost=STRESS) if r["signal"] <= end]
        po = [r for r in build(C, Y, R, c, use_dy=False) if r["signal"] <= end]
        na = [r for r in build(C, Y, R, c, mode="notAB") if r["signal"] <= end]
        bo = [r for r in build(C, Y, R, c, mode="B") if r["signal"] <= end]
        nc = [r for r in J if not any(pd.Timestamp(a) <= r["signal"] <= pd.Timestamp(b) for a, b in CRISIS)]
        res["record"] = {"stress_X": mean(st), "price_only_X": mean(po), "not_regime": dict(n=len(na), X=mean(na), gross=mean(na, "gross")),
                         "B_only": dict(n=len(bo), X=mean(bo), gross=mean(bo, "gross")), "ex_crisis": dict(n=len(nc), X=mean(nc))}
        res["pick_counts"] = pd.Series([ksm.SECT[t] for r in J for t in r["picks"]]).value_counts().head(6).to_dict()
        res["current"] = [dict(signal=str(r["signal"].date()), picks=[ksm.SECT[t] for t in r["picks"]], X=r["X"])
                          for r in rows if r["signal"] > end]
        if c == "M":
            out["regime_months"] = [str(r["signal"].date()) for r in J]
        out["cells"][c] = res
    order = {"SUPPORTED": 2, "INCONCLUSIVE": 1, "REJECT": 0}
    out["verdict"] = max((v["verdict"] for v in out["cells"].values()), key=order.get)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print(render(out))


def bp(x):
    return "—" if not np.isfinite(x) else f"{x * 1e4:+.0f}bp"


def render(o):
    cs = o["cells"]
    sig = "있음" if o["verdict"] == "SUPPORTED" else "없음"
    econ = "통과" if o["verdict"] == "SUPPORTED" else "미달"
    head = " / ".join(f"{c} {v['verdict']}({bp(v['mean_X'])}, p {v['p']:.3f})" for c, v in cs.items())
    L = ["---", "track: kr", "factor: sideways-regime-sector", "date: 2026-10-12", f"verdict: {o['verdict']}",
         "criteria_version: research-only (sideways-regime-sector-preregistration-2026-10)",
         'conditions: ["국면 = 126일 안 1년 고점 대비 −15% ∧ 40일 고저폭 ≤ 15%", "KOSPI 업종지수 19개 다음 달 보유, 종가 진입, 배당/12", "M 40일 상위 3 · R 40일 하위 3 · L 60일 저변동 3 vs 업종 등가중", "무작위 3 업종 10,000회 · p < 0.0167 · 두 시기 양", "왕복 10bp × 교체"]',
         "reason: >-", f"  신호: {sig} · 경제성: {econ}. {head}. (스크립트 판정)", "---", "",
         "# 급락 뒤 횡보 국면의 업종 고르기 — 결과", "",
         "투자 자문이 아니다. 수치는 `sideways_regime_sector.py` 출력 그대로. 정의·판정은 사전등록 그대로.", "",
         f"자료 {o['data']} · 판정 국면 달 {cs['M']['months']}개", "",
         "## 1. 판정 (월 순초과 X = 선택 − 업종 등가중 − 10bp × 교체)", "",
         "| 셀 | 달 | 평균 X | 무작위 p | 1990~2009 | 2010~2026-07 | gross | 손익분기 | 판정 |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for c, v in cs.items():
        e = v["era_X"]
        L.append(f"| {c} {CELLS[c]} | {v['months']} | {bp(v['mean_X'])} | {v['p']:.3f} | {bp(e['1990~2009'])} ({v['era_n']['1990~2009']}) | "
                 f"{bp(e['2010~2026-07'])} ({v['era_n']['2010~2026-07']}) | {bp(v['gross'])} | {v['breakeven_bp']:+.0f}bp | **{v['verdict']}** |")
    L += ["", f"전체: **{o['verdict']}** (기준: 평균 X > 0 · p < 0.0167 · 두 시기 모두 양 · 시기별 ≥ 24개월)", "",
          "## 2. 기록 (판정 불사용)", "", "| 셀 | 1990~2009 | 2010~2023 | 2024~ | 스트레스 33.5bp | 가격만 | 위기 제외 | 국면 아닌 달 | 횡보(B)만 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c, v in cs.items():
        p, r = v["periods"], v["record"]
        pc = [f"{bp(p[k]['X'])} ({p[k]['n']})" if k in p else "—" for k in PERIODS]
        L.append(f"| {c} | {' | '.join(pc)} | {bp(r['stress_X'])} | {bp(r['price_only_X'])} | {bp(r['ex_crisis']['X'])} ({r['ex_crisis']['n']}) | "
                 f"{bp(r['not_regime']['X'])} ({r['not_regime']['n']}) | {bp(r['B_only']['X'])} ({r['B_only']['n']}) |")
    L += ["", "자주 뽑힌 업종:", ""] + [f"- {c}: " + " · ".join(f"{k} {n}" for k, n in v["pick_counts"].items()) for c, v in cs.items()]
    L += ["", "현재 사례(2026-08 이후 신호, 판정 불사용):", ""]
    for c, v in cs.items():
        L.append(f"- {c}: " + ("; ".join(f"{x['signal']} {'·'.join(x['picks'])} X {bp(x['X'])}" for x in v["current"]) or "(보유 창이 아직 안 닫힘)"))
    L += ["", f"국면 달({len(o['regime_months'])}): " + " ".join(o["regime_months"]), ""]
    return "\n".join(L)


def selftest():
    cal = pd.bdate_range("2000-01-03", "2001-12-31")
    n = len(cal)
    tks = list(ksm.SECT)
    # 업종 j: 매일 j*0.01% 상승 → M 은 마지막 3, R 은 처음 3. 변동성은 모두 0 근처라 L 은 코드 순 처음 3.
    C = pd.DataFrame({tk: 100 * (1 + 0.0001 * j) ** np.arange(n) for j, tk in enumerate(tks)}, index=cal)
    Y = pd.DataFrame(0.0, index=cal, columns=tks)
    on = pd.DataFrame({"A": True, "B": True}, index=cal)
    m, r = build(C, Y, on, "M"), build(C, Y, on, "R")
    assert m and all(set(x["picks"]) == set(tks[-3:]) for x in m) and all(x["top"] > x["ew"] for x in m)
    assert all(set(x["picks"]) == set(tks[:3]) for x in r) and all(x["top"] < x["ew"] for x in r)
    assert m[0]["turnover"] == 1.0 and all(x["turnover"] == 0 for x in m[1:])
    # 국면이 격월이면 매번 교체 1
    alt = on.copy()
    alt["B"] = [d.month % 2 == 0 for d in cal]
    ma = build(C, Y, alt, "M")
    assert ma and all(x["turnover"] == 1.0 for x in ma) and all(x["signal"].month % 2 == 0 for x in ma)
    assert len(build(C, Y, alt, "M", mode="notAB")) + len(ma) == len(m)
    # 국면 정의: 100 → 80(−20%) 뒤 10% 안에서 횡보하면 A ∧ B
    P = pd.Series(np.r_[np.linspace(100, 100, 260), np.linspace(100, 80, 20), 80 + 4 * np.sin(np.arange(60))],
                  index=pd.bdate_range("2000-01-03", periods=340))
    g = regime(P)
    assert bool(g["A"].iloc[-1]) and bool(g["B"].iloc[-1]) and not bool(g["A"].iloc[250])
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
