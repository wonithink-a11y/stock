import json
import os

with open('research/strategy-lab/reports/2026-08-30-factor-discovery/factor-single-backtest-results.json', encoding='utf-8') as f:
    results = json.load(f)

# EW Benchmark results (from earlier run)
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

REPO_ROOT = 'C:/Users/User/projects/stock'

lines = []
lines.append('# Multi-Factor Composite Backtest — earnings_yield + rv60_pct (2026-08-30)')
lines.append('')
lines.append('- 실험: `MULTI-FACTOR-COMPOSITE-KR-2026-08`')
lines.append('- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only')
lines.append('- 초기자본: 1억원, max_positions=30, equal-weight, long-only')
lines.append('- Core: earnings_yield (Q10, 고EY), 보조: rv60_pct (Q1, 저변동)')
lines.append('- 결합 방식: (1) equal_weight = (z_ey + z_rv60)/2, (2) rank_composite = (rank_ey + rank_-rv60)/2')
lines.append('- 벤치마크: `ew_benchmark_liquid_v1` (전체유니버스 EW, max_positions=1500)')
lines.append('')

lines.append('## 1. 성과 요약 비교')
lines.append('')
lines.append('| 전략 | CAGR | Sharpe | MDD | Total Return | Exposure | Win Rate | Trades |')
lines.append('|---|---|---|---|---|---|---|---|')

for sid in ['factor_earnings_yield_v1', 'factor_rv60_v1', 'composite_ey_rv60_equal_weight', 'composite_ey_rv60_rank_composite']:
    m = results[sid]['metrics']
    name = sid.replace('factor_', '').replace('_v1', '').replace('composite_ey_rv60_', 'composite_')
    sharpe_str = f'{m["sharpe"]:.2f}' if m['sharpe'] is not None else 'N/A'
    lines.append(f'| {name} | {m["cagr"]:.2%} | {sharpe_str} | {m["mdd"]:.2%} | {m["total_return"]:.2%} | {m["exposure"]:.2%} | {m["win_rate"]:.2%} | {m["n_trades"]} |')

# Add EW benchmark
lines.append(f'| EW Benchmark | {ew_benchmark["cagr"]:.2%} | {ew_benchmark["sharpe"]:.2f} | {ew_benchmark["mdd"]:.2%} | {ew_benchmark["total_return"]:.2%} | {ew_benchmark["exposure"]:.2%} | {ew_benchmark["win_rate"]:.2%} | {ew_benchmark["n_trades"]} |')

lines.append('')

lines.append('## 2. earnings_yield 단독 대비 개선도')
lines.append('')
ey = results['factor_earnings_yield_v1']['metrics']
for sid in ['composite_ey_rv60_equal_weight', 'composite_ey_rv60_rank_composite']:
    m = results[sid]['metrics']
    name = sid.replace('composite_ey_rv60_', '')
    lines.append(f'### {name} vs earnings_yield 단독')
    lines.append(f'- ΔCAGR: {m["cagr"] - ey["cagr"]:.2%} ({m["cagr"]:.2%} vs {ey["cagr"]:.2%})')
    lines.append(f'- ΔSharpe: {m["sharpe"] - ey["sharpe"]:.2f} ({m["sharpe"]:.2f} vs {ey["sharpe"]:.2f})')
    lines.append(f'- ΔMDD: {m["mdd"] - ey["mdd"]:.2%} ({m["mdd"]:.2%} vs {ey["mdd"]:.2%})')
    lines.append(f'- ΔTotal Return: {m["total_return"] - ey["total_return"]:.2%}')
    lines.append(f'- ΔWin Rate: {m["win_rate"] - ey["win_rate"]:.2%}')
    lines.append('')

lines.append('## 3. 연도별 성과 비교')
lines.append('')
lines.append('| 연도 | earnings_yield | rv60 | equal_weight | rank_composite | EW BM |')
lines.append('|---|---|---|---|---|---|')
years = ['2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026']
for yr in years:
    ey_r = results['factor_earnings_yield_v1']['metrics']['yearly_returns'].get(yr, 0)
    rv_r = results['factor_rv60_v1']['metrics']['yearly_returns'].get(yr, 0)
    ew_r = results['composite_ey_rv60_equal_weight']['metrics']['yearly_returns'].get(yr, 0)
    rc_r = results['composite_ey_rv60_rank_composite']['metrics']['yearly_returns'].get(yr, 0)
    bm_r = ew_benchmark['yearly_returns'].get(yr, 0)
    lines.append(f'| {yr} | {ey_r:.2%} | {rv_r:.2%} | {ew_r:.2%} | {rc_r:.2%} | {bm_r:.2%} |')

lines.append('')

# Recent 3 years
lines.append('### 최근 3년 (2024-2026) 누적')
recent_ey = sum(results['factor_earnings_yield_v1']['metrics']['yearly_returns'].get(y, 0) for y in ['2024','2025','2026'])
recent_rv = sum(results['factor_rv60_v1']['metrics']['yearly_returns'].get(y, 0) for y in ['2024','2025','2026'])
recent_ew = sum(results['composite_ey_rv60_equal_weight']['metrics']['yearly_returns'].get(y, 0) for y in ['2024','2025','2026'])
recent_rc = sum(results['composite_ey_rv60_rank_composite']['metrics']['yearly_returns'].get(y, 0) for y in ['2024','2025','2026'])
recent_bm = sum(ew_benchmark['yearly_returns'].get(y, 0) for y in ['2024','2025','2026'])
lines.append(f'- earnings_yield: {recent_ey:.2%}')
lines.append(f'- rv60: {recent_rv:.2%}')
lines.append(f'- equal_weight: {recent_ew:.2%}')
lines.append(f'- rank_composite: {recent_rc:.2%}')
lines.append(f'- EW BM: {recent_bm:.2%}')
lines.append('')

lines.append('## 4. Factor Correlation (Discovery 단계)')
lines.append('')
lines.append('- earnings_yield IC t=6.10, slope=0.867')
lines.append('- rv60_pct IC t=-9.59, slope=-0.43')
lines.append('- 두 팩터는 서로 다른 알파 소스 (가치 vs 저변동)')
lines.append('- 월별 spread 상관관계는 별도 계산 필요 (Discovery JSON에 monthly IC series 있음)')
lines.append('')

lines.append('## 5. 최종 판정')
lines.append('')
lines.append('| 전략 | grade | 사유 |')
lines.append('|---|---|---|')

# equal_weight
ew_m = results['composite_ey_rv60_equal_weight']['metrics']
ew_grade = 'FAIL'
ew_reason = f'CAGR -7.67%, Sharpe -0.96, MDD -58.4% - 단순 평균 결합은 rv60의 노이즈가 earnings_yield 알파를 희석'
lines.append(f'| equal_weight composite | {ew_grade} | {ew_reason} |')

# rank_composite
rc_m = results['composite_ey_rv60_rank_composite']['metrics']
rc_grade = 'CONDITIONAL'
rc_reason = f'CAGR 4.33% (단독 -0.35%p), Sharpe 0.79 (+0.03), MDD -11.8% (+1.9%p) - 순위 기반 결합은 소폭 개선이나 유의미한 차이 없음. 거래회전 증가(1007 vs 567) 대비 edge 미미'
lines.append(f'| rank_composite | {rc_grade} | {rc_reason} |')

# earnings_yield single
ey_grade = 'PASS'
ey_reason = 'CAGR 4.68%, Sharpe 0.76, MDD -9.9% - 검증된 Core Value 앵커'
lines.append(f'| earnings_yield 단독 | {ey_grade} | {ey_reason} |')

lines.append('')
lines.append('## 6. 결론')
lines.append('')
lines.append('> **equal_weight composite: 폐기** - 단순 가중 평균은 두 팩터의 스케일/노이즈 차이로 알파 훼손')
lines.append('> **rank_composite: 조건부 채택** - 순위 기반은 안정적이나 earnings_yield 단독 대비 유의미한 개선 없음 (ΔCAGR -0.35%p, ΔMDD +1.9%p)')
lines.append('> **추천**: earnings_yield 단독을 Core Value로 유지, rv60_pct는 별도 LowVol 헤지 슬리브로 운용하거나 다팩터 최적화(가중치 튜닝) 후 재검증')
lines.append('')

out_path = os.path.join(REPO_ROOT, 'research', 'strategy-lab', 'findings', 'factor-composite-verification-2026-08.md')
with open(out_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Report: {out_path}')