#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""factor-earnings-yield-{single-backtest,verification,portfolio-validation,
capacity-test}.md(2026-08-30) 4건을 정밀 월별 시가평가(MTM)로 재확인.

배경: 이 4건은 전부 run_factor_backtest.py/run_capacity_test.py의
compute_metrics_fast() - 포지션 exit_date 기준 실현손익 귀속 방식을
쓴다. factor-earnings-yield-2021-concentration/-macro-rate-regime
(둘 다 2026-08-30)가 이미 이 방식이 earnings_yield 단독 vs EW 비교를
왜곡함을 확인했다(exit_date 총초과수익이 MTM의 약 1.78배). 이 스크립트는
같은 정밀 MTM 방법론(pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용)을
나머지 4개 전략(rv60·rev1m·composite 2종)과 capacity 4변형(mp=20/30/50/100)
에 적용한다.

★ policy.json 오염 발견·복구: run_capacity_test.py가 이전 실행에서
mp=50 단계 도중 중단돼 strategies/factor_earnings_yield_v1/policy.json이
원래 기본값(mp=30)으로 복원되지 못한 채 mp=50으로 남아있었다(leftover
policy.json.bak과 policy_30.json 대조로 mp=30이 진짜 원본임을 확인 후
복구). capacity 변형은 이 스크립트에서 policy.json을 건드리지 않고
PortfolioConfig.max_positions만 in-memory로 바꿔 재사용한다 - 원본
run_capacity_test.py처럼 파일을 바꿔치기하지 않는다(같은 사고 재발 방지).

  python factor_earnings_yield_mtm_reverification.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics, annual_returns_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def mtm_for_strategy(strategy_id, max_positions_override=None):
    """run_smoke 1회 + MTM 스케줄링. max_positions_override가 있으면
    policy.json은 안 건드리고 PortfolioConfig만 바꿔 재사용(같은 resolved
    신호를 여러 max_positions로 재활용할 때 씀)."""
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    mp = max_positions_override if max_positions_override is not None else params["portfolio"]["maxPositions"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=mp,
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    return snapshots, resolved, params, bars_by_ticker, calendar


def main():
    t0 = time.time()
    results = {}

    print("=== EW benchmark MTM ===")
    ew_snap, *_ = mtm_for_strategy("ew_benchmark_liquid_v1")
    ew_metrics = curve_metrics(ew_snap)
    print(f"  {ew_metrics}  ({time.time()-t0:.0f}s)")
    results["ew_benchmark_liquid_v1"] = {"metrics": ew_metrics}

    print("\n=== earnings_yield capacity 4변형 (mp=20/30/50/100, resolved 1회 재사용) ===")
    ey_snap30, ey_resolved, ey_params, ey_bars, ey_cal = mtm_for_strategy("factor_earnings_yield_v1")
    print(f"  mp=30(policy.json 기본값) 로드 완료 ({time.time()-t0:.0f}s)")
    capacity = {}
    for mp in (20, 30, 50, 100):
        if mp == 30:
            snap = ey_snap30
        else:
            portfolio_cfg = PortfolioConfig(
                initial_capital=ey_params["portfolio"]["initialCapital"], max_positions=mp,
                equal_weight=ey_params["portfolio"]["equalWeight"],
                fractional_shares=ey_params["portfolio"]["fractionalShares"],
                tie_break=ey_params["portfolio"]["tieBreak"])
            _, snap = schedule_with_monthly_mtm(ey_resolved, portfolio_cfg, ey_bars, ey_cal, START, END)
        m = curve_metrics(snap)
        capacity[mp] = m
        print(f"  mp={mp:>3}  CAGR={m['cagr']:.2%}  Sharpe={m['sharpe']}  MDD={m['mdd']:.2%}  ({time.time()-t0:.0f}s)")
    results["factor_earnings_yield_v1_capacity"] = capacity
    results["factor_earnings_yield_v1"] = {"metrics": capacity[30], "annualReturnsMtm": annual_returns_mtm(ey_snap30)}

    print("\n=== 나머지 단일/복합 팩터 MTM (rv60·rev1m·composite x2) ===")
    for sid in ("factor_rv60_v1", "factor_rev1m_v1",
                "composite_ey_rv60_equal_weight", "composite_ey_rv60_rank_composite"):
        snap, *_ = mtm_for_strategy(sid)
        m = curve_metrics(snap)
        results[sid] = {"metrics": m, "annualReturnsMtm": annual_returns_mtm(snap)}
        print(f"  {sid}: {m}  ({time.time()-t0:.0f}s)")

    print("\n=== exit_date 귀속(기존 findings) vs 정밀 MTM 비교 ===")
    exit_date_cagr = {  # factor-single-backtest-kr-2026-08.md / capacity-test 원 수치
        "factor_earnings_yield_v1": 0.0468, "factor_rv60_v1": 0.0233, "factor_rev1m_v1": -0.0088,
        "composite_ey_rv60_equal_weight": -0.0767, "composite_ey_rv60_rank_composite": 0.0433,
    }
    for sid, old_cagr in exit_date_cagr.items():
        new_cagr = results[sid]["metrics"]["cagr"]
        print(f"  {sid}: exit_date CAGR={old_cagr:+.2%} -> MTM CAGR={new_cagr:+.2%}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-30-factor-earnings-yield-mtm-reverification")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "factor-earnings-yield-mtm-reverification.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "factor-earnings-yield-{single-backtest,verification,portfolio-validation,"
                       "capacity-test}.md 4건 정밀 MTM 재확인 - exit_date 귀속 왜곡 배제",
            "period": [START, END],
            "results": results,
            "exitDateCagrForComparison": exit_date_cagr,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
