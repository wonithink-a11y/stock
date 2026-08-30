---
track: kr
factor: kr-amount-shock
date: 2026-08
verdict: REJECT
conditions: ["amount shock standalone IC insignificant and direction unstable", "incremental orth IC negative across all periods"]
reason: 거래대금 급증(shock) 단독 IC가 유의하지 않고 방향 불안정하며, 기존 amt_surge 통제 후 잔차 IC가 전 구간 유의 음수로 독립 양(+) alpha가 아니다.
cagr: -10.2
sharpe: -0.34
mdd: -40.9
---

# KR 거래대금 Shock — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_amount_shock_validation.py`
- 데이터: A4 (`a4-research-dataset.parquet`) 2016-01 ~ 2026-08, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: REJECT**

## 1. Feature 정의와 PIT 규칙

| Feature | 정의 | PIT |
|---|---|---|
| `shock` (신규) | `total_amount[t] / rolling_median(total_amount, 20)[t-1]` | baseline이 t-20..t-1만 사용, 당일 제외 — close 이후 확정 |
| `amt_surge` (기존) | `log(total_amount[t] / mean(total_amount, 20)[t-1])` | 동일하게 shift, 기존 `a4_liquidity_factor_check.py` |

`shock`의 분포: median 0.94, p99 35.7 — 급증 꼬리가 매우 두터움. forward 수익은 A4
close 기반 1D/5D/20D 재계산(close-to-close). 월별 재조정, 128개 rebalance month.

## 2. Amount Shock 단독 — quintile spread & IC

### Q5-Q1 (월별 pooled) / IC

| Period | 1D | 5D | 20D |
|---|---|---|---|
| TRAIN | +0.09% / **IC -0.015** (t=-1.9) | +0.45% / IC +0.003 (t=0.4) | +0.31% / **IC -0.007** (t=-1.1) |
| VALID | +0.17% / IC -0.001 (t=-0.0) | +0.09% / IC -0.014 (t=-0.9) | +0.81% / IC +0.010 (t=0.6) |
| TEST | +0.22% / IC -0.000 (t=-0.0) | +0.77% / IC +0.017 (t=1.2) | +0.85% / **IC +0.019** (t=2.3) |

**관찰 1 — Amount Shock 단독 IC는 거의 전 구간에서 유의하지 않음.** 모든 period×horizon
에서 |t| < 2이고 방향이 고정되지 않음(TRAIN 1D/20D 음수, TEST 20D 양수). Q5-Q1 spread도
작고(+0.1~+0.9%) 일관성이 없음. 거래대금 급증 여부가 이후 수익률을 안정적으로 예측하지
못함.

**관찰 2 — continuation/reversal 어느 쪽도 단독으로 확인 안 됨.** TEST 20D만 양(+)으로
나타나나 1D/5D 및 TRAIN/VALID에서 재현되지 않음.

## 3. 기존 volume expansion(amt_surge) 단독

### amt_surge Q5-Q1 / IC

| Period | 1D | 5D | 20D |
|---|---|---|---|
| TRAIN | +0.04% / IC -0.015 (t=-1.6) | +0.34% / IC +0.007 (t=0.9) | +0.15% / IC +0.005 (t=0.7) |
| VALID | +0.13% / IC +0.002 (t=0.1) | -0.02% / IC -0.010 (t=-0.6) | +1.23% / IC +0.032 (t=1.8) |
| TEST | +0.20% / IC +0.010 (t=0.7) | +0.77% / **IC +0.037** (t=2.6) | +1.34% / **IC +0.055** (t=5.4) |

**관찰 3 — 기존 amt_surge도 TEST 20D에서만 유의한 양(+) IC(+0.055, t=5.4).**
TRAIN/VALID는 유의하지 않고 방향 불안정. 기존 확립된 volume expansion 계열 역시
안정적 alpha가 아님. (이미 `liquidity_factor_study.py`에서 surge_5_60 약함으로 스크리닝된
것과 일치.)

## 4. 핵심 추가 검증 — Amount Shock의 incremental value

Shock를 amt_surge에 대해 rank-orthogonalize한 잔차의 IC.

### shock | amt_surge (orthogonalized incremental IC)

| Period | 1D | 5D | 20D |
|---|---|---|---|
| TRAIN | -0.009 (t=-1.4) | -0.011 (t=-1.7) | **-0.031 (t=-4.8)** |
| VALID | -0.010 (t=-0.5) | -0.021 (t=-1.4) | **-0.034 (t=-3.0)** |
| TEST | -0.016 (t=-1.6) | **-0.026 (t=-2.6)** | **-0.047 (t=-6.3)** |

**관찰 4 — 결정적: incremental orth IC가 전 구간에서 음수, 장기 horizon에서 유의.**

기존 amt_surge가 설명하지 못하는 shock의 잔차 정보는 **모든 period에서 유의미하게
음수** — 특히 20D에서 TRAIN -0.031(t=-4.8), VALID -0.034(t=-3.0), TEST -0.047(t=-6.3).

즉 **Amount Shock은 기존 volume expansion 위에 "새로운 양(+) 정보"를 주지 않는다.**
오히려 기존 amt_surge를 통제한 뒤의 잔차는 이후 수익률이 **낮아지는 방향(reversal)**
으로 비행상관한다. 스카이 스파이크 초과분은 20일 수준에서 reversal을 예측.

**핵심 질문 답변**: "Amount Shock이 기존 volume expansion이 설명하지 못하는 새로운
정보를 제공하는가?" → **제공한다면 그것은 양(+) alpha가 아니라 음(-) 방향 정보다.**
새 continuation signal이 아니라 reversal 신호를 중복·증폭할 뿐.

## 5. Shock × 가격수익률 방향 분해

### 5D forward return, high-shock 분기

| Period | high_shock & up (n) | high_shock & down (n) |
|---|---|---|
| TRAIN | +0.75% (40,322) | +0.56% (28,464) |
| VALID | +0.20% (10,860) | +1.33% (8,438) |
| TEST | **-0.41%** (16,604) | +0.34% (19,515) |

**관찰 5 — 고셕 + 상승조합이 TEST에서 -0.41%로 음전.** 거래대금 급증 속 상승 종목
(전형적 "돌파/추세" 조합)이 최근에서 reversal. 방향 분해에서도 안정적 continuation
근거 없음.

## 6. Portfolio 검증 (long top-Q5 shock, 월별, close-to-close)

### Net 30bps, 20-session hold (overlap)

| Period | CAGR | Sharpe | MDD | avg월 |
|---|---|---|---|---|
| TRAIN | +3.2% | 0.25 | -43.1% | +0.46% |
| VALID | +3.8% | 0.29 | -14.1% | +0.46% |
| TEST | **-10.2%** | -0.34 | -40.9% | -0.66% |

**관찰 6 — 포트폴리오는 TEST에서 뚜렷한 손실(-10.2% CAGR), Sharpe 음수.**
TRAIN/VALID도 Sharpe 0.25 수준으로 매우 낮아 실질 매매 가능한 alpha가 아님. 최근
구간에서는 고셕 종목 매수가 손실.

## 7. 핵심 질문 답변

1. **거래대금 급증 후 continuation인가 reversal인가?** — 단독으로는 명확한 방향 없음
   (IC 불안정). 기존 amt_surge 통제 후 잔차는 **reversal**(음수, 유의).
2. **Amount Shock이 독립적 양(+) alpha인가?** — **아니다.** 단독 IC 유의 없음 +
   incremental이 음수.
3. **기존 volume expansion 대비 incremental value?** — **새로운 양(+) 정보 없음.**
   오히려 반대(음) 방향 정보를 넣음.
4. **TRAIN→VALID→TEST 안정성?** — 단독은 불안정, incremental 음수는 **세 구간
   일관되게 유지.**

## 8. 최종 판정: REJECT

### 판정 근거

1. **단독 IC가 유의하지 않고 방향 불안정.** 거래대금 급증이 이후 수익률을 안정적으로
   예측하지 못함. 유일한 유의점(TEST 20D +0.019)은 TRAIN/VALID에서 재현 안 됨.

2. **incremental value가 결정적으로 음수.** 기존 amt_surge를 통제한 잔차 IC가
   20D에서 TRAIN·VALID·TEST 모두 유의하게 음수(t=-4.8, -3.0, -6.3). "새 정보"를
   준다면 방향이 양(+)이 아니라 반대(reversal) — continuation alpha로서 가치 없음.

3. **실질 alpha 아님.** Portfolio: TEST CAGR -10.2%, Sharpe -0.34. TRAIN/VALID도
   Sharpe 0.25로 실매매 불가.

4. **기존 volume expansion과 중복+역방향.** 기존 amt_surge도 TEST 20D에서만 유의
   (이미 약함으로 스크리닝된 계열). shock은 그 위에 음(-) 정보만 추가.

### 절대 하지 않음

- shock lookback/threshold 최적화
- TEST 20D 양(+) 결과만 골라 전략화
- 기존 feature와 임의 결합 후 재정의
- 결과에 맞춰 feature 정의 변경

거래대금 Shock은 KR 주식에서 유의한 독립 양(+) alpha가 아니고, 기존 volume
expansion 대비 incremental 양(+) alpha도 아니다. 파라미터 변경 없이 종료.

---

산출물: `reports/2026-08-28-kr-amount-shock/kr-amount-shock-results.json`
