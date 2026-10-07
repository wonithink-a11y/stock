#!/usr/bin/env python3
"""실적 급변 이벤트 — 임계값 격자 백테스트(탐색용, 판정 아님).

사용자 요청(2026-10-08): "몇 개 기업인지, 수익률은 어떤지, 어느 조건이 가장 이득인지". 선행 판정(연간·반기 REJECT)은 그대로 유효하다.
이 스크립트는 판정을 바꾸지 않는다 — 매출 증가율 5단계 × 영업이익 조건 5단계 격자의 기록표이다.
'가장 좋은 칸'은 **TRAIN 에서만 고르고** VALID·TEST 에서 확인하며, 격자 전체 최고값은 난수 격자 최고값(95백분위)과 비교한다.

    python research/strategy-lab/growth_grid_explore.py --selftest
    python research/strategy-lab/growth_grid_explore.py

산출: findings/growth-grid-explore-results-2026-10.{md,json}
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
sys.path.insert(0, str(HERE / "futures"))
import quarterly_acceleration_event as q
import annual_growth_event as ag
import half_year_growth_event as hg
from a3e_account_map import extract

OUT = HERE / "findings" / "growth-grid-explore-results-2026-10"
GS = (0.10, 0.20, 0.30, 0.40, 0.60)          # 매출 YoY 하한
KS = (0.0, 1.0, 1.3, 1.6, 2.0)               # 영업이익 조건: 0 = 흑자만, k = 전년 대비 k배 이상(전년 적자·0 은 통과)
LIQ_MIN, SEED, N_NULL, MIN_TR = 2e9, 20261010, 300, 100


def op_pass(op_t, op_p, k):
    """흑자 ∧ (k=0 이면 그것으로 충분, 아니면 전년 적자·0 이거나 당해 ≥ k×전년)."""
    if op_t is None or op_p is None or not op_t > 0:
        return False
    return True if k == 0 else (op_p <= 0 or op_t >= k * op_p - 1e-9)


def annual_events(rows):
    by = {}
    for r in rows:
        v = extract(r)
        by.setdefault((r["ticker"], r["fiscalYear"]), {})[r["fsDiv"]] = (v.get("revenue"), v.get("op_income"), r["availableFrom"])
    out = []
    for (tk, fy), d in by.items():
        p = by.get((tk, fy - 1))
        if not p:
            continue
        fs = next((x for x in ("CFS", "OFS") if x in d and x in p), None)
        if fs is None:
            continue
        rt, ot, date = d[fs]
        rp, op_, _ = p[fs]
        g = ag.rev_growth(rt, rp)
        if g is None or ot is None or op_ is None:
            continue
        out.append({"ticker": tk, "date": date, "year": int(date[:4]), "g": g, "op_t": ot, "op_p": op_})
    return out


def half_events(rows):
    pick = {}
    for r in rows:
        k = (r["corp"], r["year"])
        if k not in pick or (r["fsDiv"] == "CFS" and pick[k]["fsDiv"] != "CFS"):
            pick[k] = r
    out = []
    for r in pick.values():
        rev, op_ = r.get("revenue"), r.get("op_income")
        if not rev or not op_ or None in (rev["cur"], rev["prev"], op_["cur"], op_["prev"]) or not r.get("ticker") or not hg.in_season(r["availableFrom"]):
            continue
        g = ag.rev_growth(rev["cur"], rev["prev"])
        if g is None:
            continue
        out.append({"ticker": r["ticker"], "date": r["availableFrom"], "year": int(r["availableFrom"][:4]), "g": g, "op_t": op_["cur"], "op_p": op_["prev"]})
    return out


def cell_mask(df, g_min, k):
    return (df.g >= g_min - 1e-9) & df.apply(lambda r: op_pass(r.op_t, r.op_p, k), axis=1)


def stats(d):
    if not len(d):
        return {"n": 0, "firms": 0, "ex_mean": None, "ex_med": None, "hit": None, "ret_mean": None, "ex120_mean": None}
    return {"n": int(len(d)), "firms": int(d.ticker.nunique()), "ex_mean": float(d.ex60.mean()), "ex_med": float(d.ex60.median()),
            "hit": float((d.ex60 > 0).mean()), "ret_mean": float(d.ret60.mean()),
            "ex120_mean": float(d.ex120.mean()) if d.ex120.notna().any() else None}


def analyze(name, events, window_of, a, dates, mats, rng):
    close, vol, liq = mats["close"], mats["vol"], mats["liq"]
    h60, h120 = 60, 120
    ret60 = close.shift(-h60) / close - 1
    liquid = (liq >= LIQ_MIN) & (vol > 0) & ret60.notna()
    ex60 = ret60.sub(ret60.where(liquid).mean(axis=1), axis=0)
    ret120 = close.shift(-h120) / close - 1
    liq120 = (liq >= LIQ_MIN) & (vol > 0) & ret120.notna()
    ex120 = ret120.sub(ret120.where(liq120).mean(axis=1), axis=0)
    pool = {i: ex60.iloc[i][liquid.iloc[i]].dropna().to_numpy() * 1e4 for i in range(len(dates)) if liquid.iloc[i].any()}
    recs = []
    for e in events:
        w = window_of(e["year"])
        if w is None or e["ticker"] not in ex60.columns:
            continue
        i = q.entry_index(dates, e["date"])
        if i >= len(dates) - h60 or not liquid.iloc[i].get(e["ticker"], False):
            continue
        x = ex60.iloc[i][e["ticker"]]
        if np.isnan(x):
            continue
        y = ex120.iloc[i][e["ticker"]] if i < len(dates) - h120 and liq120.iloc[i].get(e["ticker"], False) else np.nan
        recs.append({**e, "w": w, "i": i, "ex60": float(x) * 1e4, "ret60": float(ret60.iloc[i][e["ticker"]]) * 1e4,
                     "ex120": float(y) * 1e4 if not np.isnan(y) else np.nan})
    df = pd.DataFrame(recs)
    base = float(np.nanmean([ret60.where(liquid).iloc[i].mean() for i in df.i.unique()]) * 1e4) if len(df) else None
    grid = {}
    for G in GS:
        for K in KS:
            m = cell_mask(df, G, K)
            d = df[m]
            cell = {"all": stats(d)}
            for w in ("TRAIN", "VALID", "TEST"):
                cell[w] = stats(d[d.w == w])
            grid[f"{G:.2f}|{K}"] = cell
    # TRAIN 에서만 고르기
    cand = {k: v for k, v in grid.items() if v["TRAIN"]["n"] >= MIN_TR and v["TRAIN"]["ex_mean"] is not None}
    best = max(cand, key=lambda k: cand[k]["TRAIN"]["ex_mean"]) if cand else None
    # 격자 최고값의 난수 기준: 각 칸의 TRAIN 이벤트 수·진입일 분포를 그대로 두고 무작위 종목으로 바꿔 격자 최대 평균을 반복
    tr = df[df.w == "TRAIN"]
    byc = {}
    for k in cand:
        G, K = float(k.split("|")[0]), float(k.split("|")[1])
        byc[k] = tr[cell_mask(tr, G, K)].groupby("i").size().to_dict()
    maxima = []
    for _ in range(N_NULL):
        mx = -1e18
        for k, bd in byc.items():
            tot = sum(bd.values())
            acc = sum(pool[i][rng.integers(0, len(pool[i]), n)].sum() for i, n in bd.items() if i in pool)
            mx = max(mx, acc / tot)
        maxima.append(mx)
    null95 = float(np.quantile(maxima, 0.95)) if maxima else None
    return {"name": name, "events_usable": int(len(df)), "firms": int(df.ticker.nunique()) if len(df) else 0,
            "market_ret60_bp": base, "grid": grid, "best_train_cell": best, "grid_null_max_p95_bp": null95, "n_cells": len(cand)}


def f(x, nd=0):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def render(res):
    L = ["---", "track: kr", "factor: growth-grid-explore", "date: 2026-10-08", "verdict: EXPLORATORY",
         "criteria_version: research-only (탐색 — 판정 아님, 선행 판정 annual-/half-year-growth-event 은 그대로)",
         'conditions: ["매출 YoY 하한 5단계 × 영업이익 조건 5단계 격자", "60거래일 초과수익·절대수익(유동 EW 대비)", "TRAIN 에서만 최적 칸 선택 → VALID·TEST 확인", "격자 최고값 vs 난수 격자 최고값(95p)"]',
         "reason: >-\n  신호: (탐색 — 판정 없음) · 사용자 요청 '몇 개 기업·수익률·가장 이득인 조건' 의 기록표. 이미 두 번 본 표본이라 결과는 참고용이며 점수·매매·종목 선별에 쓰지 않는다.", "---\n",
         "# 실적 급변 임계값 격자 — 탐색 백테스트\n",
         "정의: 매출 YoY ≥ G, 영업이익 조건 K(0 = 흑자만 · k = 전년 대비 k배 이상, 전년 적자·0 은 통과). 진입 = 공시 다음 거래일 종가, 60거래일 보유, 초과 = 같은 날 유동 유니버스 EW 대비. "
         "유동성 ≥ 20억. 비용 33.5bp 는 칸마다 빼지 않았다(표의 값은 비용 전).\n"]
    for key, title in (("annual", "연간 사업보고서 공시(3월 말)"), ("half", "반기보고서 공시(8월 중순)")):
        r = res[key]
        L.append(f"## {title}\n")
        L.append(f"- 사용 가능 이벤트 {r['events_usable']}건 · 회사 {r['firms']}곳 · 같은 진입일 유동 종목 평균 60일 수익(참고) {f(r['market_ret60_bp'])}bp")
        L.append(f"- 격자 {r['n_cells']}칸(TRAIN 이벤트 ≥{MIN_TR}). TRAIN 최고 칸 = **{r['best_train_cell']}**(G|K). 난수 격자 최고값 95백분위 = **{f(r['grid_null_max_p95_bp'])}bp**.\n")
        L.append("### 칸별 전체 기간 — 이벤트 수 / 회사 수 / 초과수익 평균·중앙값(bp) / 초과>0 비율 / 절대수익 평균(bp) / 120일 초과 평균\n")
        L.append("| 매출 ≥ | 영업이익 조건 | 이벤트 | 회사 | 초과 평균 | 초과 중앙 | 승률 | 절대수익 평균 | 120일 초과 |\n|---|---|---|---|---|---|---|---|---|")
        for G in GS:
            for K in KS:
                c = r["grid"][f"{G:.2f}|{K}"]["all"]
                kl = "흑자만" if K == 0 else f"전년 ×{K}"
                L.append(f"| {G:.0%} | {kl} | {c['n']} | {c['firms']} | {f(c['ex_mean'])} | {f(c['ex_med'])} | {f(c['hit'] * 100 if c['hit'] is not None else None)}% | {f(c['ret_mean'])} | {f(c['ex120_mean'])} |")
        L.append("\n### 구간별 초과 평균(bp)·이벤트 — TRAIN / VALID / TEST\n")
        L.append("| 매출 ≥ | 영업이익 조건 | TRAIN | VALID | TEST |\n|---|---|---|---|---|")
        for G in GS:
            for K in KS:
                c = r["grid"][f"{G:.2f}|{K}"]
                kl = "흑자만" if K == 0 else f"전년 ×{K}"
                L.append(f"| {G:.0%} | {kl} | " + " | ".join(f"{f(c[w]['ex_mean'])} · {c[w]['n']}" for w in ("TRAIN", "VALID", "TEST")) + " |")
        b = r["best_train_cell"]
        if b:
            c = r["grid"][b]
            L.append(f"\n**TRAIN 에서 고른 칸 {b}**: TRAIN {f(c['TRAIN']['ex_mean'])}bp({c['TRAIN']['n']}건) → VALID {f(c['VALID']['ex_mean'])}bp({c['VALID']['n']}건) → TEST {f(c['TEST']['ex_mean'])}bp({c['TEST']['n']}건). "
                     f"TRAIN 값이 난수 격자 최고값 95p({f(r['grid_null_max_p95_bp'])}bp) {'을 넘었다' if c['TRAIN']['ex_mean'] > r['grid_null_max_p95_bp'] else '을 넘지 못했다'}.\n")
    L.append("## 읽는 법과 한계\n")
    L.append("- 이 표는 **기록**이다. 칸이 25개라 우연히 높은 칸이 반드시 생기므로 '가장 높은 칸'을 최적 조건으로 읽지 않는다. 신뢰할 수 있는 읽기는 ① TRAIN 에서 고른 칸이 VALID·TEST 에서도 유지되는가, ② 격자 최고값이 난수 격자 최고값을 넘는가 두 가지다.")
    L.append("- 칸들이 포개져 있어(조건을 조일수록 부분집합) 서로 독립이 아니다. 같은 이벤트가 여러 칸에 반복된다.")
    L.append("- 사건이 3월 말·8월 중순에 몰려 실질 독립 표본은 공시 연도 10개 수준이고, 시총·업종·PBR 통제가 없다.")
    L.append("- 점수·매매·종목 선별에 연결하지 않는다. 투자 자문이 아니다.")
    return "\n".join(L) + "\n"


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    mats = {"close": a.pivot(index="date", columns="ticker", values="close").reindex(dates),
            "vol": a.pivot(index="date", columns="ticker", values="volume").reindex(dates),
            "liq": a.pivot(index="date", columns="ticker", values="liq").reindex(dates)}
    rng = np.random.default_rng(SEED)
    arows = [json.loads(l) for l in open(ag.PANEL, encoding="utf-8")]
    hrows = [json.loads(l) for l in open(hg.PANEL, encoding="utf-8")]
    res = {"annual": analyze("annual", annual_events(arows), ag.window_of, a, dates, mats, rng),
           "half": analyze("half", half_events(hrows), hg.window_of, a, dates, mats, rng)}
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    for k in ("annual", "half"):
        r = res[k]
        print(k, "events", r["events_usable"], "firms", r["firms"], "best", r["best_train_cell"], "null95", r["grid_null_max_p95_bp"])


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("op_pass: 흑자만(k=0)", op_pass(1, 100, 0) and not op_pass(-1, -5, 0))
    check("op_pass: 전년 적자·0 은 통과", op_pass(1, -5, 1.3) and op_pass(1, 0, 2.0))
    check("op_pass: 배수 경계", op_pass(130, 100, 1.3) and not op_pass(129, 100, 1.3) and op_pass(100, 100, 1.0))
    df = pd.DataFrame({"ticker": list("ABC"), "g": [0.25, 0.15, 0.7], "op_t": [10, 10, 10], "op_p": [5, 5, -1]})
    check("cell_mask: G=0.2,K=1.3", cell_mask(df, 0.20, 1.3).tolist() == [True, False, True])
    check("cell_mask: G=0.6,K=2.0", cell_mask(df, 0.60, 2.0).tolist() == [False, False, True])
    s = stats(pd.DataFrame({"ticker": ["A", "A", "B"], "ex60": [100.0, -50.0, 30.0], "ret60": [1.0, 2.0, 3.0], "ex120": [np.nan, np.nan, np.nan]}))
    check("stats: n·회사·평균·승률", s["n"] == 3 and s["firms"] == 2 and abs(s["ex_mean"] - 80 / 3) < 1e-9 and abs(s["hit"] - 2 / 3) < 1e-9 and s["ex120_mean"] is None)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
