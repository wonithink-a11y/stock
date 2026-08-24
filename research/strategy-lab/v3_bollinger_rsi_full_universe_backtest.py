#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v3_bollinger_rsi 전체 유니버스 백테스트 - 30종목 스모크(findings/
v3-engine-smoke/smoke.md, Sharpe 1.20) 이후 처음 하는 전체 실행.

전제: `v3_5dc_signal_overlap_check.py`(2026-08-24) 결과로 audit.md가 요구한
"5DC와의 독립성 검토"가 해소됐다 - 완전 동일일 겹침 4건(사실상 0%), 근접
선후관계(20거래일 내)도 5DC 신호의 17.78%뿐이라 대부분(82%) 독립적인
신호였다. 이 백테스트는 그 판단을 전제로 진행하는 다음 단계.

방법: `pbr_vs_ew_monthly_mtm.py`의 `schedule_with_monthly_mtm()`(무변경
재사용, 오늘 밤 exit_symbols_queued 가드 수정 이후 버전)으로 월별 MTM
곡선을 계산 - 이 세션에서 TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60에 쓴 것과
동일한 측정 방식. strategies/v3_bollinger_rsi/(정책·룰) 전부 무변경, 새
selection.json도 없음(V3는 selection.json 없이 rule.py가 직접 조건을 평가).

  python v3_bollinger_rsi_full_universe_backtest.py
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


def main():
    t0 = time.time()
    print("=== v3_bollinger_rsi 전체 유니버스 백테스트, monthly MTM, %s~%s ===" % (START, END))
    base = run_smoke("v3_bollinger_rsi", START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    diag = base["diag"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    print("  %d closed, %d open at end, %d monthly snapshots (%.0fs)"
          % (len(portfolio.closed_positions), len(portfolio.open_positions), len(snapshots), time.time() - t0))

    calmar = round(metrics["cagr"] / abs(metrics["mdd"]), 4) if metrics["mdd"] != 0 else None
    print("\n[전체 유니버스] CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (metrics["cagr"], metrics["mdd"], metrics["sharpe"], calmar))
    print("연도별:", ann)
    print("\n비교(30종목 스모크, findings/v3-engine-smoke/smoke.md): "
          "CAGR +5.39%, MDD -23.97%, Sharpe 1.20 (실현손익 방식, 이번과 측정방식 다름 - 참고용)")

    result = {
        "period": "%s ~ %s" % (START, END), "method": "monthly mark-to-market equity curve (full universe)",
        "diag": {k: diag.get(k) for k in ("tickersScanned", "signalCount", "invalidSignalCount",
                                          "skippedSignalCount", "executableTradeCount", "exitTypeCounts",
                                          "maxSimultaneousPositionsObserved")},
        "resultTable": metrics, "calmar": calmar, "annualReturns": ann,
        "closedPositionCount": len(portfolio.closed_positions),
        "openPositionCountAtEnd": len(portfolio.open_positions),
        "monthlySnapshotCount": len(snapshots),
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-24-v3-bollinger-rsi-full-universe")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "v3-bollinger-rsi-full-universe.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "v3_bollinger_rsi 전체 유니버스 monthly MTM 백테스트 - "
                              "30종목 스모크(Sharpe 1.20) 이후 첫 전체 실행",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
