#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pbr_value_v1(baseline) vs pbr_value_v1_sizing(미국10Y hiking 강도 연속
비중축소) - 월별 MTM 비교. pbr_ratefilter_vs_baseline_mtm.py와 동일 패턴,
strategy_id만 다르다.

  python pbr_sizing_vs_baseline_mtm.py
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
    print("=== pbr_value_v1(baseline) vs pbr_value_v1_sizing, monthly MTM, %s~%s ===" % (START, END))
    base = run_and_measure("pbr_value_v1")
    siz = run_and_measure("pbr_value_v1_sizing")

    cagr_gap = round(siz["resultTable"]["cagr"] - base["resultTable"]["cagr"], 4)
    sharpe_gap = None
    if base["resultTable"]["sharpe"] is not None and siz["resultTable"]["sharpe"] is not None:
        sharpe_gap = round(siz["resultTable"]["sharpe"] - base["resultTable"]["sharpe"], 4)

    print("\n[결과]")
    print("  baseline : CAGR=%.4f MDD=%.4f Sharpe=%s closed=%d"
          % (base["resultTable"]["cagr"], base["resultTable"]["mdd"],
             base["resultTable"]["sharpe"], base["closedPositionCount"]))
    print("  sizing   : CAGR=%.4f MDD=%.4f Sharpe=%s closed=%d"
          % (siz["resultTable"]["cagr"], siz["resultTable"]["mdd"],
             siz["resultTable"]["sharpe"], siz["closedPositionCount"]))
    print("  CAGR gap(sizing - baseline) = %.4f, Sharpe gap = %s" % (cagr_gap, sharpe_gap))

    result = {
        "period": "%s ~ %s" % (START, END), "method": "monthly mark-to-market equity curve",
        "pbr_value_v1_baseline": base, "pbr_value_v1_sizing": siz,
        "cagrGap_sizingMinusBaseline": cagr_gap, "sharpeGap_sizingMinusBaseline": sharpe_gap,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-23-pbr-sizing-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-sizing-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "pbr_value_v1_sizing(미국10Y hiking 강도 연속 비중축소, 레버리지 없음) 실전 backtest "
                              "- pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
