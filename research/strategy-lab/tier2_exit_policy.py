#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tier 2 — 청산규칙을 **실제 엔진**(슬롯·현금·비용·MTM)에서 잰다.

Tier 1.5(simulate_exits.py)는 거래 단위 기대값만 낸다. 거기서 나온 결론
("손절은 기대값을 절반 팔아 꼬리를 30% 산다", findings/portfolio-exit-policy-
validation-2026-09.md)은 포트폴리오 최대낙폭을 못 쟀다 - 손절을 거는 진짜 이유가
바로 그 MDD 인데. 이 스크립트가 그 빈칸을 채운다.

  같은 진입 · 같은 리밸런싱 일정 · 같은 비용. **청산규칙만 바꾼다.**

전략은 새로 안 만든다. run_smoke(rule_module=...) 훅으로 기존 전략의
compute_features/generate_signals/holdSessions 를 그대로 쓰고 risk_spec_for 만
갈아 끼운다(엔진 파일 무변경). 회계는 mtm_baseline.py 와 같은
schedule_with_monthly_mtm - 실현손익 누적 방식은 쓰지 않는다.

  python tier2_exit_policy.py --selftest
  python tier2_exit_policy.py --calibrate            # 기존 baseline 재현 확인
  python tier2_exit_policy.py --strategies pbr_value_v1
"""
import argparse
import json
import os
import sys
import time
import types

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.indicators.atr import atr as atr_indicator          # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig          # noqa: E402
from engine.runner import load_strategy, run_smoke              # noqa: E402
from engine.signals.schema import RiskSpec                      # noqa: E402
from pbr_vs_ew_monthly_mtm import (                             # noqa: E402
    annual_returns_mtm, curve_metrics, schedule_with_monthly_mtm)

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-tier2-exit-policy")

ATR_PERIOD = 14          # engine/indicators/atr.py = Wilder. Tier 1.5 는 SMA-20 이었다(차이 명시)

# (라벨, 손절 ATR 배수 or None=무손절, 손익비 or None=목표없음)
VARIANTS = [
    ("A 무손절-무목표 (기존)", None, None),
    ("B 손절 2xATR + 목표 RR3", 2.0, 3.0),
    ("C 손절 3xATR + 목표 RR1.5", 3.0, 1.5),
    ("D 손절 2xATR + 목표없음", 2.0, None),
    ("E 손절 3xATR + 목표없음", 3.0, None),
]

NO_TARGET_RR = 99.0      # 도달 불가 = 목표 없음 (엔진에 '목표 없음' 타입이 없다)


class _AtrMissing:
    """ATR 결측 건수를 세는 카운터. 결측을 조용히 무손절로 흘려보내지 않는다(교훈57)."""

    def __init__(self):
        self.n = 0
        self.total = 0


def make_variant(base, stop_mult, rr, counter):
    """base 전략의 진입/보유는 그대로 두고 청산규칙만 교체한 rule 모듈."""

    def compute_features(bars):
        f = base.compute_features(bars)
        if "atr" not in f.columns:
            f["atr"] = atr_indicator(f["high"], f["low"], f["close"], period=ATR_PERIOD)
        return f

    def risk_spec_for(row):
        spec = base.risk_spec_for(row)              # 보유기간(holdSessions) 로직 그대로 재사용
        counter.total += 1
        if stop_mult is None:
            return spec
        try:
            atr_t = float(row["atr"])
        except (KeyError, TypeError, ValueError):
            atr_t = float("nan")
        if pd.isna(atr_t) or atr_t <= 0:
            counter.n += 1
            return spec                              # 지어내지 않는다 - 그 건만 무손절로 두고 센다
        return RiskSpec(stop_distance=stop_mult * atr_t,
                        reward_risk=(NO_TARGET_RR if rr is None else rr),
                        max_holding_sessions=spec.max_holding_sessions)

    return types.SimpleNamespace(
        PARAMS=base.PARAMS,
        compute_features=compute_features,
        generate_signals=base.generate_signals,
        risk_spec_for=risk_spec_for,
    )


def measure(strategy_id, label, stop_mult, rr, start, end):
    t0 = time.time()
    base = load_strategy(strategy_id, REPO_ROOT)
    counter = _AtrMissing()
    rule = make_variant(base, stop_mult, rr, counter)
    run = run_smoke(strategy_id, start, end, REPO_ROOT, rule_module=rule)
    p = run["params"]
    cfg = PortfolioConfig(
        initial_capital=p["portfolio"]["initialCapital"],
        max_positions=p["portfolio"]["maxPositions"],
        equal_weight=p["portfolio"]["equalWeight"],
        fractional_shares=p["portfolio"]["fractionalShares"],
        tie_break=p["portfolio"]["tieBreak"])
    portfolio, snaps = schedule_with_monthly_mtm(
        run["resolved"], cfg, run["bars_by_ticker"], run["calendar"], start, end)
    m = curve_metrics(snaps)
    kinds = {}
    for pos in portfolio.closed_positions:
        k = getattr(pos, "exit_reason", None) or getattr(pos, "exit_type", "?")
        kinds[str(k)] = kinds.get(str(k), 0) + 1
    return {
        "strategyId": strategy_id, "variant": label,
        "stopMultiple": stop_mult, "rewardRisk": rr,
        "period": start + " ~ " + end,
        "accountingMethod": "monthly mark-to-market",
        "atrPeriod": ATR_PERIOD, "atrSmoothing": "wilder",
        "atrMissingSignals": counter.n, "riskSpecCalls": counter.total,
        "resultTable": m,
        "annualReturns": annual_returns_mtm(snaps),
        "closedPositionCount": len(portfolio.closed_positions),
        "exitKinds": kinds,
        "elapsedSeconds": round(time.time() - t0, 1),
    }


def print_table(rows):
    head = "{:<30} {:<28} {:>8} {:>9} {:>8} {:>8} {:>7} {:>8}".format(
        "전략", "변형", "CAGR", "MDD", "Sharpe", "Calmar", "청산건", "ATR결측")
    print("\n" + head)
    print("-" * 112)
    for r in rows:
        m = r["resultTable"]
        print("{:<30} {:<28} {:>8.2%} {:>9.2%} {:>8.4f} {:>8.4f} {:>7} {:>8}".format(
            r["strategyId"], r["variant"], m["cagr"], m["mdd"],
            m.get("sharpe", float("nan")), m.get("calmar", float("nan")),
            r["closedPositionCount"], r["atrMissingSignals"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategies", default="pbr_value_v1,composite_ey_rv60_equal_weight")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--calibrate", action="store_true",
                    help="변형 A(무손절)만 돌려 기존 baseline 수치를 재현하는지 확인")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    selftest(quiet=True)

    variants = VARIANTS[:1] if a.calibrate else VARIANTS
    rows = []
    os.makedirs(OUT_DIR, exist_ok=True)
    out = a.out or os.path.join(OUT_DIR, "tier2-exit-policy.json")
    for sid in a.strategies.split(","):
        for label, sm, rr in variants:
            print("[{}] {} / {} ...".format(time.strftime("%H:%M:%S"), sid, label), flush=True)
            r = measure(sid, label, sm, rr, a.start, a.end)
            rows.append(r)
            m = r["resultTable"]
            print("    CAGR {:.2%}  MDD {:.2%}  Sharpe {:.4f}  청산 {}  ({}s)".format(
                m["cagr"], m["mdd"], m.get("sharpe", 0), r["closedPositionCount"],
                r["elapsedSeconds"]), flush=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "rows": rows}, f, ensure_ascii=False, indent=1, default=str)
    print_table(rows)
    print("\n저장: " + out)


def selftest(quiet=False):
    class Base:
        PARAMS = {"x": 1}

        @staticmethod
        def compute_features(bars):
            return bars.copy()

        @staticmethod
        def generate_signals(symbol, features):
            return []

        @staticmethod
        def risk_spec_for(row):
            return RiskSpec(stop_distance=float(row["close"]) * 100,
                            reward_risk=1.0, max_holding_sessions=21)

    c = _AtrMissing()
    v = make_variant(Base, 2.0, 3.0, c)
    row = {"close": 1000.0, "atr": 25.0}
    s = v.risk_spec_for(row)
    assert s.stop_distance == 50.0 and s.reward_risk == 3.0, s
    assert s.max_holding_sessions == 21, "보유기간은 base 것을 그대로 써야 한다"

    s2 = v.risk_spec_for({"close": 1000.0, "atr": float("nan")})   # ATR 결측
    assert s2.stop_distance == 100000.0, "결측이면 무손절로 두고 센다"
    assert c.n == 1 and c.total == 2, (c.n, c.total)

    v0 = make_variant(Base, None, None, _AtrMissing())             # 변형 A = 완전 무변경
    assert v0.risk_spec_for(row).stop_distance == 100000.0

    vd = make_variant(Base, 2.0, None, _AtrMissing())              # 목표없음
    assert vd.risk_spec_for(row).reward_risk == NO_TARGET_RR

    bars = pd.DataFrame({"high": [11.0] * 30, "low": [9.0] * 30, "close": [10.0] * 30})
    f = v.compute_features(bars)
    assert "atr" in f.columns and abs(f["atr"].iloc[-1] - 2.0) < 1e-9, f["atr"].iloc[-1]

    assert len(VARIANTS) == 5 and VARIANTS[0][1] is None
    if not quiet:
        print("selftest ok (9건)")


if __name__ == "__main__":
    sys.exit(main())
