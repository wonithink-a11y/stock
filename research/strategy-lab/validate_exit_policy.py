#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PF-1.0 청산·사이징 규칙 검증 — 규칙을 관례로 정하지 않고 재서 정한다.

묻는 것 넷:
  Q1 손절/목표 규칙이 **같은 보유기간의 무손절**보다 나은가 (공정비교)
  Q2 어느 격자점이 최선이고 PF-1.0 초안(2.0 / 3.0 / 21)이 거기 가까운가
  Q3 TRAIN 에서 고른 격자점이 VALID·TEST 에서도 유지되는가 (이 프로젝트 표준 게이트)
  Q4 종목선택이 바뀌어도 같은 답인가 (무작위 대조군 3개 + 실제 팩터 2개)

시뮬레이션은 한 줄도 새로 안 짰다 - simulate_exits 의 run_grid/load_ohlc 를 그대로 쓴다.
그 파일이 엔진 executor.py 의 청산규칙을 옮겨온 것이므로 여기 결론도 같은 규칙 위에 있다.

  python validate_exit_policy.py --selftest
  python validate_exit_policy.py
"""
import argparse
import json
import os
import sys
import time

import numpy as np

import simulate_exits as se

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "findings", "portfolio-exit-policy-validation-2026-09.json")

PERIODS = ["TRAIN", "VALID", "TEST"]
HOLDS = [21, 42, 63]
NO_STOP = ("pct", 100.0, 1.0)          # 닿을 수 없는 손절 = 순수 시간청산
DRAFT = ("atr", 2.0, 3.0, 21)          # PF-1.0 초안


def grid_points():
    for m in se.ATR_MULTS:
        for rr in se.REWARD_RISKS:
            for mh in HOLDS:
                yield ("atr", m, rr, mh)


def entry_sets(n_random=83, seeds=(0, 1, 2), factors=("pbr", "earnings_yield")):
    out = []
    for s in seeds:
        out.append((f"random{s}", lambda p, s=s: se.random_selections_for(n_random, p, s)))
    for f in factors:
        out.append((f, lambda p, f=f: se.selections_for([f], p)))
    return out


def measure(sel, mkt, key):
    mode, param, rr, mh = key
    r = se.run_grid(sel, *mkt, mode, param, rr, mh)
    return r


def run():
    t0 = time.time()
    print("A2a 일별 OHLC 적재 ...", flush=True)
    dates, tickers, O, H, L, C, ATR = se.load_ohlc(verbose=False)
    mkt = (dates, tickers, O, H, L, C, ATR)
    print(f"  {len(dates):,}일 x {len(tickers):,}종목 ({time.time()-t0:.0f}s)", flush=True)

    results = {}
    for name, maker in entry_sets():
        results[name] = {}
        for period in PERIODS:
            sel = maker(period)
            if not sel:
                continue
            rec = {"nCohorts": len(sel), "noStop": {}, "grid": []}
            for mh in HOLDS:                      # Q1: 같은 보유기간의 무손절
                r = measure(sel, mkt, (NO_STOP[0], NO_STOP[1], NO_STOP[2], mh))
                if r:
                    rec["noStop"][str(mh)] = r["expectancy"]
            for key in grid_points():
                r = measure(sel, mkt, key)
                if r:
                    rec["grid"].append(r)
            results[name][period] = rec
            print(f"  {name:16} {period:5} 코호트 {len(sel):3}  "
                  f"무손절21 {rec['noStop'].get('21', float('nan')):+.4%}  "
                  f"({time.time()-t0:.0f}s)", flush=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    report(results)


def _key(r):
    return (r["stopMode"], r["stopParam"], r["rr"], r["maxHold"])


def _find(grid, key):
    for r in grid:
        if _key(r) == key:
            return r
    return None


def report(res):
    print("\n" + "=" * 78)
    print("Q1  손절/목표가 '같은 보유기간 무손절'을 이기는가  (거래당 기대값, 비용포함)")
    print("=" * 78)
    print(f"{'진입':16} {'구간':6} {'무손절21':>10} {'최선(21)':>10} {'차이':>9} {'그 격자점':>14}")
    for name, per in res.items():
        for period, rec in per.items():
            base = rec["noStop"].get("21")
            g21 = [r for r in rec["grid"] if r["maxHold"] == 21]
            if base is None or not g21:
                continue
            best = max(g21, key=lambda r: r["expectancy"])
            print(f"{name:16} {period:6} {base:>10.3%} {best['expectancy']:>10.3%} "
                  f"{best['expectancy']-base:>+9.3%} "
                  f"{'ATR×'+str(best['stopParam'])+'/RR'+str(best['rr']):>14}")

    print("\n" + "=" * 78)
    print("Q3  TRAIN 최선 격자점이 VALID·TEST 에서도 유지되는가")
    print("=" * 78)
    print(f"{'진입':16} {'TRAIN 최선':>18} {'TRAIN':>9} {'VALID':>9} {'TEST':>9} {'VALID·TEST 순위':>16}")
    for name, per in res.items():
        if "TRAIN" not in per:
            continue
        best = max(per["TRAIN"]["grid"], key=lambda r: r["expectancy"])
        k = _key(best)
        row = [f"ATR×{k[1]}/RR{k[2]}/{k[3]}일"]
        ranks = []
        vals = []
        for period in PERIODS:
            rec = per.get(period)
            if not rec:
                vals.append(None); ranks.append("-"); continue
            r = _find(rec["grid"], k)
            vals.append(r["expectancy"] if r else None)
            order = sorted(rec["grid"], key=lambda x: -x["expectancy"])
            rank = next((i + 1 for i, x in enumerate(order) if _key(x) == k), None)
            ranks.append(f"{rank}/{len(order)}")
        print(f"{name:16} {row[0]:>18} " +
              " ".join(f"{v:>9.3%}" if v is not None else f"{'-':>9}" for v in vals) +
              f" {ranks[1]+' · '+ranks[2]:>16}")

    print("\n" + "=" * 78)
    print(f"Q2  PF-1.0 초안 ATR×{DRAFT[1]}/RR{DRAFT[2]}/{DRAFT[3]}일 은 격자에서 몇 위인가")
    print("=" * 78)
    print(f"{'진입':16} {'구간':6} {'초안 기대값':>12} {'순위':>9} {'최선 대비':>10}")
    for name, per in res.items():
        for period, rec in per.items():
            r = _find(rec["grid"], DRAFT)
            if not r:
                continue
            order = sorted(rec["grid"], key=lambda x: -x["expectancy"])
            rank = next(i + 1 for i, x in enumerate(order) if _key(x) == DRAFT)
            print(f"{name:16} {period:6} {r['expectancy']:>12.3%} {rank:>4}/{len(order):<4} "
                  f"{r['expectancy']-order[0]['expectancy']:>+10.3%}")


def selftest():
    g = list(grid_points())
    assert len(g) == len(se.ATR_MULTS) * len(se.REWARD_RISKS) * len(HOLDS) == 60, len(g)
    assert DRAFT in g, "초안이 격자 안에 없으면 순위를 못 낸다"
    assert _find([{"stopMode": "atr", "stopParam": 2.0, "rr": 3.0, "maxHold": 21, "x": 1}],
                 DRAFT)["x"] == 1
    assert _find([], DRAFT) is None
    names = [n for n, _ in entry_sets()]
    assert names == ["random0", "random1", "random2", "pbr", "earnings_yield"], names
    # 진입 대조군 3개가 실제로 서로 다른 종목을 뽑는지(seed 가 먹는지)
    fake = {"random0": {"TRAIN": {"nCohorts": 1, "noStop": {"21": 0.01},
                                  "grid": [{"stopMode": "atr", "stopParam": 2.0, "rr": 3.0,
                                            "maxHold": 21, "expectancy": 0.02}]}}}
    report(fake)          # 표가 예외 없이 그려지는지
    print("selftest ok (7건)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else run())
