---
track: kr
factor: kr-pbr-incremental
date: 2026-08-29
verdict: REJECT
criteria_version: backfill-v1
conditions: ["pbr_top30", "lowmom60_top30", "50_50_two_sleeve", "pit_monthly", "30bps_cost"]
reason: "PBR 단독은 신호·TEST 모두 우수(TEST resid IC t=-9.0, +14.4% Sh .80)이나 50/50 결합 incremental은 기간별 부호 반전(TRAIN -0.78/VALID -2.15/TEST +7.65pp) - TEST 개선은 baseline 퇴화 구간에서만"
cagr: 9.3
sharpe: 0.47
mdd: -24.6
---
# PBR Incremental Alpha — vs LOWMOM60 (10-KR-15)

- 검증일: 2026-08-29
- 스크립트: `kr_pbr_incremental.py`
- 데이터: A4 `a4-research-dataset.parquet` + `valuation-panel.jsonl`(PBR, PIT)
- 비교 (동일 universe/기간/비용, PIT-safe next-day entry, 월간 rebalance, 등가중):
  1. **baseline** = LOWMOM60 (최저 60D 모멘텀 상위 30, turnover20 ≥ 1억, `strategies/lowmom60_v1` 규칙)
  2. **pbr_only** = 저PBR 상위 30 (pbr>0, turnover20 ≥ 1억, `strategies/pbr_value_v1` 규칙)
  3. **combined** = 50/50 two-sleeve
- 비용 15bps/side(월 round-trip 30bps). PBR threshold/lookback/weight 재탐색 없음, TEST 기반 변경 없음.
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **최종 판정: REJECT (LOWMOM60 대비 incremental 관점)**

## 1. 결과 (net 기준, [gross] 병기)

| Portfolio | TRAIN | VALID | TEST |
|---|---|---|---|
| baseline (LOWMOM60) | +6.1% [10.0%] Sh .35 / MDD -32.6% | +13.3% [17.4%] Sh .51 / MDD -27.9% | +1.7% [5.4%] Sh .22 / MDD -35.1% |
| pbr_only (저PBR) | +3.5% [7.3%] Sh .27 / MDD -46.5% | +7.7% [11.7%] Sh .43 / MDD -12.6% | **+14.4% [18.5%] Sh .80 / MDD -17.7%** |
| **combined (50/50)** | +5.4% [9.2%] Sh .34 | +11.1% [15.2%] Sh .51 | +9.3% [13.3%] Sh .47 |

## 2. Incremental

| (combined − baseline) | TRAIN | VALID | **TEST** |
|---|---|---|---|
| CAGR net diff | **-0.78pp** | **-2.15pp** | **+7.65pp** |
| CAGR gross diff | -0.80pp | -2.24pp | +7.89pp |
| Sharpe diff | -0.009 | -0.001 | +0.246 |
| MDD diff | **-6.77pp (악화)** | +7.62pp (개선) | +10.42pp (개선) |

| (pbr_only − baseline) | TRAIN | VALID | **TEST** |
|---|---|---|---|
| CAGR net diff | **-2.60pp** | **-5.53pp** | **+12.74pp** |
| Sharpe diff | -0.075 | -0.082 | **+0.575** |
| MDD diff | **-13.9pp (악화: -46.5% cu -32.6%)** | +15.3pp (개선) | +17.4pp (개선) |

## 3. 독립성 검증 — 신호·포트폴리오 수준

- **이름은 거의 분리** (Jaccard overlap ~0.002-0.004): 선정 종목은 3기간 모두 거의 겹치지 않음.
- **수익률 상관은 높음** (TRAIN .73 / VALID .75 / TEST .49): 이름은 달라도 두 sleeve가 같은 광범위 시장 팩터(모멘텀/가치 광의)에 공동 로딩.
- **신호 수준 독립성은 확보** (liquid universe, resid | mom60):
  - PBR IC: TRAIN -0.100 (t=-6.0) / VALID -0.086 (t=-3.7) / TEST -0.123 (t=-5.6) (60D)
  - PBR resid IC | mom60: TRAIN -0.094 (t=-5.7) / VALID -0.083 (t=-3.6) / TEST -0.124 (t=-5.8) (60D); 120D TEST t=-9.0
  - → 저PBR 신호는 모멘텀 통제 후에도 **3기간 모두 유의하게 독립적**.

## 4. 핵심 질문 답변 — REJECT

> TEST에서 PBR 단독 효과가 존재하면서, LOWMOM60에 추가했을 때도 **안정적인** incremental alpha가 발생하는가?

- **PBR 단독 효과 (신호·TEST): 예.** PBR 저가 신호는 3기간 모두 raw·잔차 유의(TEST 120D resid t=-9.0), TEST에서 standalone +14.4% Sh .80으로 baseline(+1.7%) 대비 월등. 10-KR-14의 PASS 판정과 일치.
- **LOWMOM60에 추가했을 때 incremental: 안정적이지 않음 → 아니오.**
  - combined − baseline CAGR이 부호가 기간별로 뒤집힘: TRAIN **-0.78pp**, VALID **-2.15pp**, TEST **+7.65pp**.
  - **3구간 중 2구간에서 감손**. TEST 개선만 있고, 그것도 **baseline(LOWMOM60)이 +1.7%로 퇴화한 구간에서만** 나타남 — 10-KR-13(HighShock reversal)과 동일 패턴.
  - gross diff도 3구간 중 2구간 마이너스 → **비용 탓이 아니라 sleeve 조합 자체의 열위**.
- **독립 수익원 여부**: 신호 수준에서는 모멘텀과 독립적(resid IC 유의)이나, **portfolio 수익률 상관이 .73/.75/.49로 커서** 신호 독립이 그대로 "증분 alpha"로 안 되고, TRAIN·VALID에선 오히려 저PBR이 모멘텀 sleeve를 깎아내림.
- 판정 요지: **PBR은 단독 factor로는 PASS(10-KR-14), 그러나 기존 검증 전략 LOWMOM60에 붙였을 때 OOS-stable incremental alpha를 주지 않으므로 이 실험(증분 관점)에서는 REJECT.**

## 5. 경제성 / 거래량

| | baseline | pbr_only | combined |
|---|---|---|---|
| 평균 turnover/rebal (TRAIN) | 0.69 | 0.20 | — |
| 거래 side (TEST) | 878 | 926 | 1,804 |
| MDD (TEST) | -35.1% | -17.7% | -24.6% |

- 저PBR sleeve는 turnover가 낮고(재선정 빈도 낮음) TEST MDD가 baseline보다 크게 낮음 — **리스크 관점에서는 매력적**.
- 즉 "LOWMOM60 대신 PBR"로 대체하거나, 리스크 저감 목적으로 쓰면 TEST에선 유리하나, **fixed 50/50 combination은 OOS incremental CAGR 관점에서 안정적이지 않음**.

## 6. 최종 판정: REJECT (incremental 관점)

### 판정 근거

1. **fixed 50/50 incremental이 OOS-stable하지 않음.** 부호가 기간별로 뒤집힘 — TRAIN -0.78pp / VALID -2.15pp / TEST +7.65pp. 3구간 중 2구간 감손, gross에서도 동일 → 열위는 비용 아님.
2. **TEST 개선은 퇴화 baseline 위에서만**(LOWMOM60 +1.7%) — 10-KR-13 REJECT와 동일한 "baseline이 약할 때만 살아나는" 패턴.
3. **PBR 단독은 별개의 문제다**: 신호·TEST 성과는 우수하고(10-KR-14 PASS, resid IC 3기간 유의) 이 실험은 그 진실을 부정하지 않는다. 다만 **"기존 LOWMOM60에 붙였을 때 안정적 증가분"이라는 10-KR-15의 서술은 충족되지 않음**.
4. portfolio 수익률 상관이 .49-.75로 높아 신호 독립(이름 분리)과 달리 두 sleeve의 수익원이 실질적으로 상당히 공유 — 고정 50/50에서의 기대 분산 효과 확보 미흡.

### 절대 하지 않음

- TEST만의 +7.65pp를 근거로 채택 (TEST-driven)
- 50/50 외 비중 최적화 (가중치 탐색 금지)
- PBR threshold·lookback 재탐색
- 다른 factor 추가/결합
- 기존 결과를 유리하게 만들기 위한 규칙 변경

---

산출물: `reports/2026-08-28-kr-pbr-incremental/kr-pbr-incremental-results.json`