---
track: crypto
factor: crypto-donchian-atr-d
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "Donchian+ATR walk-forward OOS 결과 - VALID -48.91%·TEST -9.53%·Sharpe -2.387로 OOS 일반화 실패 - 결과 보고, 명시 판정 없음"
cagr: -9.53
mdd: -9.18
sharpe: -2.387
win_rate: 26.67
n: 15
---

# crypto_donchian_atr (D) Walk-Forward Results

**Markets**: KRW-BTC, KRW-ETH, KRW-SOL, KRW-XRP, KRW-ADA, KRW-DOGE, KRW-DOT

**Splits**: TRAIN=2023-12-07~2025-07-25, VALID=2025-07-26~2025-12-22, TEST=2025-12-23~2026-08-28

## Best Parameters (selected on TRAIN)

```json
{
  "donchianPeriod": 40,
  "atrMult": 2.0,
  "maxHoldingSessions": 60
}
```

## Performance Comparison

| Period | CAGR | MDD | Sharpe | WinRate | PF | Trades | Turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| TRAIN (best) | - | - | - | - | - | - | - |
| VALID | -48.91% | -5.19% | -8.755 | None% | None | 4 | 0.67 |
| TEST | -9.53% | -9.18% | -2.387 | 26.67% | 0.631 | 15 | 2.38 |
| FULL | 20.73% | -20.18% | 2.452 | 47.71% | 1.47 | 109 | 25.4 |

## Annual Returns (FULL period)

| Year | Return |
|---|---:|
| 2025 | 3.71% |
| 2026 | -6.01% |

## TRAIN Grid Results

| Config | Sharpe | CAGR | Trades |
|---|---:|---:|---:|
| {'donchianPeriod': 20, 'atrMult': 2.0, 'maxHoldingSessions': 60} | 2.626 | 39.69% | 105 |
| {'donchianPeriod': 20, 'atrMult': 2.5, 'maxHoldingSessions': 60} | 2.007 | 27.02% | 85 |
| {'donchianPeriod': 20, 'atrMult': 3.0, 'maxHoldingSessions': 60} | 1.086 | 11.77% | 74 |
| {'donchianPeriod': 30, 'atrMult': 2.0, 'maxHoldingSessions': 60} | 2.853 | 38.2% | 91 |
| {'donchianPeriod': 30, 'atrMult': 2.5, 'maxHoldingSessions': 60} | 2.162 | 26.56% | 75 |
| {'donchianPeriod': 40, 'atrMult': 2.0, 'maxHoldingSessions': 60} | 3.666 | 50.72% | 83 |
