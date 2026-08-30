---
track: crypto
factor: crypto-trend-momentum
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "walk-forward 결과만 기록(판정 없음) - TEST CAGR 4992.5%는 소표본(11 trades) 극단값에 비해 FULL CAGR -4.54%·Sharpe -0.248로 부정적"
cagr: -4.54
sharpe: -0.248
mdd: -41.28
win_rate: 34.15
n: 328
---
# crypto_trend_momentum (D) Walk-Forward Results

**Markets**: KRW-BTC, KRW-ETH, KRW-SOL, KRW-XRP, KRW-ADA, KRW-DOGE, KRW-DOT

**Splits**: TRAIN=2023-12-07~2025-07-25, VALID=2025-07-26~2025-12-22, TEST=2025-12-23~2026-08-28

## Best Parameters (selected on TRAIN)

```json
{
  "trendPeriod": 200,
  "momShortPeriod": 10,
  "momMediumPeriod": 30,
  "maxHoldingSessions": 60
}
```

## Performance Comparison

| Period | CAGR | MDD | Sharpe | WinRate | PF | Trades | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| TRAIN (best) | - | - | - | - | - | - | - |
| VALID | - | - | - | - | - | - | - |
| TEST | 4992.5% | -1.39% | 10.137 | 63.64% | 4.11 | 11 | 1.72 |
| FULL | -4.54% | -41.28% | -0.248 | 34.15% | 0.946 | 328 | 54.01 |

## Annual Returns (FULL period)

| Year | Return |
|---|---:|
| 2025 | -27.17% |
| 2026 | 6.65% |

## TRAIN Grid Results

| Config | Sharpe | CAGR | Trades |
|---|---:|---:|---:|
| {'trendPeriod': 200, 'momShortPeriod': 20, 'momMediumPeriod': 60, 'maxHoldingSessions': 60} | ERROR: 'KRW-ADA' |
| {'trendPeriod': 150, 'momShortPeriod': 20, 'momMediumPeriod': 60, 'maxHoldingSessions': 60} | ERROR: 'KRW-ADA' |
| {'trendPeriod': 200, 'momShortPeriod': 10, 'momMediumPeriod': 30, 'maxHoldingSessions': 60} | -0.153 | -5.75% | 243 |
| {'trendPeriod': 200, 'momShortPeriod': 20, 'momMediumPeriod': 60, 'maxHoldingSessions': 30} | ERROR: 'KRW-ADA' |
