import json
from pathlib import Path

p = Path(r'C:\Users\User\projects\stock\research\strategy-lab\findings\fibonacci-retracement-2026-08.json')
j = json.load(open(p, encoding='utf-8'))

print('Keys:', list(j.keys()))
print()
print('pooled_decile_r7:')
for f, v in j['pooled_decile_r7'].items():
    print('  ' + f + ':', v)
print()
print('corr_f:', j['corr_f'])
print('corr_mom:', j['corr_mom'])
print()
print('regime_split_r7:')
for r, v in j['regime_split_r7'].items():
    print('  ' + r + ':')
    for f, val in v.items():
        d = val.get('D1_minus_D10')
        t = val.get('t')
        print('  ' + f + ': delta=' + ('{:+.6f}'.format(d) if d is not None else 'None') + ' t=' + ('{:+.2f}'.format(t) if t is not None else 'None'))
print()
print('controlled_fm:')
for f, v in j['controlled_fm'].items():
    d = v.get('D1_minus_D10')
    t = v.get('t')
    print('  ' + f + ': delta=' + ('{:+.6f}'.format(d) if d is not None else 'None') + ' t=' + ('{:+.2f}'.format(t) if t is not None else 'None'))
print()
print('loo_btc:')
for f, v in j['loo_btc'].items():
    d = v.get('D1_minus_D10')
    t = v.get('t')
    print('  ' + f + ': delta=' + ('{:+.6f}'.format(d) if d is not None else 'None') + ' t=' + ('{:+.2f}'.format(t) if t is not None else 'None'))