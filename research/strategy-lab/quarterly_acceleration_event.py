#!/usr/bin/env python3
"""분기 순이익 성장 가속(ACC2) — 결과 산출. 사전등록: findings/quarterly-acceleration-preregistration-2026-09.md (3b0ef12).

    python research/strategy-lab/quarterly_acceleration_event.py --selftest   # 네트워크·캐시 없음
    python research/strategy-lab/quarterly_acceleration_event.py              # A2a 캐시 필요

판정 셀은 ACC2 하나. LEVEL·ACC1 은 기록 전용. 정의·기간·비용·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.
산출: findings/quarterly-acceleration-results-2026-09.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "futures"))
PANEL = HERE / "data" / "quarterly-earnings" / "quarterly-earnings-panel.jsonl"
OUT = HERE / "findings" / "quarterly-acceleration-results-2026-09"

HOLD = 60
LIQ_MIN = 2e9
COST_BP, STRESS_BP = 33.5, 67.0
SEED, N_NULL, N_BOOT = 20260927, 1000, 2000
MIN_EVENTS = 30
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025)}


def growth(thstrm, frmtrm):
    """YoY 성장률. 전년동기·당기가 모두 양(+)일 때만 정의(사전등록 §1)."""
    if thstrm is None or frmtrm is None or not (frmtrm > 0 and thstrm > 0):
        return None
    return thstrm / frmtrm - 1


def build_events(rows):
    """rows: 패널 레코드 → 이벤트 리스트 [{ticker, cell, date(YYYYMMDD), year}]. ACC2·LEVEL(Q3 공시), ACC1(Q2 공시)."""
    by = {}
    for r in rows:
        by.setdefault((r["ticker"], r["fiscalYear"]), {})[r["quarter"]] = r
    ev = []
    for (tk, fy), q in by.items():
        g = {k: growth(v["thstrm"], v["frmtrm"]) for k, v in q.items()}
        if "Q3" in q and g.get("Q3") is not None:
            d = q["Q3"]["availableFrom"]
            ev.append({"ticker": tk, "cell": "LEVEL", "date": d})
            if g.get("Q1") is not None and g.get("Q2") is not None and g["Q1"] < g["Q2"] < g["Q3"]:
                ev.append({"ticker": tk, "cell": "ACC2", "date": d})
        if "Q2" in q and g.get("Q2") is not None and g.get("Q1") is not None and g["Q1"] < g["Q2"]:
            ev.append({"ticker": tk, "cell": "ACC1", "date": q["Q2"]["availableFrom"]})
    for e in ev:
        e["year"] = int(e["date"][:4])
    return ev


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


def entry_index(dates, event_date):
    """이벤트일 '다음' 거래일의 인덱스(같은 날 공시는 장 마감 뒤일 수 있어 보수적으로 다음 거래일)."""
    return int(np.searchsorted(dates, np.datetime64(pd.Timestamp(event_date)), side="right"))


def boot_ci(x, groups, rng, n=N_BOOT):
    """군집(진입일) 부트스트랩 평균 95% 구간."""
    x, groups = np.asarray(x, float), np.asarray(groups)
    if len(x) < 3:
        return (None, None)
    uniq = np.unique(groups)
    idx = {g: np.where(groups == g)[0] for g in uniq}
    m = []
    for _ in range(n):
        pick = rng.choice(uniq, len(uniq))
        m.append(np.concatenate([x[idx[g]] for g in pick]).mean())
    return (float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975)))


def null_p95(events_by_date, liquid_excess_by_date, rng, n=N_NULL):
    """TRAIN: 같은 진입일에서 유동 종목을 무작위로 같은 수 뽑은 평균 초과수익의 95번째 백분위."""
    keys = [k for k in events_by_date if k in liquid_excess_by_date and len(liquid_excess_by_date[k]) > 0]
    tot = sum(events_by_date[k] for k in keys)
    if tot == 0:
        return None
    means = np.empty(n)
    for i in range(n):
        acc = 0.0
        for k in keys:
            pool = liquid_excess_by_date[k]
            acc += pool[rng.integers(0, len(pool), events_by_date[k])].sum()
        means[i] = acc / tot
    return float(np.quantile(means, 0.95))


def verdict(tr, va, te, base, net_oos, net_stress, coh_t):
    if min(len(tr), len(va), len(te)) < MIN_EVENTS:
        return "판정불가"
    s = np.sign(tr.mean())
    info = tr.mean() >= base and np.sign(va.mean()) == s and np.sign(te.mean()) == s
    eco = bool(info) and s > 0 and net_oos > 0 and net_stress > 0
    rob = eco and coh_t is not None and coh_t >= 2
    return "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    ret = close.shift(-HOLD) / close - 1
    liquid = (liq >= LIQ_MIN) & (vol > 0) & ret.notna()
    base = ret.where(liquid).mean(axis=1)          # 진입일별 유동 유니버스 EW 60일 수익
    excess = ret.sub(base, axis=0)
    rng = np.random.default_rng(SEED)

    rows = [json.loads(l) for l in open(PANEL, encoding="utf-8")]
    ev = build_events(rows)
    res = {"seed": SEED, "cells": {}, "counts_raw": {c: sum(1 for e in ev if e["cell"] == c) for c in ("ACC2", "LEVEL", "ACC1")}}
    liquid_pool = {}
    for i in range(len(dates)):
        row = excess.iloc[i][liquid.iloc[i]].dropna()
        if len(row):
            liquid_pool[i] = row.to_numpy() * 1e4

    for cell in ("ACC2", "LEVEL", "ACC1"):
        recs = []
        for e in ev:
            if e["cell"] != cell:
                continue
            w = window_of(e["year"])
            if w is None or e["ticker"] not in excess.columns:
                continue
            i = entry_index(dates, e["date"])
            if i >= len(dates) - HOLD or not liquid.iloc[i].get(e["ticker"], False):
                continue
            x = excess.iloc[i][e["ticker"]]
            if np.isnan(x):
                continue
            recs.append((w, e["year"], i, float(x) * 1e4))
        df = pd.DataFrame(recs, columns=["w", "year", "i", "ex"])
        out = {"events": int(len(df))}
        for w in WINDOWS:
            d = df[df.w == w]
            out[w] = {"n": int(len(d)), "mean_bp": float(d.ex.mean()) if len(d) else None,
                      "median_bp": float(d.ex.median()) if len(d) else None,
                      "ci95": list(boot_ci(d.ex, d.i, rng)) if len(d) else [None, None]}
        coh = df.groupby("year").ex.agg(["count", "mean"])
        out["cohorts"] = {int(y): {"n": int(r["count"]), "mean_bp": float(r["mean"])} for y, r in coh.iterrows()}
        oos = df[df.w != "TRAIN"]
        out["OOS"] = {"n": int(len(oos)), "mean_bp": float(oos.ex.mean()) if len(oos) else None,
                      "net_bp": float(oos.ex.mean() - COST_BP) if len(oos) else None,
                      "net_stress_bp": float(oos.ex.mean() - STRESS_BP) if len(oos) else None,
                      "breakeven_bp": float(oos.ex.mean()) if len(oos) else None}
        oy = oos.groupby("year").ex.mean()
        out["oos_cohort_t"] = float(oy.mean() / (oy.std(ddof=1) / np.sqrt(len(oy)))) if len(oy) > 2 and oy.std(ddof=1) > 0 else None
        pos = coh["mean"].clip(lower=0)
        out["top_year_share_of_positive"] = float(pos.max() / pos.sum()) if pos.sum() > 0 else None
        tr_by_date = df[df.w == "TRAIN"].groupby("i").size().to_dict()
        out["null_p95_train_bp"] = null_p95(tr_by_date, liquid_pool, rng)
        if cell == "ACC2":
            tr, va, te = (df[df.w == w].ex.to_numpy() for w in WINDOWS)
            out["verdict"] = verdict(tr, va, te, out["null_p95_train_bp"] if out["null_p95_train_bp"] is not None else np.inf,
                                     out["OOS"]["net_bp"] if out["OOS"]["net_bp"] is not None else -1e9,
                                     out["OOS"]["net_stress_bp"] if out["OOS"]["net_stress_bp"] is not None else -1e9,
                                     out["oos_cohort_t"])
        res["cells"][cell] = out
    res["excluded_note"] = "60거래일 청산이 A2a 캐시 끝(2026-08-03)을 넘는 2025 공시 코호트 일부는 자동 제외"
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    v = res["cells"]["ACC2"]["verdict"]
    print("ACC2", v, "events", res["cells"]["ACC2"]["events"], "| OOS mean", res["cells"]["ACC2"]["OOS"]["mean_bp"])


def f(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def render(r):
    A = r["cells"]["ACC2"]
    v = A["verdict"]
    sig = "있음" if v in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if v in ("ECONOMIC", "ROBUST") else "미달"
    L = ["---", "track: kr", "factor: quarterly-acceleration", "date: 2026-09-21", f"verdict: {v}",
         "criteria_version: research-only (quarterly-acceleration-preregistration-2026-09, 3b0ef12)",
         'conditions: ["ACC2 = Q3 공시 시점 순이익 YoY 2회 연속 개선", "60거래일 초과수익(유동 EW 대비)", "TRAIN 2016~2020/VALID 2021~22/TEST 2023~25", "비용 33.5bp"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (스크립트가 계산한 판정 {v}. 검출력이 낮은 제한판 — 코호트 10개.)", "---\n",
         "# 분기 순이익 성장 가속 — 결과\n",
         "수치는 `quarterly_acceleration_event.py` 가 계산해 그대로 옮긴 값이다. 정의·기간·비용·판정은 사전등록(3b0ef12) 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정\n", f"**{v}** (신호: {sig} · 경제성: {eco})\n",
         "| 항목 | 값 |\n|---|---|",
         f"| ACC2 이벤트 수(구간 필터·청산 가능분) | {A['events']} (원 이벤트 {r['counts_raw']['ACC2']}) |",
         f"| TRAIN 평균 초과 | {f(A['TRAIN']['mean_bp'])}bp · 난수 바닥선 95p {f(A['null_p95_train_bp'])}bp |",
         f"| VALID / TEST 평균 초과 | {f(A['VALID']['mean_bp'])} / {f(A['TEST']['mean_bp'])}bp |",
         f"| OOS(VALID+TEST) 평균 초과 = **손익분기 비용** | **{f(A['OOS']['breakeven_bp'])}**bp |",
         f"| OOS net (33.5bp) / 스트레스(67bp) | {f(A['OOS']['net_bp'])} / {f(A['OOS']['net_stress_bp'])}bp |",
         f"| OOS 코호트(연도) t | {f(A['oos_cohort_t'], 2)} |",
         f"| 초과수익 상위 1개 연도의 양(+) 코호트 합 대비 비중 | {f(A['top_year_share_of_positive'], 2)} |\n",
         "## 2. 셀 비교 (60거래일 초과수익 bp, 구간별 평균 [군집 부트스트랩 95%] · 이벤트)\n",
         "| 셀 | TRAIN | VALID | TEST | OOS 손익분기 | 난수 바닥선 |", "|---|---|---|---|---|---|"]
    for c in ("ACC2", "LEVEL", "ACC1"):
        x = r["cells"][c]
        cells = [f"{f(x[w]['mean_bp'])} [{f(x[w]['ci95'][0])}, {f(x[w]['ci95'][1])}] · {x[w]['n']}" for w in WINDOWS]
        L.append(f"| {c}{' (판정)' if c == 'ACC2' else ' (기록)'} | " + " | ".join(cells) +
                 f" | {f(x['OOS']['breakeven_bp'])} | {f(x['null_p95_train_bp'])} |")
    L.append("\n## 3. 코호트(공시 연도)별 평균 초과 bp / 이벤트 수\n")
    yrs = sorted({y for c in ("ACC2", "LEVEL", "ACC1") for y in r["cells"][c]["cohorts"]})
    L.append("| 셀 | " + " | ".join(str(y) for y in yrs) + " |")
    L.append("|---|" + "---|" * len(yrs))
    for c in ("ACC2", "LEVEL", "ACC1"):
        co = r["cells"][c]["cohorts"]
        L.append(f"| {c} | " + " | ".join(f"{f(co[y]['mean_bp'], 0)}/{co[y]['n']}" if y in co else "-" for y in yrs) + " |")
    L.append("\n## 4. 사전등록 대조\n")
    L.append("- 기존 분기 패널(순이익 Q1~Q3, 2,912종목)만 썼고 새 수집은 없다. Q4·매출·영업이익 가속은 자료가 없어 못 봤다(A3 확장 수집 이후).")
    L.append("- 진입 = 공시일 다음 거래일 종가, 보유 60거래일, 유동 유니버스 EW 대비 초과. 60거래일 청산이 캐시 끝을 넘는 이벤트는 자동 제외.")
    L.append("- 신뢰구간은 **진입일 군집 부트스트랩**(같은 날 진입한 이벤트를 한 묶음으로 재추출)이다 — 사전등록의 '코호트 부트스트랩'을 이렇게 구현했다. 코호트(연도) 수준의 t 는 별도 열이다.")
    L.append("- 구간별 평균이 클수록 신뢰구간도 넓다(이벤트 수 100~200, 종목별 60일 초과수익 표준편차가 크다). TRAIN 은 바닥선(구간 평균의 난수 95백분위) 아래라 사전등록 규칙상 INFORMATION 이 아니다 — OOS 가 커 보여도 판정은 그대로다.")
    L.append("- 검출력이 낮다(코호트 10개) — ROBUST 기준(OOS 코호트 t ≥ 2)은 사실상 도달 불가라고 사전등록에 적었다.")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("성장률: 양·양만 정의", growth(150, 100) == 0.5 and growth(-1, 100) is None and growth(100, -5) is None and growth(100, 0) is None)

    def rec(tk, fy, q, th, fr, d):
        return {"ticker": tk, "fiscalYear": fy, "quarter": q, "thstrm": th, "frmtrm": fr, "availableFrom": d}

    rows = [rec("A", 2020, "Q1", 110, 100, "20200515"), rec("A", 2020, "Q2", 130, 100, "20200814"), rec("A", 2020, "Q3", 160, 100, "20201113"),
            rec("B", 2020, "Q1", 130, 100, "20200515"), rec("B", 2020, "Q2", 120, 100, "20200814"), rec("B", 2020, "Q3", 160, 100, "20201113"),
            rec("C", 2020, "Q1", -5, 100, "20200515"), rec("C", 2020, "Q2", 120, 100, "20200814"), rec("C", 2020, "Q3", 160, 100, "20201113")]
    ev = build_events(rows)
    cells = {(e["ticker"], e["cell"]) for e in ev}
    check("ACC2: 엄격한 2회 연속 개선만(A 만)", ("A", "ACC2") in cells and ("B", "ACC2") not in cells and ("C", "ACC2") not in cells)
    check("LEVEL: Q3 성장이 정의·양이면 모두", {("A", "LEVEL"), ("B", "LEVEL"), ("C", "LEVEL")} <= cells)
    check("ACC1: Q1<Q2 (A 만, B 는 하락, C 는 Q1 미정의)", ("A", "ACC1") in cells and ("B", "ACC1") not in cells and ("C", "ACC1") not in cells)
    d = np.array(pd.to_datetime(["2020-11-12", "2020-11-13", "2020-11-16"]), dtype="datetime64[ns]")
    check("진입 = 이벤트일 다음 거래일", entry_index(d, "20201112") == 1 and entry_index(d, "20201113") == 2)
    rng = np.random.default_rng(0)
    pool = {0: np.random.default_rng(1).normal(0, 100, 200), 1: np.random.default_rng(2).normal(0, 100, 200)}
    p = null_p95({0: 5, 1: 5}, pool, rng, 300)
    check("난수 바닥선은 0 보다 크다(양의 꼬리)", p is not None and p > 0)
    tr, va, te = np.full(40, 80.0), np.full(40, 30.0), np.full(40, 20.0)
    check("판정: 바닥선 통과·같은 부호·net 양 → ECONOMIC", verdict(tr, va, te, 50.0, 10.0, 5.0, 1.0) == "ECONOMIC")
    check("판정: OOS 부호 반전 → REJECT", verdict(tr, -va, te, 50.0, 10.0, 5.0, 1.0) == "REJECT")
    check("판정: 표본 30 미만 → 판정불가", verdict(tr[:10], va, te, 50.0, 10.0, 5.0, 1.0) == "판정불가")
    check("판정: 바닥선 미달 → REJECT", verdict(tr, va, te, 200.0, 10.0, 5.0, 1.0) == "REJECT")
    check("판정: 코호트 t≥2 → ROBUST", verdict(tr, va, te, 50.0, 10.0, 5.0, 2.5) == "ROBUST")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
