#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tier2_exit_policy.py 산출 JSON 들을 한 표로 모은다.

curve_metrics 는 calmar 를 안 내므로 여기서 cagr/|mdd| 로 계산한다.
비교는 항상 **같은 전략의 변형 A(무손절) 대비 차이**로 낸다 - 전략 간 절대값
비교는 이 실험의 질문이 아니다(청산규칙만 바꿨다).

  python report_tier2.py a.json b.json ...
"""
import argparse
import json
import sys


def calmar(m):
    mdd = abs(m.get("mdd") or 0.0)
    return (m["cagr"] / mdd) if mdd > 0 else float("nan")


def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            rows += json.load(f)["rows"]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.paths:
        ap.error("결과 JSON 경로를 하나 이상 준다 (또는 --selftest)")

    rows = load(a.paths)
    by_strategy = {}
    for r in rows:
        by_strategy.setdefault(r["strategyId"], []).append(r)

    for sid, rs in by_strategy.items():
        base = next((r for r in rs if r["stopMultiple"] is None), None)
        bm = base["resultTable"] if base else None
        print("\n" + "=" * 104)
        print(sid + "   (" + rs[0]["period"] + ", 월별 시가평가)")
        print("=" * 104)
        print("{:<28} {:>8} {:>9} {:>8} {:>8} {:>7} {:>6} {:>6} {:>6}".format(
            "변형", "CAGR", "MDD", "Sharpe", "Calmar", "청산건", "STOP", "TGT", "TIME"))
        print("-" * 104)
        for r in rs:
            m = r["resultTable"]
            k = r.get("exitKinds", {})
            n = max(r["closedPositionCount"], 1)
            print("{:<28} {:>8.2%} {:>9.2%} {:>8.4f} {:>8.4f} {:>7} {:>5.0%} {:>5.0%} {:>5.0%}".format(
                r["variant"], m["cagr"], m["mdd"], m.get("sharpe") or float("nan"),
                calmar(m), r["closedPositionCount"],
                k.get("STOP", 0) / n, k.get("TARGET", 0) / n, k.get("TIME_EXIT", 0) / n))
        if bm:
            print("\n  변형 A(무손절) 대비 차이")
            print("  {:<26} {:>10} {:>11} {:>10} {:>10}".format(
                "", "ΔCAGR", "ΔMDD", "ΔSharpe", "ΔCalmar"))
            for r in rs:
                if r is base:
                    continue
                m = r["resultTable"]
                print("  {:<26} {:>+10.2%} {:>+11.2%} {:>+10.4f} {:>+10.4f}".format(
                    r["variant"], m["cagr"] - bm["cagr"], m["mdd"] - bm["mdd"],
                    (m.get("sharpe") or 0) - (bm.get("sharpe") or 0),
                    calmar(m) - calmar(bm)))
        miss = sum(r["atrMissingSignals"] for r in rs)
        print("\n  ATR 결측으로 손절을 못 건 신호: {}건 (전체 risk_spec 호출 {}건)".format(
            miss, sum(r["riskSpecCalls"] for r in rs)))


def selftest():
    assert abs(calmar({"cagr": 0.10, "mdd": -0.20}) - 0.5) < 1e-9
    import math
    assert math.isnan(calmar({"cagr": 0.1, "mdd": 0.0}))
    assert math.isnan(calmar({"cagr": 0.1, "mdd": None}))
    print("selftest ok (3건)")


if __name__ == "__main__":
    sys.exit(main())
