---
track: kr
factor: flow-basic-effect
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: "Institution REJECT / Foreign 5D·20D KEEP, 60D REJECT"
criteria_version: backfill-v1
conditions: ["institution_flow_ratio", "foreign_flow_ratio", "5d_20d_60d"]
reason: "외국인 당일 수급비율은 5D·20D에서 전 구간 양(+) 방향 유지, 기관은 OOS 반전, 외국인 60D는 OOS 반전 - 지표·호라이즌별 판정이 갈려 단일 결론 없음"
---
# Flow Basic Effect — 당일 기관/외국인 수급비율 → 미래수익률

> 분석 일시: 2026-08-28 | 데이터: A4 수급 연구 데이터셋
> 기간: 2016-01-04 ~ 2026-08-03
> 종목 수: 2558 | 관측치: 5,348,454
> Feature: institution_flow_ratio = inst_net / total_amount
> Feature: foreign_flow_ratio = foreign_net / total_amount
> Forward: T+5, T+20, T+60 (A2a adjusted close)
> Quintile: cross-sectional 5분위 (Q1=최저, Q5=최고)

## 1. Quintile Forward Return (전체 기간)

| Feature | Horizon | Q1 | Q2 | Q3 | Q4 | Q5 | Q5-Q1 | Mean | Std | t-stat | NW t-stat | Obs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Institution | 5D | 0.0024 | 0.0002 | 0.0019 | 0.0016 | 0.0023 | -0.0001 | -0.000099 | 0.008604 | -0.588 | -0.397 | 2590 |
| Institution | 20D | 0.0092 | 0.0044 | 0.0089 | 0.0054 | 0.0070 | -0.0022 | -0.002212 | 0.014961 | -7.503 | -4.170 | 2575 |
| Institution | 60D | 0.0256 | 0.0141 | 0.0273 | 0.0173 | 0.0211 | -0.0045 | -0.004522 | 0.025351 | -8.981 | -4.959 | 2535 |
| Foreign | 5D | 0.0001 | 0.0004 | 0.0009 | 0.0030 | 0.0039 | +0.0038 | +0.003793 | 0.009714 | 19.870 | 15.530 | 2590 |
| Foreign | 20D | 0.0067 | 0.0058 | 0.0049 | 0.0080 | 0.0096 | +0.0029 | +0.002945 | 0.018602 | 8.034 | 5.848 | 2575 |
| Foreign | 60D | 0.0234 | 0.0199 | 0.0175 | 0.0207 | 0.0238 | +0.0004 | +0.000370 | 0.031732 | 0.588 | 0.429 | 2535 |

## 2. 시간 안정성 — Q5-Q1 Spread by Period

| Feature | Horizon | Period | Q5-Q1 | t-stat | NW t-stat | Obs |
|---|---:|---|---:|---:|---:|---:|
| Institution | 5D | TRAIN | -0.000306 | -1.467 | -0.977 | 1595 |
| Institution | 5D | VALID | +0.000307 | 0.804 | 0.575 | 370 |
| Institution | 5D | TEST | +0.000200 | 0.505 | 0.342 | 624 |
| Institution | 20D | TRAIN | -0.003053 | -8.517 | -4.750 | 1595 |
| Institution | 20D | VALID | +0.000271 | 0.348 | 0.210 | 370 |
| Institution | 20D | TEST | -0.001512 | -2.278 | -1.493 | 609 |
| Institution | 60D | TRAIN | -0.006377 | -10.464 | -5.797 | 1595 |
| Institution | 60D | VALID | +0.001107 | 0.943 | 0.584 | 370 |
| Institution | 60D | TEST | -0.003001 | -2.469 | -1.650 | 569 |
| Foreign | 5D | TRAIN | +0.004642 | 19.637 | 15.155 | 1595 |
| Foreign | 5D | VALID | +0.001620 | 3.337 | 3.263 | 370 |
| Foreign | 5D | TEST | +0.002951 | 7.161 | 5.914 | 624 |
| Foreign | 20D | TRAIN | +0.003840 | 8.601 | 6.185 | 1595 |
| Foreign | 20D | VALID | +0.000458 | 0.481 | 0.465 | 370 |
| Foreign | 20D | TEST | +0.002212 | 2.679 | 1.989 | 609 |
| Foreign | 60D | TRAIN | +0.001499 | 1.969 | 1.339 | 1595 |
| Foreign | 60D | VALID | -0.002530 | -1.550 | -1.464 | 370 |
| Foreign | 60D | TEST | -0.000857 | -0.579 | -0.515 | 569 |

## 3. 방향 일관성

- **Institution 5D**: TRAIN=-0.0003(NEG) VALID=+0.0003(POS) TEST=+0.0002(POS) → **INCONSISTENT**
- **Institution 20D**: TRAIN=-0.0031(NEG) VALID=+0.0003(POS) TEST=-0.0015(NEG) → **INCONSISTENT**
- **Institution 60D**: TRAIN=-0.0064(NEG) VALID=+0.0011(POS) TEST=-0.0030(NEG) → **INCONSISTENT**
- **Foreign 5D**: TRAIN=+0.0046(POS) VALID=+0.0016(POS) TEST=+0.0030(POS) → **CONSISTENT**
- **Foreign 20D**: TRAIN=+0.0038(POS) VALID=+0.0005(POS) TEST=+0.0022(POS) → **CONSISTENT**
- **Foreign 60D**: TRAIN=+0.0015(POS) VALID=-0.0025(NEG) TEST=-0.0009(NEG) → **INCONSISTENT**

## 4. 유동성 비교 — 전체 vs 상위 30%

| Feature | Horizon | Universe | Q5-Q1 | NW t-stat | Obs |
|---|---:|---|---:|---:|---:|
| Institution | 5D | All | -0.000099 | -0.397 | 2590 |
| Institution | 5D | Top 30% | +0.000013 | 0.031 | 2590 |
| Institution | 20D | All | -0.002212 | -4.170 | 2575 |
| Institution | 20D | Top 30% | -0.001262 | -1.574 | 2575 |
| Institution | 60D | All | -0.004522 | -4.959 | 2535 |
| Institution | 60D | Top 30% | -0.002153 | -1.599 | 2535 |
| Foreign | 5D | All | +0.003793 | 15.530 | 2590 |
| Foreign | 5D | Top 30% | +0.001054 | 2.998 | 2590 |
| Foreign | 20D | All | +0.002945 | 5.848 | 2575 |
| Foreign | 20D | Top 30% | +0.000218 | 0.323 | 2575 |
| Foreign | 60D | All | +0.000370 | 0.429 | 2535 |
| Foreign | 60D | Top 30% | -0.001613 | -1.398 | 2535 |

## 5. 판정

**Institution (기관 당일 수급비율): REJECT**
- TRAIN에서 **음(-)의 관계**(고기관수급 → 낮은 미래수익률), 20D/60D NW t=-4.75/-5.80으로 통계적으로 뚜렷.
- 그러나 VALID에서 **반전**(양) → TEST에서 다시 음. 방향이 OOS에서 유지되지 않음.
- 5D는 중요도 전 구간 미미(전 구간 NW |t|<1).
- 방향 반전 + 단기 무관계 → OOS에서 신뢰할 관계 아님.

**Foreign (외국인 당일 수급비율): KEEP (5D·20D 단기) / REJECT (60D 장기)**
- **5D**: TRAIN/VALID/TEST **전 구간 양(+) 방향 유지** (NW t=+15.2/+3.3/+5.9). 강하고 안정적 — KEEP.
- **20D**: TRAIN/VALID/TEST 전 구간 양(+) 방향 유지, 단 VALID 약함(0.47)·TEST 경계(NW +1.99). 방향 유지 → KEEP(강도는 약·경계).
- **60D**: TRAIN 약한 양(+1.34) → VALID/TEST 음으로 **반전**. 장기는 OOS 반전 → REJECT.
- 종합: 외국인 당일 수급비율은 **단기(5D)에서만 안정적 양의 관계**, 장기로 갈수록 소멸·반전.

**전체 요약**
| Feature | 5D | 20D | 60D |
|---|---|---|---|
| Institution | 무관계 | TRAIN 음→OOS 반전 | TRAIN 음→OOS 반전 |
| Foreign | **일관 양 (KEEP)** | 방향 유지·약함 | OOS 반전 |

## 6. 부록 — Feature 결측률

- Institution: 0.17%
- Foreign: 0.17%
- 5D: 0.24%
- 20D: 0.92%
- 60D: 2.73%
