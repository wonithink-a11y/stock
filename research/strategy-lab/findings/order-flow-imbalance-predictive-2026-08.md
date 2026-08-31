---
track: crypto
factor: order-flow-imbalance-predictive
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: "FAIL"
criteria_version: backfill-v1
conditions: ["taker_buy_ratio_q", "imbalance_q", "imb_q_chg_7d", "imbalance_q_z30"]
reason: "imbalance_q_z30만 유의한 mean-reversion 신호를 보이나 funding rate와 -0.24 상관으로 독립 정보 아니고 스프레드가 10bp 비용 대비 너무 작아 독립적 알파 소스로 부적합"
---

# Step 35 — Order-Flow Imbalance Predictive Test

날짜: 2026-08-29 | 판정: **FAIL**

## 검증 설정
- 데이터: 기존 `activity/` 28종목 1h → KST daily order-flow features
- 핵심 피처 4개:
  - `taker_buy_ratio_q_of`: quote 기준 taker 매수 비율
  - `imbalance_q_of`: quote 기준 매수/매도 불균형
  - `imb_q_chg_7d_of`: imbalance_q 7일 변화율
  - `imbalance_q_z30_of`: imbalance_q 30일 z-score
- 타깃: r_1, r_3, r_7 (KST daily forward returns)
- 검증: pooled decile D1-D10 spread, funding/mom30 상관, LOO (BTC drop)
- 기존 데이터만 사용, 신규 수집/백테스트/전략화/커밋 금지

---

## 핵심 결과 (r_7 기준)

| 피처 | D1-D10 Spread | t-stat | n_D1 | 방향 |
|---|---|---|---|---|
| `taker_buy_ratio_q_of` | +0.0041 | +1.32 | 5,676 | 고비율 → 고수익 |
| `imbalance_q_of` | +0.0041 | +1.32 | 5,676 | 고불균형(매수) → 고수익 |
| `imb_q_chg_7d_of` | +0.0017 | +0.65 | 5,699 | 변화율 양 → 고수익 |
| **`imbalance_q_z30_of`** | **−0.0132** | **−4.49** | 5,703 | **고z-score(과매수) → 저수익** |

---

## 기존 변수와의 중복성

| 피처 | corr(f_avg) | corr(mom30) |
|---|---|---|
| `taker_buy_ratio_q_of` | **−0.244** | −0.086 |
| `imbalance_q_of` | **−0.244** | −0.086 |
| `imb_q_chg_7d_of` | +0.125 | +0.038 |
| **`imbalance_q_z30_of`** | −0.076 | **−0.100** |

→ **funding(f_avg)과 유의한 음의 상관** (−0.24) → funding이 이미 order-flow 정보 일부 포함
→ **momentum(mom30)과도 약한 음의 상관** (특히 z-score에서 −0.10)

---

## LOO (BTC 제외) 안정성

| 피처 | Δ (D1-D10) | t-stat | 변화 |
|---|---|---|---|
| `taker_buy_ratio_q_of` | +0.0054 | +1.67 | 미미 |
| `imbalance_q_of` | +0.0054 | +1.67 | 미미 |
| `imb_q_chg_7d_of` | +0.0017 | +0.63 | 미미 |
| **`imbalance_q_z30_of`** | **−0.0134** | **−4.40** | **견고** |

→ BTC 제외해도 `imbalance_q_z30_of` 신호 **유지** (t = -4.40) → **특정 종목 의존 없음**

---

## 경제적 해석

- `taker_buy_ratio`, `imbalance_q`: D1-D10 스프레드 양수이나 **t-stat 약함** (1.32) → 유의미하지 않음
- `imb_q_chg_7d`: 신호 약함 (t=0.65)
- **`imbalance_q_z30_of`만 유의한 음의 스프레드** (−0.0132, t=−4.49):
  - 30일 z-score가 높음(과매수 구간) → 7일 후 수익률 낮음
  - **mean-reversion / overbought reversal** 패턴
  - funding/mom30과 약한 음의 상관 → 독립적 신호 가능성 존재

---

## 판정: **FAIL**

| 기준 | 결과 | 비고 |
|---|---|---|
| **통계적 유의성** | ⚠️ | `imbalance_q_z30`만 유의 (t=-4.49), 나머지 무의미 |
| **방향성 일관성** | ⚠️ | `imbalance_q_z30`만 sound한 mean-reversion |
| **기존 변수 독립성** | ❌ | funding과 −0.24 강한 음의 상관 → 중복 |
| **LOO 안정성** | ✅ | `imbalance_q_z30` BTC 제외해도 유지 |
| **실전 활용성** | ❌ | 스프레드 크기 작음 (7일 1.3%), 10bp 비용으로 마진 없음 |

### 핵심 문제
1. **신호 약함**: 4개 피처 중 `imbalance_q_z30`만 통계적 유의 (t=-4.49)
2. **중복성**: funding(f_avg)과 −0.24 강한 음의 상관 → order-flow 정보가 funding에 이미 반영됨
3. **경제적 크기 작음**: 7일 1.3% 스프레드 → 일간 0.2% 수준 → 10bp 비용으로 마진 없음
4. **나머지 3개 피처 무의미**: t-stat 모두 2 미만

---

## 결론
Order-flow imbalance 피처 중 **`imbalance_q_z30`(30일 z-score)만 통계적으로 유의한 mean-reversion 신호**를 보이나:
1. funding rate와 강한 음의 상관(−0.24) → **독립 정보 아님**
2. 스프레드 크기(7일 1.3%)가 **거래비용(10bp) 대비 너무 작음**
3. 나머지 3개 피처(taker_buy_ratio, imbalance_q, imb_chg_7d)는 **통계적으로 무의미**

**독립적 알파 소스로는 부적합**. Funding rate가 이미 order-flow 정보를 상당 부분 반영하고 있음.

---

## 산출물
- `order_flow_imbalance_predictive.py`
- `findings/order-flow-imbalance-predictive-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.