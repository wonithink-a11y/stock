#!/usr/bin/env python3
"""분기 기본 사건 B 그림자 관측 — 사전등록 findings/quarterly-growth-shadow-preregistration-2026-10.md.

반사실 계산 — 실주문 불변, 점수·매매 불연결. 동결일(2026-10-09) 이후 접수된 분기보고서의 사건 B 만 기록한다.

    python research/strategy-lab/run_quarterly_growth_shadow.py --collect 2026Q3   # DART ≈250콜, events.jsonl 에 추가(멱등)
    python research/strategy-lab/run_quarterly_growth_shadow.py --mature           # A2a 갱신 뒤: 60·20·120거래일 만기 결과 추가(멱등)
    python research/strategy-lab/run_quarterly_growth_shadow.py --report           # 상황판(판정 전 중간 판정 없음) → status.md
    python research/strategy-lab/run_quarterly_growth_shadow.py --selftest

DART_API_KEY 는 .env 또는 환경변수. 기록: reports/2026-10-quarterly-growth-shadow/{events,outcomes}.jsonl · status.md (추적됨, 커밋한다).
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
import collect_quarterly_multi as cqm
import quarterly_growth_sector_event as qgs
import quarterly_acceleration_event as q

OUT_DIR = HERE / "reports" / "2026-10-quarterly-growth-shadow"
EVENTS, OUTCOMES, STATUS = OUT_DIR / "events.jsonl", OUT_DIR / "outcomes.jsonl", OUT_DIR / "status.md"
A2A_DIR = ROOT / "data" / "backfill" / "price" / "a2a"
FREEZE = "20261009"
MIN_PEERS, HORIZONS = 8, (60, 20, 120)
LIQ_MIN, COST_BP, STRESS_BP = 2e9, 33.5, 67.0
MIN_EVENTS, MIN_COHORTS, SEED, N_NULL, N_BOOT = 300, 4, 20261012, 1000, 2000
KST = timezone(timedelta(hours=9))


def jl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")] if path.exists() else []


def append(path, rows):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def parse_quarter(s):
    """'2026Q3' → (2026, 3)."""
    return int(s[:4]), int(s[5])


def select_events(ev, qs, gmap, sector_of, size, frac, target_t, freeze=None):
    freeze = freeze or FREEZE
    """classify() 결과에서 목표 분기·동결일 이후 사건만 기록 행으로. 멱등 키 = id."""
    rows = []
    for e in ev:
        if e["t"] != target_t or e["date"] < freeze:
            continue
        v = qs[(e["corp"], e["t"])]
        sec = sector_of.get(e["ticker"])
        rows.append({"id": f"{e['ticker']}-{e['t']}", "ticker": e["ticker"], "corp": e["corp"], "year": v["year"], "q": v["q"], "date": e["date"],
                     "g": e["g"], "rev": v["rev"], "rev_prev": v["rev_prev"], "op": v["op"], "op_prev": v["op_prev"], "fs": v["fs"],
                     "cells": e["cells"], "sector": sec, "static_peers": (size.get(sec, 0) - 1) if sec else None,
                     "frac": frac(e["ticker"], e["t"]), "recorded": datetime.now(KST).strftime("%Y-%m-%d")})
    return rows


def collect(qstr):
    year, qn = parse_quarter(qstr)
    k = cqm.key()
    if not k:
        print("DART_API_KEY 없음")
        return 1
    corp2tk = cqm.corp_list()
    corps = sorted(corp2tk)
    batches = [corps[i:i + cqm.BATCH] for i in range(0, len(corps), cqm.BATCH)]
    recs, calls = [], 0
    for y in sorted({year - 1, year}):
        for code in cqm.CODES:
            for b in batches:
                rows, err = cqm.call(k, b, y, code)
                calls += 1
                if err:
                    print("중단:", y, code, err)
                    return 1
                recs.extend(cqm.parse(rows, corp2tk))
                time.sleep(0.3)
    by = {}
    for r in recs:
        by.setdefault((r["corp"], r["year"], r["reprt"]), {})[r["fsDiv"]] = r
    qs, ex = qgs.build_quarters(by)
    ev, gmap = qgs.classify(qs)
    items = json.load(open(qgs.A5, encoding="utf-8"))["items"]
    sector_of = {x["t"]: x["s"] for x in items if x.get("s")}
    size = pd.Series(sector_of).value_counts().to_dict()
    frac = qgs.coincidence(qs, gmap, sector_of)
    target_t = year * 4 + qn
    rows = select_events(ev, qs, gmap, sector_of, size, frac, target_t)
    have = {r["id"] for r in jl(EVENTS)}
    new = [r for r in rows if r["id"] not in have]
    append(EVENTS, new)
    n_q = sum(1 for (c, t) in qs if t == target_t)
    log = {"asof": datetime.now(KST).strftime("%Y-%m-%d"), "quarter": qstr, "calls": calls, "quarter_records": n_q, "events_B": len(rows),
           "new_events": len(new), "excluded": ex}
    append(OUT_DIR / "collect-log.jsonl", [log])
    print(json.dumps(log, ensure_ascii=False))
    if n_q == 0:
        print("경고: 목표 분기 레코드가 0건 — 아직 접수되지 않았거나 수집 실패")
    return 0


def load_prices():
    rows = []
    for y in (datetime.now(KST).year - 1, datetime.now(KST).year):
        p = A2A_DIR / f"{y}.jsonl.gz"
        if p.exists():
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rows.extend(json.loads(l) for l in f)
    a = pd.DataFrame(rows)
    a["date"] = pd.to_datetime(a["date"])
    a = a[(a.close > 0) & (a.volume >= 0)].sort_values(["ticker", "date"]).reset_index(drop=True)
    a["amt"] = a.close * a.volume
    a["liq"] = a.groupby("ticker").amt.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    return a


def mature():
    ev = jl(EVENTS)
    if not ev:
        print("기록된 사건 없음")
        return 0
    done = {(r["id"], r["h"]) for r in jl(OUTCOMES)}
    todo = [(e, h) for e in ev for h in HORIZONS if (e["id"], h) not in done]
    if not todo:
        print("만기 대상 없음")
        return 0
    a = load_prices()
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    items = json.load(open(qgs.A5, encoding="utf-8"))["items"]
    sector_of = {x["t"]: x["s"] for x in items if x.get("s")}
    sec_names = sorted(set(sector_of.values()))
    sidx = {s: i for i, s in enumerate(sec_names)}
    size = pd.Series(sector_of).value_counts()
    cols = list(close.columns)
    sector_idx = np.array([sidx.get(sector_of.get(c), -1) for c in cols])
    static_peers = np.array([size.get(sector_of.get(c), 0) - 1 if sector_of.get(c) else -1 for c in cols])
    colpos = {c: i for i, c in enumerate(cols)}
    qgs.LIQ_MIN = LIQ_MIN
    mats, rows = {}, []
    for h in sorted({h for _, h in todo}):
        mats[h] = qgs.sn_mats(close, vol, liq, sector_idx, len(sec_names), {MIN_PEERS: static_peers >= MIN_PEERS}, h)
    n = len(dates)
    for e, h in todo:
        i = q.entry_index(dates, e["date"])
        if i >= n - h:
            continue                       # 아직 만기 아님
        j = colpos.get(e["ticker"], -1)
        M = mats[h]
        base = {"id": e["id"], "h": h, "entry": str(pd.Timestamp(dates[i]).date()), "asof_price": str(pd.Timestamp(dates[-1]).date())}
        if j < 0 or not M["liquid"][i, j]:
            rows.append({**base, "eligible": False, "why": "유동성·가격 없음"})
            continue
        sn, mk = M["SN"][i, j], M["MK"][i, j]
        if not M["static_ok"][MIN_PEERS][j] or np.isnan(sn):
            rows.append({**base, "eligible": False, "why": "업종 동종 부족", "mk_bp": None if np.isnan(mk) else float(mk * 1e4)})
            continue
        rows.append({**base, "eligible": True, "sn_bp": float(sn * 1e4), "mk_bp": float(mk * 1e4)})
    append(OUTCOMES, rows)
    print(f"만기 결과 추가 {len(rows)}건 (대기 {len(todo) - len(rows)}) · 가격 끝 {pd.Timestamp(dates[-1]).date()}")
    return 0


def tercile(frac_by_quarter):
    return qgs.tercile_labels(frac_by_quarter)


def status_table(events, outcomes, rng):
    """만기 60일 결과로 상황판 값을 만든다. 판정 규칙은 사전등록 §3 — 여기서는 '충족 여부와 숫자'만 낸다."""
    ev = {e["id"]: e for e in events}
    out = [o for o in outcomes if o["h"] == 60 and o.get("eligible")]
    df = pd.DataFrame([{"id": o["id"], "sn": o["sn_bp"], "mk": o["mk_bp"], "i": o["entry"], "t": ev[o["id"]]["year"] * 4 + ev[o["id"]]["q"],
                        "cells": ev[o["id"]]["cells"], "frac": ev[o["id"]]["frac"]} for o in out if o["id"] in ev])
    res = {"events_recorded": len(events), "matured60": int(len(out)), "cohorts": int(df.t.nunique()) if len(df) else 0}
    res["ready"] = res["matured60"] >= MIN_EVENTS and res["cohorts"] >= MIN_COHORTS
    if not len(df):
        return res, df
    res["mean_sn"] = float(df.sn.mean())
    res["median_sn"] = float(df.sn.median())
    res["hit"] = float((df.sn > 0).mean())
    res["mean_mk"] = float(df.mk.mean())
    ci = q.boot_ci(df.sn.to_numpy(), pd.factorize(df.i)[0], rng, N_BOOT) if len(df) >= 3 else (None, None)
    res["ci95"] = list(ci)
    res["by_quarter"] = {int(t): {"n": int(len(g)), "mean_sn": float(g.sn.mean())} for t, g in df.groupby("t")}
    res["pos_cohort_share"] = float(np.mean([v["mean_sn"] > 0 for v in res["by_quarter"].values()]))
    return res, df


def report():
    events, outcomes = jl(EVENTS), jl(OUTCOMES)
    rng = np.random.default_rng(SEED)
    res, df = status_table(events, outcomes, rng)
    L = [f"# 분기 기본 사건 B 그림자 — 상황판 ({datetime.now(KST).strftime('%Y-%m-%d')} 기준)\n",
         "사전등록 `findings/quarterly-growth-shadow-preregistration-2026-10.md`. **판정 전 중간 판정을 내리지 않는다** — 아래는 진행 상황이다.\n",
         f"- 기록된 사건 {res['events_recorded']}건 · 60거래일 만기(업종 중립 정의 가능) **{res['matured60']}건** · 공시 분기 코호트 **{res['cohorts']}개**",
         f"- 판정 시점 조건(만기 ≥ {MIN_EVENTS}건 ∧ 코호트 ≥ {MIN_COHORTS}): **{'충족 — 사전등록 §3 판정 실행 가능' if res['ready'] else '미충족 — 관측 계속'}**"]
    if "mean_sn" in res:
        c = res["ci95"]
        L += ["", "## 기록(판정 아님)", "",
              f"- 업종 중립 평균 {res['mean_sn']:.0f}bp [{c[0]:.0f}, {c[1]:.0f}] · 중앙값 {res['median_sn']:.0f}bp · 승률 {res['hit'] * 100:.0f}% · 시장 초과 평균 {res['mean_mk']:.0f}bp" if c[0] is not None else
              f"- 업종 중립 평균 {res['mean_sn']:.0f}bp · 중앙값 {res['median_sn']:.0f}bp · 승률 {res['hit'] * 100:.0f}%",
              "- in-sample(참고): TRAIN +176 · VALID +180 · TEST +458bp, 중앙값 −170~−225bp",
              "", "| 분기 코호트 | 만기 사건 | 업종 중립 평균 bp |", "|---|---|---|"]
        for t, v in sorted(res["by_quarter"].items()):
            L.append(f"| {t // 4}Q{t % 4 or 4}{'' if t % 4 else ''} | {v['n']} | {v['mean_sn']:.0f} |")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("분기 문자열 파싱", parse_quarter("2026Q3") == (2026, 3))

    def rec(corp, yr, rp, dt, rev, op, date, tk, fs="CFS", add_r=None, add_o=None):
        return {"ticker": tk, "corp": corp, "year": yr, "reprt": rp, "fsDiv": fs, "dt": dt, "availableFrom": date,
                "revenue": {"cur": rev[0], "prev": rev[1], "cur_add": add_r[0] if add_r else None, "prev_add": add_r[1] if add_r else None},
                "op_income": {"cur": op[0], "prev": op[1], "cur_add": add_o[0] if add_o else None, "prev_add": add_o[1] if add_o else None}}
    by = {}
    for r in [rec("c", 2026, "11014", "2026.01.01 ~ 2026.09.30", (150, 100), (15, 7), "20261112", "AAA"),     # 동결일 이후 → 기록
              rec("d", 2026, "11014", "2026.01.01 ~ 2026.09.30", (150, 100), (15, 7), "20261005", "BBB"),     # 동결일 이전 → 제외
              rec("e", 2026, "11014", "2026.01.01 ~ 2026.09.30", (110, 100), (15, 7), "20261112", "CCC")]:    # 매출 +10% → B 아님
        by.setdefault((r["corp"], r["year"], r["reprt"]), {})[r["fsDiv"]] = r
    qs, _ = qgs.build_quarters(by)
    ev, gmap = qgs.classify(qs)
    sector_of = {"AAA": "S", "BBB": "S", "CCC": "S"}
    rows = select_events(ev, qs, gmap, sector_of, {"S": 10}, qgs.coincidence(qs, gmap, sector_of), 2026 * 4 + 3)
    check("동결일 이후·B 만 기록", [r["ticker"] for r in rows] == ["AAA"] and rows[0]["id"] == f"AAA-{2026 * 4 + 3}" and rows[0]["static_peers"] == 9)
    # 상황판: 만기 부족이면 ready False
    ev_rows = [{"id": f"X{i}-8100", "year": 2026, "q": 3, "cells": ["B"], "frac": None} for i in range(5)]
    out_rows = [{"id": f"X{i}-8100", "h": 60, "eligible": True, "sn_bp": 100.0 + i, "mk_bp": 150.0, "entry": "2026-11-17"} for i in range(5)]
    res, _ = status_table(ev_rows, out_rows, np.random.default_rng(0))
    check("상황판: 5건·코호트 1 → 미충족", res["matured60"] == 5 and res["cohorts"] == 1 and not res["ready"] and abs(res["mean_sn"] - 102.0) < 1e-9)
    res2, _ = status_table(ev_rows, [], np.random.default_rng(0))
    check("상황판: 만기 0건도 안전", res2["matured60"] == 0 and not res2["ready"])
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", metavar="YYYYQn")
    ap.add_argument("--mature", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sandbox", metavar="DIR", help="검증용: 이 폴더에 쓰고 동결일을 2025-01-01 로 낮춘다(실제 기록 폴더는 건드리지 않는다)")
    a = ap.parse_args()
    if a.sandbox:
        OUT_DIR = Path(a.sandbox)
        EVENTS, OUTCOMES, STATUS = OUT_DIR / "events.jsonl", OUT_DIR / "outcomes.jsonl", OUT_DIR / "status.md"
        FREEZE = "20250101"
    if a.selftest:
        sys.exit(selftest())
    if a.collect:
        sys.exit(collect(a.collect))
    if a.mature:
        sys.exit(mature())
    if a.report:
        sys.exit(report())
    ap.print_help()
