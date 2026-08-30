---
track: kr
factor: kr-opmargin-regime
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["opMargin", "mom60_regime", "vol_regime", "residual_control", "pit_monthly", "30bps_cost"]
reason: "방향성 IC는 시간·regime 무관하게 견고(24m rolling 100% 양)하나 경제적 규모가 2023년 이후에만 2~3배 강해짐(TEST 가중 의심) - 단독 포지션 부여 보류"

---

# opMargin Time & Regime 안정성 (10-KR-21)

- 검증일: 2026-08-29
- 스크립트: `kr_opmargin_regime.py`
- 데이터: A4 PIT 월간 패널(2016~2026) + opMargin(raw A3 재현) + residual(allOther = netMargin+roe+revenueGrowth+mom60 통제). next-day entry, 월간 rebalance, 30bps/side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- regime: 등가중 cross-sectional 지수 일수익 → trailing 60D 등락(>+5% Bull / <-5% Bear / else Sideways), 60D 실현변동성(>중앙값 highVol / < lowVol)
- **기존 opMargin 정의·고정 구성(또는 top20%) 사용, 새 threshold/가중치 최적화 없음**
- **최종: WEAK** — **신호(IC) 방향은 시간·regime 전반에 안정적(10/11년 양, 24m rolling 100% 양, Bull/Bear/Sideways · 고/저변동성 모두 양)** 이지만, **경제 효과(Q5-Q1·portfolio)는 2023 이후(최근 TEST)에 집중되고 초기년도는 불안정** → 방향은 regime 무관, 세기는 기간/regime 의존.

## 1. 핵심 질문별 답

| 질문 | 답 |
|---|---|
| 특정 몇 년에만 발생? | **아니오(방향).** raw IC 10/11년 양(유일 2020 -0.003). 다만 크기는 2023~26에 급증 |
| 최근 TEST에서만 강해졌나? | **예(세기).** raw IC 2016~22 0.0~0.08 → 2023 .093 / 2024 .118 / 2025 .113 / 2026 .218 / 24m rolling 최근 구간 상승. Q5-Q1도 2023 이후에서만 양 |
| 시장 regime 무관 방향 유지? | **예.** Bull/Bear/Sideways·고/저변동성 모두 raw·residual IC 양 |
| residual도 동일 안정성? | raw보다 약하나(24m resid 양 82%) regime 전부 양. 초기년도(TRAIN)는 flat~약 |

## 2. 연도별 raw IC / resid IC / Q5-Q1 (120D, 월 평균)

| 연도 | rawIC | residIC | Q5-Q1 |
|---|---|---|---|
| 2016 | +.008 | – | -0.013 |
| 2017 | +.035 | +.036 | -0.067 |
| 2018 | +.006 | -0.011 | -0.017 |
| 2019 | +.083 | +.011 | +0.040 |
| 2020 | -0.003 | +.002 | -0.081 |
| 2021 | +.036 | +.003 | -0.012 |
| 2022 | +.064 | +.015 | +0.003 |
| 2023 | +.093 | +.064 | +0.014 |
| 2024 | +.118 | +.067 | +0.033 |
| 2025 | +.113 | +.049 | +0.008 |
| 2026 | +.218 | +.116 | +0.152 |

- **raw IC: 2016년부터 거의 매년 양(10/11)** — 특정 몇 년 현상은 아님.
- **Q5-Q1: 처음 7년(2016~22) 중 5년 음 → 최근 4년 전부 양.** 경제적 스프레드는 2023 이후에서만 일관. → 10-KR-19의 "TRAIN 약·TEST 강"을 시간 축에서 재확인.

## 3. 24개월 rolling IC (120D)

- raw: **96/96 (100%) 양**, resid: **79/96 (82%) 양**.
- 방향은 시간에 걸쳐 극도로 안정(raw). residual은 대부분 양이나 약 18% 구간 음(2016~18 상당수).

## 4. Regime별 IC (raw/resid) + top-Q portfolio

| regime | n | rawIC(t) | residIC(t) |
|---|---|---|---|
| Bull | 42m | +.036 (2.8) | +.013 (1.8) |
| Bear | 29m | +.074 (**6.2**) | +.021 (2.4) |
| Sideways | 47m | +.075 (**7.2**) | +.044 (**6.2**) |
| highVol | 57m | +.057 (5.9) | +.019 (3.1) |
| lowVol | 62m | +.061 (5.8) | +.036 (5.5) |

→ **모든 regime에서 raw·residual IC 양.** 방향이 regime 특정이 아님. Sideways가 가장 강, Bull 가장 약(그래도 양). residual은 Bull에서만 경계(t=1.8).

**top-Q portfolio CAGR (월별, net) — 셀 샘플 적음(regime×기간)**: 
- Bull: TRAIN -6.9 / VALID -13.1 / TEST +17.3 (Sh .72) — TEST만 양
- Bear: TRAIN +26.9 / VALID +8.0 / TEST **-24.4** — TEST 음
- Sideways: TRAIN -24.1 / VALID -2.3 / TEST +10.3
- highVol: TRAIN +10.2 / VALID +6.4 / TEST -5.4
- lowVol: TRAIN -13.1 / VALID +3.7 / TEST +13.9 (Sh 1.45)

→ **portfolio 경제성은 regime·기간에 걸쳐 부호가 뒤섞임**(같은 regime 내에서도 TRAIN/TEST 반대). regime×기간 셀 샘플이 얇아 노이즈 크나, 경제적으론 안정적이지 않다는 점은 명확.

## 5. TRAIN/VALID/TEST reference

| | rawIC(t) | residIC(t) |
|---|---|---|
| TRAIN | +.029 (3.3) | +.006 (1.2) |
| VALID | +.091 (7.4) | +.051 (5.8) |
| TEST | +.123 (13.4) | +.062 (10.0) |

raw·residual 모두 시간에 따라 단조 강화(2016~26 누적). 최근일수록 신호가 셉니다.

## 6. 판정: **WEAK**

- **PASS 후보 아님**: 여러 regime·기간에서 "경제성"이 안정적이지 않음. Q5-Q1은 처음 7년 대부분 음(2023 이후에만 양), top-Q portfolio는 regime·기간별 부호 혼재(특히 Bear TEST -24%), 초기년도 residual flat.
- **REJECT 아님**: 방향이 특정 기간에만 존재하는 게 아님. raw IC 2016년부터 10/11년 양, 24m rolling 100% 양, 모든 regime(방향) 양. 최근 TEST에만 "존재"하는 게 아니라 "세기"가 강해진 것.
- **WEAK (채택)**: *"신호는 안정적이나 특정 regime/기간 의존"*. 10-KR-19(구성/기간 의존)·20(증분 portfolio 불안정)과 일관 — opMargin은 **방향성 신호(true positive IC)로는 시간·regime 무관하게 견고하지만, 그 세기와 경제 실현은 2023+ recent 기간에 집중**.

## 7. 메모

- raw 방향 안정성은 유의미한 재현 증거(Covid·Bull·Bear·Sideways·저변동성 모두 양)지만, **경제적 규모가 최근에 2~3배 강해진 것**은 10-KR-19~20의 "TEST 가중" 경고와 일치. 단독 포지션 부여는 여전히 보류.
- 후속(기록용): 신호 세기의 시간 가중(최근 과대표출)을 보정하거나, 세기가 강한 조건에서만(예: 최근 regime) 조건부 사용 여부 판단. 현재 검증 스코프 밖.

## 8. 제한 준수

- 새 threshold/가중치 최적화 없음 — 기존 opMargin 정의, 고정 top20% 구성, 고정 regime 정의. TEST 결과로 조정 없음.

---

산출물: `reports/2026-08-28-kr-opmargin-regime/kr-opmargin-regime-results.json`
