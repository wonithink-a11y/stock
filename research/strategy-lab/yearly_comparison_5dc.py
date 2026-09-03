#!/usr/bin/env python
"""Yearly breakdown comparison: baseline (pre-fix) vs rerun (post-fix) for
5DC-v1A-P, using the same realized-pnl-at-exit-event method for both."""

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
from engine.metrics.metrics import total_return, max_drawdown  # noqa: E402
from replay_scheduler_5dc import schedule_pre_fix, schedule_post_fix  # noqa: E402


def _to_ordinal(date_str):
    y, m, d = map(int, date_str[:10].split("-"))
    return _date(y, m, d).toordinal()


def yearly(closed_positions, initial_capital):
    """Same method as baseline ablation: realized pnl at exit event, year
    boundaries at last exit event of each year."""
    events = sorted((p["exit_date"], p["pnl"]) for p in closed_positions)
    # curve points: (exit_date, running equity)
    curve = []
    eq = initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))

    yearly_events = defaultdict(list)
    for d, pnl in events:
        yearly_events[d[:4]].append(pnl)
    yearly_curve = defaultdict(list)
    for d, eq in curve:
        yearly_curve[d[:4]].append((d, eq))

    out = {}
    years = sorted(yearly_curve.keys())
    prev_end_eq = initial_capital
    prev_end_date = "2014-05-13"
    for y in years:
        yc = yearly_curve[y]
        trades = yearly_events[y]
        wins = [p for p in trades if p > 0]
        losses = [p for p in trades if p <= 0]
        gp, gl = sum(wins), -sum(losses)
        full = [(prev_end_date, prev_end_eq)] + yc
        out[y] = {
            "trades": len(trades),
            "winRate": (len(wins) / len(trades)) if trades else None,
            "netReturn": total_return(full),
            "mdd": max_drawdown(full),
            "profitFactor": (gp / gl) if gl > 0 else None,
        }
        prev_end_eq = yc[-1][1]
        prev_end_date = yc[-1][0]
    return out


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

    baseline_yearly = json.load(open("reports/2026-08-14-5dc-v1a-p-baseline/ablation_b0_b3.json", encoding="utf-8"))["B3_BB_plus_CCI_5DC_v1A_P"]["yearlyBreakdown"]

    post_yearly = yearly(port_p.closed_positions, params["portfolio"]["initialCapital"])
    pre_yearly = yearly(port_b.closed_positions, params["portfolio"]["initialCapital"])

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "method": "realized-pnl-at-exit-event yearly (same as baseline ablation)",
        "baseline_recorded_yearly": baseline_yearly,
        "pre_fix_replay_yearly": pre_yearly,
        "post_fix_rerun_yearly": post_yearly,
    }
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_yearly_comparison.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print("year | baseline(trades,ret,mdd) | pre_replay(trades,ret,mdd) | post_rerun(trades,ret,mdd)")
    for y in sorted(baseline_yearly):
        b = baseline_yearly[y]
        pr = pre_yearly.get(y, {})
        po = post_yearly.get(y, {})
        print(
            f"{y} | {b['trades']:4d} {b['netReturn']:+.4f} {b['mdd']:.4f}"
            f" | {pr.get('trades',0):4d} {pr.get('netReturn',0):+.4f} {pr.get('mdd',0):.4f}"
            f" | {po.get('trades',0):4d} {po.get('netReturn',0):+.4f} {po.get('mdd',0):.4f}"
        )


if __name__ == "__main__":
    main()