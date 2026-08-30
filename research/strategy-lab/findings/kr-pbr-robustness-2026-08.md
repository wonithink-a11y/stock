---
track: kr
factor: kr-pbr-robustness
date: 2026-08-29
verdict: REJECT
criteria_version: backfill-v1
conditions: ["low_pbr", "pit_monthly", "30bps_cost"]
reason: "IC는 3기간 유의 음수이나 TEST +13.2%가 최저 10% PBR 꼬리 하나에만 의존(trim 시 +1.5%), 단조성 미확보(Q3 스파이크·Q5 반등) - 구성·기간 특이적, PASS 유지 불가"
cagr: 13.2
sharpe: 0.76
---
# PBR Robustness — 저PBR factor 자체 (10-KR-16)

- 검증일: 2026-08-29
- 스크립트: `kr_pbr_robustness.py`
- 데이터: A4 `a4-research-dataset.parquet` + `valuation-panel.jsonl`(PBR, PIT)
- 고정: 저PBR long, PIT-safe, 월간 rebalance, 동일 universe, 동일 비용(30bps/side), **LOWMOM60 비결합**
- 비교: 기존 top-30 / 분위수(Q1~Q5) / 연속 rank long-only / 극저분위 제거(trim)
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **최종 판정: REJECT (10-KR-14의 PASS 유지 불가 — 구성 의존·비단조·극단값 의존)**

## 1. factor-level IC / Q5-Q1 (liquid universe, 월간)

| horizon | TRAIN | VALID | TEST |
|---|---|---|---|
| 20D IC (t) | -0.070 (-5.0) | -0.051 (-2.2) | -0.105 (-4.1) |
| 60D IC (t) | -0.100 (-6.0) | -0.087 (-3.7) | -0.125 (-5.6) |
| 120D IC (t) | -0.126 (-6.7) | -0.083 (-4.3) | -0.153 (-8.4) |
| 20D Q5-Q1 | -0.0116 | +0.0004 | -0.0101 |
| 120D Q5-Q1 | -0.0575 | +0.0146 | -0.0180 |

- **IC는 3기간 모두 유의한 음수** — "저PBR → 고수익"의 거친 방향 신호 자체는 존재.
- 그러나 **Q5-Q1 spread는 VALID에서 양(+0.0146 @120D)으로 뒤집히고**, TEST에서도 크기(-0.018 @120D)가 작음. IC(rank)와 달리 분위수 spread가 안정적이지 않음.

## 2. 분위수별 net CAGR — 단조성 검증

| | Q1(최저PBR) | Q2 | Q3 | Q4 | Q5(최고PBR) |
|---|---|---|---|---|---|
| TRAIN | +7.0% | +4.6% | **+11.2%** | -0.6% | -5.8% |
| VALID | +5.1% | -1.0% | +1.5% | -5.3% | **-0.6%(=Q5 반등)** |
| TEST | **+5.8%** | +0.8% | -5.1% | -7.4% | -4.5%(=Q5 반등) |

- **단조 아님.** Q1이 전반적으로 좋지만:
  - TRAIN에서 **Q3(+11.2%)가 Q1(+7.0%)보다 높아 중간 밴드가 최고**.
  - VALID·TEST에서 **Q5가 Q4보다 높아(반등) 최저가 최고PBR 밴드가 아니게 됨**.
- 3기간 모두 "Q5 vs Q1"의 거친 방향만 유지되고, 중간 분위수 순서는 불안정.

## 3. 포트폴리오 구성별 성과 (net CAGR / Sharpe)

| 구성 | TRAIN | VALID | TEST |
|---|---|---|---|
| 기존 top-30 | +3.8% (Sh .28) | +7.8% (Sh .43) | **+13.2% (Sh .76)** |
| 연속 rank long-only (전체 liquid, w~1-rank) | +5.5% (Sh .35) | +1.3% (Sh .16) | **+0.2% (Sh .10)** |
| top-30에서 최저 10% PBR 제거(trim) | **+11.8% (Sh .60)** | -0.2% (Sh .10) | **+1.5% (Sh .17)** |

### 관찰 — TEST 성과는 극단값에만 의존
- **기존 top-30의 TEST +13.2%는 최저 10% PBR 종목(극저 분위)에서만 발생.** 이 밴드를 잘라내고 다음 저PBR 30개를 뽑으면 TEST가 +13.2% → **+1.5%로 붕괴**.
- **연속 rank long-only(극저 꼬리 가중을 희석)로도 TEST ≈ 0% (+0.2%)** — 저PBR 효과가 "전체 low-PBR 대역"에 고르게 퍼져 있는 게 아니라 **TEST에서는 최저 PBR 꼬리에 집중**.
- 반대로 **TRAIN은 극저 꼬리가 오히려 손실원**: top-30(+3.8%)에 꼬리를 쳐내면 +11.8%로 개선됨.

→ 즉 **"어느 구간의 저PBR이 이기는지"가 TRAIN과 TEST에서 정반대로 뒤집힘**:
- TRAIN: 중간 낮은 PBR 대역이 승리, 최저 꼬리는 손실.
- TEST: 최저 꼬리만 승리, 그 밖은 모두 성과 없음.

## 4. 핵심 질문 답변 — REJECT

> 10-KR-14의 PBR PASS가 특정 극단값/특정 기간/monotonic하지 않은/구성 의존인가?

- **특정 극단값 몇 종목 때문? → 예(결정적).** trim 검정에서 top-30의 TEST +13.2% 성과가 전부 최저 10% PBR 꼬리에 국한(+13.2%→+1.5%). 연속 rank로 극저 꼬리를 희석해도 TEST≈0%.
- **특정 기간에만? → 예.** "최저 PBR 꼬리가 이기는" 현상은 TEST 특유. TRAIN에서는 같은 꼬리가 손실원(trim 시 +3.8→+11.8%). 극단값의 기여 부호가 기간마다 반전.
- **낮은 PBR 전반에서 monotonic? → 아니오.** TRAIN Q3>Q1 스파이크, VALID·TEST의 Q5 반등. 오직 거친 "Q1 > Q5" 방향만 유지.
- **TEST에서 factor-level과 portfolio-level 일치? → 부분적.** factor IC는 TEST에서 유의하나(-0.125, t=-5.6 @60D), **portfolio-level 성과는 극저 꼬리 1개 구성에만 유효**하고 연속·trim 구성에선 0에 수렴 — **IC 유의성이 견고한 거래가능한 포트폴리오로 이어지지 않음**.

## 5. 최종 판정: REJECT

### 판정 근거

1. 10-KR-14의 top-30 PASS 성과가 **극단(최저 10% PBR) 꼬리 하나에만 의존**하며, 그 꼬리의 기여 부호가 TRAIN(손실)과 TEST(전부)에서 뒤집힘 — "저PBR factor"라기보다 **구성·기간 특이적**.
2. **단조성 미확보.** 분위수간 net CAGR이 3기간 어디서도 깨끗하지 않은 단조 패턴을 보이지 않고(TRAIN Q3 스파이크, VALID·TEST Q5 반등), Q5-Q1 spread도 VALID에서 양으로 반전.
3. **대안 구성 모두 재현 불가.** 연속 rank long-only TEST +0.2%, trim(+1.5%) — 기존 top-30(+13.2%)의 TEST 우위는 어떤 대체 구성으로도 견고하게 재현되지 않음.
4. 잔여 신호: 거친 **IC 방향(저PBR→고수익)은 3기간 유의**하므로 "전혀 없다"고 단정하지는 않음. 다만 **그 신호가 특정 포트폴리오 구성(최저 꼬리 top-30)에만 경제적 크기로 나타나** PASS를 유지할 근거가 되지 못함 → **WEAK 이상의 견고한 factor로는 채택 불가**.

### 절대 하지 않음

- TEST +13.2%만 보고, 극저 PBR 꼬리만 집중하는 새로운 threshold 채택 (TEST-driven)
- "trim 했을 때 TRAIN이 좋았다/꼬리가 TEST에서 좋았다" 편향으로 부분 구간 선별
- LOWMOM60 결합, threshold 최적화, 다른 factor 추가, lookback 탐색
- IC 유의성 하나만으로 경제적 견고성으로 확대해석하는 TEST 기반 규칙 변경

---

산출물: `reports/2026-08-28-kr-pbr-robustness/kr-pbr-robustness-results.json`