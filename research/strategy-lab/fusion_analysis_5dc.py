#!/usr/bin/env python
"""Quantify exactly how the pre-fix scheduler differs from the post-fix one on
the SAME resolved list (5DC-v1A-P, 25,735 resolved trades):

- 848 (pre) vs 1592 (post) closed = +744.
- 130 are the same-bar trades themselves.
- The remaining +614 = pre-fix fused trades: a same-bar exit was dropped, the
  symbol stayed open, and a LATER unrelated trade's exit closed BOTH (fused
  entry/exit), OR a later re-entry on the same symbol closed the stale open.

We replay both schedulers, and diff per-symbol closed-position sequences to
count fusions and identify the same-bar trades that caused them.
"""
import sys
import os
import json
import pickle
from collections import defaultdict
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from replay_scheduler_5dc import schedule_pre_fix, schedule_post_fix  # noqa: E402


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

    port_p = Portfolio(make_cfg())
    schedule_post_fix(resolved, port_p, make_cfg())
    port_b = Portfolio(make_cfg())
    schedule_pre_fix(resolved, port_b)

    def key(p):
        return (p["symbol"], p["entry_date"], p["exit"].fill_date, round(p["pnl"], 2))

    post_keys = set(key(p) for p in port_p.closed_positions)
    pre_keys = set(key(p) for p in port_b.closed_positions)

    in_post_only = [p for p in port_p.closed_positions if key(p) not in pre_keys]
    in_pre_only = [p for p in port_b.closed_positions if key(p) not in post_keys]
    common = [p for p in port_p.closed_positions if key(p) in pre_keys]

    same_bar_post = [p for p in port_p.closed_positions if p["entry_date"] == p["exit"].fill_date]
    sb_keys = set(key(p) for p in same_bar_post)
    in_post_only_non_sb = [p for p in in_post_only if key(p) not in sb_keys]

    # pre-fix stale open positions (open at end) - these are same-bar exits that
    # were never closed and whose symbol never had a later trade.
    stale = port_b.open_positions
    stale_pnl = 0.0
    stale_shares = 0
    stale_syms = []
    for sym, pos in stale.items():
        # if the same symbol's same-bar trade exists in post list, it would have
        # closed there
        stale_pnl += pos["cost_basis"]
        stale_shares += pos["shares"]
        stale_syms.append(sym)

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "resolvedTrades": len(resolved),
        "pre_fix_closed": len(port_b.closed_positions),
        "post_fix_closed": len(port_p.closed_positions),
        "diff_closed": len(port_p.closed_positions) - len(port_b.closed_positions),
        "post_fix_same_bar": len(same_bar_post),
        "post_only_non_same_bar": len(in_post_only_non_sb),
        "pre_only": len(in_pre_only),
        "common": len(common),
        "pre_fix_open_at_end": len(port_b.open_positions),
        "post_fix_open_at_end": len(port_p.open_positions),
        "fusion_estimate": {
            "explanation": (
                "post-only trades that are NOT same-bar are fused-fabricated in pre-fix: "
                "their symbol had a stale open position from a dropped same-bar exit, "
                "and a later unrelated exit closed a fused entry/exit pair. "
                "pre-only trades are pre-fix fabricated closes that do not correspond to "
                "any real post-fix closed trade (they are the fusion partner closes)."
            ),
            "post_only_non_sb": len(in_post_only_non_sb),
            "pre_only": len(in_pre_only),
        },
        "stale_open_at_end_pre_fix": {
            "count": len(stale_syms),
            "symbols": stale_syms,
            "totalCostBasis": round(stale_pnl, 2),
            "totalShares": stale_shares,
        },
    }

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_fusion_analysis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()