import json

with open('reports/2026-08-30-factor-discovery/factor-discovery-results.json', encoding='utf-8') as f:
    r = json.load(f)

v = r['factors']['earnings_yield']

print('=== Decile Stats (pooled) ===')
for d in range(1, 11):
    dec = v['deciles'][str(d)]
    print(f'Q{d}: n={dec["n"]} mean={dec["mean"]:.4%} median={dec["median"]:.4%}')

print()
print('=== Recent 3 Years (2024-2026) ===')
for yr in ['2024', '2025', '2026']:
    val = v['spread']['yearly'][yr]
    print(f'{yr}: {val:.4%}')

print()
print('=== Coverage ===')
print(f'nObs: {v["nObs"]}')
print(f'coverage: {v["coverage"]:.3f}')
print(f'periods: {v["periods"]}')