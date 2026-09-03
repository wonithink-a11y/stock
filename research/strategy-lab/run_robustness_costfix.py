#!/usr/bin/env python
"""Fix cost-sensitivity runs: use round-trip cost convention (30/50/65 bps RT).
Removes the previously mislabeled per-side cost keys, then re-runs with
entry=exit=round_trip/2 and saves under cost_rt{30,50,65}.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "research", "strategy-lab"))

from run_robustness_real import make_rule_module, run_one, OUT_JSON  # noqa: E402

# 1. Remove the mislabeled per-side cost keys (they were 60/100/130 bps round-trip in reality)
with open(OUT_JSON, encoding="utf-8") as f:
    results = json.load(f)
for k in ["cost_30bps", "cost_50bps", "cost_65bps"]:
    if k in results:
        del results[k]
        print(f"removed mislabeled key: {k}", flush=True)
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

# 2. Run correct round-trip cost variants
for rt in [30, 50, 65]:
    mod = make_rule_module(max_positions=50, round_trip_bps=rt)
    run_one(f"cost_rt{rt}", rule_module=mod, note=f"max50 cost {rt}bps round-trip")

print("Cost fix complete.", flush=True)