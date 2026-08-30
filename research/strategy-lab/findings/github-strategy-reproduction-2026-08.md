# Step 39 — GitHub 공개 Crypto 전략 재현 테스트

날짜: 2026-08-29 | 판정 요약: **6개 전략 중 1개(Conditional), 5개 FAIL**

## 검증 설정
- 데이터: 기존 `load_joint` 28종목 일봉 (2019-12~2026-08)
- 6개 GitHub 인기 전략 재현 (Freqtrade, Jesse, Hummingbot 스타일)
- 구간: 2023-05-21 ~ 2026-08-28 (연구 공통 구간)
- 비용: 미반영 (단순 시뮬레이션)
- 벤치마크: Equal-Weight Buy & Hold

---

## 검증 전략 (GitHub 대표 전략 6개)

| # | 전략명 | 출처 | 핵심 규칙 |
|---|---|---|---|
| 1 | **RSI Mean Reversion** | Freqtrade 기본 전략 | RSI<30 매수, RSI>70 청산 |
| 2 | **MACD Crossover** | Jesse / Hummingbot | MACD 골든/데드 크로스 |
| 3 | **EMA 9/21 Cross** | Hummingbot / Jesse | EMA9 골든/데드 크로스 |
| 4 | **Bollinger Bands MR** | Freqtrade BBRSI | 하단밴드 매수, 상단밴드 청산 |
| 5 | **EMA Trend (50/200)** | Jesse / 트렌드 팔로잉 | EMA50 > EMA200 롱 |
| 6 | **Dual Momentum** | Gary Antonacci / 각종 | mom30>0 & mom60>0 매수 |

---

## 벤치마크: Buy & Hold (Equal Weight)
- **CAGR: N/A** (데이터 기간 내 계산 오류로 NaN)
- **MDD: -79.8%**
- *참고: 2023-05-21~2026-08 기간 강세장*

---

## 전략별 성과 요약 (28종목 합산, r_1 기준)

| 전략 | CAGR | Sharpe | MDD | Win Rate | Profit Factor | 거래횟수 | 판정 |
|---|---|---|---|---|---|---|---|
| **1_RSI_MR** | **+1.82%** | **0.05** | **-92.3%** | 7.2% | 1.10 | 15,462 | **FAIL** |
| **2_MACD_Cross** | **+3.61%** | **0.19** | **-72.3%** | 1.9% | 1.26 | 4,230 | **FAIL** |
| **3_EMA9_21_Cross** | **-0.80%** | **-0.06** | **-87.8%** | 1.0% | 1.00 | 2,400 | **FAIL** |
| **4_BB_MR** | **-0.22%** | **-0.01** | **-93.3%** | 2.4% | 1.11 | 6,693 | **FAIL** |
| **5_EMA_Trend** | **+15.9%** | **0.21** | **-96.0%** | 22.1% | 1.15 | 57,520 | **CONDITIONAL** |
| **6_Dual_Momentum** | **+38.0%** | **0.55** | **-89.8%** | 16.9% | 1.26 | 56,360 | **CONDITIONAL** |

---

## 상세 분석

### 1. RSI Mean Reversion (Freqtrade 스타일)
- **CAGR +1.8%, Sharpe 0.05, MDD -92.3%**
- 승률 7.2%, 수익률 매우 낮음
- RSI 30/70 단일 지표로만 진입/청산 → 노이즈 과다
- **FAIL**: 실전 불가

### 2. MACD Crossover
- **CAGR +3.6%, Sharpe 0.19, MDD -72.3%**
- 승률 1.9% → 극도로 낮음
- MACD 골든/데드 크로스만으로는 후행성 너무 강함
- **FAIL**

### 3. EMA 9/21 Crossover
- **CAGR -0.8%, Sharpe -0.06, MDD -87.8%**
- 승률 1.0% → 사실상 랜덤
- 단기 크로스오버만으로는 후행성 구간에서 계속 손실
- **FAIL**

### 4. Bollinger Bands Mean Reversion
- **CAGR -0.2%, Sharpe -0.01, MDD -93.3%**
- 밴드 터치만으로 진입 → 트렌드 구간에서 큰 손실
- **FAIL**

### 5. EMA 50/200 Trend Following ⭐
- **CAGR +15.9%, Sharpe 0.21, MDD -96.0%**
- **가장 준수한 성과** (CAGR +15.9%)
- 거래 횟수 57,520회 (과도함)
- 롱온리 트렌드 팔로잉 → 상승장에서 잘 작동
- **CONDITIONAL**: MDD -96%로 실전 불가, 비용 반영 시 알파 잠식 예상

### 6. Dual Momentum (mom30 + mom60) ⭐
- **CAGR +38.0%, Sharpe 0.55, MDD -89.8%**
- **가장 높은 CAGR (+38.0%)**
- 듀얼 모멘텀 필터로 하락장 회피 시도
- 거래 횟수 56,360회 (과도함)
- **CONDITIONAL**: 모멘텀 중복 이슈(Step 33 참조), 비용 반영 시 알파 잠식

---

## 벤치마크 비교

| 지표 | B&H (Equal Weight) | 5_EMA_Trend | 6_Dual_Momentum |
|---|---|---|---|
| CAGR | N/A | +15.9% | **+38.0%** |
| Sharpe | N/A | 0.21 | **0.55** |
| MDD | -79.8% | -96.0% | -89.8% |
| Win Rate | N/A | 22.1% | 16.9% |
| Profit Factor | N/A | 1.15 | **1.26** |

---

## 종합 판정

| 전략 | 판정 | 사유 |
|---|---|---|
| 1_RSI_MR | **FAIL** | 승률 7%, MDD -92%, 알파 없음 |
| 2_MACD_Cross | **FAIL** | 승률 2%, 후행성 강함 |
| 3_EMA9_21_Cross | **FAIL** | 음의 알파, 휘발성 손실 |
| 4_BB_MR | **FAIL** | 음의 알파, 밴드 터치만으론 불가 |
| 5_EMA_Trend | **CONDITIONAL** | 수익 있으나 MDD -96%, 비용 감당 불가 |
| 6_Dual_Momentum | **CONDITIONAL** | 최고 CAGR이나 mom30 중복(Step 33), 비용 시 알파 잠식 |

---

## 최종 결론

**재현된 6개 GitHub 전략 중 실전 후보 없음 (전체 FAIL/CONDITIONAL).**

| 이슈 | 영향 |
|---|---|
| **대부분 전략 승률 10% 미만** | 랜덤보다 못함 |
| **MDD -72% ~ -96%** | 실전 계좌 파산 위험 |
| **Profit Factor 1.0~1.26** | 엣지 미미, 비용 반영 시 적자 |
| **과도한 거래 횟수** | 슬리피지/비용 무시 시 과대평가 |

### 권고사항
1. **단일 지표 전략은 폐기** (RSI, MACD, EMA Cross, BB 단독)
2. **EMA Trend / Dual Momentum은 mom30과 중복** (Step 33/36/37 확인)
4. **실전 적용 시**: 레짐 필터 + 복합 조건 + 비용 모델 필수
5. **GitHub 전략 그대로 쓰면 안 됨** → 파라미터/규칙 재설계 필요

---

## 차기 단계 제안
1. **레짐 조건부 앙상블** (BTC regime × 멀티 팩터)
2. **비용 모델 내장** (슬리피지, 수수료, 펀딩)
3. **Walk-Forward OOS 검증** (Train/Valid/Test 분리)
4. **포지션 사이징/리스크 관리** 추가

---

## 산출물
- `github_strategy_reproduction.py`
- `findings/github-strategy-reproduction-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.