#!/usr/bin/env python3
"""연간 실적 급변(매출 +20% ∧ 영업이익 +30%) 공시 이벤트 — 결과 산출.
사전등록: findings/annual-growth-event-preregistration-2026-10.md (dbf55bfb). 정의·기간·비용·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/annual_growth_event.py --selftest   # 네트워크·캐시 없음
    python research/strategy-lab/annual_growth_event.py              # A2a 캐시 필요

판정 셀 E1 하나. R20·E1S·R35 와 보유 20·120일은 기록 전용.
산출: findings/annual-growth-event-results-2026-10.{md,json}
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
import quarterly_acceleration_event as q  # boot_ci·null_p95·verdict·entry_index·f 재사용(정의 동일)
from a3e_account_map import extract

PANEL = HERE / "data" / "fundamentals-ext" / "annual-ext-panel.jsonl"
OUT = HERE / "findings" / "annual-growth-event-results-2026-10"
HOLD = 60
RECORD_HOLDS = (20, 120)
LIQ_MIN = 2e9
COST_BP, STRESS_BP = 33.5, 67.0
SEED, N_NULL, N_BOOT = 20261008, 1000, 2000
WINDOWS = {"TRAIN": (2017, 2020), "VALID": (2021, 2022), "TEST": (2023, 2026)}
CELLS = ("E1", "R20", "E1S", "R35")
G_MIN, G_STINE, OP_MULT = 0.20, 0.35, 1.3
EPS = 1e-9


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


def rev_growth(rev_t, rev_p):
    """매출 YoY. 두 해 모두 양(+)일 때만 정의(사전등록 §1)."""
    if rev_t is None or rev_p is None or not (rev_t > 0 and rev_p > 0):
        return None
    return rev_t / rev_p - 1


def op_ok(op_t, op_p):
    """영업이익 조건: 당해 흑자 ∧ (전년 적자·0 이거나 당해 ≥ 1.3×전년). 전년 값이 없으면 정의 안 됨."""
    if op_t is None or op_p is None or not op_t > 0:
        return False
    return op_p <= 0 or op_t >= OP_MULT * op_p


def build_events(rows):
    """rows: 패널 레코드 → 이벤트 [{ticker, cell, date, year}]. 같은 fsDiv 로 FY t, t−1 이 모두 있어야 한다(CFS 우선)."""
    by = {}
    for r in rows:
        v = extract(r)
        by.setdefault((r["ticker"], r["fiscalYear"]), {})[r["fsDiv"]] = (v.get("revenue"), v.get("op_income"), r["availableFrom"])
    ev = []
    for (tk, fy), d in by.items():
        p = by.get((tk, fy - 1))
        if not p:
            continue
        fs = next((x for x in ("CFS", "OFS") if x in d and x in p), None)
        if fs is None:
            continue
        rev_t, op_t, date = d[fs]
        rev_p, op_p, _ = p[fs]
        g = rev_growth(rev_t, rev_p)
        if g is None or op_t is None or op_p is None:
            continue
        ok = op_ok(op_t, op_p)
        cells = []
        if g >= G_MIN - EPS:     # 부동소수 경계(120/100−1 = 0.19999…) 보정
            cells.append("R20")
            if ok:
                cells.append("E1")
                if op_p > 0:
                    cells.append("E1S")
                if g >= G_STINE - EPS:
                    cells.append("R35")
        for c in cells:
            ev.append({"ticker": tk, "cell": c, "date": date, "year": int(date[:4])})
    return ev


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    rng = np.random.default_rng(SEED)

    rows = [json.loads(l) for l in open(PANEL, encoding="utf-8")]
    ev = build_events(rows)
    res = {"seed": SEED, "cells": {}, "counts_raw": {c: sum(1 for e in ev if e["cell"] == c) for c in CELLS}, "records": {}}

    def prep(h):
        ret = close.shift(-h) / close - 1
        liquid = (liq >= LIQ_MIN) & (vol > 0) & ret.notna()
        base = ret.where(liquid).mean(axis=1)
        return liquid, ret.sub(base, axis=0)

    liquid, excess = prep(HOLD)
    pool = {}
    for i in range(len(dates)):
        row = excess.iloc[i][liquid.iloc[i]].dropna()
        if len(row):
            pool[i] = row.to_numpy() * 1e4

    def collect(cell, excess_h, liquid_h, h):
        recs = []
        for e in ev:
            if e["cell"] != cell:
                continue
            w = window_of(e["year"])
            if w is None or e["ticker"] not in excess_h.columns:
                continue
            i = q.entry_index(dates, e["date"])
            if i >= len(dates) - h or not liquid_h.iloc[i].get(e["ticker"], False):
                continue
            x = excess_h.iloc[i][e["ticker"]]
            if np.isnan(x):
                continue
            recs.append((w, e["year"], i, float(x) * 1e4))
        return pd.DataFrame(recs, columns=["w", "year", "i", "ex"])

    for cell in CELLS:
        df = collect(cell, excess, liquid, HOLD)
        out = {"events": int(len(df))}
        for w in WINDOWS:
            d = df[df.w == w]
            out[w] = {"n": int(len(d)), "mean_bp": float(d.ex.mean()) if len(d) else None,
                      "median_bp": float(d.ex.median()) if len(d) else None,
                      "ci95": list(q.boot_ci(d.ex, d.i, rng, N_BOOT)) if len(d) else [None, None]}
        coh = df.groupby("year").ex.agg(["count", "mean"])
        out["cohorts"] = {int(y): {"n": int(r["count"]), "mean_bp": float(r["mean"])} for y, r in coh.iterrows()}
        oos = df[df.w != "TRAIN"]
        out["OOS"] = {"n": int(len(oos)), "mean_bp": float(oos.ex.mean()) if len(oos) else None,
                      "net_bp": float(oos.ex.mean() - COST_BP) if len(oos) else None,
                      "net_stress_bp": float(oos.ex.mean() - STRESS_BP) if len(oos) else None,
                      "breakeven_bp": float(oos.ex.mean()) if len(oos) else None}
        oy = oos.groupby("year").ex.mean()
        out["oos_cohort_t"] = float(oy.mean() / (oy.std(ddof=1) / np.sqrt(len(oy)))) if len(oy) > 2 and oy.std(ddof=1) > 0 else None
        posc = coh["mean"].clip(lower=0)
        out["top_year_share_of_positive"] = float(posc.max() / posc.sum()) if posc.sum() > 0 else None
        tr_by_date = df[df.w == "TRAIN"].groupby("i").size().to_dict()
        out["null_p95_train_bp"] = q.null_p95(tr_by_date, pool, rng, N_NULL)
        if cell == "E1":
            tr, va, te = (df[df.w == w].ex.to_numpy() for w in WINDOWS)
            out["verdict"] = q.verdict(tr, va, te, out["null_p95_train_bp"] if out["null_p95_train_bp"] is not None else np.inf,
                                       out["OOS"]["net_bp"] if out["OOS"]["net_bp"] is not None else -1e9,
                                       out["OOS"]["net_stress_bp"] if out["OOS"]["net_stress_bp"] is not None else -1e9,
                                       out["oos_cohort_t"])
        res["cells"][cell] = out

    for h in RECORD_HOLDS:       # 기록 전용: 판정에 쓰지 않는다
        lq, ex_h = prep(h)
        res["records"][str(h)] = {}
        for cell in ("E1", "R20"):
            df = collect(cell, ex_h, lq, h)
            res["records"][str(h)][cell] = {w: {"n": int((df.w == w).sum()), "mean_bp": float(df[df.w == w].ex.mean()) if (df.w == w).any() else None}
                                            for w in WINDOWS}
    res["excluded_note"] = "청산이 A2a 캐시 끝(2026-08-03)을 넘는 이벤트는 자동 제외"
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    E = res["cells"]["E1"]
    print("E1", E["verdict"], "events", E["events"], "| OOS mean", E["OOS"]["mean_bp"])


f = q.f


def render(r):
    A = r["cells"]["E1"]
    v = A["verdict"]
    sig = "있음" if v in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if v in ("ECONOMIC", "ROBUST") else "미달"
    L = ["---", "track: kr", "factor: annual-growth-event", "date: 2026-10-08", f"verdict: {v}",
         "criteria_version: research-only (annual-growth-event-preregistration-2026-10, dbf55bfb)",
         'conditions: ["E1 = 연간 매출 YoY ≥ +20% ∧ 영업이익 흑자·YoY ≥ +30%(사업보고서 공시일)", "60거래일 초과수익(유동 EW 대비)", "TRAIN 2017~2020/VALID 2021~22/TEST 2023~26", "비용 33.5bp"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (스크립트가 계산한 판정 {v}. 연간 제한판 — 코호트 10개, 반기 실적은 못 봤다.)", "---\n",
         "# 연간 실적 급변 공시 이벤트 — 결과\n",
         "수치는 `annual_growth_event.py` 가 계산해 그대로 옮긴 값이다. 정의·기간·비용·판정은 사전등록(dbf55bfb) 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정\n", f"**{v}** (신호: {sig} · 경제성: {eco})\n",
         "| 항목 | 값 |\n|---|---|",
         f"| E1 이벤트 수(구간 필터·청산 가능분) | {A['events']} (원 이벤트 {r['counts_raw']['E1']}) |",
         f"| TRAIN 평균 초과 | {f(A['TRAIN']['mean_bp'])}bp · 난수 바닥선 95p {f(A['null_p95_train_bp'])}bp |",
         f"| VALID / TEST 평균 초과 | {f(A['VALID']['mean_bp'])} / {f(A['TEST']['mean_bp'])}bp |",
         f"| OOS(VALID+TEST) 평균 초과 = **손익분기 비용** | **{f(A['OOS']['breakeven_bp'])}**bp |",
         f"| OOS net (33.5bp) / 스트레스(67bp) | {f(A['OOS']['net_bp'])} / {f(A['OOS']['net_stress_bp'])}bp |",
         f"| OOS 코호트(연도) t | {f(A['oos_cohort_t'], 2)} |",
         f"| 초과수익 상위 1개 연도의 양(+) 코호트 합 대비 비중 | {f(A['top_year_share_of_positive'], 2)} |\n",
         "## 2. 셀 비교 (60거래일 초과수익 bp, 구간별 평균 [군집 부트스트랩 95%] · 이벤트)\n",
         "| 셀 | TRAIN | VALID | TEST | OOS 손익분기 | 난수 바닥선 |", "|---|---|---|---|---|---|"]
    for c in CELLS:
        x = r["cells"][c]
        cells = [f"{f(x[w]['mean_bp'])} [{f(x[w]['ci95'][0])}, {f(x[w]['ci95'][1])}] · {x[w]['n']}" for w in q_windows()]
        L.append(f"| {c}{' (판정)' if c == 'E1' else ' (기록)'} | " + " | ".join(cells) +
                 f" | {f(x['OOS']['breakeven_bp'])} | {f(x['null_p95_train_bp'])} |")
    L.append("\n## 3. 코호트(공시 연도)별 평균 초과 bp / 이벤트 수\n")
    yrs = sorted({y for c in CELLS for y in r["cells"][c]["cohorts"]})
    L.append("| 셀 | " + " | ".join(str(y) for y in yrs) + " |")
    L.append("|---|" + "---|" * len(yrs))
    for c in CELLS:
        co = r["cells"][c]["cohorts"]
        L.append(f"| {c} | " + " | ".join(f"{f(co[y]['mean_bp'], 0)}/{co[y]['n']}" if y in co else "-" for y in yrs) + " |")
    L.append("\n## 4. 기록 전용 — 보유기간 20·120거래일 평균 초과 bp (판정 아님)\n")
    L.append("| 보유 | 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|---|")
    for h, d in r["records"].items():
        for c, x in d.items():
            L.append(f"| {h}일 | {c} | " + " | ".join(f"{f(x[w]['mean_bp'])} · {x[w]['n']}" for w in q_windows()) + " |")
    L.append("\n## 5. 사전등록 대조\n")
    L.append("- 연간 재무 패널(A3e, a3e-map-1.1)만 썼고 새 수집은 없다. 반기(H1) 매출·영업이익은 자료가 없어 못 봤다.")
    L.append("- 진입 = 공시일 다음 거래일 종가, 보유 60거래일, 유동 유니버스 EW 대비 초과. 청산이 캐시 끝을 넘는 이벤트는 자동 제외.")
    L.append("- 신뢰구간은 진입일 군집 부트스트랩이다. 사업보고서는 3월 말에 몰려 같은 날 진입한 이벤트가 많다 — 실질 독립 표본은 코호트(연도) 10개 수준이다.")
    return "\n".join(L) + "\n"


def q_windows():
    return list(WINDOWS)


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("매출 성장률: 양·양만 정의", abs(rev_growth(120, 100) - 0.2) < 1e-12 and rev_growth(-1, 100) is None and rev_growth(100, 0) is None)
    check("영업이익 조건: 흑자전환 통과", op_ok(10, -5) and op_ok(10, 0))
    check("영업이익 조건: 1.3배 경계", op_ok(130, 100) and not op_ok(129, 100))
    check("영업이익 조건: 당해 적자 탈락·전년 미정의 탈락", not op_ok(-1, -5) and not op_ok(10, None))

    def rec(tk, fy, fs, rev, op, d):
        return {"ticker": tk, "fiscalYear": fy, "fsDiv": fs, "availableFrom": d,
                "rows": [["IS", "ifrs-full_Revenue", "매출액", rev], ["IS", "dart_OperatingIncomeLoss", "영업이익", op]]}

    rows = [rec("A", 2019, "CFS", 100, 10, "20200325"), rec("A", 2020, "CFS", 125, 14, "20210325"),    # E1 통과·E1S 통과
            rec("B", 2019, "CFS", 100, -5, "20200325"), rec("B", 2020, "CFS", 150, 8, "20210325"),    # 흑자전환: E1·R35 통과, E1S 아님
            rec("C", 2019, "CFS", 100, 10, "20200325"), rec("C", 2020, "CFS", 125, 11, "20210325"),   # 영업이익 +10% → R20 만
            rec("D", 2019, "CFS", 100, 10, "20200325"), rec("D", 2020, "OFS", 200, 30, "20210325"),   # fsDiv 불일치 → 제외
            rec("E", 2019, "OFS", 100, 10, "20200325"), rec("E", 2020, "OFS", 120, 20, "20210325")]   # 별도 기준 E1·E1S
    cells = {(e["ticker"], e["cell"]) for e in build_events(rows)}
    check("A: R20·E1·E1S", {("A", "R20"), ("A", "E1"), ("A", "E1S")} <= cells and ("A", "R35") not in cells)
    check("B: 흑자전환은 E1·R35, E1S 아님", {("B", "E1"), ("B", "R35")} <= cells and ("B", "E1S") not in cells)
    check("C: 영업이익 부족 → R20 만", ("C", "R20") in cells and ("C", "E1") not in cells)
    check("D: 연결/별도 혼합 → 제외", not any(t == "D" for t, _ in cells))
    check("E: 별도(OFS) 두 해면 사용", ("E", "E1") in cells)
    check("구간: 공시 2017~2020 TRAIN · 2026 TEST · 2016 없음", window_of(2017) == "TRAIN" and window_of(2026) == "TEST" and window_of(2016) is None)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
