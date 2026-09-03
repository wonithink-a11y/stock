#!/usr/bin/env python
"""Re-run subgroup tests at the correct 30bps round-trip cost (reference).
Only keys that were run with the wrong per-side cost (60bps RT) are cleared
and re-run with round_trip_bps=30.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "research", "strategy-lab"))

from run_robustness_real import (  # noqa: E402
    make_rule_module, run_one, OUT_JSON, _load_a1a, _classify_mcap,
)

# 1. Clear keys that were computed at 60bps RT (per-side cost_bps=30)
to_clear = [
    "market_kospi", "market_kosdaq",
    "period_2016-2020", "period_2021-2023", "period_2024-2026",
    "mcap_large", "mcap_mid", "mcap_small",
    "survivorship",
]
with open(OUT_JSON, encoding="utf-8") as f:
    results = json.load(f)
for k in to_clear:
    if k in results:
        del results[k]
        print(f"cleared {k} (was 60bps RT)", flush=True)
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

# 2. Re-run at 30bps round-trip
mod_ref = make_rule_module(max_positions=50, round_trip_bps=30)

a1a = _load_a1a()
kospi = [t for t, i in a1a.items() if i.get("market") == "KOSPI"]
kosdaq = [t for t, i in a1a.items() if i.get("market") == "KOSDAQ"]

run_one("market_kospi", ticker_subset=set(kospi), rule_module=mod_ref, note="max50 cost30RT, KOSPI only")
run_one("market_kosdaq", ticker_subset=set(kosdaq), rule_module=mod_ref, note="max50 cost30RT, KOSDAQ only")

for name, s, e in [("2016-2020", "2016-01-01", "2020-12-31"),
                   ("2021-2023", "2021-01-01", "2023-12-31"),
                   ("2024-2026", "2024-01-01", "2026-08-14")]:
    run_one(f"period_{name}", rule_module=mod_ref, start=s, end=e, note=f"period {name} 30RT")

segs, mcap, _, _ = _classify_mcap()
if segs:
    run_one("mcap_large", ticker_subset=set(segs["large"]), rule_module=mod_ref, note="max50 cost30RT, large cap")
    run_one("mcap_mid", ticker_subset=set(segs["mid"]), rule_module=mod_ref, note="max50 cost30RT, mid cap")
    run_one("mcap_small", ticker_subset=set(segs["small"]), rule_module=mod_ref, note="max50 cost30RT, small cap")

mod_surv = make_rule_module(max_positions=50, round_trip_bps=30, universe_mode="A1A_A1B_MERGED")
run_one("survivorship", rule_module=mod_surv, note="max50 cost30RT, A1A+A1B merged universe")

print("Subgroup re-run complete.", flush=True)