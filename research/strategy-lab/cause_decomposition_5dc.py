#!/usr/bin/env python
"""Cause decomposition of the 5DC-v1A-P same-bar impact.
Replays both schedulers from the same resolved list and decomposes how the
130 same-bar trades + fusions propagate into trade-count / PnL / MDD diffs.
Read-only. Outputs to reports/2026-08-16-parallel-validation/deepseek/.
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
from collections import defaultdict
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.metrics.metrics import max_drawdown  # noqa: E402
from replay_scheduler_5dc import schedule_pre_fix, schedule_post_fix  # noqa: E402


def _to_ordinal(date_str):
    y, m, d = map(int, date_str[:10].split("-"))
    return _date(y, m, d).toordinal()


def realized_curve(portfolio):
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    return curve


def mdd_window(curve):
    peak, mdd = curve[0][1], 0.0
    peak_d, trough_d = curve[0][0], curve[0][0]
    for d, eq in curve:
        if eq > peak:
            peak, peak_d = eq, d
        dd = (eq - peak) / peak
        if dd < mdd:
            mdd, trough_d = dd, d
    return {"mdd": mdd, "peak_date": peak_d, "trough_date": trough_d, "peak_equity": peak}


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
    non_sb = [p for p in port_p.closed_positions if p["entry_date"] != p["exit"].fill_date]

    cat = {"never_admitted": [], "fused": [], "stale_open_at_end": []}
    fused_examples = []
    for sb in same_bar:
        sym, d = sb["symbol"], sb["entry_date"]
        fused = [pc for pc in pre_closed_by_sym.get(sym, []) if pc["entry_date"] == d]
        stale = sym in pre_open and pre_open[sym]["entry_date"] == d
        if fused:
            pc = fused[0]
            cat["fused"].append(sb)
            fused_examples.append({
                "symbol": sym,
                "sb_entry": d,
                "sb_exit": sb["exit"].fill_date,
                "sb_exit_type": sb["exit"].fill_type,
                "sb_pnl_postfix": round(sb["pnl"], 2),
                "fused_pre_entry": pc["entry_date"],
                "fused_pre_exit": pc["exit"].fill_date,
                "fused_pre_pnl": round(pc["pnl"], 2),
                "fused_pre_holding_days": _to_ordinal(pc["exit"].fill_date) - _to_ordinal(pc["entry_date"]),
            })
        elif stale:
            cat["stale_open_at_end"].append(sb)
        else:
            cat["never_admitted"].append(sb)

    curve_b = realized_curve(port_b)
    curve_p = realized_curve(port_p)
    mdd_b = max_drawdown(curve_b)
    mdd_p = max_drawdown(curve_p)
    wb = mdd_window(curve_b)
    wp = mdd_window(curve_p)

    eq_b = dict(curve_b)
    eq_p = dict(curve_p)
    all_dates = sorted(set(eq_b) | set(eq_p))
    cum_b = cum_p = 100_000_000.0
    divergence_series = []
    for dt in all_dates:
        cum_b = eq_b.get(dt, cum_b)
        cum_p = eq_p.get(dt, cum_p)
        divergence_series.append((dt, round(cum_p - cum_b, 2)))

    same_bar_pnl = sum(p["pnl"] for p in same_bar)
    non_sb_pnl = sum(p["pnl"] for p in non_sb)
    pre_closed_pnl = sum(p["pnl"] for p in port_b.closed_positions)
    post_closed_pnl = sum(p["pnl"] for p in port_p.closed_positions)

    stale_unrealized = [
        {"symbol": sym, "entry_date": pos["entry_date"], "cost_basis": round(pos["cost_basis"], 2), "shares": pos["shares"]}
        for sym, pos in pre_open.items()
    ]

    def fate_sum(lst):
        return round(sum(p["pnl"] for p in lst), 2)

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "purpose": "cause decomposition of 5DC-v1A-P same-bar impact",
        "resolvedTrades": len(resolved),
        "overview": {
            "pre_fix": {
                "closed": len(port_b.closed_positions),
                "open_at_end": len(port_b.open_positions),
                "finalCash": round(port_b.cash, 2),
                "realizedEquity": round(pre_closed_pnl + 100_000_000, 2),
                "mdd": mdd_b,
            },
            "post_fix": {
                "closed": len(port_p.closed_positions),
                "open_at_end": len(port_p.open_positions),
                "finalCash": round(port_p.cash, 2),
                "realizedEquity": round(post_closed_pnl + 100_000_000, 2),
                "mdd": mdd_p,
            },
            "diff_closed": len(port_p.closed_positions) - len(port_b.closed_positions),
            "diff_realizedEquity": round(post_closed_pnl - pre_closed_pnl, 2),
            "diff_mdd_pp": round((mdd_p - mdd_b) * 100, 2),
        },
        "same_bar_decomposition": {
            "same_bar_trades": len(same_bar),
            "same_bar_pnl_sum": round(same_bar_pnl, 2),
            "non_same_bar_postfix_pnl_sum": round(non_sb_pnl, 2),
            "pre_fix_fate": {
                "never_admitted_count": len(cat["never_admitted"]),
                "fused_count": len(cat["fused"]),
                "stale_open_at_end_count": len(cat["stale_open_at_end"]),
                "never_admitted_pnl_sum": fate_sum(cat["never_admitted"]),
                "fused_pnl_sum": fate_sum(cat["fused"]),
                "stale_open_at_end_pnl_sum": fate_sum(cat["stale_open_at_end"]),
            },
            "fused_examples": fused_examples,
        },
        "equity_mdd_propagation": {
            "pre_fix_mdd_window": wb,
            "post_fix_mdd_window": wp,
            "divergence_series": divergence_series,
            "note": "divergence = post_fix_equity - pre_fix_equity per event date",
        },
        "stale_unrealized_at_end": stale_unrealized,
        "pnl_aggregates": {
            "pre_fix_closed_pnl_sum": round(pre_closed_pnl, 2),
            "post_fix_closed_pnl_sum": round(post_closed_pnl, 2),
            "same_bar_pnl_sum": round(same_bar_pnl, 2),
            "post_fix_minus_same_bar_pnl_sum": round(post_closed_pnl - same_bar_pnl, 2),
        },
    }

    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_cause_decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "overview": report["overview"],
        "same_bar": report["same_bar_decomposition"]["pre_fix_fate"],
        "mdd_windows": {"pre": wb, "post": wp},
    }, indent=2, default=str))
    print("saved:", out_path)


if __name__ == "__main__":
    main()