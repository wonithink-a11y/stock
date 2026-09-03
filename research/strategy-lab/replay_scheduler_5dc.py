#!/usr/bin/env python
"""Reproduce BOTH scheduling behaviors (pre-fix vs post-fix) from the SAME
resolved trade list, to prove the 848 -> 1592 difference is caused entirely by
the same-bar fix (engine/runner.py _schedule_portfolio), not by data changes.

Pre-fix = the exact 9b5355c date-loop (exits first, same-bar exits silently
dropped). Post-fix = current _schedule_portfolio (same-bar exit retry).

Read-only. No production file touched.
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
import pickle
from collections import Counter
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.metrics.metrics import (  # noqa: E402
    total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats,
)


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def schedule_pre_fix(resolved, portfolio):
    """Exact pre-fix logic from 9b5355c: single process_day per event date,
    exits only for symbols already in open_positions (same-bar exits dropped)."""
    by_entry_date = {}
    by_exit_date = {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)
    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    max_open_seen = 0
    for date in event_dates:
        exits_today = []
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)
        assert len(portfolio.open_positions) <= portfolio.config.max_positions
        max_open_seen = max(max_open_seen, len(portfolio.open_positions))
    return max_open_seen


def schedule_post_fix(resolved, portfolio, portfolio_cfg):
    """Current engine's _schedule_portfolio (same-bar retry)."""
    by_entry_date = {}
    by_exit_date = {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)
    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    max_open_seen = 0
    for date in event_dates:
        exits_today = []
        same_bar_exit_candidates = []
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)
        max_open_seen = max(max_open_seen, len(portfolio.open_positions))
        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])
                max_open_seen = max(max_open_seen, len(portfolio.open_positions))
    return max_open_seen


def realized_pnl_metrics(portfolio):
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve = []
    eq = portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return None
    return {
        "finalEquity": eq,
        "totalReturn": total_return(curve),
        "cagr": cagr(curve),
        "mdd": max_drawdown(curve),
        "sharpe": sharpe(curve),
    }


def summarize(tag, portfolio, config, diag_extra=None):
    trades = []
    for p in portfolio.closed_positions:
        trades.append({
            "pnl": p["pnl"],
            "holding_sessions": _to_ordinal(p["exit"].fill_date) - _to_ordinal(p["entry_date"]),
            "symbol": p["symbol"],
            "entry_date": p["entry_date"],
            "exit_date": p["exit"].fill_date,
            "exit_type": p["exit"].fill_type,
        })
    ts = trade_stats(trades)
    r = realized_pnl_metrics(portfolio)
    same_bar = [t for t in trades if t["entry_date"] == t["exit_date"]]
    return {
        "tag": tag,
        "closedPositionCount": len(portfolio.closed_positions),
        "openPositionCountAtEnd": len(portfolio.open_positions),
        "finalCash": portfolio.cash,
        "realized": r,
        "tradeStats": ts,
        "sameBarTrades": len(same_bar),
        "sameBarByType": dict(Counter(t["exit_type"] for t in same_bar)),
    }


def main():
    with open("5dc_v1a_p_resolved.pkl", "rb") as f:
        data = pickle.load(f)
    resolved = data["resolved"]
    params = data["params"]

    def make_cfg():
        return PortfolioConfig(
            initial_capital=params["portfolio"]["initialCapital"],
            max_positions=params["portfolio"]["maxPositions"],
            equal_weight=params["portfolio"]["equalWeight"],
            fractional_shares=params["portfolio"]["fractionalShares"],
            tie_break=params["portfolio"]["tieBreak"],
        )

    # POST-FIX (current engine behavior)
    port_p = Portfolio(make_cfg())
    m_p = schedule_post_fix(resolved, port_p, make_cfg())
    post = summarize("post_fix", port_p, make_cfg())

    # PRE-FIX (9b5355c behavior)
    port_b = Portfolio(make_cfg())
    m_b = schedule_pre_fix(resolved, port_b)
    pre = summarize("pre_fix", port_b, make_cfg())

    out = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "resolvedTrades": len(resolved),
        "pre_fix": {**pre, "maxOpenSeen": m_b},
        "post_fix": {**post, "maxOpenSeen": m_p},
        "baseline_recorded": {
            "closedPositionCount": 848,
            "source": "reports/2026-08-14-5dc-v1a-p-baseline/ablation_b0_b3.json B3",
        },
    }
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_pre_post_scheduler_replay.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()