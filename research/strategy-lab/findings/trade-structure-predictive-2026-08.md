---
track: crypto
factor: trade-structure-predictive
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: FAIL
criteria_version: backfill-v1
reason: "거래구조 피처가 momentum과 강한 양의 상관(ats_z r=0.275)으로 독립 알파 아님, 고활동→저수익(mean-reversion)이라 롱온리 부적합 - FAIL"
t_stat: -7.73
n: 5674
---

# Step 32 — Trade Structure Predictive Test

날짜: 2026-08-29 | 판정: **FAIL**

## 검증 설정
- 데이터: `activity/` 28종목 1h → KST daily features
- 피처 (핵심 3개):
  - `tc_chg_7d`: trade_count 7일 변화율
  - `ats_chg_7d`: avg_trade_size 7일 변화율  
  - `ats_z`: avg_trade_size 30일 z-score
- 타깃: r_1, r_3, r_7
- 검증: pooled decile spread, funding/mom 상관, LOO (BTC drop)

---

## 핵심 결과 (r_7 기준)

| 피처 | D1-D10 Spread | t-stat | n_D1 | 방향 |
|---|---|---|---|---|
| `tc_chg_7d` (거래량 변화) | **−0.0209** | **−5.55** | 5,701 | 고거래량 → **저수익** |
| `ats_chg_7d` (평균거래규모 변화) | **−0.0214** | **−6.30** | 5,643 | 고거래규모 → **저수익** |
| `ats_z` (평균거래규모 z-score) | **−0.0269** | **−7.73** | 5,674 | 고z-score → **저수익** |

**모든 피처에서 D10(고활동/고규모) 그룹이 D1(저활동)보다 7일 후 수익률이 유의하게 낮음** (p < 0.001).

---

## 기존 변수와의 중복성

| 피처 | corr(f_avg) | corr(mom30) |
|---|---|---|
| `tc_chg_7d` | +0.052 | **+0.082** |
| `ats_chg_7d` | +0.068 | **+0.096** |
| `ats_z` | +0.111 | **+0.275** |

→ **momentum(mom30)과 양의 상관** (특히 `ats_z` r=0.275).  
funding과도 약한 양의 상관.  
→ **momentum과 상당 부분 중복되는 정보**로 해석됨.

---

## LOO (BTC 제외) 안정성

| 피처 | Δ (D1-D10) | t-stat |
|---|---|---|
| `tc_chg_7d` | −0.0209 | −5.34 |
| `ats_chg_7d` | −0.0222 | −6.29 |
| `ats_z` | −0.0278 | **−7.69** |

→ BTC 제외해도 t-stat 거의 변화 없음 → **특정 종목 의존성 없음**.

---

## 경제적 해석

- **D10 (고거래활동/고거래규모) → 7일 후 저수익** → **mean-reversion / overtrading 신호**
- 고빈도/대규모 거래가 이후 반전되는 패턴 (단기 과열 후 조정)
- momentum과 양의 상관 → momentum 신호의 일부를 포착하나 **반대 방향(저수익)**으로 작용

---

## 판정: **FAIL**

### 실패 사유
| 기준 | 결과 | 비고 |
|---|---|---|
| **독립적 예측력** | ❌ | mom30과 강한 양의 상관 (0.08~0.28) → 독립 정보 아님 |
| **방향성** | ❌ | 고활동 → **저수익** (mean-reversion) → 롱온리 전략에 부적합 |
| **비용 반영 후 생존** | ❌ | 스프레드 약 2~3% (r_7) → 일간 환산 약 0.3~0.4% → 10bp 비용으로도 마진 얇음 |
| **LOO 안정성** | ✅ | BTC 제외해도 유의함 |
| **실전 활용성** | ❌ | 숏 레그 필요, 롱온리 포트폴리오에서 활용 어려움 |

### 핵심 문제
1. **중복성**: mom30과 0.08~0.28 상관 → 독립 정보 아님 (Step 25/26에서 mom 잔차 통제 시 신호 소멸 예상)
2. **반대 방향**: 고활동 → 저수익 → 롱온리 전략에서 롱 신호로 쓸 수 없음 (숏 필요)
3. **비용 문제**: 7일 2~3% 스프레드 → 일간 0.3~0.4% → 10bp 왕복 비용으로도 마진 극히 얇음
4. **롱온리 부적합**: D1(저활동) 롱, D10(고활동) 숏 구조 필요 → 실전 제약 큼

---

## 결론
거래구조 피처는 **momentum의 일부를 포착하는 보조 지표**이나, **독립적 알파 소스로는 부적합**.  
고거래활동이 단기 반전(mean-reversion)을 예고하는 현상은 통계적으로 유의하나, 실전 전략화(특히 롱온리)에는 부적합.

---

## 산출물
- `trade_structure_predictive.py` (ultra-fast)
- `findings/trade-structure-predictive-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.