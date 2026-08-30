---
track: kr
factor: kr-institutional-flow
date: 2026-08-28
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["inst_flow", "foreign_flow+mom60_control", "pit_monthly", "30bps_cost"]
reason: "기관 수급 잔차 정보 TRAIN·VALID 유의 양이나 TEST에서 0/음으로 붕괴, portfolio도 TEST 음 - OOS-stable incremental value 미확보"
---
# KR 기관 수급 — 최소 검증

- 검증일: 2026-08-28
- 스크립트: `kr_institutional_flow_validation.py`
- 데이터: A4 `a4-research-dataset.parquet`, 2016~2026, 2,558 종목
- OOS 분할: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 비용: 15bps per side
- **최종 판정: WEAK**

## 1. 정보축 정의 (PIT-safe, backward rolling)

| 축 | Feature | 정의 |
|---|---|---|
| magnitude | `inst_flow_ratio` | `inst_net / total_amount` |
| cumulative 5D | `inst_5d_ratio` | `inst_nb_5d / amt5` (거래대금 정규화) |
| cumulative 20D | `inst_20d_ratio` | `inst_nb_20d / amt20` |
| acceleration | `inst_accel` | `inst_flow_ratio - inst_nb20_ratio` |
| liquidity-adjusted | `inst_per_logamt` | `inst_net / log1p(total_amount)` |

forward 5D/20D close-to-close, 월별 재조정, 128 rebalance month. 당일 수급은
close 이후 확정 → close[t] 진입.

## 2. 단독 검증 — Q5-Q1 / IC (기관 수급)

| Axis | TRAIN 5D | VALID 5D | TEST 5D | TRAIN 20D | VALID 20D | TEST 20D |
|---|---|---|---|---|---|---|
| magnitude | +0.006 (t=1.5) | +0.014 (t=1.8) | -0.003 (t=-0.4) | -0.001 (t=-0.2) | +0.012 (t=1.4) | -0.005 (t=-0.7) |
| cum5d | -0.007 (t=-1.4) | -0.001 (t=-0.1) | +0.002 (t=0.2) | -0.011 (t=-2.2) | +0.015 (t=1.2) | +0.006 (t=0.7) |
| cum20d | -0.009 (t=-1.6) | -0.003 (t=-0.3) | +0.006 (t=0.6) | -0.015 (t=-2.9) | +0.002 (t=0.2) | +0.008 (t=0.8) |
| acceleration | +0.008 (t=2.0) | +0.017 (t=2.4) | -0.006 (t=-1.0) | +0.007 (t=1.9) | +0.010 (t=1.0) | -0.009 (t=-1.7) |
| liq_adjusted | +0.009 (t=2.1) | +0.015 (t=2.0) | -0.008 (t=-1.0) | +0.003 (t=0.7) | +0.010 (t=1.3) | -0.010 (t=-1.5) |

**관찰 1 — 단독으로는 약하고 불안정.** 기관 수급 단독 IC는 대부분 |t|<2.5로 약하고,
acceleration·liq-adjusted만 TRAIN/VALID 5D에서 t≈2로 미약한 양(+), **TEST에서 음(-)으로
뒤집힘**. cum5d/cum20d는 TRAIN에서 오히려 음. 단독으로는 기관 수급이 안정적 alpha를
주지 않음.

## 3. 핵심 검증 — residual IC (독립성)

### orth | foreign_flow_ratio + mom60 (외국인 수급 + 가격 factor 통제)

| Axis | TRAIN 5D | VALID 5D | TEST 5D | TRAIN 20D | VALID 20D | TEST 20D |
|---|---|---|---|---|---|---|
| magnitude | **+0.014 (t=3.6)** | **+0.019 (t=2.7)** | **-0.000 (t=-0.0)** | +0.004 (t=0.9) | **+0.018 (t=2.5)** | -0.003 (t=-0.4) |
| acceleration | **+0.012 (t=3.2)** | **+0.015 (t=2.1)** | -0.004 (t=-0.7) | +0.007 (t=1.8) | +0.008 (t=0.9) | -0.008 (t=-1.5) |
| liq_adjusted | **+0.016 (t=4.0)** | **+0.020 (t=2.6)** | -0.006 (t=-0.8) | +0.007 (t=1.6) | **+0.017 (t=2.3)** | -0.008 (t=-1.2) |
| cum5d | +0.001 (t=0.2) | +0.008 (t=1.0) | +0.003 (t=0.4) | -0.002 (t=-0.5) | +0.024 (t=2.5) | +0.007 (t=1.0) |
| cum20d | -0.001 (t=-0.2) | +0.010 (t=1.2) | +0.007 (t=0.9) | -0.005 (t=-1.1) | +0.016 (t=1.8) | +0.010 (t=1.2) |

**관찰 2 — 인-샘플(TRAIN+VALID)에서는 기관 수급이 외국인 수급·가격 통제 후에도
유의한 양(+) 잔차를 가짐.**

magnitude·acceleration·liq-adjusted가 TRAIN 5D(t=3.2~4.0)와 VALID 5D(t=2.1~2.7)에서
모두 **양(+)으로 유의**. 20D에서도 magnitude·liq-adjusted가 VALID에서 양(+).
이것은 기관 수급이 **외국인 수급·mom60이 설명하지 못하는 독립 정보**를 인-샘플에서
가지고 있음을 의미.

**핵심 질문 답변**: "기관 수급이 기존 factor들이 설명하지 못하는 OOS-stable
incremental information을 제공하는가?" → **부분적으로 그렇다(TRAIN·VALID)지만
TEST에서 붕괴 → 안정적이진 않다.**

### orth | foreign_flow_ratio only (외국인만 통제, 가격 제외)

방향은 동일 — magnitude/acceleration/liq이 TRAIN·VALID 5D에서 양(+) 마진리, TEST 음.
가격통제를 빼도 같은 결론.

## 4. TEST 구간 실패

**관찰 3 — 결정적 한계: TEST(2024-2026)에서 잔차 IC가 0 근처/음으로 붕괴.**
모든 축에서 TEST 5D·20D 잔차 t가 -1.7 ~ +1.2로 비유의, magnitude·accel·liq은 음.
**TRAIN·VALID에선 살아 있고 TEST에선 죽는** 전형적 퇴화 패턴. 외국인 수급(10-KR-7)과
같이 최근 구간에서 매매가 불안정해진 것과 일치.

## 5. Portfolio (long top-Q5, 월별, net 30bps)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| magnitude | +0.6% (Sh 0.13) | +8.8% (Sh 0.56) | **-2.6%** (Sh -0.03) |
| acceleration | +3.3% (Sh 0.26) | +7.8% (Sh 0.49) | **-4.1%** (Sh -0.09) |

**관찰 4 — 포트폴리오는 VALID에서만 뚜렷한 양(+), TEST에서 음.**
준비지표(approx, 20% 종목×2side/월 재조정). 실매매 alpha로는 TEST 실패로 채택 어려움.

## 6. 최종 판정: WEAK

### 판정 근거

1. **독립 정보는 존재하나 단독 약함.** residual 기준 기관 수급이 외국인+가격
   통제 후 TRAIN·VALID에서 모두 유의 양(+) — 독립성은 어느 정도 확보됨.
   그러나 단독 IC는 약하고.

2. **OOS-stable이 아님 — TEST 붕괴가 결정적 약점.** 3 기간 중 TRAIN·VALID는
   양(+)이지만 TEST(최근)에서 잔차 IC 0/음으로 뒤집힘. "3구간 안정성" 기준을
   충족하지 못함.

3. **portfolio도 TEST 음.** 실매매 alpha 아님.

4. **기존 결론과 정합.** 기관 수급은 기존 `flow-basic-effect`에서 REJECT였으며,
   이번 검증은 그 이유(최근 퇴화)를 residual 관점에서 다시 확인. 인-샘플 독립성은
   실리나 최근 OOS에서 실패 → WEAK.

### 절대 하지 않음

- lookback/threshold 최적화
- TRAIN·VALID의 양(+)만 골라 TEST 재튜닝
- cum 축 중 일부만 선택
- 기존 전략과 임의 결합

기관 수급은 기존 foreign-flow + 가격 factor 대비 **인-샘플 독립 정보는 있으나
TEST에서 퇴화하여 OOS-stable incremental value를 확보하지 못함 → WEAK**로 종료.

---

산출물: `reports/2026-08-28-kr-institutional-flow/kr-institutional-flow-results.json`
