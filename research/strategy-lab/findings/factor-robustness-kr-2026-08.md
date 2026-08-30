# Factor Robustness Check — KR (2026-08-30)

- 실험: `FACTOR-ROBUSTNESS-KR-2026-08`
- 대상: `earnings_yield`, `rv60_pct`, `rev1m`, `op_margin_trend`, `dv20_log`
- 방법론: 기존 `factor_discovery_kr.py`와 동일 PIT / 월별 리밸런스 / 유동성 게이트 / 1M forward
- 분할: KOSPI/KOSDAQ, 기간별(2016-2020 / 2021-2023 / 2024-현재)
- 비용: 30bps 왕복 적용 후 net spread

## 종합 판정 요약

| factor | grade | overall spread | t | posYR | KOSPI t | KOSDAQ t | sign reversal |
|---|---|---|---|---|---|---|---|
| earnings_yield | PASS | 0.7634% | 2.26 | 0.82 | 1.80 | 2.38 | NO |
| rv60_pct | PASS | -1.5868% | -3.41 | 0.18 | -1.50 | -4.33 | NO |
| rev1m | PASS | -0.9764% | -2.60 | 0.18 | -0.30 | -3.21 | NO |
| op_margin_trend | CONDITIONAL | 0.3752% | 1.81 | 0.80 | 3.07 | 0.68 | NO |
| dv20_log | FAIL | -1.7239% | -3.85 | 0.18 | -1.25 | -5.20 | YES |

## earnings_yield — PASS

- Overall: spread=0.7634%, t=2.26, hit=0.56, posYR=0.82
  net spread=0.4634%, net t=1.37, IC t=6.10
  yearly: {'2016': 0.0012090189590211649, '2017': -0.00142518303549768, '2018': -0.0017970555671267107, '2019': 0.012978614797727613, '2020': 0.0013775432583817062, '2021': 0.009107168309275, '2022': 0.013569669824734206, '2023': 0.0036393736604208916, '2024': 0.0066932975369039275, '2025': 0.012615566015140252, '2026': 0.03637374263216923}

### By Market

- KOSPI: spread=0.7330%, t=1.80, hit=0.52, posYR=0.91, n_months=124
- KOSDAQ: spread=0.8565%, t=2.38, hit=0.63, posYR=0.82, n_months=124

### By Period

- 2016_2020: spread=0.2535%, t=0.57, hit=0.53, posYR=0.60, n_months=57
- 2021_2023: spread=0.8772%, t=1.76, hit=0.58, posYR=1.00, n_months=36
- 2024_now: spread=1.5688%, t=1.73, hit=0.61, posYR=1.00, n_months=31

**Sign reversal (2024-now vs 2021-2023): NO**

## rv60_pct — PASS

- Overall: spread=-1.5868%, t=-3.41, hit=0.35, posYR=0.18
  net spread=-1.8868%, net t=-4.05, IC t=-9.59
  yearly: {'2016': 0.00025404407276630875, '2017': -0.010291212247181386, '2018': -0.01576871736683976, '2019': -0.009814817309622017, '2020': 0.010753168619413361, '2021': -0.02547693478786499, '2022': -0.03391410513854802, '2023': -0.019625298409120032, '2024': -0.023967304596401215, '2025': -0.02604335818679569, '2026': -0.021766501023514986}

### By Market

- KOSPI: spread=-0.7452%, t=-1.50, hit=0.41, posYR=0.36, n_months=126
- KOSDAQ: spread=-1.9640%, t=-4.33, hit=0.31, posYR=0.09, n_months=126

### By Period

- 2016_2020: spread=-0.5062%, t=-0.87, hit=0.44, posYR=0.40, n_months=59
- 2021_2023: spread=-2.6339%, t=-3.50, hit=0.28, posYR=0.00, n_months=36
- 2024_now: spread=-2.4274%, t=-1.96, hit=0.26, posYR=0.00, n_months=31

**Sign reversal (2024-now vs 2021-2023): NO**

## rev1m — PASS

- Overall: spread=-0.9764%, t=-2.60, hit=0.44, posYR=0.18
  net spread=-1.2764%, net t=-3.40, IC t=-4.59
  yearly: {'2016': -0.013057502806244809, '2017': -0.01171440531307955, '2018': -0.0069285000061961475, '2019': -0.024094105386542056, '2020': -0.004407903960094573, '2021': -0.000438719441149012, '2022': -0.027748960502580206, '2023': -0.0031586137670412337, '2024': -0.02058405153170255, '2025': 0.004811071932488998, '2026': 0.005893480725683788}

### By Market

- KOSPI: spread=-0.1290%, t=-0.30, hit=0.48, posYR=0.55, n_months=125
- KOSDAQ: spread=-1.3367%, t=-3.21, hit=0.38, posYR=0.27, n_months=125

### By Period

- 2016_2020: spread=-1.2005%, t=-2.05, hit=0.43, posYR=0.00, n_months=58
- 2021_2023: spread=-1.0449%, t=-1.57, hit=0.42, posYR=0.00, n_months=36
- 2024_now: spread=-0.4775%, t=-0.67, hit=0.48, posYR=0.67, n_months=31

**Sign reversal (2024-now vs 2021-2023): NO**

## op_margin_trend — CONDITIONAL

- Overall: spread=0.3752%, t=1.81, hit=0.55, posYR=0.80
  net spread=0.0752%, net t=0.36, IC t=4.03
  yearly: {'2017': -0.005421058903794627, '2018': 0.007942923075727651, '2019': 0.0031066280521847636, '2020': -0.004001166871451887, '2021': 0.0005812013114952363, '2022': 0.0007058430197222938, '2023': 0.0067100223515334035, '2024': 0.012510153423934666, '2025': 0.006144080124337215, '2026': 0.009235528583467439}

### By Market

- KOSPI: spread=1.0123%, t=3.07, hit=0.61, posYR=0.80, n_months=112
- KOSDAQ: spread=0.1817%, t=0.68, hit=0.52, posYR=0.60, n_months=112

### By Period

- 2016_2020: spread=0.0795%, t=0.22, hit=0.56, posYR=0.50, n_months=45
- 2021_2023: spread=0.2666%, t=0.76, hit=0.44, posYR=1.00, n_months=36
- 2024_now: spread=0.9306%, t=2.71, hit=0.68, posYR=1.00, n_months=31

**Sign reversal (2024-now vs 2021-2023): NO**

## dv20_log — FAIL

- Overall: spread=-1.7239%, t=-3.85, hit=0.32, posYR=0.18
  net spread=-2.0239%, net t=-4.53, IC t=-8.34
  yearly: {'2016': -0.036113571775829696, '2017': -0.001954608944098667, '2018': -0.02440406968848073, '2019': -0.029446609378691774, '2020': -0.00397857236374637, '2021': -0.0437667945175203, '2022': -0.03638796176664757, '2023': -0.01485949115604942, '2024': -0.009257490737126655, '2025': 0.0038334412508501114, '2026': 0.021109502598748102}

### By Market

- KOSPI: spread=-0.6134%, t=-1.25, hit=0.44, posYR=0.36, n_months=126
- KOSDAQ: spread=-2.7216%, t=-5.20, hit=0.25, posYR=0.00, n_months=126

### By Period

- 2016_2020: spread=-1.8892%, t=-3.54, hit=0.31, posYR=0.00, n_months=59
- 2021_2023: spread=-3.1671%, t=-4.44, hit=0.22, posYR=0.00, n_months=36
- 2024_now: spread=0.2667%, t=0.22, hit=0.45, posYR=0.67, n_months=31

**Sign reversal (2024-now vs 2021-2023): YES**

## 최종 Portfolio Backtest 후보

**PASS (즉시 후보)**: earnings_yield, rv60_pct, rev1m
**CONDITIONAL (추가 검증 후)**: op_margin_trend

### 추천 구성
- **Core Value**: `earnings_yield` (양시장 안정, 비용 후에도 net spread 양호)
- **LowVol Hedge**: `rv60_pct` (고변동 숏, KOSDAQ 편중)

> 이 조합으로 Long-only / Long-Short 포트폴리오 백테스트 진행 권장