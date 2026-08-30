# Earnings Yield — Capacity Test (max_positions Scaling)

- 실험: `EARNINGS-YIELD-CAPACITY-TEST-KR-2026-08`
- 대상: `earnings_yield` 단독, max_positions = 20 / 30 / 50 / 100
- 조건: 동일 유니버스/PIT/비용/기간/리밸런싱, 초기자본 1억원, Long-only

## 1. 핵심 성과 비교

| max_positions | CAGR | Sharpe | MDD | Total Return | Max Simultaneous | Exposure (rel to 30) |
|---|---|---|---|---|---|---|
| 20 | 3.84% | 0.75 | -9.62% | 51.40% | 20 | 66.67% |
| 30 | 4.68% | 0.76 | -9.90% | 65.32% | 30 | 100.00% |
| 50 | 4.56% | 0.83 | -9.37% | 63.29% | 50 | 166.67% |
| 100 | 2.91% | 0.71 | -8.32% | 37.11% | 85 | 283.33% |
| EW BM | 2.93% | 0.24 | -11.10% | 37.33% | - | 84.00% |

## 2. 분석

- **Best Sharpe**: max_positions=50 (Sharpe=0.83)
- **Best CAGR**: max_positions=30 (CAGR=4.68%)
- **Best MDD**: max_positions=30 (MDD=-9.90%)

### 용량 효과 분석
- max_positions 20->30: CAGR 3.84%->4.68% (+0.83%), Sharpe 0.75->0.76 (+0.01)
- max_positions 30->50: CAGR 4.68%->4.56% (-0.12%), Sharpe 0.76->0.83 (+0.07)
- max_positions 50->100: CAGR 4.56%->2.91% (-1.65%), Sharpe 0.83->0.71 (-0.12)

### 알파 희석 확인
- max_positions=20: CAGR 차이 -0.83% -> 희석
- max_positions=50: CAGR 차이 -0.12% -> 희석
- max_positions=100: CAGR 차이 -1.77% -> 희석

## 3. 최종 권장 max_positions

> **PASS: max_positions=50** — 분산효과로 Sharpe/MDD 개선, CAGR 미미한 감소(-0.12%p)