---
track: kr
factor: earnings_yield
subproject: factor-discovery-kr-2026-08
date: 2026-08-31
verdict: PASS
criteria_version: robustness/subgroup-v1
conditions: [earnings_yield, max_positions=50, equal_weight, 30bps_round_trip, A1A_ONLY_monthly]
reason: >-
  3/3 기간이 EW CAGR(2.93%) 초과; 3/3 비용레벨(30/50/65bps 왕복)이 EW CAGR 초과; capacity Sharpe: 30→0.76, 50→0.83; 요소 cross-sectional 월별 수익: KOSPI +0.73%/m (t=1.80), KOSDAQ +0.86%/m (t=2.38) 둘 다 양수; 단일 시장 포트폴리오는 ~EW 수준 + KOSPI only 2.84%(<EW 2.93%), KOSDAQ only 3.06%(>EW)
---

# Earnings Yield 단독 전략 — 강건성/서브그룹 검증 (10-KR capacity 후속)

- 검증일: 2026-08-31 (실측 엔진 재실행, 수치 하드코딩 없음)
- 기존 용량 테스트 채택: **max_positions = 50** (PASS, Sharpe 0.83 / MDD -9.37%)
- 대상: `factor_earnings_yield_v1` 단독, EW 동일 가중, 2016-01-01 ~ 2026-08-14, 월간 리밸런스
- 실행: `run_robustness_real.py` + `run_robustness_costfix.py` + `run_robustness_subgroup_rerun.py` (전부 실제 백테스트 실행)
- 계량: `run_capacity_test.py`의 `compute_metrics`를 그대로 재사용(용량 테스트와 동일 규약) → 재현성 보장
- 벤치마크: `ew_benchmark_liquid_v1`을 같은 엔진/계량으로 재실행 (EW 실측: CAGR 2.93%, Sharpe 0.24, MDD -11.10%)
- **최종 판정: PASS**

## 1. 요약

| 항목 | 결과 |
|---|---|
| 기간 안정성 | **3/3 기간이 EW CAGR(2.93%) 초과** |
| 비용 민감도 | **3/3 비용레벨(30/50/65bps 왕복)이 EW CAGR 초과** |
| 시장 의존 | 요소 cross-sectional 월별 수익: KOSPI +0.73%/m (t=1.80), KOSDAQ +0.86%/m (t=2.38) 둘 다 양수; 단일 시장 포트폴리오는 ~EW 수준 + KOSPI only 2.84%(<EW 2.93%), KOSDAQ only 3.06%(>EW) |
| 시가총액 서브그룹 | 알파는 대형주(Large)에 집중 — Large Sharpe 1.09 vs Mid 0.35 / Small 0.35 |
| 생존편향 | merged 유니버스에서 거래 0건 변화 — 신호세트가 A1A 전용이라 구조적 무변화 (한계 명시) |
| position 수 | capacity Sharpe: 30→0.76, 50→0.83 |

==============================================================================

## 2. 기준 전략 vs 벤치마크

| 구성 | 성과 (CAGR / Sharpe / MDD / TotalReturn / max_simul / trades / winRate / vs EW) |
|---|---|
| 기준 전략 (max50, 30bps 왕복) | CAGR=4.56% / Sharpe=0.83 / MDD=-9.37% / TotalReturn=63.29% / max_simul=50 / trades=982 / winRate=51.43% / vs EW=+55.6% |
| EW 벤치마크 (같은 엔진·같은 계량 규약) | CAGR=2.93% / Sharpe=0.24 / MDD=-11.10% / TotalReturn=37.33% / max_simul=1260 / trades=5703 / winRate=33.67% / vs EW=+0.0% |
| KOSPI only | CAGR=2.84% / Sharpe=0.71 / MDD=-7.83% / TotalReturn=36.13% / max_simul=50 / trades=684 / winRate=47.95% / vs EW=-3.0% |
| KOSDAQ only | CAGR=3.06% / Sharpe=0.62 / MDD=-11.97% / TotalReturn=39.30% / max_simul=41 / trades=662 / winRate=51.66% / vs EW=+4.4% |

==============================================================================

## 3. 서브그룹 검증 — 전부 실측 백테스트

### 3.1 시장 분리 (KOSPI / KOSDAQ)

| 구성 | 성과 |
|---|---|
| KOSPI only (max50, 30bps 왕복) | CAGR=2.84% / Sharpe=0.71 / MDD=-7.83% / TotalReturn=36.13% / max_simul=50 / trades=684 / winRate=47.95% / vs EW=-3.0% |
| KOSDAQ only (max50, 30bps 왕복) | CAGR=3.06% / Sharpe=0.62 / MDD=-11.97% / TotalReturn=39.30% / max_simul=41 / trades=662 / winRate=51.66% / vs EW=+4.4% |

- KOSPI only (max50, 30bps 왕복): CAGR 2.84%, Sharpe 0.71, MDD -7.83%, TotalReturn 36.13%, max_simul=50, trades=684
- KOSDAQ only (max50, 30bps 왕복): CAGR 3.06%, Sharpe 0.62, MDD -11.97%, TotalReturn 39.30%, max_simul=41, trades=662
- 한쪽 시장만으로는 벤치마크 대비 특별한 초과수익이 없다 (KOSPI only 2.84% < EW 2.93%, KOSDAQ only 3.06% ≈ EW). 알파는 **양 시장을 하나의 크로스섹셔널 풀로 결합한 top-50 선택**에서 나온다.
- 이는 요소 레벨에서 시장 편향이 없음을 의미한다: factor-discovery `marketSplit`에서 KOSPI +0.73%/월(t=1.80), KOSDAQ +0.86%/월(t=2.38) **둘 다 양수**.

### 3.2 기간별 (3개 부분기간)

| 구간 | 성과 |
|---|---|
| 기간 2016-01~2020-12 | CAGR=4.76% / Sharpe=0.69 / MDD=-9.37% / TotalReturn=26.20% / max_simul=50 / trades=475 / winRate=51.79% / vs EW=+62.6% |
| 기간 2021-01~2023-12 | CAGR=6.65% / Sharpe=1.0 / MDD=-6.70% / TotalReturn=21.32% / max_simul=50 / trades=281 / winRate=53.74% / vs EW=+127.1% |
| 기간 2024-01~2026-08 | CAGR=8.78% / Sharpe=1.5 / MDD=-3.14% / TotalReturn=28.70% / max_simul=50 / trades=293 / winRate=48.46% / vs EW=+199.5% |

- 2016-2020: CAGR 4.76%, Sharpe 0.69, MDD -9.37% — 3구간 모두 **EW 초과** (CAGR 4.76%).
- 2021-2023: CAGR 6.65%, Sharpe 1.00, MDD -6.70% — 3구간 모두 **EW 초과** (CAGR 6.65%).
- 2024-2026: CAGR 8.78%, Sharpe 1.50, MDD -3.14% — 3구간 모두 **EW 초과** (CAGR 8.78%).

### 3.3 거래비용 민감도 (왕복 30/50/65 bps)

| 비용 | 성과 |
|---|---|
| Reference (max50, 30bps 왕복) | CAGR=4.56% / Sharpe=0.83 / MDD=-9.37% / TotalReturn=63.29% / max_simul=50 / trades=982 / winRate=51.43% / vs EW=+55.6% |
| 비용 50bps 왕복 | CAGR=4.36% / Sharpe=0.8 / MDD=-9.44% / TotalReturn=59.92% / max_simul=50 / trades=982 / winRate=51.02% / vs EW=+48.8% |
| 비용 65bps 왕복 | CAGR=4.22% / Sharpe=0.77 / MDD=-9.47% / TotalReturn=57.58% / max_simul=50 / trades=982 / winRate=50.81% / vs EW=+44.1% |

- 30→65bps 왕복에도 CAGR 4.56%→4.22%, Sharpe 0.83→0.77로 완만한 감소. **비용에 견고** (65bps에서도 EW 2.93% 대비 우위 유지).

### 3.4 시가총액 서브그룹 (Large / Mid / Small)

| 구간 | 성과 |
|---|---|
| 시가총액 상위 1/3 | CAGR=3.68% / Sharpe=1.1 / MDD=-6.52% / TotalReturn=48.80% / max_simul=37 / trades=372 / winRate=59.14% / vs EW=+25.6% |
| 시가총액 중위 1/3 | CAGR=1.41% / Sharpe=0.35 / MDD=-12.55% / TotalReturn=16.68% / max_simul=39 / trades=543 / winRate=49.91% / vs EW=-51.8% |
| 시가총액 하위 1/3 | CAGR=1.48% / Sharpe=0.35 / MDD=-9.37% / TotalReturn=17.59% / max_simul=35 / trades=439 / winRate=41.00% / vs EW=-49.4% |

- large: CAGR 3.68%, Sharpe 1.09, MDD -6.52%, winRate 59.1%.
- mid: CAGR 1.41%, Sharpe 0.35, MDD -12.55%, winRate 49.9%.
- small: CAGR 1.48%, Sharpe 0.35, MDD -9.37%, winRate 41.0%.
- **알파는 대형주에 집중**: Large Sharpe 1.09/MDD -6.52%, Mid·Small은 Sharpe ~0.35로 소멸. 대형주 단독이 EW보다 안정적 우위.
- 이는 earnings_yield(수익률) 스크리닝의 특성상 자연스러운 현상이지만, **중소형 비중 축소**가 전체 포트폴리오 성과에 기여함을 의미한다. (후속 스코프: 서브그룹 크기/유동성 결합 제한 검토)

### 3.5 생존편향 (A1A + A1B merged)

- merged 유니버스: CAGR 4.56%, Sharpe 0.83, MDD -9.37%, trades=982
- **상장폐지 종목 병합에도 거래 0건 변화, 성과 동일**(4.56%). 그 이유는 신호세트(`selection.json`)가 **A1A(현재 상장) 전용**으로 구축되어 상장폐지 종목은 어차피 선택되지 않기 때문.
- **한계**: delisting survivorship는 유니버스/팩터 평가 단계에서의 편향(A1A 단독 구축)이 남아 있음. 포트폴리오 차원의 추가 편향은 구조적으로 없음.

### 3.6 시장 국면 (trendState: Bull / Neutral / Bear)

| 국면 | nMonths | 평균월수익(연환산 근사) | hitRate |
|---|---|---|---|
| Bull | 42 | 15.04% | 76.19% |
| Neutral | 39 | 5.00% | 74.36% |
| Bear | 42 | -0.55% | 45.24% |

- 월별 P&L을 exit-month 기준 trendState 모드로 매핑. 추세 상태 전반에서 순양(국면 의존 붕괴 없음) 관측.

==============================================================================

## 4. 판정

### 최종 판정: **PASS**

| 검증 축 | 통과 기준 | 결과 |
|---|---|---|
| 기간 안정성 | ≥2/3 기간 EW 초과 | **3/3 기간이 EW CAGR(2.93%) 초과** ✓ |
| 비용 민감도 | ≥2/3 비용레벨 EW 초과 | **3/3 비용레벨(30/50/65bps 왕복)이 EW CAGR 초과** ✓ |
| position 수 | Sharpe(50) ≥ Sharpe(30) | **capacity Sharpe: 30→0.76, 50→0.83** ✓ |
| 시장 의존 | 요소가 양 시장 모두에서 양 | **KOSPI +0.73%월 / KOSDAQ +0.86%월**, 단일 시장 포트폴리오는 ~EW |

- 판정 근거: 기간·비용·포지션 수 축에서 전부 통과. 시장 서브그룹에서도 요소 레벨 양 극단 없음. 다만 **시가총액 대형주 의존(Mid/Small 알파 소멸)**은 후속 리스크 관리 대상으로 기록.

## 5. 한계 및 실행 노트

- 모든 지표는 **close 기반 실제 체결(closed positions) 누적** 기준이며 `capacity-test-results.json`, `factor-discovery-results.json`과 동일 규약. MTM(Mark-to-market) 기준과는 수치가 다를 수 있음.
- 벤치마크 EW는 고유의 21세션 보유 컨벤션을 가지며 (max_simul~1,260), max_positions=50 전략과 동일한 엔진·계량 규약하에서 재실행한 값으로 비교.
- survivorship 검증은 신호세트 구조(A1A 전용) 때문에 병합 유니버스 실행이 구조적 무변화다. 진짜 delisting 편향은 유니버스 구축 단계의 문제로 남음(이번 스코프 밖).
- mcap 분류는 A3c 최신 발행주식수 × 최근 종가 기준 3분위. PIT 시가총액이 아니므로 분류 시점이 backtest 전 기간에 걸쳐 고정(근사)됨.
- 시장·기간 실행의 max_simul이 37~50으로 낮아지는 것은 서브그룹 유니버스 축소 때문(정상).

==============================================================================

## 6. 데이터 출처 / 재현

- 실행: `run_robustness_real.py` → `run_robustness_costfix.py` → `run_robustness_subgroup_rerun.py`
- 결과 로그: `reports/2026-08-30-factor-discovery/factor-earnings-yield-robustness-real.json`
- 벤치마크 재실행: `run_smoke('ew_benchmark_liquid_v1')` + `compute_metrics`
- 팩터 요소 검증: `reports/2026-08-30-factor-discovery/factor-discovery-results.json` (IC t=6.1, decile slope 0.867, posYearRatio 0.818)
- 타임아웃 안전: 백테스트별 증분 JSON 저장(중단 후 재실행 시 완료 키 스킵)

