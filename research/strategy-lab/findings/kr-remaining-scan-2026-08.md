---
track: kr
factor: kr-remaining-scan
date: 2026-08-29
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["assetTurnover", "treasuryRatio", "dividendPresent", "pit_monthly", "30bps_cost"]
reason: "treasuryRatio만 독립신호(TEST residual +8.7)로 확인되나 portfolio 경제성이 전 기간 0~1.6%로 실현 불가 수준 - 전용 견고성 검증 필요. assetTurnover는 대리변수, dividendPresent는 REJECT급"

---

# 남은 Fundamental/Value Factor Screening (10-KR-22)

- 검증일: 2026-08-29
- 스크립트: `kr_remaining_scan.py`
- 데이터: A4 PIT 월간 패널(2016~2026). next-day entry, 월간 rebalance, 30bps/side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- **스크리닝만 수행 — 후보 최적화 없음. TEST 결과로 threshold/가중치 생성·조정 없음.**
- **최종: 후속 후보 1개 선정 — treasuryRatio(우선 1순위, 독립 신호). assetTurnover WEAK(대리변수 의심). dividendPresent REJECT(변질).**

## 1. 후보 재고 (이미 검증된 것 제외)

**이미 판정**: PBR(10-KR-15~17), ROE, revenueGrowth, retention, debtRatio(10-KR-14), opMargin(10-19~21), netMargin, netIncomeGrowth/opProfitGrowth/equityGrowth(10-KR-18 growth-family), currentRatio(10-KR-14). PER/EPS/DPS/dividendYield = split 불일치로 제외(기록).

**A3/A3b/A3c raw 필드**:
- A3: `currentAssets, currentLiab, equity, liabilities, netIncome, opProfit, revenue` (절대 KRW = split-invariant)
- A3b: `eps, dividendPerShare`(split 민감, 제외), `dividendRowPresent`(flag), `dividendStockKnd`(코드)
- A3c: `istcTotqy(자사주), isuStockTotqy(발행주수), distbStockCo`

**주요 제외 근거**:
- **equityRatio = equity/(equity+liab)** = 1/(1+debtRatio) — 이미 판정된 debtRatio의 결정적 변환(**이름만 바꾼 재검증 금지** 원칙) → 제외.
- per-share level(주당) — split 민감.
- **신규·split-safe·PIT-safe 후보 3개**: assetTurnover, treasuryRatio, dividendPresent.

## 2. 후보별 결과 (120D 기준)

### assetTurnover = revenue/(equity+liabilities) — 효율성 — **WEAK (대리변수 의심)**
| | TRAIN | VALID | TEST |
|---|---|---|---|
| IC (t) | +.028 (2.9) | +.062 (**6.5**) | +.023 (2.4) |
| Q5-Q1 | +.004 | +.013 | -0.010 |
| **TEST resid\|통제 120D** | | | **-0.067 (t=-5.3)** |
| top-Q CAGR (Sh) | +3.1% (.25) | +2.0% (.19) | **-1.4% (.02)** |

- raw IC 3기간 양(약)이나 **TEST residual이 강하게 음 → 기존 factor의 대리변수**(수익·margin·자산계열과 정보 공유), 독립 신호 없음. TEST portfolio 비양.

### treasuryRatio = istcTotqy/isuStockTotqy — 자사주/발행주 비(바이백) — **WEAK (독립 신호, 경제성 약)**
| | TRAIN | VALID | TEST |
|---|---|---|---|
| IC (t) | +.009 (1.9) | +.051 (4.1) | +.085 (**10.4**) |
| Q5-Q1 | -0.017 | -0.002 | +.047 |
| **TEST resid\|통제 120D** | | | **+0.044 (t=+8.7)** |
| top-Q CAGR (Sh) | +1.6% (.18) | -0.1% (.10) | +0.6% (.13) |

- **TEST residual이 전체 통제(mom60+roe+pbr+revG+retention+debtRatio+netMargin+opMargin) 후에도 +8.7로 강한 양** → **기존 factor와 무관한 진짜 독립 신호**(기업 바이백 강도는 margin/ROE/PBR 계열과 정보가 겹치지 않음).
- 그러나 **top-Q portfolio 경제성은 전 기간 flat**(CAGR ~0~1.6%, Sharpe <0.2), Q5-Q1도 TEST에서만 양. 신호는 있으나 거래로 실현되는 alpha는 미약.

### dividendPresent = dividendRowPresent flag — **REJECT (변질)**
- liquid universe에서 거의 모든 종목이 동일 값 → 월별 nunique≤1 → IC 계산 불가(변질 이진 변수). 미검증 factor 아님.

## 3. 판정 및 후속 우선순위

| 후보 | 3기간 방향 | TEST residual | portfolio 경제성 | 판정 | 후속 우선순위 |
|---|---|---|---|---|---|
| **treasuryRatio** | ✅ (t 1.9/4.1/10.4) | ✅ **+8.7** | ❌ flat | **WEAK** | **1 (후속 검증 대상)** |
| assetTurnover | ✅ (약) | ❌ -5.3 (대리) | ❌ | **WEAK** | 2 (낮음) |
| dividendPresent | – (변질) | – | – | **REJECT** | – |

- **후속 선정: treasuryRatio (1개, 1순위).**
  - 선정 근거: **유일하게 신규·독립 신호**(자사주 비율). TEST residual(전 통제) +8.7로 기존 factor들과 무관한 정보. buyback/자본구조가 margin·ROE·PBR 계열과 다른 독립 축.
  - 보류 근거(왜 PASS가 아닌가): portfolio 경제성이 모든 기간 ~0~1.6%로 실현 불가 수준, Q5-Q1 TEST에서만 양. **독립성은 유효하나 경제적 규모가 아직 미확인 → 전용 견고성 실험(3기간·residual·portfolio·decile)으로 규명 필요.**
- assetTurnover는 raw IC가 3기간 양이나 대리변수(TEST resid -5.3) → 후속 우선순위 낮음(큰 기대 불가). 기록만.

## 4. 제한 준수

- 후보 최적화·조정 없음 — 사전 고정 sign(+1)·top20%·5분위. TEST 결과로 threshold 생성/조정 없음.
- 판정된 factor 재명명 검증 금지 준수(equityRatio 제외). 데이터에 없는 feature 계산 안 함(3 후보 모두 실제 raw 필드로만 구성).

---

산출물: `reports/2026-08-28-kr-remaining-scan/kr-remaining-scan-results.json`
