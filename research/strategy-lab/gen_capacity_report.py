import json
import os

with open('research/strategy-lab/reports/2026-08-30-factor-discovery/capacity-test-results.json', encoding='utf-8') as f:
    results = json.load(f)

ew = {"cagr": 0.0293, "sharpe": 0.24, "mdd": -0.1110, "total_return": 0.3733, "exposure": 0.84}

lines = []
lines.append('# Earnings Yield — Capacity Test (max_positions Scaling)')
lines.append('')
lines.append('- 실험: `EARNINGS-YIELD-CAPACITY-TEST-KR-2026-08`')
lines.append('- 대상: `earnings_yield` 단독, max_positions = 20 / 30 / 50 / 100')
lines.append('- 조건: 동일 유니버스/PIT/비용/기간/리밸런싱, 초기자본 1억원, Long-only')
lines.append('')

lines.append('## 1. 핵심 성과 비교')
lines.append('')
lines.append('| max_positions | CAGR | Sharpe | MDD | Total Return | Max Simultaneous | Exposure (rel to 30) |')
lines.append('|---|---|---|---|---|---|---|')
for mp in [20, 30, 50, 100]:
    m = results[str(mp)]
    lines.append('| {} | {:.2%} | {:.2f} | {:.2%} | {:.2%} | {} | {:.2%} |'.format(
        mp, m["cagr"], m["sharpe"], m["mdd"], m["total_return"], m["max_simul"], m["exposure"]))
lines.append('| EW BM | {:.2%} | {:.2f} | {:.2%} | {:.2%} | - | {:.2%} |'.format(
    ew["cagr"], ew["sharpe"], ew["mdd"], ew["total_return"], ew["exposure"]))
lines.append('')

lines.append('## 2. 분석')
lines.append('')

best_sharpe = max(results.items(), key=lambda x: x[1]['sharpe'] or 0)
best_cagr = max(results.items(), key=lambda x: x[1]['cagr'])
best_mdd = min(results.items(), key=lambda x: x[1]['mdd'])

lines.append('- **Best Sharpe**: max_positions={} (Sharpe={:.2f})'.format(best_sharpe[0], best_sharpe[1]['sharpe']))
lines.append('- **Best CAGR**: max_positions={} (CAGR={:.2%})'.format(best_cagr[0], best_cagr[1]['cagr']))
lines.append('- **Best MDD**: max_positions={} (MDD={:.2%})'.format(best_mdd[0], best_mdd[1]['mdd']))
lines.append('')

lines.append('### 용량 효과 분석')
for a,b in [(20,30), (30,50), (50,100)]:
    diff_cagr = results[str(b)]['cagr'] - results[str(a)]['cagr']
    diff_sharpe = (results[str(b)]['sharpe'] or 0) - (results[str(a)]['sharpe'] or 0)
    lines.append('- max_positions {}->{}: CAGR {:.2%}->{:.2%} ({:+.2%}), Sharpe {:.2f}->{:.2f} ({:+.2f})'.format(
        a, b, results[str(a)]['cagr'], results[str(b)]['cagr'], diff_cagr,
        results[str(a)]['sharpe'] or 0, results[str(b)]['sharpe'] or 0, diff_sharpe))
lines.append('')

lines.append('### 알파 희석 확인')
base_cagr = results['30']['cagr']
for mp in [20, 50, 100]:
    diff = results[str(mp)]['cagr'] - base_cagr
    status = '희석' if diff < -0.001 else ('개선' if diff > 0.001 else '유사')
    lines.append('- max_positions={}: CAGR 차이 {:+.2%} -> {}'.format(mp, diff, status))
lines.append('')

lines.append('## 3. 최종 권장 max_positions')
lines.append('')

# Decision: 50 has better Sharpe and better MDD (less negative), slightly lower CAGR
if results['50']['sharpe'] > results['30']['sharpe'] and results['50']['mdd'] > results['30']['mdd']:
    lines.append('> **PASS: max_positions=50** — 분산효과로 Sharpe/MDD 개선, CAGR 미미한 감소(-0.12%p)')
elif results['30']['sharpe'] >= results['50']['sharpe'] and results['30']['mdd'] <= results['50']['mdd']:
    lines.append('> **PASS: max_positions=30** (기존 유지) — 50 확대 시 유의미한 개선 없음')
elif results['20']['sharpe'] > results['30']['sharpe']:
    lines.append('> **CONDITIONAL: max_positions=20** — 소수 정예가 유리하나 용량 제한')
else:
    lines.append('> **CONDITIONAL: max_positions=50** — Sharpe/MDD 개선이나 CAGR 미미 감소, 운용 목적에 따라 선택')

out_path = os.path.join('C:/Users/User/projects/stock/research/strategy-lab/findings', 'factor-earnings-yield-capacity-test-2026-08.md')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('Report: ' + out_path)