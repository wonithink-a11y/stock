#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""임의 전략의 baseline 성과를 월별 시가평가(MTM)로 재계산한다.

실현손익 누적 회계(청산일에만 손익 적립)는 연속보유 중 미실현 낙폭이 곡선에
안 나타나 MDD·Sharpe를 크게 왜곡한다(2026-08-22 발견, 2026-09-02 PBR 확정 -
MDD -10.47%→-21.70%, Sharpe 2.2486→0.4556). `pbr_vs_ew_monthly_mtm.py`가
이미 그 문제를 푼 범용 함수를 갖고 있는데 스크립트마다 복붙된 옛 회계가
17개 남아 있어, 새로 짜지 않고 그 함수를 그대로 재사용하는 얇은 CLI로 만든다.

policy.json의 universeMode를 그대로 따르므로 5dc_v1a_p는 A1A_A1B_MERGED
(PRIMARY, 2026-08-24 승격)로 돈다 - 리포트에 universeMode를 같이 남긴다.

  python mtm_baseline.py 5dc_v1a_p
  python mtm_baseline.py 5dc_v1a_p trend_breakout_v1 --start 2016-01-01
  python mtm_baseline.py --selftest
"""
import argparse
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


def measure(strategy_id, start, end):
    t0 = time.time()
    base = run_smoke(strategy_id, start, end, REPO_ROOT)
    params = base["params"]
    cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(
        base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], start, end)
    diag = base["diag"]
    return {
        "strategyId": strategy_id, "period": f"{start} ~ {end}",
        "universeMode": diag["universeMode"], "runClass": diag["runClass"],
        "accountingMethod": "monthly mark-to-market (pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm)",
        "resultTable": curve_metrics(snapshots),
        "annualReturns": annual_returns_mtm(snapshots),
        "closedPositionCount": len(portfolio.closed_positions),
        "openPositionCountAtEnd": len(portfolio.open_positions),
        "monthlySnapshotCount": len(snapshots),
        "elapsedSeconds": round(time.time() - t0, 1),
    }


def selftest():
    # 미실현 낙폭이 곡선에 실제로 반영되는지: 100 -> 50 -> 100 은 MDD -50%다.
    m = curve_metrics([("2020-01-31", 100.0), ("2020-02-29", 50.0), ("2020-03-31", 100.0)])
    assert m["mdd"] == -0.5, m
    assert m["totalReturn"] == 0.0, m
    assert annual_returns_mtm([("2020-01-31", 100.0), ("2020-12-31", 110.0),
                               ("2021-12-31", 121.0)]) == {2020: 0.1, 2021: 0.1}
    print("selftest ok (3 assertions)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategies", nargs="*")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return
    if not args.strategies:
        ap.error("strategy id를 하나 이상 준다 (또는 --selftest)")

    results = {}
    for sid in args.strategies:
        results[sid] = measure(sid, args.start, args.end)
        print(json.dumps(results[sid], ensure_ascii=False, indent=2, default=str))

    out_path = args.out or os.path.join(
        REPO_ROOT, "research", "strategy-lab", "reports",
        "2026-09-03-mtm-baselines", "mtm-baselines.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    prior = {}
    if os.path.exists(out_path):
        prior = (json.load(open(out_path, encoding="utf-8")) or {}).get("results", {})
    prior.update(results)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "results": prior},
                  f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
