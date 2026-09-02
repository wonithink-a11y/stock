#!/usr/bin/env python
"""sector_neutral_pbr_growth 를 engine.runner.run_smoke() 로 실제 실행 — Tier 2 검증.

run_pbr_value_v1.py 와 같은 구조다(파이프라인 복제 없음, run_smoke 그대로).
run_smoke() 는 진단만 반환하므로 CAGR/MDD/Sharpe 는 engine/metrics 로 계산한다.

이 실행이 답하는 질문: **Tier 1 에서 본 초과수익이 실제 포트폴리오 회계
(공유 현금·정수 주식수·슬롯 경쟁·같은날 현금 재사용 금지)를 통과하고도 남는가.**
이 프로젝트는 사전점검이 엔진에서 40~50% 로 줄어든 사례를 반복해 겪었다
(PBR +7.06%->+2.95%, LOWMOM60 +13.90%->+5.09%, DD252 는 전면 기각).

  python run_sector_neutral_pbr_growth.py [--strategy <id>]
"""
import argparse
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.metrics.metrics import (  # noqa: E402
    total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats)

START = "2016-01-01"
END = "2026-08-14"
PERIODS = [("TRAIN", "2016-01-01", "2022-06-30"),
           ("VALID", "2022-07-01", "2024-01-01"),
           ("TEST", "2024-01-02", "2026-08-14")]


def _ord(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def trades_from_portfolio(portfolio):
    out = []
    for p in portfolio.closed_positions:
        entry, exit_ = p["entry"], p["exit"]
        out.append({
            "pnl": p["pnl"],
            "holding_sessions": _ord(exit_.fill_date) - _ord(p["entry_date"]),
            "symbol": p["symbol"], "entry_date": p["entry_date"], "exit_date": exit_.fill_date,
            "exit_type": exit_.fill_type, "entry_price": entry.fill_price,
            "exit_price": exit_.fill_price, "shares": p["shares"],
        })
    return out


def realized_metrics(portfolio, lo=None, hi=None):
    """실현손익 누적 곡선 기준. lo/hi 를 주면 그 구간에서 청산된 거래만 본다."""
    ev = sorted((p["exit"].fill_date, p["pnl"]) for p in portfolio.closed_positions
                if (lo is None or p["exit"].fill_date >= lo)
                and (hi is None or p["exit"].fill_date <= hi))
    if not ev:
        return None
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in ev:
        eq += pnl
        curve.append((d, eq))
    return {"nTrades": len(ev), "finalEquity": eq, "totalReturn": total_return(curve),
            "cagr": cagr(curve), "mdd": max_drawdown(curve), "sharpe": sharpe(curve),
            "sortino": sortino(curve), "calmar": calmar(curve)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="sector_neutral_pbr_growth_v1")
    a = ap.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    t0 = time.time()
    result = run_smoke(a.strategy, START, END, repo_root)
    elapsed = time.time() - t0

    diag, portfolio = result["diag"], result["portfolio"]
    trades = trades_from_portfolio(portfolio)
    overall = realized_metrics(portfolio) or {}
    by_period = {name: realized_metrics(portfolio, lo, hi) for name, lo, hi in PERIODS}

    report = {
        "runIdentification": {
            "strategyId": a.strategy, "runClass": diag["runClass"],
            "universeMode": diag["universeMode"], "period": f"{START} ~ {END}",
            "elapsedSeconds": round(elapsed, 1),
        },
        "diag": diag,
        "resultTable": {**{k: overall.get(k) for k in
                           ("finalEquity", "totalReturn", "cagr", "mdd", "sharpe",
                            "sortino", "calmar")},
                        **trade_stats(trades)},
        "byPeriod": by_period,
        "exitTypeCounts": {t: sum(1 for x in trades if x["exit_type"] == t)
                           for t in {x["exit_type"] for x in trades}},
        "comparisonToTier1": {
            "note": "Tier 1(월별 패널 근사)의 EW 대비 초과수익. 엔진은 공유 현금·정수 "
                    "주식수·슬롯 경쟁을 반영하므로 낮아지는 것이 정상이다 - 이 프로젝트는 "
                    "40~50% 로 줄어든 사례를 반복해 겪었다.",
            "tier1MonthlyExcess": {"TRAIN": 0.00606, "VALID": 0.00668, "TEST": 0.00656},
        },
    }

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports",
                           f"{time.strftime('%Y-%m-%d')}-sector-neutral-smoke")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{a.strategy}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    r = report["resultTable"]
    print(f"\n=== {a.strategy} ===")
    print(f"  {elapsed:.0f}s · 신호 {diag['signalCount']:,} · 청산 {diag['closedPositionCount']:,}")
    print(f"  CAGR {r.get('cagr', 0) * 100:.2f}%  MDD {r.get('mdd', 0) * 100:.1f}%  "
          f"Sharpe {r.get('sharpe') or 0:.2f}  총수익 {r.get('totalReturn', 0) * 100:.1f}%")
    print(f"  거래 {r.get('tradeCount')}  승률 {(r.get('winRate') or 0) * 100:.1f}%")
    print(f"  청산유형 {report['exitTypeCounts']}")
    print(f"\n  {'구간':<7}{'거래':>7}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}")
    for name, _, _ in PERIODS:
        p = by_period.get(name)
        if not p:
            print(f"  {name:<7}  (거래 없음)")
            continue
        print(f"  {name:<7}{p['nTrades']:>7}{p['cagr'] * 100:>8.2f}%{p['mdd'] * 100:>8.1f}%"
              f"{(p['sharpe'] or 0):>8.2f}")
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
