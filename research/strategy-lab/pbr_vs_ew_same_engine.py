#!/usr/bin/env python
"""PBR(top-30) vs 전체유니버스 EW(모든 적격종목)를 완전히 동일한 엔진 경로
(run_smoke -> _schedule_portfolio -> 같은 CostModel·같은 continuousHoldOnRenewal)
로 재계산해 비교한다. 기존 결과(panel-naive 계산 등) 재사용 없음 - 이번에 처음부터
다시 돈다. 기간 2016-01~2026-08.14, turnover20>=1억원, 30bps, 동일 티커
유니버스(pbr_value_v1이 draw하는 것과 같은 - valuation-panel.jsonl에 pbr이
있는 1,500종목). pbr_value_v1(정책 커밋됨, continuousHoldOnRenewal=true)과
ew_benchmark_liquid_v1(진단전용 신규 폴더, 같은 옵션)을 그대로 실행한다.
코드·정책 변경 없음 - 둘 다 이미 커밋된/신설된 정책 그대로 읽기만 한다.

  python pbr_vs_ew_same_engine.py
"""
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats  # noqa: E402


def _to_ordinal(d):
    y, m, dd = map(int, d.split("-"))
    return _date(y, m, dd).toordinal()


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

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def realized_metrics_and_curve(portfolio):
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return {}, []
    metrics = {
        "finalEquity": eq, "totalReturn": total_return(curve), "cagr": cagr(curve),
        "mdd": max_drawdown(curve), "sharpe": sharpe(curve), "sortino": sortino(curve),
        "calmar": calmar(curve),
    }
    return metrics, curve


def annual_returns(curve, initial_capital):
    by_year_last_eq = {}
    for d, eq in curve:
        y = int(d[:4])
        by_year_last_eq[y] = eq  # curve already sorted by date -> last write per year wins
    years = sorted(by_year_last_eq.keys())
    prev_eq = initial_capital
    out = {}
    for y in years:
        end_eq = by_year_last_eq[y]
        out[y] = round(end_eq / prev_eq - 1, 4)
        prev_eq = end_eq
    return out


def run_and_measure(strategy_id):
    t0 = time.time()
    result = run_smoke(strategy_id, START, END, REPO_ROOT)
    elapsed = time.time() - t0
    diag, portfolio = result["diag"], result["portfolio"]
    metrics, curve = realized_metrics_and_curve(portfolio)
    t_stats = trade_stats(trades_from_portfolio(portfolio))
    ann = annual_returns(curve, portfolio.config.initial_capital)
    print(f"  {strategy_id}: {diag['closedPositionCount']} closed positions "
          f"(merged {diag.get('continuousHoldsMergedCount', 0)}), {elapsed:.0f}s")
    return {
        "signalCount": diag["signalCount"],
        "closedPositionCount": diag["closedPositionCount"],
        "continuousHoldsMergedCount": diag.get("continuousHoldsMergedCount", 0),
        "resultTable": {
            "finalEquity": round(metrics.get("finalEquity")) if metrics.get("finalEquity") is not None else None,
            "totalReturn": round(metrics.get("totalReturn"), 4) if metrics.get("totalReturn") is not None else None,
            "cagr": round(metrics.get("cagr"), 4) if metrics.get("cagr") is not None else None,
            "mdd": round(metrics.get("mdd"), 4) if metrics.get("mdd") is not None else None,
            "sharpe": round(metrics.get("sharpe"), 4) if metrics.get("sharpe") is not None else None,
            "sortino": round(metrics.get("sortino"), 4) if metrics.get("sortino") is not None else None,
            "calmar": round(metrics.get("calmar"), 4) if metrics.get("calmar") is not None else None,
            "winRate": round(t_stats.get("winRate", 0), 4) if t_stats.get("winRate") is not None else None,
            "tradeCount": t_stats.get("tradeCount"),
        },
        "annualReturns": ann,
    }


def main():
    print(f"=== PBR vs EW, same engine, {START} ~ {END} ===")
    pbr = run_and_measure("pbr_value_v1")
    ew = run_and_measure("ew_benchmark_liquid_v1")

    excess_cagr = None
    if pbr["resultTable"]["cagr"] is not None and ew["resultTable"]["cagr"] is not None:
        excess_cagr = round(pbr["resultTable"]["cagr"] - ew["resultTable"]["cagr"], 4)

    result = {"period": f"{START} ~ {END}", "pbr_value_v1": pbr,
              "ew_benchmark_liquid_v1": ew, "pbrMinusEW_cagrGap": excess_cagr}
    print("\n", json.dumps(result, ensure_ascii=False, indent=2))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-22-pbr-vs-ew-same-engine")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-vs-ew-same-engine.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR(top-30) vs 전체유니버스 EW(적격종목 전부, maxPositions=1500 "
                       "트렁케이션 없음)를 완전히 동일한 엔진(run_smoke, 같은 cost 30bps, "
                       "같은 continuousHoldOnRenewal) 경로로 재계산. 기존 결과 재사용 없음.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
