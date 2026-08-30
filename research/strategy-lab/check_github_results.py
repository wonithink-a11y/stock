import json
from pathlib import Path

p = Path(r'C:\Users\User\projects\stock\research\strategy-lab\findings\github-strategy-reproduction-2026-08.json')
j = json.load(open(p, encoding='utf-8'))

print('Keys:', list(j.keys()))
print()
for name, res in j['results'].items():
    agg = res['aggregated']
    cagr = agg.get('cagr', 0)
    sharpe = agg.get('sharpe', 0)
    mdd = agg.get('max_dd', 0)
    wr = agg.get('win_rate', 0)
    pf = agg.get('profit_factor', 0)
    trades = agg.get('n_trades', 0)
    print(name + ': CAGR=' + '{:.4f}'.format(cagr) + ', Sharpe=' + '{:.4f}'.format(sharpe) + 
          ', MDD=' + '{:.4f}'.format(mdd) + ', WR=' + '{:.4f}'.format(wr) + 
          ', PF=' + '{:.4f}'.format(pf) + ', Trades=' + str(trades))