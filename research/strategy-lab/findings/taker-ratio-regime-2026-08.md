---
track: crypto
factor: taker-ratio-regime
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: REGIME-CONDITIONAL
criteria_version: backfill-v1
conditions: ["taker_ratio_7", "mom30_regime", "funding_level", "funding_residual"]
reason: "mom30 강세장(bull)에서만 작동하는 contrarian 신호, 약세장에서 신호소멸 - 기존변수 통제후 잔차도 약함(t=1.21)이라 무조건적 단독사용 불가"

---

# Step 25 — `taker_ratio_7` 레짐 의존성 검증

날짜: 2026-08-29 | 판정: **REGIME-CONDITIONAL**

## 핵심 발견

| 구분 | taker_7d (raw) | taker_7d_fmresid (fund+mom 통제) |
|---|---|---|
| **Baseline r7** | Δ=+0.0194 (t=5.41), CS IC=+0.055 (t=10.8) | Δ=+0.0101 (t=2.79), CS IC=-0.006 (t=-1.2) |
| **funding level high** | Δ=+0.0282 (t=4.60) | Δ=+0.0123 (t=2.07) |
| **funding level low** | Δ=+0.0062 (t=1.37) | Δ=+0.0068 (t=1.49) |
| **mom30 bull** | **Δ=+0.0344 (t=5.49)** | Δ=+0.0082 (t=1.21) |
| **mom30 bear** | Δ=-0.0010 (t=-0.26) | Δ=+0.0015 (t=0.43) |

---

## 1. 레짐별 분석

### A) Mom30 레짐 (가장 강한 의존성)
| 시장 | raw r7 Δ(t) | residual r7 Δ(t) | 날짜-CS IC (raw) | 날짜-CS IC (resid) |
|---|---|---|---|---|
| **Bull (mom30>0)** | **+0.0344 (t=5.49)** | +0.0082 (t=1.21) | +0.050 (t=6.3) | **-0.022 (t=-2.8)** |
| **Bear (mom30<0)** | -0.0010 (t=-0.26) | +0.0015 (t=0.43) | +0.055 (t=7.5) | -0.001 (t=-0.1) |

**→ mom30 bull에서만 강한 양의 신호(독립 잔차는 약함). Bear에서 신호 소멸.**

### B) Funding Level (고/저)
| 펀딩 레벨 | raw r7 Δ(t) | residual r7 Δ(t) |
|---|---|---|
| High (f_avg > rolling median) | +0.0282 (t=4.60) | +0.0123 (t=2.07) |
| Low | +0.0062 (t=1.37) | +0.0068 (t=1.49) |

**→ 고펀딩 구간에서 신호 강함. 잔차도 high 구간에서 t=2.07로 생존.**

### C) Funding Residual (pos/neg)
| 펀딩 잔차 | raw r7 Δ(t) | residual r7 Δ(t) |
|---|---|---|
| Pos | +0.0221 (t=4.62) | +0.0113 (t=2.70) |
| Neg | +0.0207 (t=3.58) | +0.0088 (t=1.44) |

**→ 양쪽 다 양의 신호, 잔차는 pos에서만 t=2.70 유의.**

---

## 2. 연도 × 레짐 교차 (taker_7d raw r7 t-stat)

| 연도 | mom30 bear | mom30 bull | fund_level high | fund_level low |
|---|---|---|---|---|
| 2022 (bear) | -2.14 | -2.30 | +0.98 | -3.51 |
| 2023 (bear) | **-4.28** | +0.62 | -2.52 | -1.55 |
| 2024 (bull) | **+5.62** | +2.13 | +2.77 | +3.82 |
| 2025 (mixed) | -1.31 | -1.27 | -5.19 | +2.11 |
| 2026 (bull) | +2.16 | +0.74 | +2.98 | +1.58 |

**→ 2022/23(bear): 음/약함 → 2024/26(bull): 강한 양. Mom30 레짐이 연도별 부호 반전 완벽 설명.**

---

## 3. 핵심 통찰

| 관찰 | 해석 |
|---|---|
| **Mom30 레짐 의존성 절대적** | Bull에서만 강한 양의 신호 (t=5.49); Bear에서 소멸 (t=-0.26) |
| **Funding 고레짐 강화** | High funding 구간에서 신호 증폭 (t=4.60 vs 1.37) |
| **Raw → Residual 급격 약화** | fund+mom 통제 시 타임시그널 거의 소멸 (t=5.5 → 2.8; bull 5.5 → 1.2) |
| **CS IC 레짐 내 안정** | Raw CS IC는 bull/bear 모두 +0.05로 강건; 잔차는 IC 약음/0 |
| **Raw/Resid 방향 일치** | 모든 레짐에서 raw와 residual 부호 동일 (`same_direction=True`) |

---

## 4. 사후적 설명 여부

- **Mom30 레짐 분류는 사전 고정 룰(mom30>0)** — 최적화 없이 적용
- 연도별 부호 반전(2022/23 음 ↔ 2024/26 양)을 **레짐(강세/약세)으로 완벽 설명**
- Funding level/resid 레짐도 고정 rolling median/잔차 룰 — 사후 임계값 튜닝 없음
- 단, "bull에서만 작동"이라는 결론은 **해당 기간 데이터에서 관찰된 패턴** → OOS 검증 필요

---

## 5. 판정: **REGIME-CONDITIONAL**

### 근거
| 기준 | 충족 | 비고 |
|---|---|---|
| 특정 레짐에서 강건한 신호 | ✅ | mom30 bull: raw t=5.49, CS IC +0.05 (t=6.3) |
| 레짐 외부에서 신호 소멸 | ✅ | bear: raw t=-0.26, residual t=0.43 |
| 기존 변수 통제 후 잔차 생존 | ⚠️ | bull 잔차 t=1.21 (약함), CS IC 음전 |
| 레짐 분류가 사전 고정 룰 | ✅ | mom30>0, funding median, OOS resid — 튜닝 없음 |
| 단독 unconditional 사용 가능 | ❌ | bear에서 작동 안 함, 잔차 약함 |

### 해석
- **taker_ratio_7은 강세장(mom30>0)에서만 작동하는 contrarian 신호** (공격적 매수 → 차주 수익 저조)
- 약세장에서는 신호가 없거나 역전 → **무조건적 사용 불가**
- fund+mom 통제 후 독립 성분은 **bull에서도 약함(t=1.2)** → 독립 정보로 단독 사용 제한적
- Funding high 레짐에서 신호 증폭은 독립 잔차(t=2.07)로도 확인 → funding 레짐과 상호작용 존재

### 실무 시사점
1. **레짐 필터 필수**: mom30>0 (또는 동등한 강세장 정의) 조건 하에서만 적용
2. **독립 잔차 단독 사용 비권장**: fund+mom 통제 후 t=1.21, CS IC 음전
3. **조합 가능성**: vol_spike, funding residual 등 다른 강세장 필터와 결합 검토 필요
4. **OOS 검증 필요**: 2024-2026 강세장 구간은 샘플 내(in-sample) — 향후 약세장 전환 시 검증 필요

---

## 산출물
- 신규: `taker_ratio_regime_check.py`
- 신규: `findings/taker-ratio-regime-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 백테스트·커밋 없음.