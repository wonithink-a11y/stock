#!/usr/bin/env python
"""Trace exactly what the pre-fix scheduler did with the 130 same-bar trades
(5DC-v1A-P). For each same-bar trade (from post-fix closed positions), find the
same symbol's pre-fix closed position that absorbed it, or the stale open at end.

Explains the mechanism: dropped same-bar exit -> stale open -> later fusion.
"""
import sys
import os
import json
import pickle
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from replay_scheduler_5dc import schedule_pre_fix, schedule_post_fix  # noqa: E402


def _to_ordinal(date_str):
    y, m, d = map(int, date_str[:10].split("-"))
    return _date(y, m, d).toordinal()


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

    post_by_sym = {}
    for p in port_p.closed_positions:
        post_by_sym.setdefault(p["symbol"], []).append(p)
    pre_by_sym = {}
    for p in port_b.closed_positions:
        pre_by_sym.setdefault(p["symbol"], []).append(p)

    same_bar = [p for p in port_p.closed_positions if p["entry_date"] == p["exit"].fill_date]

    traces = []
    stale_absorbed = 0
    fusion_absorbed = 0
    for sb in same_bar:
        sym = sb["symbol"]
        # pre-fix closed positions for this symbol
        pre_closed = pre_by_sym.get(sym, [])
        # was the symbol stale-open at end in pre-fix?
        stale_at_end = sym in port_b.open_positions
        # find a pre-fix closed pos whose entry_date <= sb entry and that had a
        # long holding (fusion indicator) - or the stale one
        trace = {
            "symbol": sym,
            "samebar_entry_date": sb["entry_date"],
            "samebar_exit_date": sb["exit"].fill_date,
            "samebar_exit_type": sb["exit"].fill_type,
            "samebar_pnl": round(sb["pnl"], 2),
            "pre_fix_closed_count_for_symbol": len(pre_closed),
            "stale_open_at_end_pre_fix": stale_at_end,
        }
        if stale_at_end:
            stale_absorbed += 1
            pos = port_b.open_positions[sym]
            trace["absorbed_by"] = "STALE_OPEN_AT_END"
            trace["stale_entry_date"] = pos["entry_date"]
            trace["stale_cost_basis"] = round(pos["cost_basis"], 2)
        else:
            # find pre-fix closed pos on same symbol with holding > 1 that
            # overlaps the same-bar window
            candidates = []
            for pc in pre_closed:
                holding = _to_ordinal(pc["exit"].fill_date[:10]) - _to_ordinal(pc["entry_date"][:10])
                overlap = pc["entry_date"] <= sb["exit"].fill_date <= pc["exit"].fill_date
                candidates.append({
                    "entry_date": pc["entry_date"],
                    "exit_date": pc["exit"].fill_date,
                    "holding": holding,
                    "overlaps_samebar_window": bool(overlap),
                    "pnl": round(pc["pnl"], 2),
                })
            trace["pre_fix_closed_positions"] = candidates
            fusion_absorbed += 1

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "same_bar_trades": len(same_bar),
        "absorbed_by_stale_open_at_end": stale_absorbed,
        "absorbed_by_later_fusion": fusion_absorbed,
        "traces": traces,
    }
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_samebar_trace.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "same_bar_trades": len(same_bar),
        "absorbed_by_stale_open_at_end": stale_absorbed,
        "absorbed_by_later_fusion": fusion_absorbed,
    }, indent=2))
    # print a few representative traces
    for t in traces[:8]:
        print(json.dumps(t, indent=1, default=str))


if __name__ == "__main__":
    main()