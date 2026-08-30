import json
import os

with open('research/strategy-lab/reports/2026-08-30-factor-discovery/factor-single-backtest-results.json', encoding='utf-8') as f:
    results = json.load(f)

REPO_ROOT = 'C:/Users/User/projects/stock'

lines = []
lines.append('# Factor Single-Factor Backtest — KR (2026-08-30)')
lines.append('')
lines.append('- 실험: `FACTOR-SINGLE-BACKTEST-KR-2026-08`')
lines.append('- 대상: `earnings_yield` (Q10), `rv60_pct` (Q1), `rev1m` (Q1)')
lines.append('- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only')
lines.append('- 벤치마크: `ew_benchmark_liquid_v1` (동일 유니버스/비용/캘린더)')
lines.append('')
lines.append('## 결과 요약')
lines.append('')
lines.append('| factor | grade | Total Return | CAGR | Sharpe | MDD | Exposure | Win Rate | Trades |')
lines.append('|---|---|---|---|---|---|---|---|---|')

for sid, res in results.items():
    m = res['metrics']
    d = res['diag']
    if m:
        grade = 'PASS' if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else 'FAIL'
        factor_name = sid.replace('factor_', '').replace('_v1', '')
        sharpe_str = f'{m["sharpe"]:.2f}' if m['sharpe'] else 'N/A'
        lines.append(f'| {factor_name} | {grade} | {m["total_return"]:.2%} | {m["cagr"]:.2%} | {sharpe_str} | {m["mdd"]:.2%} | {m["exposure"]:.2%} | {m["win_rate"]:.2%} | {m["n_trades"]} |')

lines.append('')

for sid, res in results.items():
    m = res['metrics']
    d = res['diag']
    if not m:
        continue
    factor_name = sid.replace('factor_', '').replace('_v1', '')
    grade = 'PASS' if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else 'FAIL'
    lines.append(f'## {factor_name} — {grade}')
    lines.append('')
    lines.append(f'- Total Return: {m["total_return"]:.2%}')
    lines.append(f'- CAGR: {m["cagr"]:.2%}')
    sharpe_str = f'{m["sharpe"]:.2f}' if m['sharpe'] is not None else 'N/A'
    lines.append(f'- Sharpe: {sharpe_str}')
    lines.append(f'- MDD: {m["mdd"]:.2%}')
    lines.append(f'- Exposure: {m["exposure"]:.2%}')
    lines.append(f'- Win Rate: {m["win_rate"]:.2%}')
    lines.append(f'- Trades: {m["n_trades"]}')
    lines.append(f'- Total Cost (bps): {m["total_cost_bps"]:.1f}')
    lines.append(f'- Yearly Returns: {m["yearly_returns"]}')
    lines.append('')
    lines.append('### Diagnostics')
    lines.append(f'- Signals: {d["signalCount"]}, Executable: {d["executableTradeCount"]}, Closed: {d["closedPositionCount"]}')
    lines.append(f'- Exit Types: {d["exitTypeCounts"]}')
    lines.append(f'- Max Simultaneous Positions: {d["maxSimultaneousPositionsObserved"]}')
    lines.append('')

out_path = os.path.join(REPO_ROOT, 'research', 'strategy-lab', 'findings', 'factor-single-backtest-kr-2026-08.md')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Report: {out_path}')