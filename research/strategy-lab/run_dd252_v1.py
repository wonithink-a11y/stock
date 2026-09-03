#!/usr/bin/env python
"""dd252_v1을 engine.runner.run_smoke()로 실제 실행 - A1A_A1B_MERGED 유니버스라
run_smoke()가 universeMode="A1A_A1B_MERGED"를 지원하는지 확인 필요(engine/runner.py의
run_class 결정 로직 참조). run_smoke()는 진단만 반환하므로 CAGR/MDD/Sharpe는
engine/metrics로 계산한다.

  python run_dd252_v1.py
"""
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics, annual_returns_mtm  # noqa: E402
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
    """폐기된 회계 방식 - 참고·대조용으로만 남긴다(resultTable에 쓰지 않는다).

    청산일에만 손익을 적립하므로 연속보유 포지션의 미실현 낙폭이 곡선에 전혀
    안 나타난다. 곡선 시작점도 initial_capital이 아니라 '첫 청산 직후 자산'이라
    totalReturn까지 어긋난다(2026-08-22 발견, run_pbr_value_v1은 2026-09-02 수정).
    """
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
    result = run_smoke("dd252_v1", START, END, repo_root)
    elapsed = time.time() - t0

    diag = result["diag"]
    # run_smoke()가 이미 스케줄한 portfolio 대신 같은 로직으로 다시 스케줄하며
    # 월말 시가평가 스냅샷을 받는다(_schedule_portfolio() 무수정 복제본).
    params = result["params"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(
        result["resolved"], portfolio_cfg, result["bars_by_ticker"], result["calendar"], START, END)
    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    mtm = curve_metrics(snapshots)
    realized = realized_pnl_metrics(portfolio) or {}

    report = {
        "runIdentification": {
            "strategyId": "dd252_v1", "runClass": diag["runClass"],
            "universeMode": diag["universeMode"], "period": f"{START} ~ {END}",
            "elapsedSeconds": round(elapsed, 1),
        },
        "diag": diag,
        "accountingMethod": "monthly mark-to-market (pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm)",
        "resultTable": {**mtm, **t_stats},
        "annualReturns": annual_returns_mtm(snapshots),
        "monthlySnapshotCount": len(snapshots),
        "openPositionCountAtEnd": len(portfolio.open_positions),
        "deprecatedRealizedPnL": {
            "note": "폐기된 실현손익 누적 회계. 인용 금지 - 위 resultTable을 쓴다. "
                    "미실현 낙폭이 곡선에 안 나타나 MDD·Sharpe를 크게 왜곡한다.",
            **{k: realized.get(k) for k in ("finalEquity", "totalReturn", "cagr", "mdd", "sharpe", "sortino", "calmar")},
        },
        "comparisonToSurvivorshipStudy": {
            "note": "dd252_survivorship_study.py의 MERGED 패널 d120 IC +0.0684 / monthly spread +0.0385 (NWT 2.08). "
                    "이 실행은 engine의 실제 포트폴리오 회계(공유 현금·정수 주식수·같은날 현금 재사용 금지·"
                    "staggered cohort 근사 continuousHoldOnRenewal=false)를 반영해 다를 수 있다.",
            "survivorshipIC_d120": 0.06836,
            "survivorshipSpreadMonthly_d120": 0.03849,
        },
    }

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports", "2026-08-26-dd252-v1-smoke")
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