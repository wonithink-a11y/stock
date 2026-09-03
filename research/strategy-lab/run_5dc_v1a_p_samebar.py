#!/usr/bin/env python
"""Independent re-run of 5DC-v1A-P SMOKE on the CURRENT engine (same-bar fix
applied, commit c140c26+) under the EXACT baseline conditions, then compute
metrics using the SAME method as the baseline (realized-pnl-at-exit-event
stepwise curve; no intra-holding mark-to-market), plus a same-bar trade census.

This is read-only w.r.t. production: it only reads data/backfill (via the
strategy-lab engine's read-only A2a provider + local cache), writes nothing to
git, and saves its report under reports/2026-08-22-convention-standardized-rerun/
(since 2026-08-22 the frozen 2026-08-16 artifacts are never overwritten).
"""

# --------------------------------------------------------------------------
# 이 스크립트는 폐기된 실현손익 누적 회계(`eq += pnl`)를 **의도적으로** 유지한다 —
# 냉동 baseline과 '같은 방법으로' A/B를 재는 것이 목적이라 회계를 바꾸면 비교가
# 깨진다. **비교의 방향·차분은 유효하나 절대 MDD·Sharpe는 무효다**(2026-08-22
# 발견, 실측 왜곡 배율은 보유기간이 정한다: PBR 4.9x · dd252 2.2x · LOWMOM60 2.1x
# · foreign_flow5d 1.0x). 절대값이 필요하면 mtm_baseline.py로 다시 잰다.
# --------------------------------------------------------------------------
import sys
import os
import json
import time
from collections import Counter
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.metrics.metrics import (  # noqa: E402
    total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats,
)


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def realized_pnl_metrics(portfolio, calendar, start, end):
    """Anchored realized-pnl-at-exit-event stepwise curve (convention standard
    fixed 2026-08-22): the curve starts at (evaluation start date, initial
    capital) so totalReturn == finalEquity/initialCapital - 1 and cagr spans
    the full evaluation window. Exits still step the same cumulative closed
    pnl - no intra-holding mark-to-market, no change to trades or accounting.
    MDD is invariant to this anchor; Sharpe/Sortino shift because one return
    segment is added."""
    events = sorted(
        (p["exit_date"], p["pnl"]) for p in portfolio.closed_positions
    )
    curve = []
    eq = portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return None
    curve = [(start, portfolio.config.initial_capital)] + curve
    return {
        "initialCapital": portfolio.config.initial_capital,
        "finalEquity": eq,
        "totalReturn": total_return(curve),
        "cagr": cagr(curve),
        "mdd": max_drawdown(curve),
        "sharpe": sharpe(curve),
        "sortino": sortino(curve),
        "calmar": calmar(curve),
    }


def main():
    start = time.time()
    start_date, end_date = "2014-05-13", "2026-08-03"

    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    result = run_smoke(
        strategy_id="5dc_v1a_p",
        start=start_date,
        end=end_date,
        repo_root=repo_root,
        trace_limit=0,
    )
    elapsed = time.time() - start

    portfolio = result["portfolio"]
    diag = result["diag"]
    params = result["params"]
    calendar = result["calendar"]

    trades = []
    for p in portfolio.closed_positions:
        entry = p["entry"]
        exit_ = p["exit"]
        holding = _to_ordinal(exit_.fill_date) - _to_ordinal(p["entry_date"])
        trades.append({
            "pnl": p["pnl"],
            "holding_sessions": holding,
            "symbol": p["symbol"],
            "entry_date": p["entry_date"],
            "exit_date": exit_.fill_date,
            "exit_type": exit_.fill_type,
            "entry_price": entry.fill_price,
            "exit_price": exit_.fill_price,
            "shares": p["shares"],
        })

    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio, calendar, start_date, end_date)

    same_bar = [t for t in trades if t["entry_date"] == t["exit_date"]]
    same_bar_by_type = Counter(t["exit_type"] for t in same_bar)

    result_table = {
        "warning": "SMOKE/A1A_ONLY diagnostic numbers - NOT a validated performance result (survivorship bias present)",
        "equityCurveMethod": "anchored realized-pnl-at-exit-event stepwise curve: starts at (evaluation start date, initial_capital) so totalReturn==final/initial-1 and cagr spans the full evaluation window; exits step cumulative closed pnl with no intra-holding mark-to-market",
        "initialCapital": params["portfolio"]["initialCapital"],
        "finalEquity": realized["finalEquity"],
        "totalReturn": realized["totalReturn"],
        "cagr": realized["cagr"],
        "mdd": realized["mdd"],
        "sharpe": realized["sharpe"],
        "sortino": realized["sortino"],
        "calmar": realized["calmar"],
        **{k: v for k, v in t_stats.items()},
    }

    report = {
        "analysis_date": "2026-08-22",
        "model_name": "deepseek",
        "runIdentification": {
            "strategyId": "5dc_v1a_p",
            "runClass": diag["runClass"],
            "universeMode": diag["universeMode"],
            "engineGitCommit": "CURRENT_HEAD(c140c26+)",
            "manifestHash": result["price_provider"].manifest_hash,
            "period": f"{start_date} ~ {end_date}",
            "elapsedSeconds": round(elapsed, 1),
        },
        "diag": {
            "tickersScanned": diag["tickersScanned"],
            "signalCount": diag["signalCount"],
            "executableTradeCount": diag["executableTradeCount"],
            "portfolioEligibleTradeCount": diag["portfolioEligibleTradeCount"],
            "closedPositionCount": diag["closedPositionCount"],
            "openPositionCountAtEnd": diag["openPositionCountAtEnd"],
            "maxSimultaneousPositionsObserved": diag["maxSimultaneousPositionsObserved"],
            "finalCash": diag["finalCash"],
            "exitTypeCounts": diag["exitTypeCounts"],
        },
        "sameBarCensus": {
            "sameBarTrades": len(same_bar),
            "totalClosedTrades": len(trades),
            "sameBarShare": round(len(same_bar) / len(trades), 4) if trades else None,
            "byExitType": dict(same_bar_by_type),
        },
        "resultTable": result_table,
        "allTrades": trades,
    }

    import pickle
    # 2026-08-22: outputs redirected to a versioned dir so re-runs can never
    # overwrite the frozen 2026-08-16 artifacts (5dc_v1a_p_resolved.pkl at the
    # lab root and reports/2026-08-16-parallel-validation/deepseek/*.json).
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-22-convention-standardized-rerun",
    )
    os.makedirs(out_dir, exist_ok=True)
    pkl_path = os.path.join(out_dir, "5dc_v1a_p_resolved_standard.pkl")
    with open(pkl_path, "wb") as f:
        pickle.dump({
            "resolved": result["resolved"],
            "portfolio": portfolio,
            "diag": diag,
            "params": params,
            "calendar": calendar,
        }, f, protocol=pickle.HIGHEST_PROTOCOL)

    out_path = os.path.join(out_dir, "5dc_v1a_p_samebar_rerun_anchored_convention.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "elapsedSeconds": round(elapsed, 1),
        "closedPositionCount": diag["closedPositionCount"],
        "signalCount": diag["signalCount"],
        "sameBarTrades": len(same_bar),
        "resultTable": result_table,
    }, indent=2, default=str))
    print("saved:", out_path)
    print("saved resolved pkl:", pkl_path)


if __name__ == "__main__":
    main()
