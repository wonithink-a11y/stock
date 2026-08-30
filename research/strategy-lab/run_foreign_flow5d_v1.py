#!/usr/bin/env python
"""foreign_flow5d_v1을 engine.runner.run_smoke()로 실제 실행 - lowmom60_v1과
동일 패턴(표준 A1A_ONLY, run_smoke() 그대로 사용, CAGR/MDD/Sharpe는 이
스크립트가 engine/metrics로 계산).

  python run_foreign_flow5d_v1.py
"""
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats  # noqa: E402

START = "2016-01-01"
END = "2026-08-03"


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def trades_from_portfolio(portfolio):
    trades = []
    for p in portfolio.closed_positions:
        entry, exit_ = p["entry"], p["exit"]
        trades.append({
            "pnl": p["pnl"],
            "holding_sessions": _to_ordinal(exit_.fill_date) - _to_ordinal(p["entry_date"]),
            "symbol": p["symbol"], "entry_date": p["entry_date"], "exit_date": exit_.fill_date,
            "exit_type": exit_.fill_type, "entry_price": entry.fill_price, "exit_price": exit_.fill_price,
            "shares": p["shares"],
        })
    return trades


def realized_pnl_metrics(portfolio):
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return None
    return {
        "initialCapital": portfolio.config.initial_capital, "finalEquity": eq,
        "totalReturn": total_return(curve), "cagr": cagr(curve), "mdd": max_drawdown(curve),
        "sharpe": sharpe(curve), "sortino": sortino(curve), "calmar": calmar(curve),
    }


def main():
    strategy_id = sys.argv[sys.argv.index("--strategy") + 1] if "--strategy" in sys.argv else "foreign_flow5d_v1"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    t0 = time.time()
    result = run_smoke(strategy_id, START, END, repo_root)
    elapsed = time.time() - t0

    diag = result["diag"]
    portfolio = result["portfolio"]
    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio) or {}

    report = {
        "runIdentification": {
            "strategyId": strategy_id, "runClass": diag["runClass"],
            "universeMode": diag["universeMode"], "period": f"{START} ~ {END}",
            "elapsedSeconds": round(elapsed, 1),
        },
        "diag": diag,
        "resultTable": {
            "finalEquity": realized.get("finalEquity"), "totalReturn": realized.get("totalReturn"),
            "cagr": realized.get("cagr"), "mdd": realized.get("mdd"), "sharpe": realized.get("sharpe"),
            "sortino": realized.get("sortino"), "calmar": realized.get("calmar"),
            **t_stats,
        },
        "comparisonToIndependentVerification": {
            "note": "findings/kr-foreign-flow-5d-independent-verification-2026-08.md의 날짜별 "
                    "cross-sectional Q5-Q1 스프레드(순수 통계, 비용/슬롯경쟁 없음)와 이 실행(실제 "
                    "포트폴리오 회계 - maxPositions=30 슬롯경쟁, 30bps 비용, 정수 주식수)은 다를 "
                    "것으로 예상된다 - 이 프로젝트가 반복 확인한 패턴(cross-sectional 통계가 "
                    "실제 엔진에서 사라지거나 축소됨).",
            "independentVerificationNwT": 15.530,
        },
    }

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports", f"2026-08-30-{strategy_id}-smoke")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "run.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "elapsedSeconds": round(elapsed, 1), "signalCount": diag["signalCount"],
        "closedPositionCount": diag["closedPositionCount"],
        "resultTable": {k: report["resultTable"].get(k) for k in ("cagr", "mdd", "sharpe", "winRate", "tradeCount")},
    }, indent=2, default=str))
    print("saved:", out_path)


if __name__ == "__main__":
    main()
