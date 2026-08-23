#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pbr_value_v1(baseline) vs pbr_value_v1_ratefilter(미국10Y hiking 런필터)
- 월별 MTM으로 실제 경제적 가치가 남는지 확인.

pbr_vs_ew_monthly_mtm.py의 검증된 함수(run_and_measure 등가 로직)를 **무변경
재사용**해 두 전략을 동일 조건(같은 엔진·같은 스케줄링·같은 비용)으로 돌린다.
차이는 selection.json 하나뿐(build_pbr_ratefilter_selection.py, 런단위
hiking 필터) - 신호계산·체결·비용·portfolio 설정 전부 동일.

  python pbr_ratefilter_vs_baseline_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402
    annual_returns_mtm, curve_metrics, schedule_with_monthly_mtm,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def run_and_measure(strategy_id):
    t0 = time.time()
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    print("  %s: %d closed, %d open at end, %d monthly snapshots (%.0fs)"
          % (strategy_id, len(portfolio.closed_positions), len(portfolio.open_positions),
             len(snapshots), time.time() - t0))
    return {"resultTable": metrics, "annualReturns": ann,
            "closedPositionCount": len(portfolio.closed_positions),
            "openPositionCountAtEnd": len(portfolio.open_positions),
            "monthlySnapshotCount": len(snapshots)}


def main():
    print("=== pbr_value_v1(baseline) vs pbr_value_v1_ratefilter, monthly MTM, %s~%s ===" % (START, END))
    base = run_and_measure("pbr_value_v1")
    filt = run_and_measure("pbr_value_v1_ratefilter")

    cagr_gap = round(filt["resultTable"]["cagr"] - base["resultTable"]["cagr"], 4)
    sharpe_gap = None
    if base["resultTable"]["sharpe"] is not None and filt["resultTable"]["sharpe"] is not None:
        sharpe_gap = round(filt["resultTable"]["sharpe"] - base["resultTable"]["sharpe"], 4)

    print("\n[결과]")
    print("  baseline   : CAGR=%.4f MDD=%.4f Sharpe=%s closed=%d"
          % (base["resultTable"]["cagr"], base["resultTable"]["mdd"],
             base["resultTable"]["sharpe"], base["closedPositionCount"]))
    print("  ratefilter : CAGR=%.4f MDD=%.4f Sharpe=%s closed=%d"
          % (filt["resultTable"]["cagr"], filt["resultTable"]["mdd"],
             filt["resultTable"]["sharpe"], filt["closedPositionCount"]))
    print("  CAGR gap(ratefilter - baseline) = %.4f, Sharpe gap = %s" % (cagr_gap, sharpe_gap))

    result = {
        "period": "%s ~ %s" % (START, END), "method": "monthly mark-to-market equity curve",
        "pbr_value_v1_baseline": base, "pbr_value_v1_ratefilter": filt,
        "cagrGap_filterMinusBaseline": cagr_gap, "sharpeGap_filterMinusBaseline": sharpe_gap,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-23-pbr-ratefilter-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-ratefilter-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "pbr_value_v1_ratefilter(미국10Y hiking 런필터) 실전 backtest "
                              "- pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
