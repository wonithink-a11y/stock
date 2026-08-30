---
track: crypto
factor: crypto-regime-filtered-walkforward
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["donchian20", "atrMult2.0", "volThreshold0.04", "useVolRegimeFilter", "useBtcTrendFilter", "maxHolding60"]
reason: "crypto_regime_filtered 7종목 walk-forward FULL CAGR 12.31%·Sharpe 5.05·PF 2.37 - 그러나 VALID 거래 1건·TEST 15건으로 표본 극히 빈약, 판정 없음"
cagr: 12.31
mdd: -11.73
sharpe: 5.051
win_rate: 58.14
n: 43
---
# crypto_regime_filtered (D) Walk-Forward Results

**Markets**: KRW-BTC, KRW-ETH, KRW-SOL, KRW-XRP, KRW-ADA, KRW-DOGE, KRW-DOT

**Splits**: TRAIN=2023-12-07~2025-07-25, VALID=2025-07-26~2025-12-22, TEST=2025-12-23~2026-08-28

## Best Parameters (selected on TRAIN)

```json
{
  "donchianPeriod": 20,
  "atrMult": 2.0,
  "volThreshold": 0.04,
  "useVolRegimeFilter": true,
  "useBtcTrendFilter": true,
  "maxHoldingSessions": 60
}
```

## Performance Comparison

| Period | CAGR | MDD | Sharpe | WinRate | PF | Trades | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| TRAIN (best) | - | - | - | - | - | - | - |
| VALID | -63.28% | -0.82% | None | None% | None | 1 | 0.14 |
| TEST | 12.46% | -5.29% | 2.606 | 46.67% | 1.647 | 15 | 2.26 |
| FULL | 12.31% | -11.73% | 5.051 | 58.14% | 2.366 | 43 | 8.84 |

## Annual Returns (FULL period)

| Year | Return |
|---|---:|
| 2025 | 11.86% |
| 2026 | -0.2% |

## TRAIN Grid Results

| Config | Sharpe | CAGR | Trades |
|---|---:|---:|---:|
| {'donchianPeriod': 20, 'atrMult': 2.0, 'volThreshold': 0.03, 'useVolRegimeFilter': True, 'useBtcTrendFilter': True, 'maxHoldingSessions': 60} | None | 256.56% | 1 |
| {'donchianPeriod': 20, 'atrMult': 2.5, 'volThreshold': 0.03, 'useVolRegimeFilter': True, 'useBtcTrendFilter': True, 'maxHoldingSessions': 60} | None | 389.63% | 1 |
| {'donchianPeriod': 20, 'atrMult': 2.0, 'volThreshold': 0.04, 'useVolRegimeFilter': True, 'useBtcTrendFilter': True, 'maxHoldingSessions': 60} | 9.506 | 23.03% | 22 |
| {'donchianPeriod': 20, 'atrMult': 2.0, 'volThreshold': 0.03, 'useVolRegimeFilter': True, 'useBtcTrendFilter': False, 'maxHoldingSessions': 60} | None | 256.56% | 1 |
| {'donchianPeriod': 20, 'atrMult': 2.0, 'volThreshold': 0.03, 'useVolRegimeFilter': False, 'useBtcTrendFilter': True, 'maxHoldingSessions': 60} | 2.818 | 42.55% | 99 |
