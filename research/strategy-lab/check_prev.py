import json
r=json.load(open('reports/2026-08-30-factor-discovery/factor-discovery-results.json',encoding='utf-8'))
for k in ['earnings_yield','rv60_pct','rev1m','op_margin_trend','dv20_log']:
    v=r['factors'][k]
    sp=v['spread']
    print(f'{k}: spread={sp["mean"]:.4%} t={sp["t"]} hit={sp["hitRate"]} posYR={sp["posYearRatio"]}')
    print('  yearly:', v['spread']['yearly'])
    ms=v['marketSplit']
    for m in ['KOSPI','KOSDAQ']:
        if ms.get(m): print(f'  {m}: mean={ms[m]["mean"]:.4%} t={ms[m]["t"]} posYR={ms[m]["posYearRatio"]}')