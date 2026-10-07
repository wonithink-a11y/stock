#!/usr/bin/env python3
"""반기(H1) 실적 급변(매출 +20% ∧ 영업이익 +30%) 공시 이벤트 — 결과 산출.
사전등록: findings/half-year-growth-event-preregistration-2026-10.md. 정의·기간·비용·판정은 사전등록(= 연간판 규칙)을 그대로 따른다.

    python research/strategy-lab/half_year_growth_event.py --selftest
    python research/strategy-lab/half_year_growth_event.py            # data/half-year-ext + A2a 캐시 필요

판정 셀 E1H 하나. R20H·E1SH·R35H 와 보유 20·120일은 기록 전용.
산출: findings/half-year-growth-event-results-2026-10.{md,json}
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
import annual_growth_event as g

PANEL = HERE / "data" / "half-year-ext" / "half-year-panel.jsonl"
OUT = HERE / "findings" / "half-year-growth-event-results-2026-10"
HOLD, RECORD_HOLDS = 60, (20, 120)
LIQ_MIN, COST_BP, STRESS_BP = 2e9, 33.5, 67.0
SEED, N_NULL, N_BOOT = 20261009, 1000, 2000
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025)}
CELLS = ("E1H", "R20H", "E1SH", "R35H")


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


def in_season(date):
    """접수일이 그 연도 7/1~9/30 안인가(밖이면 지연·정정 공시 추정 → 제외)."""
    return len(date) == 8 and "0701" <= date[4:] <= "0930"


def build_events(rows):
    """rows: half-year-panel 레코드 → (이벤트, 제외 집계). 같은 corp·연도에서 CFS 우선."""
    pick = {}
    for r in rows:
        k = (r["corp"], r["year"])
        if k not in pick or (r["fsDiv"] == "CFS" and pick[k]["fsDiv"] != "CFS"):
            pick[k] = r
    ev, ex = [], {"계정 없음": 0, "시즌 밖": 0, "티커 없음": 0}
    for (corp, yr), r in pick.items():
        rev, op = r.get("revenue"), r.get("op_income")
        if not rev or not op or None in (rev["cur"], rev["prev"], op["cur"], op["prev"]):
            ex["계정 없음"] += 1
            continue
        gr = g.rev_growth(rev["cur"], rev["prev"])
        if gr is None:
            ex["계정 없음"] += 1
            continue
        if not r.get("ticker"):
            ex["티커 없음"] += 1
            continue
        if not in_season(r["availableFrom"]):
            ex["시즌 밖"] += 1
            continue
        ok = g.op_ok(op["cur"], op["prev"])
        cells = []
        if gr >= g.G_MIN - g.EPS:
            cells.append("R20H")
            if ok:
                cells.append("E1H")
                if op["prev"] > 0:
                    cells.append("E1SH")
                if gr >= g.G_STINE - g.EPS:
                    cells.append("R35H")
        for c in cells:
            ev.append({"ticker": r["ticker"], "cell": c, "date": r["availableFrom"], "year": int(r["availableFrom"][:4])})
    return ev, ex


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    rng = np.random.default_rng(SEED)
    rows = [json.loads(l) for l in open(PANEL, encoding="utf-8")]
    ev, excl = build_events(rows)
    res = {"seed": SEED, "cells": {}, "excluded": excl, "records": {},
           "counts_raw": {c: sum(1 for e in ev if e["cell"] == c) for c in CELLS}}

    def prep(h):
        ret = close.shift(-h) / close - 1
        liquid = (liq >= LIQ_MIN) & (vol > 0) & ret.notna()
        return liquid, ret.sub(ret.where(liquid).mean(axis=1), axis=0)

    liquid, excess = prep(HOLD)
    pool = {}
    for i in range(len(dates)):
        row = excess.iloc[i][liquid.iloc[i]].dropna()
        if len(row):
            pool[i] = row.to_numpy() * 1e4

    def collect(cell, ex_h, lq_h, h):
        recs = []
        for e in ev:
            if e["cell"] != cell:
                continue
            w = window_of(e["year"])
            if w is None or e["ticker"] not in ex_h.columns:
                continue
            i = q.entry_index(dates, e["date"])
            if i >= len(dates) - h or not lq_h.iloc[i].get(e["ticker"], False):
                continue
            x = ex_h.iloc[i][e["ticker"]]
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
        out["null_p95_train_bp"] = q.null_p95(df[df.w == "TRAIN"].groupby("i").size().to_dict(), pool, rng, N_NULL)
        if cell == "E1H":
            tr, va, te = (df[df.w == w].ex.to_numpy() for w in WINDOWS)
            out["verdict"] = q.verdict(tr, va, te, out["null_p95_train_bp"] if out["null_p95_train_bp"] is not None else np.inf,
                                       out["OOS"]["net_bp"] if out["OOS"]["net_bp"] is not None else -1e9,
                                       out["OOS"]["net_stress_bp"] if out["OOS"]["net_stress_bp"] is not None else -1e9,
                                       out["oos_cohort_t"])
            # 기록: 거래대금 백분위(시총 통제 아님)
            pct = []
            for e in ev:
                if e["cell"] != "E1H" or e["ticker"] not in liq.columns:
                    continue
                i = q.entry_index(dates, e["date"])
                if i >= len(dates):
                    continue
                row = liq.iloc[i][(liq.iloc[i] >= LIQ_MIN) & (vol.iloc[i] > 0)].dropna()
                v = liq.iloc[i].get(e["ticker"])
                if v is None or np.isnan(v) or v < LIQ_MIN or len(row) < 50:
                    continue
                pct.append((row < v).mean())
            out["liq_pct_mean"] = float(np.mean(pct)) if pct else None
        res["cells"][cell] = out

    for h in RECORD_HOLDS:
        lq, ex_h = prep(h)
        res["records"][str(h)] = {}
        for cell in ("E1H", "R20H"):
            df = collect(cell, ex_h, lq, h)
            res["records"][str(h)][cell] = {w: {"n": int((df.w == w).sum()), "mean_bp": float(df[df.w == w].ex.mean()) if (df.w == w).any() else None}
                                            for w in WINDOWS}
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    E = res["cells"]["E1H"]
    print("E1H", E["verdict"], "events", E["events"], "| OOS mean", E["OOS"]["mean_bp"], "| 제외", excl)


f = q.f


def render(r):
    A = r["cells"]["E1H"]
    v = A["verdict"]
    sig = "있음" if v in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if v in ("ECONOMIC", "ROBUST") else "미달"
    L = ["---", "track: kr", "factor: half-year-growth-event", "date: 2026-10-08", f"verdict: {v}",
         "criteria_version: research-only (half-year-growth-event-preregistration-2026-10)",
         'conditions: ["E1H = 반기 누적 매출 YoY ≥ +20% ∧ 영업이익 흑자·YoY ≥ +30%(반기보고서 접수일)", "60거래일 초과수익(유동 EW 대비)", "TRAIN 2016~2020/VALID 2021~22/TEST 2023~25", "비용 33.5bp"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (스크립트가 계산한 판정 {v}. 공시 연도 10개 — 검출력 낮음.)", "---\n",
         "# 반기 실적 급변 공시 이벤트 — 결과\n",
         "수치는 `half_year_growth_event.py` 가 계산해 그대로 옮긴 값이다. 정의·기간·비용·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정\n", f"**{v}** (신호: {sig} · 경제성: {eco})\n",
         "| 항목 | 값 |\n|---|---|",
         f"| E1H 이벤트 수(구간 필터·청산 가능분) | {A['events']} (원 이벤트 {r['counts_raw']['E1H']}) |",
         f"| 제외(계정 없음 / 시즌 밖 / 티커 없음) | {r['excluded']['계정 없음']} / {r['excluded']['시즌 밖']} / {r['excluded']['티커 없음']} |",
         f"| TRAIN 평균 초과 | {f(A['TRAIN']['mean_bp'])}bp · 난수 바닥선 95p {f(A['null_p95_train_bp'])}bp |",
         f"| VALID / TEST 평균 초과 | {f(A['VALID']['mean_bp'])} / {f(A['TEST']['mean_bp'])}bp |",
         f"| OOS(VALID+TEST) 평균 초과 = **손익분기 비용** | **{f(A['OOS']['breakeven_bp'])}**bp |",
         f"| OOS net (33.5bp) / 스트레스(67bp) | {f(A['OOS']['net_bp'])} / {f(A['OOS']['net_stress_bp'])}bp |",
         f"| OOS 코호트(연도) t | {f(A['oos_cohort_t'], 2)} |",
         f"| 초과수익 상위 1개 연도의 양(+) 코호트 합 대비 비중 | {f(A['top_year_share_of_positive'], 2)} |",
         f"| 기록: 이벤트 종목의 거래대금 백분위 평균(시총 통제 아님) | {f(A.get('liq_pct_mean'), 2)} |\n",
         "## 2. 셀 비교 (60거래일 초과수익 bp, 구간별 평균 [군집 부트스트랩 95%] · 이벤트)\n",
         "| 셀 | TRAIN | VALID | TEST | OOS 손익분기 | 난수 바닥선 |", "|---|---|---|---|---|---|"]
    for c in CELLS:
        x = r["cells"][c]
        cells = [f"{f(x[w]['mean_bp'])} [{f(x[w]['ci95'][0])}, {f(x[w]['ci95'][1])}] · {x[w]['n']}" for w in WINDOWS]
        L.append(f"| {c}{' (판정)' if c == 'E1H' else ' (기록)'} | " + " | ".join(cells) + f" | {f(x['OOS']['breakeven_bp'])} | {f(x['null_p95_train_bp'])} |")
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
            L.append(f"| {h}일 | {c} | " + " | ".join(f"{f(x[w]['mean_bp'])} · {x[w]['n']}" for w in WINDOWS) + " |")
    L.append("\n## 5. 사전등록 대조\n")
    L.append("- 반기보고서 주요계정(DART fnlttMultiAcnt 341콜)만 썼다. 보고서 안의 당기 반기 누적·전년 동기 누적으로 YoY 를 계산했다(CFS 우선).")
    L.append("- 접수일이 7/1~9/30 밖인 보고서는 PIT 불명으로 제외(위 표). 진입 = 다음 거래일 종가, 보유 60거래일, 유동 EW 대비 초과.")
    L.append("- 반기보고서는 8월 중순에 몰려 같은 날 진입한 이벤트가 많다 — 실질 독립 표본은 공시 연도 10개 수준이다.")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    def rec(corp, yr, fs, rc, rp, oc, op, d, tk="000001"):
        return {"ticker": tk, "corp": corp, "year": yr, "fsDiv": fs, "availableFrom": d,
                "revenue": {"cur": rc, "prev": rp}, "op_income": {"cur": oc, "prev": op}}

    rows = [rec("a", 2020, "CFS", 125, 100, 14, 10, "20200814", "A"),      # E1H·E1SH
            rec("b", 2020, "CFS", 150, 100, 8, -5, "20200814", "B"),       # 흑자전환: E1H·R35H, E1SH 아님
            rec("c", 2020, "CFS", 125, 100, 11, 10, "20200814", "C"),      # 영업이익 부족 → R20H 만
            rec("d", 2020, "OFS", 200, 100, 30, 10, "20201120", "D"),      # 시즌 밖 → 제외
            rec("e", 2020, "OFS", 200, 100, 30, 10, "20200814", "E"), rec("e", 2020, "CFS", 90, 100, -5, 10, "20200814", "E"),   # 같은 보고서 CFS 우선 → 탈락
            {"ticker": "F", "corp": "f", "year": 2020, "fsDiv": "CFS", "availableFrom": "20200814", "revenue": {"cur": 1, "prev": 1}}]  # 영업이익 없음
    ev, ex = build_events(rows)
    cells = {(e["ticker"], e["cell"]) for e in ev}
    check("A: R20H·E1H·E1SH", {("A", "R20H"), ("A", "E1H"), ("A", "E1SH")} <= cells)
    check("B: 흑자전환은 E1H·R35H, E1SH 아님", {("B", "E1H"), ("B", "R35H")} <= cells and ("B", "E1SH") not in cells)
    check("C: 영업이익 부족 → R20H 만", ("C", "R20H") in cells and ("C", "E1H") not in cells)
    check("D: 접수일 시즌 밖 제외 + 집계", not any(t == "D" for t, _ in cells) and ex["시즌 밖"] == 1)
    check("E: CFS 우선(OFS 가 통과여도 CFS 가 탈락이면 이벤트 없음)", not any(t == "E" for t, _ in cells))
    check("F: 계정 없음 집계", ex["계정 없음"] == 1)
    check("접수일 시즌 경계", in_season("20200701") and in_season("20200930") and not in_season("20200630") and not in_season("20201001"))
    check("구간: 2016 TRAIN · 2025 TEST · 2026 없음", window_of(2016) == "TRAIN" and window_of(2025) == "TEST" and window_of(2026) is None)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
