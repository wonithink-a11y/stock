#!/usr/bin/env python
"""pbr_value_v1을 engine.runner.run_smoke()로 구간별(설계 2016-2022 / OOS 2023 /
OOS 2024 밸류업regime / OOS 2025-2026 / 전체 2016-2026) 실제 실행 - 실제
포트폴리오 회계(공유 현금풀·정수 주식수·같은날 현금재사용 금지·max_positions=30·
거래비용 30bps)와 2026-08-21 겹침판정 수정(runner.py) 반영 결과. selection.json은
전체 기간에 대해 미리 계산돼 있고, generate_signals()가 그 신호 날짜가
run_smoke()에 로드된 bars.index 안에 있을 때만 내보내므로(rule.py) start/end만
바꿔 호출하면 그 구간 신호만 자연히 걸러진다 - selection.json·policy.json·
runner.py 전부 미변경, 순수 재실행.

  python run_pbr_value_v1_oos.py
"""
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats  # noqa: E402

PERIODS = {
    "design_2016_2022": ("2016-01-01", "2022-12-31"),
    "oos_2023": ("2023-01-01", "2023-12-31"),
    "oos_2024_valueup_regime": ("2024-01-01", "2024-12-31"),
    "oos_2025_2026": ("2025-01-01", "2026-08-14"),
    "full_2016_2026": ("2016-01-01", "2026-08-14"),
}


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


def run_period(repo_root, start, end):
    t0 = time.time()
    result = run_smoke("pbr_value_v1", start, end, repo_root)
    elapsed = time.time() - t0

    diag = result["diag"]
    portfolio = result["portfolio"]
    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio) or {}

    return {
        "period": f"{start} ~ {end}", "elapsedSeconds": round(elapsed, 1),
        "diag": {k: diag[k] for k in (
            "signalCount", "invalidSignalCount", "skippedSignalCount", "skippedReasons",
            "executableTradeCount", "portfolioEligibleTradeCount", "closedPositionCount",
            "maxSimultaneousPositionsObserved",
        )},
        "resultTable": {
            "finalEquity": realized.get("finalEquity"), "totalReturn": realized.get("totalReturn"),
            "cagr": realized.get("cagr"), "mdd": realized.get("mdd"), "sharpe": realized.get("sharpe"),
            "sortino": realized.get("sortino"), "calmar": realized.get("calmar"),
            **t_stats,
        },
    }


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    results = {}
    for name, (start, end) in PERIODS.items():
        print(f"\n=== {name} ({start} ~ {end}) ===")
        block = run_period(repo_root, start, end)
        results[name] = block
        print(json.dumps({
            "elapsedSeconds": block["elapsedSeconds"],
            "signalCount": block["diag"]["signalCount"],
            "closedPositionCount": block["diag"]["closedPositionCount"],
            "skippedReasons": block["diag"]["skippedReasons"],
            "resultTable": {k: block["resultTable"].get(k) for k in ("cagr", "mdd", "sharpe", "winRate", "tradeCount")},
        }, indent=2, default=str))

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports", "2026-08-21-pbr-value-v1-oos-engine")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "run.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "pbr_value_v1 실제 engine.runner.run_smoke() 구간별 재실행 - "
                       "겹침판정 수정(e526cf8) 반영 후. selection.json/policy.json 미변경, "
                       "start/end만 바꿔 재호출(순수 실제-엔진 OOS 재현).",
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
