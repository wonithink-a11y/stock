import json
with open('research/strategy-lab/reports/2026-08-30-factor-discovery/capacity-test-results.json') as f:
    cap = json.load(f)
print(json.dumps(cap, indent=2))