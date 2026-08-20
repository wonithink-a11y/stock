#!/usr/bin/env python
"""Part 2: quantify fusion PnL distortion and slot/cash cascade propagation.

Complements cause_decomposition_5dc.py. For each fused same-bar trade we
compare the pre-fix fused position PnL vs the post-fix true split
(same-bar trade + partner trade that later closed the stale position).
Also quantifies position-size / slot cascade via common-symbol analysis.
Read-only. Outputs JSON to the same deepseek report dir.
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

    pre_closed_by_sym = defaultdict(list)
    for p in port_b.closed_positions:
        pre_closed_by_sym[p["symbol"]].append(p)
    pre_open = port_b.open_positions

    same_bar = [p for p in port_p.closed_positions if p["entry_date"] == p["exit"].fill_date]

    # ---- fusion pair comparison ----
    fused_cases = []
    for sb in same_bar:
        sym, d = sb["symbol"], sb["entry_date"]
        fused = [pc for pc in pre_closed_by_sym.get(sym, []) if pc["entry_date"] == d]
        if not fused:
            continue
        pc = fused[0]
        ex = pc["exit"].fill_date
        # partner = post-fix trade on same symbol closed on the same date as fused exit
        partner = [q for q in port_p.closed_positions
                   if q["symbol"] == sym and q["exit"].fill_date == ex and q is not sb]
        partner_pnl = sum(q["pnl"] for q in partner) if partner else 0.0
        fused_cases.append({
            "symbol": sym,
            "sb_entry": d,
            "sb_exit": sb["exit"].fill_date,
            "sb_pnl": round(sb["pnl"], 2),
            "fused_pre_exit": ex,
            "fused_pre_holding_days": _to_ordinal(ex) - _to_ordinal(d),
            "fused_pre_pnl": round(pc["pnl"], 2),
            "partner_count": len(partner),
            "partner_pnl_sum": round(partner_pnl, 2),
            "post_true_split": round(sb["pnl"] + partner_pnl, 2),
        })

    def s(x):
        return round(sum(v["sb_pnl"] for v in x), 2)

    def fs(x):
        return round(sum(v["fused_pre_pnl"] for v in x), 2)

    def pt(x):
        return round(sum(v["post_true_split"] for v in x), 2)

    fused_cases.sort(key=lambda v: v["sb_pnl"])

    # ---- common positions: size cascade check ----
    def key(p):
        return (p["symbol"], p["entry_date"], p["exit"].fill_date)

    post_by_key = defaultdict(list)
    for p in port_p.closed_positions:
        post_by_key[key(p)].append(p)
    common = []
    for p in port_b.closed_positions:
        k = key(p)
        if k in post_by_key:
            for q in post_by_key[k]:
                common.append({"symbol": k[0], "pre_shares": p["shares"],
                               "post_shares": q["shares"], "pre_pnl": p["pnl"], "post_pnl": q["pnl"]})
    size_same = sum(1 for c in common if abs(c["pre_shares"] - c["post_shares"]) < 1e-9)
    size_diff = len(common) - size_same
    pnl_equal = sum(1 for c in common if abs(c["pre_pnl"] - c["post_pnl"]) < 1.0)

    # ---- slot/cash cascade proxies ----
    # number of post-fix entry dates blocked in pre-fix by stale-open symbol
    stale_syms = set(pre_open.keys())
    blocked_sym_entries = sum(1 for p in port_p.closed_positions if p["symbol"] in stale_syms)

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "part": 2,
        "fusion_pnl_distortion": {
            "fused_cases": len(fused_cases),
            "sb_pnl_sum": s(fused_cases),
            "fused_pre_pnl_sum": fs(fused_cases),
            "post_true_split_sum": pt(fused_cases),
            "fusion_distortion": round(pt(fused_cases) - fs(fused_cases), 2),
            "note": "post_true_split = same-bar trade pnl + partner trade pnl in post-fix; "
                    "fused_pre_pnl = what pre-fix actually booked for the stale entry closed by the later exit.",
            "examples": fused_cases[:15],
        },
        "common_position_cascade": {
            "common_count": len(common),
            "same_shares_count": size_same,
            "diff_shares_count": size_diff,
            "pnl_equal_within_1_krw_count": pnl_equal,
            "note": "share-size differences on identical entry/exit dates indicate cash/slot cascade from stale positions.",
        },
        "slot_cascade": {
            "stale_open_symbols_at_end": len(stale_syms),
            "post_fix_trades_on_stale_symbols": blocked_sym_entries,
            "note": "trades on symbols that were stale-open at backtest end in pre-fix; in pre-fix these "
                    "symbols could not be re-entered until the stale position closed.",
        },
    }

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    out_path = os.path.join(out_dir, "5dc_v1a_p_fusion_pnl_distortion.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "fusion_pnl_distortion": {
            "fused_cases": len(fused_cases),
            "sb_pnl_sum": s(fused_cases),
            "fused_pre_pnl_sum": fs(fused_cases),
            "post_true_split_sum": pt(fused_cases),
            "fusion_distortion": round(pt(fused_cases) - fs(fused_cases), 2),
        },
        "common_position_cascade": {"common_count": len(common), "same_shares": size_same,
                                    "diff_shares": size_diff, "pnl_equal": pnl_equal},
        "slot_cascade": {"stale_open_symbols": len(stale_syms),
                         "post_fix_trades_on_stale_symbols": blocked_sym_entries},
    }, indent=2, default=str))
    print("saved:", out_path)


if __name__ == "__main__":
    main()