#!/usr/bin/env python3
"""단기 반등 4규칙 × 새 시장 6곳 재현 — 사전등록 findings/tech-timing-3x-c-preregistration-2026-11.md

    python research/strategy-lab/tech_timing_3x_c.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tech_timing_3x as B  # noqa: E402
import tech_timing_3x_b as B2  # noqa: E402

KEEP = ["C2 IBS", "C4 3일연속하락", "C3 Double7", "C8 VIX>30후3일하락"]
MARKETS = [("^GSPC", 3, 0.03, True), ("^RUT", 3, 0.03, True), ("^N225", 2, 0.02, False), ("^GDAXI", 2, 0.02, False), ("^KQ11", 2, 0.02, False), ("^HSI", 2, 0.02, False)]


def ok(cell):
    return cell["dSharpe"] >= 0.10 and cell["p"] <= 0.01


def main() -> int:
    vix = B.load("^VIX")["Close"]
    out = {}
    tally = {k: 0 for k in KEEP}
    for tk, lev, drag, us in MARKETS:
        df = B.load(tk)
        df = df[df.index <= B.END]
        vv = vix if us else vix.shift(1)
        allr = B2.community_rules(df, vv, lev)
        rules = {k: allr[k] for k in KEEP}
        res, bh_m, bounds = B2.evaluate(df, rules, lev, drag)
        out[tk] = dict(lev=lev, bh=bh_m, rules=res, bounds={k: [str(df.index[a]), str(df.index[b - 1])] for k, (a, b) in bounds.items() if bounds[k]})
        print(f"\n=== {tk} {lev}배 보유 " + " | ".join(f"{k} {v['cagr']:.0f}/{v['sharpe']:.2f}/{v['mdd']:.0f}" for k, v in bh_m.items()))
        for rn, row in res.items():
            both = "VALID" in row and "TEST" in row and ok(row["VALID"]) and ok(row["TEST"])
            tally[rn] += int(both)
            print(f"  {rn:18s} " + " | ".join(f"{k} Δ{row[k]['dSharpe']:+.2f} p{row[k]['p']:.3f} C{row[k]['cagr']:.0f}" for k in row) + (" ★충족" if both else ""))
    verdict = {k: ("REPLICATED" if v >= 3 else "NOT REPLICATED") for k, v in tally.items()}
    print("\n규칙별 VALID·TEST 충족 시장 수", tally, verdict)
    out["_tally"] = tally
    out["_verdict"] = verdict
    (B.ROOT / "findings" / "tech-timing-3x-c-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
