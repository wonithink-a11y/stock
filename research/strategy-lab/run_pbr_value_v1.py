#!/usr/bin/env python
"""pbr_value_v1을 engine.runner.run_smoke()로 실제 실행 - 파이프라인 복제 없음
(run_5dc_v1a_p_merged.py는 커스텀 A1A+A1B 병합 가격소스가 필요해 파이프라인을
복제했지만, pbr_value_v1은 표준 A1A_ONLY라 run_smoke()를 그대로 쓸 수 있다).
run_smoke()는 진단만 반환하므로(runner.py 자신의 docstring: "No performance/
return metrics... computed here") CAGR/MDD/Sharpe는 이 스크립트가 engine/
metrics로 계산한다.

  python run_pbr_value_v1.py
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
END = "2026-08-14"


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
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    t0 = time.time()
    result = run_smoke("pbr_value_v1", START, END, repo_root)
    elapsed = time.time() - t0

    diag = result["diag"]
    portfolio = result["portfolio"]
    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio) or {}

    report = {
        "runIdentification": {
            "strategyId": "pbr_value_v1", "runClass": diag["runClass"],
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
        "comparisonToPrecheck": {
            "note": "a5_valuation_factor_precheck_v2_absolute.py lowPBR_high_liquidity_absoluteThreshold "
                    "(top30 하드컷, 동일가중 평균수익률 근사 - 이 실행은 engine의 실제 포트폴리오 "
                    "회계(공유 현금·정수 주식수·같은날 현금 재사용 금지 등)를 반영해 다를 수 있다)",
            "precheckCagr": 0.0706,
        },
    }

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports", "2026-08-21-pbr-value-v1-smoke")
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
