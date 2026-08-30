# Factor Single-Factor Backtest — KR (2026-08-30)

- 실험: `FACTOR-SINGLE-BACKTEST-KR-2026-08`
- 대상: `earnings_yield` (Q10), `rv60_pct` (Q1), `rev1m` (Q1)
- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only
- 벤치마크: `ew_benchmark_liquid_v1` (동일 유니버스/비용/캘린더)

## 결과 요약

| factor | grade | Total Return | CAGR | Sharpe | MDD | Exposure | Win Rate | Trades |
|---|---|---|---|---|---|---|---|---|
| earnings_yield | PASS | 65.32% | 4.68% | 0.76 | -9.90% | 100.00% | 50.97% | 567 |
| rv60 | PASS | 28.84% | 2.33% | 0.42 | -15.58% | 100.00% | 50.55% | 1094 |
| rev1m | FAIL | -9.22% | -0.88% | -0.07 | -36.97% | 100.00% | 45.11% | 3252 |
| composite_ey_rv60_equal_weight | FAIL | -58.43% | -7.67% | -0.96 | -58.43% | 100.00% | 31.78% | 1202 |
| composite_ey_rv60_rank_composite | PASS | 59.36% | 4.33% | 0.79 | -11.80% | 100.00% | 51.04% | 1007 |

## earnings_yield — PASS

- Total Return: 65.32%
- CAGR: 4.68%
- Sharpe: 0.76
- MDD: -9.90%
- Exposure: 100.00%
- Win Rate: 50.97%
- Trades: 567
- Total Cost (bps): 0.0
- Yearly Returns: {'2016': 0.07416867377500003, '2017': -0.003164396875, '2018': 0.008136810259999992, '2019': 0.07780490136999996, '2020': 0.010243633035000008, '2021': 0.31713707104499994, '2022': 0.071524395845, '2023': -0.03773729785499996, '2024': -0.045639309970000035, '2025': 0.11485443892500004, '2026': 0.065875227185}

### Diagnostics
- Signals: 8350, Executable: 8270, Closed: 567
- Exit Types: {'TIME_EXIT': 8270}
- Max Simultaneous Positions: 30

## rv60 — PASS

- Total Return: 28.84%
- CAGR: 2.33%
- Sharpe: 0.42
- MDD: -15.58%
- Exposure: 100.00%
- Win Rate: 50.55%
- Trades: 1094
- Total Cost (bps): 0.0
- Yearly Returns: {'2016': 0.08136663682500005, '2017': -0.011072161969999965, '2018': -0.01806879667499999, '2019': -0.03521633426, '2020': 0.05372142911500001, '2021': 0.17582851547000006, '2022': -0.018962223079999993, '2023': -0.003479803314999987, '2024': 0.020409526900000002, '2025': 0.12605137882499998, '2026': -0.08214467596000002}

### Diagnostics
- Signals: 23378, Executable: 23164, Closed: 1094
- Exit Types: {'TIME_EXIT': 23164}
- Max Simultaneous Positions: 30

## rev1m — FAIL

- Total Return: -9.22%
- CAGR: -0.88%
- Sharpe: -0.07
- MDD: -36.97%
- Exposure: 100.00%
- Win Rate: 45.11%
- Trades: 3252
- Total Cost (bps): 0.0
- Yearly Returns: {'2016': -0.00034431412499997535, '2017': 0.03331685105499995, '2018': -0.024567444530000017, '2019': 0.07088342947999993, '2020': 0.17752826523499993, '2021': 0.03714086228500001, '2022': -0.045933427849999965, '2023': -0.13241038688500006, '2024': -0.13574949750499996, '2025': 0.02988772832499994, '2026': -0.10198837890999993}

### Diagnostics
- Signals: 23225, Executable: 23008, Closed: 3252
- Exit Types: {'TIME_EXIT': 23008}
- Max Simultaneous Positions: 30

## composite_ey_rv60_equal_weight — FAIL

- Total Return: -58.43%
- CAGR: -7.67%
- Sharpe: -0.96
- MDD: -58.43%
- Exposure: 100.00%
- Win Rate: 31.78%
- Trades: 1202
- Total Cost (bps): 0.0
- Yearly Returns: {'2016': -0.044617142195000035, '2017': -0.20804793636499996, '2018': 0.004666769435000012, '2019': -0.034594880215000005, '2020': 0.03861054063999998, '2021': 0.015761309950000017, '2022': -0.16492410302500002, '2023': -0.09033531500000004, '2024': -0.047961075719999975, '2025': -0.04515189731499998, '2026': -0.007713392064999995}

### Diagnostics
- Signals: 8350, Executable: 8268, Closed: 1202
- Exit Types: {'TIME_EXIT': 8268}
- Max Simultaneous Positions: 30

## composite_ey_rv60_rank_composite — PASS

- Total Return: 59.36%
- CAGR: 4.33%
- Sharpe: 0.79
- MDD: -11.80%
- Exposure: 100.00%
- Win Rate: 51.04%
- Trades: 1007
- Total Cost (bps): 0.0
- Yearly Returns: {'2016': 0.007219785455000007, '2017': 0.02496460798999999, '2018': -0.0037111461350000136, '2019': 0.02555709342000002, '2020': 0.008768003459999996, '2021': 0.2308981495899999, '2022': 0.09194501092500001, '2023': 0.006206472185000011, '2024': 0.02004713964000002, '2025': 0.19300163740500015, '2026': -0.011346190640000035}

### Diagnostics
- Signals: 8350, Executable: 8271, Closed: 1007
- Exit Types: {'TIME_EXIT': 8271}
- Max Simultaneous Positions: 30
