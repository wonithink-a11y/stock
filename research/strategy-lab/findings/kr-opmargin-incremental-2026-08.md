---
track: kr
factor: kr-opmargin-incremental
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["opMargin", "roe_orthogonalize", "netMargin_control", "50_50_rank_combo"]
reason: "opMargin은 ROE orthogonalize 후 3기간 유의로 독립 정보가 입증되나 결합 portfolio 증분이 TRAIN에서 flat/불안정해 매매 가능한 3기간 안정 alpha 미확보 - WEAK"
cagr: 6.4
sharpe: 0.58
---
# opMargin Incremental Alpha — 독립성 vs 대리변수 (10-KR-20)

- 검증일: 2026-08-29
- 스크립트: `kr_opmargin_incremental.py`
- 데이터: A4 PIT 월간 패널(2016~2026) + A3/quality-panel 재현 opMargin·netMargin·roe·revenueGrowth. next-day entry, 월간 rebalance, 30bps/side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 50/50 rank 결합만 사용 — **가중치·threshold 최적화 없음** (TEST 결과로 조정 안 함)
- 질문: opMargin이 자체로 좋은가? 다른 quality factor의 대리변수인가? 독립 정보를 추가하는가?
- **최종: WEAK** — 독립성은 명확(특히 ROE orthogonalize 후 3기간 유의, 전 control-set 후 VALID·TEST 강한 유의)하지만, **portfolio 증분 알파가 TRAIN에서 flat/불안정** → 3기간 안정 incremental portfolio alpha 미확보.

## 1. Factor 간 상관 (full-sample rank)

| pair | corr |
|---|---|
| netMargin ~ opMargin | **0.824** |
| netMargin ~ roe | **0.886** |
| opMargin ~ roe | **0.763** |
| opMargin ~ revenueGrowth | 0.275 |
| revenueGrowth ~ roe | 0.275 |

→ margin·ROE는 타이트한 "profitability-quality" collinear 계열. opMargin은 ROE/netMargin과 상관 높음(대리변수 의심 근거). revenueGrowth와는 독립적.

## 2. Residual IC — opMargin을 각 factor에 orthogonalize (120D, NW t)

| control | TRAIN | VALID | TEST |
|---|---|---|---|
| (raw) | +.028 (3.3) | +.091 (7.4) | +.123 (13.4) |
| netMargin | +.004 (0.7) | +.053 (**6.9**) | +.070 (**10.4**) |
| **roe** | **+.015 (2.5)** | **+.052 (7.5)** | **+.050 (7.2)** |
| revenueGrowth | +.033 (3.7) | +.091 (6.6) | +.125 (14.5) |
| mom60 | +.031 (3.6) | +.097 (8.4) | +.125 (13.2) |
| **allOther(netMargin+roe+revG+mom60)** | +.006 (1.2) | +.051 (**5.8**) | +.062 (**10.0**) |

- **opMargin|roe: 3기간 모두 유의 양**(TRAIN t=2.5 포함) — ROE라는 최강 collinear factor를 제거해도 독립 잔류 정보가 3기간 유지. → **opMargin은 ROE의 단순 대리변수가 아님**.
- opMargin|netMargin, opMargin|allOther: VALID·TEST 강한 유의, **TRAIN은 flat**(음 아님, t=1.2~1.9). 방향 역전은 없고 TRAIN에서만 약화.

## 3. factor 단독 portfolio (top20%, CAGR net)

| factor | TRAIN | VALID | TEST |
|---|---|---|---|
| opMargin | +0.2% | +1.9% | +4.0% |
| netMargin | +0.8% | +1.6% | +3.8% |
| roe | +0.6% | +2.7% | +4.6% |
| revenueGrowth | +3.0% | +1.1% | +5.9% |

모두 TEST 양, TRAIN은 ~0~3%.

## 4. 50/50 rank 결합 portfolio (top20%, CAGR net / Sharpe TEST)

| combo | TRAIN | VALID | TEST | Sh(TEST) |
|---|---|---|---|---|
| opMargin 단독 | +0.2% | +1.9% | +4.0% | .30 |
| opMargin + netMargin | +0.5% | +2.7% | +3.3% | .35 |
| **opMargin + roe** | +0.0% | +3.7% | +5.7% | **.55** |
| **opMargin + revenueGrowth** | **+1.3%** | +3.1% | **+6.4%** | **.58** |

**결합 − opMargin 단독 증분(pp)**:
- opMargin+roe: TRAIN -0.2 / VALID +1.8 / TEST +1.7 → **VALID·TEST 개선, TRAIN flat**.
- opMargin+revenueGrowth: TRAIN +1.1 / VALID +1.2 / TEST +2.4 → **3기간 모두 개선**(유일).

## 5. 기존 LOWMOM60 대비 incremental (top20%)

| | TRAIN | VALID | TEST |
|---|---|---|---|
| LOWMOM60 baseline | +5.4% | +7.3% | **-2.0%** |
| opMargin+roe | +0.0% | +3.7% | +5.7% |
| opMargin+revenueGrowth | +1.3% | +3.1% | +6.4% |

- LOWMOM60은 TRAIN/VALID 우위, **TEST에서 붕괴(-2.0%)**. quality factor 결합은 **TEST에서 큰 증분(+7.7pp 대비)**. 10-KR-13/15와 같은 패턴 — **baseline이 무너진 TEST에서 fundamental quality가 살아남음**.
- 다만 TRAIN/VALID에서는 LOWMOM60이 우위 → 전체 기간 incremental는 아님.

## 6. 판정

- **PASS 후보 아님**: 3기간 안정적 incremental **portfolio** alpha 미충족. 결합 portfolio 증분이 TRAIN flat/음(opMargin+roe TRAIN -0.2pp), full-control residual도 TRAIN에서 불유의.
- **REJECT 아님**: incremental value가 분명 존재. opMargin|roe 3기간 유의(독립성), opMargin|allOther VALID·TEST 강한 유의(방향 역전 없음), 결합이 VALID/TEST economics를 뚜렷 개선(Sh .55~.58).
- **WEAK (채택)**: *"독립성은 있으나 portfolio 증분 불안정"*에 해당. opMargin은 ROE/netMargin의 단순 대리변수가 아니고 독립 정보를 추가하나, 경제 효과(portfolio)가 TRAIN에서 재현 안 됨.

## 7. 결론 메모

- **Independence: 입증됨.** ROE orthogonalize 후 3기간 유의 → proxy hypothesis 기각.
- **채택 결정: 보류(WEAK).** TEST 중심 경제성은 우수(LOWMOM60 붕괴 구간에서 양), 독립 신호는 OOS 견고하나 TRAIN portfolio 잔류 알파가 확보되지 않아 단독 위치 부여는 위험. **후속: TRAIN flat 원인(저종목·값 분산) 규명 또는 기간 조건부(예: LOWMOM60 약화구간)에서만 결합 사용** 검증 후보로 기록.

## 8. 제한 준수

- 50/50 고정 — 가중치·threshold 최적화 없음(전 구성 사전 고정). TEST 결과로 조정 없음. lookback 변경 없음.

---

산출물: `reports/2026-08-28-kr-opmargin-incremental/kr-opmargin-incremental-results.json`
