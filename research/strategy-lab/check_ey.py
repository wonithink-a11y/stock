import json

with open('reports/2026-08-30-factor-discovery/factor-discovery-results.json', encoding='utf-8') as f:
    r = json.load(f)

v = r['factors']['earnings_yield']

print('=== Overall ===')
sp = v['spread']
print(f'spread: {sp["mean"]:.4%} t={sp["t"]:.2f} hit={sp["hitRate"]:.2f} posYR={sp["posYearRatio"]:.2f}')
print(f'net spread: {v["netSpread"]["mean"]:.4%} t={v["netSpread"]["t"]:.2f}')
print(f'IC: {v["ic"]}')
print(f'decile slope: {v["decileSlopeSpearman"]:.3f}')
print()

print('=== By Market ===')
for mkt in ['KOSPI', 'KOSDAQ']:
    ms = v['marketSplit'][mkt]
    print(f'{mkt}: spread={ms["mean"]:.4%} t={ms["t"]:.2f} hit={ms["hitRate"]:.2f} posYR={ms["posYearRatio"]:.2f} nMonths={ms["nMonths"]}')
print()

print('=== Yearly ===')
for yr, val in v['spread']['yearly'].items():
    print(f'{yr}: {val:.4%}')
print()

print('=== Long Q10 (net) ===')
lt = v['longTopDecile']['net']
print(f'CAGR={lt["cagr"]:.2%} Sharpe={lt["sharpe"]:.2f} MDD={lt["mdd"]:.2%} nMonths={lt["nMonths"]}')
print()

print('=== Long Q1 (net) ===')
lb = v['longBottomDecile']['net']
print(f'CAGR={lb["cagr"]:.2%} Sharpe={lb["sharpe"]:.2f} MDD={lb["mdd"]:.2%} nMonths={lb["nMonths"]}')