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
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics, annual_returns_mtm  # noqa: E402

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
    """폐기된 회계 방식 - 참고·대조용으로만 남긴다(resultTable에 쓰지 않는다).

    청산일에만 손익을 적립하므로 연속보유 포지션의 미실현 낙폭이 곡선에 전혀
    안 나타난다. 이 전략은 평균 보유가 149일이라 왜곡이 크다 - 실측으로
    MDD를 -21.70%에서 -10.47%로, Sharpe를 0.4556에서 2.2486으로 부풀렸다
    (2026-08-22 발견, 2026-09-02 이 스크립트 수정). 곡선 시작점도
    initial_capital이 아니라 '첫 청산 직후 자산'이라 totalReturn까지 어긋난다.
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
    result = run_smoke("pbr_value_v1", START, END, repo_root)
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
            "strategyId": "pbr_value_v1", "runClass": diag["runClass"],
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
