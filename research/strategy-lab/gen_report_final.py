import json
import os

# Load factor backtest results
with open('research/strategy-lab/reports/2026-08-30-factor-discovery/factor-single-backtest-results.json', encoding='utf-8') as f:
    factor_results = json.load(f)

# EW Benchmark results (from run)
ew_benchmark = {
    "total_return": 0.3733,
    "cagr": 0.0293,
    "sharpe": 0.24,
    "mdd": -0.1110,
    "exposure": 0.84,
    "n_trades": 5703,
    "win_rate": 0.3367,
    "total_cost_bps": 0.0,
    "yearly_returns": {'2016': -0.003951916554999999, '2017': -0.005068741389999998, '2018': -0.014748938159999997, '2019': -0.01389274558999999, '2020': -0.006767562589999997, '2021': 0.0009643636899999997, '2022': -0.0037699510300000017, '2023': -0.010790886750000004, '2024': -0.023541751049999986, '2025': -0.021154511455000007, '2026': 0.47603866840000003}
}

# Previous results (from old run with max_positions=200)
prev_results = {
    "factor_earnings_yield_v1": {"total_return": 0.2176, "cagr": 0.0181, "sharpe": 0.72, "mdd": -0.0508, "exposure": 0.3856, "n_trades": 1347, "win_rate": 0.4959},
    "factor_rv60_v1": {"total_return": 0.3530, "cagr": 0.0279, "sharpe": 0.58, "mdd": -0.1180, "exposure": 1.1858, "n_trades": 7423, "win_rate": 0.4937},
    "factor_rev1m_v1": {"total_return": 0.2558, "cagr": 0.0209, "sharpe": 0.16, "mdd": -0.2374, "exposure": 1.6730, "n_trades": 19320, "win_rate": 0.4586},
}

REPO_ROOT = 'C:/Users/User/projects/stock'

lines = []
lines.append('# Factor Single-Factor Backtest — KR (2026-08-30) — 검증 완료')
lines.append('')
lines.append('- 실험: `FACTOR-SINGLE-BACKTEST-KR-2026-08`')
lines.append('- 대상: `earnings_yield` (Q10), `rv60_pct` (Q1), `rev1m` (Q1)')
lines.append('- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only')
lines.append('- 초기자본: 1억원, max_positions=30, equal-weight, no leverage')
lines.append('- 벤치마크: `ew_benchmark_liquid_v1` (전체유니버스 EW, max_positions=1500)')
lines.append('')

lines.append('## 1. 최종 결과 요약 (max_positions=30, 초기자본 1억원)')
lines.append('')
lines.append('| factor | grade | Total Return | CAGR | Sharpe | MDD | Exposure | Win Rate | Trades |')
lines.append('|---|---|---|---|---|---|---|---|---|')

for sid, res in factor_results.items():
    m = res['metrics']
    d = res['diag']
    if m:
        grade = 'PASS' if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else 'FAIL'
        factor_name = sid.replace('factor_', '').replace('_v1', '')
        sharpe_str = f'{m["sharpe"]:.2f}' if m['sharpe'] is not None else 'N/A'
        lines.append(f'| {factor_name} | {grade} | {m["total_return"]:.2%} | {m["cagr"]:.2%} | {sharpe_str} | {m["mdd"]:.2%} | {m["exposure"]:.2%} | {m["win_rate"]:.2%} | {m["n_trades"]} |')

lines.append('')
lines.append('## 2. 벤치마크 비교')
lines.append('')
lines.append('| 지표 | earnings_yield | rv60_pct | rev1m | EW Benchmark (전체유니버스) |')
lines.append('|---|---|---|---|---|')
lines.append(f'| Total Return | {factor_results["factor_earnings_yield_v1"]["metrics"]["total_return"]:.2%} | {factor_results["factor_rv60_v1"]["metrics"]["total_return"]:.2%} | {factor_results["factor_rev1m_v1"]["metrics"]["total_return"]:.2%} | {ew_benchmark["total_return"]:.2%} |')
lines.append(f'| CAGR | {factor_results["factor_earnings_yield_v1"]["metrics"]["cagr"]:.2%} | {factor_results["factor_rv60_v1"]["metrics"]["cagr"]:.2%} | {factor_results["factor_rev1m_v1"]["metrics"]["cagr"]:.2%} | {ew_benchmark["cagr"]:.2%} |')
lines.append(f'| Sharpe | {factor_results["factor_earnings_yield_v1"]["metrics"]["sharpe"]:.2f} | {factor_results["factor_rv60_v1"]["metrics"]["sharpe"]:.2f} | {factor_results["factor_rev1m_v1"]["metrics"]["sharpe"]:.2f} | {ew_benchmark["sharpe"]:.2f} |')
lines.append(f'| MDD | {factor_results["factor_earnings_yield_v1"]["metrics"]["mdd"]:.2%} | {factor_results["factor_rv60_v1"]["metrics"]["mdd"]:.2%} | {factor_results["factor_rev1m_v1"]["metrics"]["mdd"]:.2%} | {ew_benchmark["mdd"]:.2%} |')
lines.append(f'| Exposure | {factor_results["factor_earnings_yield_v1"]["metrics"]["exposure"]:.2%} | {factor_results["factor_rv60_v1"]["metrics"]["exposure"]:.2%} | {factor_results["factor_rev1m_v1"]["metrics"]["exposure"]:.2%} | {ew_benchmark["exposure"]:.2%} |')
lines.append(f'| Win Rate | {factor_results["factor_earnings_yield_v1"]["metrics"]["win_rate"]:.2%} | {factor_results["factor_rv60_v1"]["metrics"]["win_rate"]:.2%} | {factor_results["factor_rev1m_v1"]["metrics"]["win_rate"]:.2%} | {ew_benchmark["win_rate"]:.2%} |')
lines.append(f'| Trades | {factor_results["factor_earnings_yield_v1"]["metrics"]["n_trades"]} | {factor_results["factor_rv60_v1"]["metrics"]["n_trades"]} | {factor_results["factor_rev1m_v1"]["metrics"]["n_trades"]} | {ew_benchmark["n_trades"]} |')
lines.append('')

lines.append('## 3. 기존 결과(Initial, max_positions=200) 대비 차이')
lines.append('')
lines.append('| factor | 지표 | 이전(max_positions=200) | 현재(max_positions=30) | 차이 |')
lines.append('|---|---|---|---|---|')
for sid in ['factor_earnings_yield_v1', 'factor_rv60_v1', 'factor_rev1m_v1']:
    factor_name = sid.replace('factor_', '').replace('_v1', '')
    curr = factor_results[sid]['metrics']
    prev = prev_results[sid]
    lines.append(f'| {factor_name} | Total Return | {prev["total_return"]:.2%} | {curr["total_return"]:.2%} | {curr["total_return"] - prev["total_return"]:.2%} |')
    lines.append(f'| {factor_name} | CAGR | {prev["cagr"]:.2%} | {curr["cagr"]:.2%} | {curr["cagr"] - prev["cagr"]:.2%} |')
    lines.append(f'| {factor_name} | Sharpe | {prev["sharpe"]:.2f} | {curr["sharpe"]:.2f} | {curr["sharpe"] - prev["sharpe"]:.2f} |')
    lines.append(f'| {factor_name} | MDD | {prev["mdd"]:.2%} | {curr["mdd"]:.2%} | {curr["mdd"] - prev["mdd"]:.2%} |')
    lines.append(f'| {factor_name} | Exposure | {prev["exposure"]:.2%} | {curr["exposure"]:.2%} | {curr["exposure"] - prev["exposure"]:.2%} |')
    lines.append(f'| {factor_name} | Trades | {prev["n_trades"]} | {curr["n_trades"]} | {curr["n_trades"] - prev["n_trades"]} |')

lines.append('')
lines.append('## 4. 상세 결과')

for sid, res in factor_results.items():
    m = res['metrics']
    d = res['diag']
    if not m:
        continue
    factor_name = sid.replace('factor_', '').replace('_v1', '')
    grade = 'PASS' if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else 'FAIL'
    lines.append(f'### {factor_name} — {grade}')
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
    lines.append('#### Diagnostics')
    lines.append(f'- Signals: {d["signalCount"]}, Executable: {d["executableTradeCount"]}, Closed: {d["closedPositionCount"]}')
    lines.append(f'- Exit Types: {d["exitTypeCounts"]}')
    lines.append(f'- Max Simultaneous Positions: {d["maxSimultaneousPositionsObserved"]}')
    lines.append('')

lines.append('## 5. EW Benchmark (전체유니버스, max_positions=1500)')
lines.append('')
lines.append(f'- Total Return: {ew_benchmark["total_return"]:.2%}')
lines.append(f'- CAGR: {ew_benchmark["cagr"]:.2%}')
lines.append(f'- Sharpe: {ew_benchmark["sharpe"]:.2f}')
lines.append(f'- MDD: {ew_benchmark["mdd"]:.2%}')
lines.append(f'- Exposure: {ew_benchmark["exposure"]:.2%}')
lines.append(f'- Trades: {ew_benchmark["n_trades"]}')
lines.append(f'- Win Rate: {ew_benchmark["win_rate"]:.2%}')
lines.append(f'- Yearly: {ew_benchmark["yearly_returns"]}')
lines.append('')

lines.append('## 6. 최종 판정')
lines.append('')
lines.append('| factor | grade | 사유 |')
lines.append('|---|---|---|')
for sid in ['factor_earnings_yield_v1', 'factor_rv60_v1', 'factor_rev1m_v1']:
    factor_name = sid.replace('factor_', '').replace('_v1', '')
    m = factor_results[sid]['metrics']
    grade = 'PASS' if (m['cagr'] > 0 and (m['sharpe'] or 0) > 0.3 and m['mdd'] > -0.3) else 'FAIL'
    if factor_name == 'earnings_yield':
        reason = 'CAGR 4.68%, Sharpe 0.76, MDD -9.9% - 벤치마크 대비 초과수익, 위험조정수익 우수'
    elif factor_name == 'rv60':
        reason = 'CAGR 2.33%, Sharpe 0.42, MDD -15.6% - 벤치마크와 유사 CAGR이나 Sharpe 낮음, MDD 큼'
    else:
        reason = 'CAGR -0.88%, Sharpe -0.07, MDD -37.0% - 음의 위험조정수익, 최대낙폭 과대'
    lines.append(f'| {factor_name} | {grade} | {reason} |')

lines.append('')
lines.append('> **Portfolio Backtest 후보**: `earnings_yield` 단독 또는 `earnings_yield` + `rv60_pct` 결합 (추가 검증 필요)')

out_path = os.path.join(REPO_ROOT, 'research', 'strategy-lab', 'findings', 'factor-single-backtest-kr-2026-08.md')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Report: {out_path}')