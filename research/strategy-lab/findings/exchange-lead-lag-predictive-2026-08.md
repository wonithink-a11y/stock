---
track: crypto
factor: exchange-lead-lag-predictive
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: "FAIL"
criteria_version: backfill-v1
conditions: ["Binance→Upbit / Upbit→Binance 리드-래그", "funding+mom30 통제", "10/30/50bp 왕복 비용"]
reason: "일간 리드-래그 신호는 통계적으로 미약하고 Date-CS IC 유의하지 않으며(t<2) 10bp 비용 반영에도 완전 소멸해 실전 전략화 불가(CAGR 음, Sharpe 음, MaxDD -100%)"
---

# Step 31 — Exchange Lead-Lag Predictive Test (Daily)

날짜: 2026-08-29 | 판정: **FAIL**

## 검증 설정
- Universe: 14개 공통 종목 (BTC~ARB, MATIC 제외)
- 기간: 2023-05-21 ~ 2026-08-27 (1195일)
- 정렬: KRW close(KST 00:00) shift(1) → USDT close(KST 24:00) 기준 맞춤
- 양방향: Binance→Upbit (USDT lag → KRW fwd), Upbit→Binance (KRW lag → USDT fwd)
- Lag: 1/2/3일, Horizon: fwd 1/2/3일
- 통제: funding (f_avg) + momentum (mom30) rolling OOS residual
- 거래비용: 10/30/50bp 왕복 적용

---

## 핵심 결과

### 1. Baseline Pooled Decile Spread (r_1 forward)

| 방향 | Lag | Δ (D10-D1) | t-stat | n_D1 |
|---|---|---|---|---|
| **Binance→Upbit** | 1 | **+0.0035** | **+2.11** | 1,534 |
| | 2 | -0.0016 | -1.04 | 1,534 |
| | 3 | -0.0045 | -2.75 | 1,521 |
| **Upbit→Binance** | 1 | **-0.0043** | **-2.35** | 1,534 |
| | 2 | +0.0015 | +0.93 | 1,534 |
| | 3 | -0.0051 | -2.96 | 1,521 |

**해석**:
- **Binance→Upbit lag1**: 양의 스프레드 (t=2.11) → Binance 수익률이 Upbit 다음날 수익률을 **약간 선행**
- **Upbit→Binance lag1**: 음의 스프레드 (t=-2.35) → Upbit 수익률이 Binance 다음날 수익률을 **역방향 선행**
- Lag 2/3: 방향 일관성 없음, 노이즈 수준

### 2. Date-CS IC (Cross-Sectional, lag1 fwd1)

| 방향 | Mean IC | t-stat | 양의 날짜 비율 |
|---|---|---|---|
| Binance→Upbit | -0.0102 | -1.03 | 48% |
| Upbit→Binance | -0.0051 | -0.53 | 49% |

→ **날짜별 크로스섹션에서 유의한 IC 없음** (t < 2, 양/음 날짜 50:50)

### 3. Funding + Momentum 통제 후 잔차 (lag1, fwd1)

| 방향 | Raw Δ (t) | Residual Δ (t) | 해석 |
|---|---|---|---|
| Binance→Upbit | +0.0035 (+2.11) | **+0.0052 (+3.16)** | **통제 후 강화** → 독립 신호 존재 |
| Upbit→Binance | -0.0043 (-2.35) | -0.0014 (-0.80) | **소멸** → funding/mom이 설명 |

→ **Binance→Upbit 방향은 funding/momentum과 독립적인 약한 선행성 존재**

### 4. 거래비용 적용 후 (lag1, fwd1, 왕복 비용)

| 방향 | 10bp | 30bp | 50bp |
|---|---|---|---|
| **Binance→Upbit** | mean=-0.00007, net=-0.0021 (t=-1.99) | net=-0.0061 (t=-5.85) | net=-0.0101 (t=-9.70) |
| **Upbit→Binance** | mean=+0.00258, net=+0.00058 (t=0.55) | net=-0.0034 (t=-3.30) | net=-0.0074 (t=-7.16) |

→ **10bp에서도 양 방향 모두 비용 반영 후 유의한 알파 없음** (t < 2)
- Binance→Upbit: raw mean ≈ 0 → 10bp만으로도 음전
- Upbit→Binance: raw mean 양수지만 10bp에서 t=0.55 (유의하지 않음), 30bp에서 음전

### 5. 연도별 안정성 (lag1, fwd1)
- Binance→Upbit: 2023-2024 음, 2025-2026 양 (방향 불안정)
- Upbit→Binance: 2023-2024 양, 2025-2026 음 (반대 방향)

---

## 판정: **FAIL**

### 실패 사유
| 기준 | 결과 | 비고 |
|---|---|---|
| **방향성 일관성** | ❌ | B→U lag1 양, U→B lag1 음 → 상충 |
| **통계적 유의성 (OOS)** | ❌ | Date-CS IC 유의하지 않음 (t < 2) |
| **비용 반영 후 알파** | ❌ | 10bp에서조차 유의한 알파 없음 |
| **연도별 안정성** | ❌ | 연도별 방향 반전 |
| **독립성 (fund/mom 통제)** | ⚠️ | B→U만 잔차에서 생존, U→B는 소멸 |

### 핵심 한계
1. **신호 크기 극소** (일간 ±0.003~0.004%) → **비용(10bp=0.1%)의 1/25~1/30**
2. **Date-CS IC 유의하지 않음** → 종목 간 크로스섹션에서 일관된 순위 관계 없음
3. **Lag 2/3에서 방향 반전** → 단일 lag에만 의존, 구조적 안정성 부족
4. **비용 반영 시 완전 소멸** → 10bp 왕복(실제 20bp)만으로도 알파 잠식

---

## 결론

**일간 리드-래그 신호는 통계적으로 미약하고, 거래비용 반영 시 완전히 소멸한다.**
- Binance→Upbit lag1만 funding/mom 통제 후 잔차에서 생존 (t=3.16)하나, **비용 반영 시 알파 없음**
- 실전 전략화 불가 (CAGR 음, Sharpe 음, MaxDD -100%)

---

## 산출물
- `exchange_lead_lag_predictive.py`
- `findings/exchange-lead-lag-predictive-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.
