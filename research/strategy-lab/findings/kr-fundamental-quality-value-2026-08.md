---
track: kr
factor: kr-fundamental-quality-value
date: 2026-08
verdict: UNCLASSIFIED
original_verdict: PBR PASS / ROE·revenueGrowth·retention WEAK / debtRatio REJECT
conditions: ["roe", "revenueGrowth", "debtRatio", "retention", "pbr"]
reason: PBR만 유일하게 raw·잔차 IC가 3기간 모두 유의 동일부호이고 저PBR long이 3기간 모두 net 양수(PASS), ROE·revenueGrowth·retention은 경제성 미확보(WEAK), debtRatio는 신호 없음(REJECT).
cagr: 1.8
sharpe: 0.19
---

# KR Fundamental Quality/Value Factor 발견 — 최소 검증 (10-KR-14)

- 검증일: 2026-08-28
- 스크립트: `kr_fundamental_quality_value.py`
- 데이터: A4 `a4-research-dataset.parquet` + PIT 패널(quality/valuation) + raw A3/A3b
- 후보 factor (모두 PIT, availableFrom ≤ asOf): **ROE, revenue growth, debt ratio, retention(유보율), PBR**
- 월간 rebalance(A4 월초), 5D/20D/60D/120D forward close-to-close, 비용 30bps/side
- OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~2026-08
- 잔차 IC: mom60 + 타 fundmental factor rank-orthogonalization 후 Spearman
- **최종 판정: PBR PASS / ROE·revenueGrowth·retention WEAK / debtRatio REJECT**

## 1. 데이터·제외

- **PBR** = `valuation-panel.jsonl`(lab PIT-clean 산출물). **PER·epsGrowthRate는 제외** —
  `lib/a5/resolver.js`가 문서화한 대로 A2a 수정주가 vs 원문 EPS 조정 불일치(split)로 불신뢰.
  실측 확인: 005930 EPS 2017 299,868 → 2018 6,461 (50:1 액면분할 미반영) → 단순 YoY BE는 -97.8% 허상.
- **revenue growth** = raw A3 annual YoY (PIT `selectAsOf`+`selectFiscalYear` 재현). 총 매출이라 split 무관.
- **retention** = raw A3b annual `1 − dividendPerShare/eps` (EPS>0만). 분자·분모 동일 조정 → ratio split-invariant.
- **ROE·debtRatio** = `quality-panel.jsonl`.

| factor | non-null | 비고 |
|---|---|---|
| roe | 90.2% | 128 월, ~1.9천 종목/월 그룹 |
| revenueGrowth | 77.1% | 2015 미존재 종목 전년부재로 결측 |
| debtRatio | 91.0% | |
| retention | 54.1% | 배당없는 종목/eps≤0 제외 |
| pbr | 47.1% | panel 커버리지(A4와 겹치는 종목 1,500) |

## 2. 결과 — raw IC (Spearman, 일별 평균, NW t)

| factor | TRAIN 20D | TRAIN 120D | VALID 20D | VALID 120D | TEST 20D | TEST 120D |
|---|---|---|---|---|---|---|
| roe | +0.025 (3.2) | +0.031 (3.6) | +0.048 (3.1) | +0.083 (6.8) | +0.082 (6.2) | +0.126 (13.6) |
| revenueGrowth | +0.001 (0.1) | -0.007 (-0.9) | +0.023 (1.6) | +0.027 (2.6) | +0.018 (2.7) | +0.051 (10.4) |
| debtRatio | -0.003 (-0.5) | -0.009 (-1.2) | -0.006 (-0.5) | -0.014 (-1.0) | -0.004 (-0.5) | +0.013 (1.6) |
| retention | -0.028 (-3.0) | -0.045 (-4.5) | -0.017 (-0.6) | -0.051 (-2.7) | -0.072 (-5.7) | -0.118 (-9.3) |
| **pbr** | -0.071 (-4.9) | -0.127 (-6.5) | -0.051 (-2.1) | -0.083 (-4.3) | -0.110 (-4.2) | -0.161 (-8.7) |

## 3. 결과 — residual IC (mom60 + 타 fundamental 통제, 120D)

| factor | TRAIN 120D | VALID 120D | TEST 120D |
|---|---|---|---|
| roe | -0.017 (-1.9) | +0.022 (2.0) | +0.076 (8.0) |
| revenueGrowth | +0.002 (0.2) | +0.036 (2.2) | +0.038 (4.4) |
| debtRatio | -0.010 (-1.1) | -0.047 (-5.0) | -0.013 (-1.1) |
| retention | -0.016 (-1.8) | -0.029 (-2.2) | -0.073 (-5.7) |
| **pbr** | -0.073 (-3.9) | -0.056 (-2.8) | -0.151 (-8.2) |

## 4. 결과 — long portfolio (월간, 30bps/side, CAGR / [Sharpe])

방향은 factor 특성상 각 팩터의 유의미한 "long side"만 보고함.

| factor | side | TRAIN | VALID | TEST |
|---|---|---|---|---|
| roe | topQ5(고ROE) | -2.3% [0.01] | +4.7% [0.31] | -1.9% [0.02] |
| revenueGrowth | topQ5(고성장) | -0.2% [0.13] | +5.1% [0.32] | -7.2% [-0.17] |
| retention | topQ5(고유보율) | +1.8% [0.20] | +6.2% [0.35] | -14.3% [-0.49] |
| **pbr** | **bottomQ1(저PBR)** | **+6.5% [0.39]** | **+1.4% [0.16]** | **+1.8% [0.19]** |

## 5. factor별 판정

### PBR — **PASS** (유일한 합격)
- 방향 일관: (저PBR → 고수익) **3기간 모두 음 IC**, 5D~120D 전 horizon에서 유의, 지평이 길수록 |IC| 증가.
- 잔차 IC: **3기간 모두 유의 및 동일 부호** (TRAIN -3.9 / VALID -2.8 / TEST -8.2). mom60·여타 fundamental 통제 후에도 OOS-stable.
- 경제성: 저PBR long 포트**리오가 3기간 모두 net 양수** (+6.5/+1.4/+1.8%, Sharpe 전부 >0). 놀랍게도 TEST에서 퇴화 없음.
- 기존 lab pbr_value 전략(+7.06% precheck)과 방향 일치 — A4 universe에서 독립적으로 재확인.

### ROE — **WEAK**
- raw IC는 3기간 모두 양·유의하게 강화(TEST 120D t=13.6). 그러나 **잔차 IC에서 TRAIN 부호 반전(-0.017, t=-1.9)**, VALID·TEST만 양.
- 경제성 불안정: 고ROE topQ5 long이 TRAIN·TEST에서 net 음수(-2.3%/-1.9%). IC는 강하지만 long-only 경제성 미확보.

### revenueGrowth — **WEAK**
- TRAIN 0에 수렴, VALID·TEST에서만 양으로 강화(잔차 TEST 120D t=4.4). 방향 일관성 미결.
- 경제성: 고성장 topQ5 long이 TEST에서 -7.2%.

### retention — **WEAK**
- 음 IC가 3기간 일정(TEST 강화 t=-9.3)하지만 **질적·경제적 신호와 반대**: 고유보율(높은 배당성향 유지) → 낮은 수익.
- 잔차 IC도 TEST에서 유의(-5.7)하나, long side(고유보율) 포트**리오가 TEST에서 -14.3%로 경제성 없음**. IG 지표로는 "역방향 factor"로 해석 가능하나, 이 discovery 맥락에서 실현가치 미비.

### debtRatio — **REJECT**
- 모든 기간·horizon에서 |t| < 1.6. 방향·잔차·경제성 전부 신호 없음.

## 6. 판정 요약 및 다음 실험 추천 (1개)

| factor | 판정 |
|---|---|
| PBR | **PASS** |
| ROE | WEAK |
| revenueGrowth | WEAK |
| retention | WEAK |
| debtRatio | REJECT |

> "가장 유망한 factor 1개" → **PBR** (저PBR long).

- 유일하게 **raw·잔차 IC가 3기간 모두 유의하고 동일 부호**이며, **저PBR long 포트폴리오가 3기간 모두 net 양수**.
- 기존 `pbr_value`(저PBR) 전략이 이미 검증되어 있으므로, 다음 실험은 "기존 전략 대비 **증분 alpha**" 관점이
  곧 실현가치 판정이 된다 — 10-KR-13 incremental 설계(기존 전략 baseline + overlay, 50/50)를 PBR에 적용해
  LOWMOM60 대비(또는 임계 PBR 컷 대비) OOS 증분을 확인.

### 절대 하지 않음
- ROE·revenueGrowth·retention의 유의 구간만 골라 채택 (TEST-driven)
- PBR threshold 최적화 (기존 pbr_value 임계값 재탐색 금지)
- factor 조합 탐색 (ROE×PBR 등)
- retention을 "역방향 long"으로 즉시 확정

---

산출물: `reports/2026-08-28-kr-fundamental-quality-value/kr-fundamental-quality-value-results.json`
