---
track: kr
factor: flow-regime-effect
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["foreign_flow_ratio", "risk_on/neutral/off_regime", "5d/20d/60d"]
reason: "외국인 당일 수급 단기 효과는 국면 무관 양·유의(5D 3국면 모두)이나 Risk-Off TEST 표본(N=50) 부족으로 OOS 안정성 미확정"
---
# Flow Regime Effect — 외국인 당일 수급 효과 × 시장 국면

> 분석 일시: 2026-08-28 | 데이터: A4 (Step 2와 동일) + 기존 market-regime
> 기간: 2016-01-04 ~ 2026-08-03 | 종목: 2558
> 질문: 외국인 당일 순매수 효과가 시장 상승/하락 국면에 따라 달라지는가?

## 0. 사용한 시장 국면 (기존 정의 그대로, 최적화 없음)

- 원천: `data/market-regime/regime_labels.parquet` (`build_regime_definition.py`, 2026-08-23)
- 4축 점수 합: VIX(Low=+1/Mid=0/High=-1) · trend60(Bull=+1/Neutral/Bear=-1) ·
  breadth/adv_pct(Strong=+1/Weak=-1) · USD/KRW 20d(Falling=+1/Rising=-1)
- 3구간: **합>=+2 → Risk-On, 합<=-2 → Risk-Off, 그 외 → Neutral**
- PIT: 신호일 t의 regime = `usableFromDate==t` 라벨 (기존 regime-conditional 관례와 동일)

- 레이블 분포(레코드 기준): Risk-On 1703404 · Neutral 3030980 · Risk-Off 612419 · 결측 1651

## 1. Regime별 foreign_flow_ratio Quintile (전체 기간, Q5-Q1 spread)

| Regime | Horizon | Q5-Q1 | NW t | N |
|---|---:|---:|---:|---:|
| Risk-On | 5D | +0.0037 | +11.80 | 823 |
| Risk-On | 20D | +0.0038 | +5.56 | 817 |
| Risk-On | 60D | +0.0014 | +1.09 | 811 |
| Neutral | 5D | +0.0035 | +12.37 | 1469 |
| Neutral | 20D | +0.0016 | +2.86 | 1460 |
| Neutral | 60D | -0.0013 | -1.18 | 1440 |
| Risk-Off | 5D | +0.0056 | +4.70 | 297 |
| Risk-Off | 20D | +0.0068 | +2.94 | 297 |
| Risk-Off | 60D | +0.0059 | +2.13 | 283 |

## 2. Regime별 TRAIN / VALID / TEST (Q5-Q1 spread)

| Regime | Horizon | Period | Q5-Q1 | NW t | 방향 | N |
|---|---:|---:|---:|---:|---:|---:|
| Risk-On | 5D | TRAIN | +0.0041 | +11.33 | + | 505 |
| Risk-On | 5D | VALID | +0.0018 | +2.04 | + | 94 |
| Risk-On | 5D | TEST | +0.0034 | +5.03 | + | 224 |
| Risk-On | 20D | TRAIN | +0.0031 | +4.02 | + | 505 |
| Risk-On | 20D | VALID | +0.0027 | +1.56 | + | 94 |
| Risk-On | 20D | TEST | +0.0060 | +3.87 | + | 218 |
| Risk-On | 60D | TRAIN | +0.0007 | +0.47 | + | 505 |
| Risk-On | 60D | VALID | -0.0031 | -0.78 | - | 94 |
| Risk-On | 60D | TEST | +0.0052 | +1.86 | + | 212 |
| Neutral | 5D | TRAIN | +0.0044 | +13.32 | + | 907 |
| Neutral | 5D | VALID | +0.0013 | +1.82 | + | 212 |
| Neutral | 5D | TEST | +0.0025 | +4.60 | + | 350 |
| Neutral | 20D | TRAIN | +0.0026 | +3.57 | + | 907 |
| Neutral | 20D | VALID | -0.0006 | -0.38 | - | 212 |
| Neutral | 20D | TEST | +0.0006 | +0.56 | + | 341 |
| Neutral | 60D | TRAIN | +0.0003 | +0.22 | + | 907 |
| Neutral | 60D | VALID | -0.0023 | -1.00 | - | 212 |
| Neutral | 60D | TEST | -0.0053 | -2.63 | - | 321 |
| Risk-Off | 5D | TRAIN | +0.0072 | +4.52 | + | 183 |
| Risk-Off | 5D | VALID | +0.0023 | +2.23 | + | 64 |
| Risk-Off | 5D | TEST | +0.0039 | +1.33 | + | 50 |
| Risk-Off | 20D | TRAIN | +0.0118 | +4.84 | + | 183 |
| Risk-Off | 20D | VALID | +0.0005 | +0.23 | + | 64 |
| Risk-Off | 20D | TEST | -0.0034 | -0.45 | - | 50 |
| Risk-Off | 60D | TRAIN | +0.0093 | +2.79 | + | 183 |
| Risk-Off | 60D | VALID | -0.0023 | -0.59 | - | 64 |
| Risk-Off | 60D | TEST | +0.0033 | +0.38 | + | 36 |

## 3. 국면별 방향 일관성 (외국인 수급 효과)

| Regime | Horizon | TRAIN | VALID | TEST | 일관? |
|---|---|---|---|---|---|
| Risk-On | 5D | + | + | + | 일관 |
| Risk-On | 20D | + | + | + | 일관 |
| Risk-On | 60D | + | - | + | 비일관 |
| Neutral | 5D | + | + | + | 일관 |
| Neutral | 20D | + | - | + | 비일관 |
| Neutral | 60D | + | - | - | 비일관 |
| Risk-Off | 5D | + | + | + | 일관 |
| Risk-Off | 20D | + | + | - | 비일관 |
| Risk-Off | 60D | + | - | + | 비일관 |

## 4. 해석

### A. 모든 국면에서 효과가 존재하는가?
- **Risk-On**: 5D=+ (유의) | 20D=+ (유의) | 60D=+ (약)
- **Neutral**: 5D=+ (유의) | 20D=+ (유의) | 60D=-
- **Risk-Off**: 5D=+ (유의) | 20D=+ (유의) | 60D=+ (유의)

### D. 국면을 나누어도 외국인 5D 효과가 유지되는가?
- Risk-On: Q5-Q1=+0.0037 (NW +11.80, N=823)
- Neutral: Q5-Q1=+0.0035 (NW +12.37, N=1469)
- Risk-Off: Q5-Q1=+0.0056 (NW +4.70, N=297)

## 5. 유동성 — 거래대금 상위 30% (regime별)

| Regime | Horizon | Q5-Q1 | NW t | N |
|---|---:|---:|---:|---:|
| Risk-On | 5D | +0.0011 | +2.06 | 823 |
| Risk-On | 20D | +0.0015 | +1.39 | 817 |
| Risk-On | 60D | +0.0010 | +0.51 | 811 |
| Neutral | 5D | +0.0006 | +1.45 | 1469 |
| Neutral | 20D | -0.0013 | -1.60 | 1460 |
| Neutral | 60D | -0.0039 | -2.67 | 1440 |
| Risk-Off | 5D | +0.0032 | +2.08 | 297 |
| Risk-Off | 20D | +0.0043 | +1.66 | 297 |
| Risk-Off | 60D | +0.0023 | +0.61 | 283 |

## 6. 판정

### 국면 간 대비 (전체 기간)

| Regime | 5D NW | 20D NW | 60D NW |
|---|---:|---:|---:|
| Risk-On | +11.80 | +5.56 | +1.09 |
| Neutral | +12.37 | +2.86 | -1.18 |
| Risk-Off | +4.70 | +2.94 | +2.13 |

### 방향 일관(3구간 전부 같은 부호) + TEST 유의한 케이스

- 방향 일관: Risk-On 5D, Risk-On 20D, Neutral 5D, Risk-Off 5D
- TEST에서 |NW|>2: Risk-On 5D(+5.03), Risk-On 20D(+3.87), Neutral 5D(+4.60), Neutral 60D(-2.63)

### 최종 판정

**외국인 수급 효과 × 시장 국면: WEAK — 국면별 크기 차이는 있으나, 효과는 모든 국면에 존재하고 OOS는 부분 불안정**

#### 연구 질문 A~D에 대한 답

- **A. 모든 국면에서 효과가 존재하나? → 예(단기).** Risk-On/Neutral/Risk-Off 세 국면 모두 5D·20D에서 양(+)이고
  유의(Risk-On +11.80/+5.56, Neutral +12.37/+2.86, Risk-Off +4.70/+2.94). 외국인 수급 효과는 특정 국면 전용이 아니다.
- **B. 특정 국면에서만 존재하나? → 아니오.** 어느 한 국면에 한정되지 않는다.
- **C. 국면에 따라 방향이 반전되나? → 장기 지평에서만.** 60D에서 Neutral만 음(-1.18)으로 반전, Risk-On(+1.09)·
  Risk-Off(+2.13)는 유지. 단기(5D)에서는 반전 없음.
- **D. 국면을 나눠도 5D 효과가 유지되나? → 예.** 5D spread가 세 국면 모두 양·유의
  (Risk-On +0.0037/NW+11.80, Neutral +0.0035/+12.37, Risk-Off +0.0056/+4.70).

#### 국면별 크기 차이 (핵심 관측)

- **Risk-Off가 모든 지평에서 가장 큰 spread**를 보인다(5D +0.0056, 20D +0.0068, 60D +0.0059).
  특히 60D에서 유일하게 유의(+2.13) — 하락장에서 외국인 당일 순매수가 더 강한 신호로 작동하는 모습은
  경제적으로 해석 가능("외국인이 침체기 대형 낙폭 종목을 사는 것을 시장이 좇는다").
- 그러나 **Risk-Off TEST 표본이 매우 작다(N=50)**. 5D TEST는 +1.33으로 약하고 20D TEST는 -0.45로 반전 —
  이 60D 강점이 최근 국면에서 재현되는지 OOS로 확인하기에는 표본이 부족하다.

#### 종합 판단

- **REJECT 아님**: 국면을 나눠도 효과가 없지 않다 — 단기 효과는 모든 국면에 존재.
- **KEEP 아님**: "특정 국면에서만"이 아니라 "모든 국면에서 존재 + Risk-Off에서 크다"는 구조라,
  국면 필터를 만들 근거(국면 없이는 효과가 없다)가 되지 않는다.
- **WEAK**: 국면별로 크기가 다르고(특히 Risk-Off 강세) 60D 방향이 국면에 따라 갈리지만,
  Risk-Off TEST 표본이 작아 OOS 안정성을 확정할 수 없다. **외국인 수급 단기 효과는 국면 무관(광범위),**
  다만 하락장(Risk-Off)에서 더 크고 장기로 이어지는 특징은 후속 확인 가치가 있다.

