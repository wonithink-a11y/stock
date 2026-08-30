track: crypto
factor: volatility-structure-predictive
date: 2026-08-29
verdict: REJECT
criteria_version: backfill-v1
conditions: ["rv/atr/range_z", "fwd7", "funding_ctrl", "momentum_ctrl"]
reason: "변동성 피처(RV·ATR·range) 7일 후 저수익 방향이 funding과 0.17~0.18 상관으로 중복, 롱온리 부적합·비용 마진 극히 얇음 - 독립 알파 소스 부적합(FAIL/REJECT)"
n: 5738
t_stat: -10.71

# Step 33 — Volatility Structure Predictive Test

날짜: 2026-08-29 | 판정: **FAIL**

## 검증 설정
- 데이터: 기존 `basis/1h/` 28종목 mark data
- 피처 (핵심 4개):
  - `rv_1d_vol`: 일간 Realized Volatility (RV)
  - `rv_7d_vol`: 7일 누적 RV
  - `range_z_vol`: 일간 range (high-low)/open의 30일 z-score
  - `atr_7d_vol`: 7일 평균 ATR/price
- 타깃: r_1, r_3, r_7 (KST daily forward returns)
- 검증: pooled decile D1-D10 spread, funding/mom 상관, LOO (BTC drop)
- 기존 데이터만 사용, 신규 수집/수정/백테스트/커밋 없음

---

## 핵심 결과 (r_7 기준)

| 피처 | D1-D10 Spread | t-stat | n_D1 | 방향 |
|---|---|---|---|---|
| `rv_1d_vol` (일간 RV) | **−0.0384** | **−10.71** | 5,738 | 고변동성 → **저수익** |
| `rv_7d_vol` (7일 RV) | **−0.0262** | **−7.92** | 5,734 | 고변동성 → **저수익** |
| `range_z_vol` (range z-score) | **−0.0294** | **−8.85** | 5,718 | 고range z → **저수익** |
| `atr_7d_vol` (7일 ATR) | **−0.0216** | **−6.49** | 5,734 | 고ATR → **저수익** |

**모든 변동성 피처에서 고변동성 그룹(D10)이 저변동성 그룹(D1)보다 7일 후 수익률이 유의하게 낮음** (p < 0.001).

---

## 기존 변수와의 중복성

| 피처 | corr(f_avg) | corr(mom30) |
|---|---|---|
| `rv_1d_vol` | **+0.168** | +0.095 |
| `rv_7d_vol` | **+0.184** | +0.088 |
| `range_z_vol` | +0.023 | +0.065 |
| `atr_7d_vol` | **+0.171** | +0.078 |

→ **funding rate(f_avg)와 양의 상관** (0.17~0.18), momentum(mom30)과도 약한 양의 상관 (0.07~0.09).
→ **funding과 상당 부분 중복**되는 정보로 해석됨.

---

## LOO (BTC 제외) 안정성

| 피처 | Δ (D1-D10) | t-stat |
|---|---|---|
| `rv_1d_vol` | −0.0394 | −10.57 |
| `rv_7d_vol` | −0.0271 | −7.88 |
| `range_z_vol` | −0.0306 | −8.89 |
| `atr_7d_vol` | −0.0224 | −6.48 |

→ BTC 제외해도 t-stat 거의 변화 없음 → **특정 종목 의존성 없음**.

---

## 경제적 해석

- **D10 (고변동성) → 7일 후 저수익** → 변동성 확대 후 **mean-reversion / 위험 회피** 패턴
- 고변동성 기간 이후 수익률 하락 → **변동성 리스크 프리미엄이 음수** (이 샘플에서)
- funding과 0.17~0.18 상관 → funding이 이미 변동성 정보를 부분적으로 포함

---

## 판정: **FAIL**

| 기준 | 결과 | 비고 |
|---|---|---|
| **독립적 예측력** | ❌ | funding과 0.17~0.18 상관 → 독립 정보 아님 |
| **방향성** | ❌ | 고변동성 → **저수익** (mean-reversion) → 롱온리 전략에 부적합 |
| **비용 반영 후 생존** | ❌ | 7일 2~4% 스프레드 → 일간 0.3~0.5% → 10bp 비용으로 마진 얇음 |
| **LOO 안정성** | ✅ | BTC 제외해도 유의함 |

### 핵심 문제
1. **중복성**: funding rate(f_avg)와 0.17~0.18 상관 → 독립 정보 아님
2. **반대 방향**: 고변동성 → 저수익 → 롱온리 전략에서 롱 신호로 쓸 수 없음 (숏 필요)
3. **비용 문제**: 7일 2~4% 스프레드 → 일간 0.3~0.5% → 10bp 왕복 비용으로 마진 극히 얇음
4. **롱온리 부적합**: D1(저변동) 롱, D10(고변동) 숏 구조 필요 → 실전 제약 큼

---

## 결론
변동성 피처(RV, ATR, range)는 **funding rate와 상당 부분 중복**되며, **고변동성 → 이후 저수익** 패턴을 보이지만 이는 **funding이 이미 포착한 정보**와 겹친다. 독립 알파 소스로는 부적합하며, 실전 롱온리 전략화는 불가.

---

## 산출물
- `volatility_structure_predictive.py` (minimal)
- `findings/volatility-structure-predictive-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.