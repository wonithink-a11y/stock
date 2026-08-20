#!/usr/bin/env python
"""Compare baseline recorded closed-trade evidence vs pre-fix replay closed
trades to explain the finalEquity gap (86,267,666.95 baseline vs 87,580,180.58
pre-fix replay, diff ~1.31M) on the same 848-trade count.

Baseline evidence available in 5dc_v1a_p_smoke_verification.json:
- 6_costVerification samples (20 closed trades with shares/entry/exit/pnl)
- 3_signalVerification samples (20 signals)
We match those baseline samples against pre-fix replay closed positions.
"""
import sys
import os
import json
import pickle
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from replay_scheduler_5dc import schedule_pre_fix  # noqa: E402


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

    port_b = Portfolio(make_cfg())
    schedule_pre_fix(resolved, port_b)

    closed = port_b.closed_positions
    by_key = {}
    for p in closed:
        by_key[(p["symbol"], p["entry_date"], p["exit"].fill_date)] = p

    # baseline cost samples
    v = json.load(open("reports/2026-08-14-5dc-v1a-p-baseline/5dc_v1a_p_smoke_verification.json", encoding="utf-8"))
    samples = v["6_costVerification"]["samples"]

    matches = []
    mismatches = []
    for s in samples:
        key = (s["symbol"], s["entryDate"], s["exitDate"])
        p = by_key.get(key)
        if p is None:
            mismatches.append({"sample": s, "found": False})
            continue
        rec = {
            "symbol": s["symbol"],
            "entryDate": s["entryDate"],
            "exitDate": s["exitDate"],
            "baseline_shares": s["shares"],
            "replay_shares": p["shares"],
            "baseline_netPnl": s["netPnlStored"],
            "replay_pnl": p["pnl"],
            "match": s["shares"] == p["shares"] and abs(s["netPnlStored"] - p["pnl"]) < 1e-6,
        }
        (matches if rec["match"] else mismatches).append(rec)

    report = {
        "analysis_date": "2026-08-16",
        "model_name": "deepseek",
        "baselineCostSamplesMatched": len(matches),
        "baselineCostSamplesMismatched": len(mismatches),
        "matches": matches,
        "mismatches": mismatches,
        "replayFinalEquity": port_b.cash + sum(p["pnl"] for p in closed),
        "replayClosedCount": len(closed),
        "baselineFinalEquity": 86267666.94729893,
    }
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-16-parallel-validation", "deepseek",
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc_v1a_p_baseline_sample_match.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "baselineCostSamplesMatched": len(matches),
        "baselineCostSamplesMismatched": len(mismatches),
        "replayFinalEquity": report["replayFinalEquity"],
        "replayClosedCount": len(closed),
    }, indent=2, default=str))
    for m in mismatches:
        print("MISMATCH:", json.dumps(m, default=str))


if __name__ == "__main__":
    main()