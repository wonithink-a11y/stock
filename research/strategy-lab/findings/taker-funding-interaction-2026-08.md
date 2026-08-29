---
track: crypto
factor: taker-funding-interaction
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: REDUNDANT
criteria_version: backfill-v1
conditions: ["taker_ratio_7", "funding_residual", "bull_regime", "2d_combination"]
---
# Step 26 — `taker_ratio_7` × Funding Residual 결합 정보 검증 (Bull Regime Only)

날짜: 2026-08-29 | 판정: **REDUNDANT**

## 핵심 결과 요약

| 구성 | r7 spread (D1-D10) | t-stat | 방향 |
|---|---|---|---|
| **taker_7d 단독** | **+0.0357** | **+5.71** | **양 (+)** |
| funding residual 단독 | -0.0067 | -0.84 | 음 (무의미) |
| **결합 (top20% vs bottom20%)** | **-0.0142** | **-3.57** | **음 (-)** |

---

## 1. Bull Regime (mom30>0) 단독 Baseline

| feature | r1 | r3 | **r7** |
|---|---|---|---|
| **taker_7d** | +0.0021 (t=1.09) | +0.0136 (t=3.34) | **+0.0357 (t=5.71)** |
| **f_avg_fmresid** | +0.0027 (t=1.14) | +0.0013 (t=0.30) | **-0.0067 (t=-0.84)** |

→ **taker_7d만 강한 양의 신호**; funding residual은 유의미하지 않음.

---

## 2. 2D 결합 분석 (Q5×Q5 grid, r7)

| 셀 | 평균 r7 | 전체 대비 편차 | 샘플 수 | t vs 전체 |
|---|---|---|---|---|
| **Q1_Q1** (low taker, low fund) | **+0.0632** | **+0.0368** | 1,556 | **+4.38** |
| **Q1_Q5** (low taker, high fund) | **+0.0619** | **+0.0355** | 1,774 | **+5.44** |
| **Q5_Q1** (high taker, low fund) | +0.0413 | +0.0149 | 922 | +2.64 |
| **Q5_Q5** (high taker, high fund) | +0.0332 | +0.0068 | 868 | +1.34 |

→ **최고 수익은 low taker + low funding residual (Q1_Q1)**.  
high taker + high funding (Q5_Q5)가 가장 낮음.

---

## 3. 결합 vs 단독 Spread (Top/Bottom 20%)

| horizon | combined (Δ, t) | taker 단독 (Δ, t) | fund resid 단독 (Δ, t) |
|---|---|---|---|
| r1 | **-0.0017 (t=-1.34)** | +0.0021 (t=1.09) | +0.0027 (t=1.14) |
| r3 | **-0.0049 (t=-1.94)** | **+0.0136 (t=3.34)** | +0.0013 (t=0.30) |
| **r7** | **-0.0142 (t=-3.57)** | **+0.0357 (t=5.71)** | -0.0067 (t=-0.84) |

**결합이 단독 taker 신호를 완전히 뒤집음** (양→음).  
결합 rank(rx+ry)가 높을수록(=taker↑ & fund_resid↑) 수익이 낮아짐.

---

## 4. 날짜별 Cross-Sectional IC

| horizon | mean IC | t | 양의 날짜 비율 |
|---|---|---|---|
| r1 | +0.021 | 2.63 | 53% |
| r3 | +0.033 | 4.11 | 54% |
| r7 | +0.035 | 4.28 | 54% |

결합 rank IC는 양호하나, **방향은 단독 taker와 반대** (결합 high = low return).

---

## 5. ZEC 제외 (r7)

| | combined Δ | t |
|---|---|---|
| **all 28** | -0.0142 | -3.57 |
| **no ZEC** | **-0.0163** | **-4.01** |

ZEC 제외 시 결합 음의 스프레드 **강화** → ZEC 의존 아님.

---

## 5. 셀 지배 여부 (r7)

| corner | mean r7 | t vs overall | n |
|---|---|---|---|
| Q1_Q1 (low taker, low fund) | **+0.063** | **+4.38** | 1,556 |
| Q1_Q5 (low taker, high fund) | **+0.062** | **+5.44** | 1,774 |
| Q5_Q1 (high taker, low fund) | +0.041 | +2.64 | 922 |
| Q5_Q5 (high taker, high fund) | +0.033 | +1.34 | 868 |

**특정 극단 셀이 지배하지 않음** (Q1_Q1, Q1_Q5 둘 다 높음).  
하지만 **high taker 셀(Q5_*)이 low taker 셀(Q1_*)보다 모두 낮음** → taker 방향과 funding residual 방향이 충돌.

---

## 6. 판정: **REDUNDANT**

### 사유

| 기준 | 충족? | 비고 |
|---|---|---|
| 단독 각각 유의 | ❌ | taker만 유의; funding residual 무의미 |
| 결합이 단독보다 강함 | ❌ | **결합이 단독 taker 신호를 역전** (Δ +0.036 → -0.014) |
| 상호보완적 정보 | ❌ | **충돌**: high taker + high fund_resid = 최저 수익 |
| 특정 셀 지배 | ❌ | Q1_Q1/Q1_Q5가 높음 (high taker 제외 유리) |
| ZEC 의존성 | ❌ | ZEC 제외 시 결합 음의 스프레드 강화 |

### 해석

- **taker_ratio_7은 bull에서 강건한 단독 신호** (r7 t=5.71).
- **funding residual은 bull에서 정보 없음** (t=-0.84).
- 두 피처를 결합하면 **taker의 양의 신호가 funding residual의 잡음과 섞여 음의 스프레드로 뒤집힘**.
- 경제적으로: **low taker + low funding residual** 구간에서 수익이 가장 높음 → passive/저활동 구간이 강세장에서 아웃퍼폼 (contrarian 확인).
- 결합 rank(rx+ry)는 **taker 신호를 희석**시키는 역할만 함.

---

## 산출물
- 신규: `taker_funding_interaction_check.py`
- 신규: `findings/taker-funding-interaction-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 백테스트·커밋 없음.