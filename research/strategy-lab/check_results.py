import json
from pathlib import Path

p = Path(r'C:\Users\User\projects\stock\research\strategy-lab\findings\btc-regime-ma-2026-08.json')
j = json.load(open(p, encoding='utf-8'))

print('regime_split_r7:')
for r, v in j['regime_split_r7'].items():
    print('  ' + r + ':')
    for f, val in v.items():
        d = val.get('D1_minus_D10')
        t = val.get('t')
        print('  ' + f + ': delta=' + ('{:+.6f}'.format(d) if d is not None else 'None') + ' t=' + ('{:+.2f}'.format(t) if t is not None else 'None'))

print()
print('corr_f:', j['corr_f'])
print('corr_mom:', j['corr_mom'])