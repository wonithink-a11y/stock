# Multi-Factor Composite Backtest — earnings_yield + rv60_pct (2026-08-30)

- 실험: `MULTI-FACTOR-COMPOSITE-KR-2026-08`
- 조건: A1A_ONLY, 월별 리밸런스, 30bps 왕복비용, Equal-Weight, Time-exit only
- 초기자본: 1억원, max_positions=30, equal-weight, long-only
- Core: earnings_yield (Q10, 고EY), 보조: rv60_pct (Q1, 저변동)
- 결합 방식: (1) equal_weight = (z_ey + z_rv60)/2, (2) rank_composite = (rank_ey + rank_-rv60)/2
- 벤치마크: `ew_benchmark_liquid_v1` (전체유니버스 EW, max_positions=1500)

## 1. 성과 요약 비교

| 전략 | CAGR | Sharpe | MDD | Total Return | Exposure | Win Rate | Trades |
|---|---|---|---|---|---|---|---|
| earnings_yield | 4.68% | 0.76 | -9.90% | 65.32% | 100.00% | 50.97% | 567 |
| rv60 | 2.33% | 0.42 | -15.58% | 28.84% | 100.00% | 50.55% | 1094 |
| composite_equal_weight | -7.67% | -0.96 | -58.43% | -58.43% | 100.00% | 31.78% | 1202 |
| composite_rank_composite | 4.33% | 0.79 | -11.80% | 59.36% | 100.00% | 51.04% | 1007 |
| EW Benchmark | 2.93% | 0.24 | -11.10% | 37.33% | 84.00% | 33.67% | 5703 |

## 2. earnings_yield 단독 대비 개선도

### equal_weight vs earnings_yield 단독
- ΔCAGR: -12.35% (-7.67% vs 4.68%)
- ΔSharpe: -1.72 (-0.96 vs 0.76)
- ΔMDD: -48.53% (-58.43% vs -9.90%)
- ΔTotal Return: -123.75%
- ΔWin Rate: -19.19%

### rank_composite vs earnings_yield 단독
- ΔCAGR: -0.35% (4.33% vs 4.68%)
- ΔSharpe: 0.03 (0.79 vs 0.76)
- ΔMDD: -1.90% (-11.80% vs -9.90%)
- ΔTotal Return: -5.97%
- ΔWin Rate: 0.07%

## 3. 연도별 성과 비교

| 연도 | earnings_yield | rv60 | equal_weight | rank_composite | EW BM |
|---|---|---|---|---|---|
| 2016 | 7.42% | 8.14% | -4.46% | 0.72% | -0.40% |
| 2017 | -0.32% | -1.11% | -20.80% | 2.50% | -0.51% |
| 2018 | 0.81% | -1.81% | 0.47% | -0.37% | -1.47% |
| 2019 | 7.78% | -3.52% | -3.46% | 2.56% | -1.39% |
| 2020 | 1.02% | 5.37% | 3.86% | 0.88% | -0.68% |
| 2021 | 31.71% | 17.58% | 1.58% | 23.09% | 0.10% |
| 2022 | 7.15% | -1.90% | -16.49% | 9.19% | -0.38% |
| 2023 | -3.77% | -0.35% | -9.03% | 0.62% | -1.08% |
| 2024 | -4.56% | 2.04% | -4.80% | 2.00% | -2.35% |
| 2025 | 11.49% | 12.61% | -4.52% | 19.30% | -2.12% |
| 2026 | 6.59% | -8.21% | -0.77% | -1.13% | 47.60% |

### 최근 3년 (2024-2026) 누적
- earnings_yield: 13.51%
- rv60: 6.43%
- equal_weight: -10.08%
- rank_composite: 20.17%
- EW BM: 43.13%

## 4. Factor Correlation (Discovery 단계)

- earnings_yield IC t=6.10, slope=0.867
- rv60_pct IC t=-9.59, slope=-0.43
- 두 팩터는 서로 다른 알파 소스 (가치 vs 저변동)
- 월별 spread 상관관계는 별도 계산 필요 (Discovery JSON에 monthly IC series 있음)

## 5. 최종 판정

| 전략 | grade | 사유 |
|---|---|---|
| equal_weight composite | FAIL | CAGR -7.67%, Sharpe -0.96, MDD -58.4% - 단순 평균 결합은 rv60의 노이즈가 earnings_yield 알파를 희석 |
| rank_composite | CONDITIONAL | CAGR 4.33% (단독 -0.35%p), Sharpe 0.79 (+0.03), MDD -11.8% (+1.9%p) - 순위 기반 결합은 소폭 개선이나 유의미한 차이 없음. 거래회전 증가(1007 vs 567) 대비 edge 미미 |
| earnings_yield 단독 | PASS | CAGR 4.68%, Sharpe 0.76, MDD -9.9% - 검증된 Core Value 앵커 |

## 6. 결론

> **equal_weight composite: 폐기** - 단순 가중 평균은 두 팩터의 스케일/노이즈 차이로 알파 훼손
> **rank_composite: 조건부 채택** - 순위 기반은 안정적이나 earnings_yield 단독 대비 유의미한 개선 없음 (ΔCAGR -0.35%p, ΔMDD +1.9%p)
> **추천**: earnings_yield 단독을 Core Value로 유지, rv60_pct는 별도 LowVol 헤지 슬리브로 운용하거나 다팩터 최적화(가중치 튜닝) 후 재검증
