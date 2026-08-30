---
track: kr
factor: kr-fundamental-scan
date: 2026-08-29
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["opMargin","netMargin","netIncomeGrowth","opProfitGrowth","equityGrowth","currentRatio","residual_control","pit_monthly","30bps_cost"]
reason: "미검증 후보 6종 스크리닝 - opMargin만 residual OOS 유효+portfolio 3기간 순양(PASS 후보), netMargin·currentRatio WEAK, 성장계열 3종 TRAIN 방향 불일치 REJECT"
---

# Fundamental/Value factor 탐색 — 신규 후보 (10-KR-18)

- 검증일: 2026-08-29
- 스크립트: `kr_fundamental_scan.py`
- 데이터: A4 PIT 월간 패널(2016~2026) + raw A3(annual) PIT 재현 + 기존 패널(quality/valuation) 통제
- 후보(all split-safe, PIT, availableFrom ≤ asOf): **netMargin, opMargin, netIncomeGrowth, opProfitGrowth, equityGrowth, currentRatio**
- 5/20/60/120D forward IC, Q5-Q1, long portfolio(월간, 30bps/side, next-day entry), residual IC | (mom60+roe+pbr+revenueGrowth+retention+debtRatio)
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **최종: opMargin = PASS 후보 / netMargin · currentRatio = WEAK / netIncomeGrowth · opProfitGrowth · equityGrowth = REJECT**

## 1. 후보 채택·제외 근거

- A3 annual 원자료: `revenue, netIncome, opProfit, equity, currentAssets, currentLiab` → 모두 **절대 KRW·비율 → share-split invariant**(10-KR-14에서 revenue growth로 안전성 확인) → PIT로 직접 재현 가능.
- **채택**(이미 검증된 PBR/ROE/revenueGrowth/retention/debtRatio 외 신규): netMargin, opMargin, netIncomeGrowth, opProfitGrowth, equityGrowth, currentRatio.
- **제외·사유 기록**:
  - EPS·EPS growth, dividend yield, PER — A2a 수정주가 vs A3b 원문 EPS split 조정 불일치(`resolver.js`)로 정의 불신뢰.
  - grossMargin — A3에 COGS 미존재. totalAssetsTurnover — A3에 total assets 필드 미존재.

| factor | coverage | 비고 |
|---|---|---|
| netMargin | 89% | netIncome/revenue |
| opMargin | 89% | opProfit/revenue |
| netIncomeGrowth | 78% | netIncome YoY |
| opProfitGrowth | 79% | opProfit YoY |
| equityGrowth | 79% | equity YoY |
| currentRatio | 89% | currentAssets/currentLiab |

결측률 과다 없음.

## 2. 결과 — raw IC (Spearman, NW t) @120D

| factor | TRAIN | VALID | TEST |
|---|---|---|---|
| **opMargin** | +0.029 (3.3) | +0.091 (**7.4**) | +0.123 (**13.4**) |
| netMargin | +0.036 (4.2) | +0.080 (5.8) | +0.114 (11.9) |
| netIncomeGrowth | -0.003 (-0.6) | +0.020 (2.9) | +0.039 (7.7) |
| opProfitGrowth | **-0.008 (-2.2)** | +0.027 (4.3) | +0.054 (8.1) |
| equityGrowth | **-0.020 (-2.9)** | +0.018 (2.4) | +0.047 (5.0) |
| currentRatio | +0.007 (0.9) | +0.022 (1.9) | +0.012 (1.8) |

- **opMargin·netMargin만 3기간 모두 양 & 강화.** 나머지는 TRAIN에서 0 또는 음(TRAIN 방향 불일치).

## 3. 결과 — residual IC | (mom60+roe+pbr+revG+ret+debt) @120D

| factor | TRAIN | VALID | TEST |
|---|---|---|---|
| opMargin | -0.001 (-0.1) | +0.039 (**4.1**) | +0.061 (**7.4**) |
| netMargin | +0.003 (0.5) | -0.002 (-0.4) | +0.049 (4.4) |
| netIncomeGrowth | -0.004 (-0.9) | -0.001 (-0.1) | +0.032 (4.2) |
| opProfitGrowth | **-0.014 (-2.6)** | +0.016 (2.3) | +0.031 (3.1) |
| equityGrowth | **-0.027 (-4.5)** | +0.017 (1.5) | +0.018 (1.2) |
| currentRatio | +0.002 (0.3) | +0.044 (**7.7**) | +0.029 (5.5) |

- **opMargin만 residual이 VALID·TEST 모두 유의**(TRAIN flat). netMargin은 residual이 TEST만(넓은 계열과 공유 성분). equityGrowth·opProfitGrowth는 TRAIN residual이 유의하게 음(방향 반전).

## 4. 결과 — long portfolio (net CAGR / Sharpe, 월간 30bps)

| factor | side | TRAIN | VALID | TEST |
|---|---|---|---|---|
| opMargin | topQ5 | +0.3% (.11) | +2.0% (.19) | **+4.1% (.30)** |
| netMargin | topQ5 | +0.8% (.14) | +1.5% (.17) | +3.4% (.26) |
| netIncomeGrowth | topQ5 | +3.3% (.26) | +1.4% (.17) | +0.8% (.14) |
| opProfitGrowth | topQ5 | +2.6% (.23) | +0.9% (.15) | +1.9% (.19) |
| equityGrowth | topQ5 | +0.4% (.13) | +1.2% (.17) | -0.7% (.08) |
| currentRatio | topQ5 | +2.9% (.24) | -0.6% (.08) | -1.0% (.05) |

- opMargin·netMargin topQ5만 **3기간 모두 순양**. 나머지는 TEST에서 0 이하 또는 미미.

## 5. factor별 판정

### opMargin — **PASS 후보** (가장 유망)
- raw IC 3기간 모두 양·유의 + OOS 강화(TEST 120D t=13.4).
- **residual | 기존 factor 통제 후에도 VALID·TEST 유의**(TEST 120D t=7.4) → 변동성·value·성장·유보 계열로부터 OOS 독립 성분.
- long portfolio topQ5 3기간 모두 순양(+0.3/+2.0/+4.1%).
- 단, absolute 크기가 작고(연 4% 이하) TRAIN residual은 flat — **즉시 확정이 아닌, 후속 실험으로 견고성(incremental alpha) 확인 대상**.

### netMargin — **WEAK**
- raw 방향·TEST·portfolio는 좋지만(**양 3기간, TEST 120D t=11.9, topQ5 3기간 순양**), **residual은 TEST에만 유의(TRAIN·VALID flat)** — 넓은 quality 계열(ROE 등)과 공유 성분이 커서 증분 alpha 확인 안 됨.

### currentRatio — **WEAK**
- residual은 VALID·TEST 유의(자산 유동성 신호)지만 **raw IC·portfolio 경제성 약함**(topQ5 TEST -1.0%). 신호는 존재하나 거래 불가능 수준.

### netIncomeGrowth / opProfitGrowth / equityGrowth — **REJECT**
- **TRAIN에서 방향 불일치**: opProfitGrowth raw -0.008(t=-2.2), equityGrowth raw -0.020(t=-2.9)로 TRAIN 음 → VALID·TEST 양. residual도 TRAIN에서 유의한 음(opProfitGrowth -0.014, equityGrowth -0.027). **3기간 동일 방향 미충족, OOS 방향 반전** → 재현 실패.

## 6. 후속 실험 제안 (1~3개)

1. **opMargin** (우선) — profitability-margin quality factor의 독립성·단조성·incremental alpha 검증. raw/residual 모두 OOS 유효, portfolio 3기간 순양.
2. **netMargin** (동일 family, 2순위) — opMargin과 multi-collinear하므로 하나의 "margin quality" family로 묶어 후속 검증.
3. (제안 보류) currentRatio — residual은 흥미로우나 경제성 부족 → 논외.

제한 준수: **TEST 결과로 factor·threshold 최적화 없음**(수치 그대로 기록), lookback 신규 없음, 기존 결과 유리하게 만들 규칙 변경 없음.

---

산출물: `reports/2026-08-28-kr-fundamental-scan/kr-fundamental-scan-results.json`