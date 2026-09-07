---
track: kr
factor: pbr_roe_quality_overlay
subproject: pbr-value-v1 (PBR top-30 내부 ROE quality gate)
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: oos-split-v1
conditions: ["PBR top-30 (turnover20>=1억, 오름차순)", "ROE gate {상위100%, 70%, 50%} (그 달 PBR-30 내 ROE pct-rank)", "TRAIN Sharpe 선택 게이트 → VALID/TEST 고정", "ROE 결측 제외·임의 대체 금지", "월별 리밸런스", "MTM 회계", "연속보유 병합", "비용 30bps 왕복·슬리피지 0"]
reason: >-
  TRAIN(2016-01~2022-05)에서 Sharpe 1위로 선택된 gate50(TRAIN Sharpe 0.742)이
  VALID(2022-05~2023-12)와 TEST(2023-12~2026-08)에서 세 게이트 중 각각 최하위
  (0.011 / 0.529)로 떨어져 순위가 TRAIN→VALID에서 완전 역전했다. gate50의
  전체기간 수치(CAGR 6.76%·MDD -19.4%)는 '종목 수 축소' 효과와 분리되지 않았다:
  같은 N(15개)의 ROE 없는 PBR top-15가 OOS(VALID 0.384·TEST 0.592)에서 gate50
  보다 우월했고, gate50과 같은 수(약 15개)를 무작위로 제외한 placebo 5시드
  평균도 OOS에서 gate50 대비 낫거나 비슷했다(placebo VALID 평균 0.146·TEST 평균
  0.674 vs 실제 0.011·0.529). 즉 관측상 품질 gate의 개선 실체는 ROE 신호라기보다
  표본 축소(소형 포트폴리오 효과)로 설명되며, TRAIN에서 선택한 게이트로는
  OOS 방향 유지가 확인되지 않았다. 2022 집중도도 선택된 gate50과 baseline이
  비슷했다(2022 수익 -1.5% vs -1.8%, 2022 MDD -12.4% vs -11.6%).
cagr: 0.0676
sharpe: 0.5855
mdd: -0.1938
win_rate: 0.5244
n: 431
t_stat: 1.2117
stats:
  split_boundaries: {TRAIN: "2016-01-01 ~ 2022-05-31", VALID: "2022-05-31 ~ 2023-12-28", TEST: "2023-12-28 ~ 2026-08-14"}
  train_selected_gate: gate50
  selection_metric: sharpe (TRAIN 한정)
  gate_rank_by_split: {TRAIN: [gate50, gate70, gate100], VALID: [gate100, gate70, gate50], TEST: [gate70, gate100, gate50]}
  tstat_vs_zero_full: 1.9123
  tstat_vs_ew_full: 1.2117
  roe_source: factor-panel kr-monthly-v1 (manifest source=quality-panel, PIT-safe; PBR-30 내 ROE 커버리지 2016 평균 26.8/30, 그 외 연도 29~30/30)
  baseline_top30_full: {cagr: 0.0549, sharpe: 0.5189, mdd: -0.2109, closed: 777}
  ew_full: {cagr: 0.023, sharpe: 0.2303, mdd: -0.2572, closed: 5726}
---

# PBR × ROE Quality Overlay — TRAIN 선택 → VALID/TEST 고정 (2026-09-06)

## 0. 질문과 사전 고정 조건

저PBR 신호(pbr_value_v1, turnover20≥1억, 월별 리밸런싱, top-30)에 **ROE가 높은
종목만 남기는 quality gate를 overlay하면 value trap을 줄여 위험조정성과를
개선하는가**를 검증한다. ROE 단독 알파가 아니라 **PBR 포트폴리오 내부의
overlay**로만 본다. Gate 후보는 상위 100%(=PBR baseline)·상위 70%·상위 50%.
**TRAIN에서만 gate를 선택**하고 VALID·TEST는 선택된 gate를 고정해 보고만 한다.
TEST 결과로 게이트를 다시 고르지 않는다. ROE 방향은 사전 가설 그대로(높을수록
좋음), ROE 결측은 제외·임의 대체 금지. liquidity tercile 사용 금지. ROE
단독 전략을 승자로 해석하지 않는다.

## 1. 방법 (기존 엔진·데이터 재사용, 새 엔진 없음)

- **PBR top-30 유지**: 기존 build_selection.py와 동일 — valuation-panel(pbr,
  PIT-safe) × a2a bars에서 turnover20(종가×거래량 20일 롤링 평균, 리밸런싱일
  기준) ≥ 1억, 그 달 PBR 오름차순 상위 30.
- **Quality gate**: 그 달 PBR top-30 종목 중 ROE non-null 종목의 pct-rank
  (높을수록 1.0) 기준 top X% 유지. ROE 결측 종목은 rank가 매겨지지 않아
  자동 제외(임의 대체 없음). ROE는 factor-panel `kr-monthly-v1.parquet`의
  `roe` 컬럼(manifest source=quality-panel, 같은 a5 resolve() PIT 규칙)을
  가장 최근 과거일 기준으로 인출.
- **포트폴리오**: gate 후보를 자르지 않도록 `maxPositions = nominal gate size`
  (100%→30, 70%→21, 50%→15) — 같은 목적의 top-N 실험과 동일한 원리
  (소형 게이트 포트폴리오가 cash/maxPositions로 풀사이즈를 못 갖는 왜곡 방지).
  그 외 초기자본 1억, equalWeight, 정수 주식수, 연속보유 병합, 15bps/측
  (왕복 30bps)·슬리피지 0 — 전부 기존 정책 그대로.
- **구간 분할**: 월별 MTM 스냅샷(129개)을 시간순 60/15/25%로 분할, 각 구간은
  자기 첫 스냅샷을 t0으로 (top-N 실험과 동일한 분할 원리).
- **N-matched control(표본 축소 대조)**: gate와 같은 N이지만 ROE 없이 PBR로만
  뽑은 `pbrTop21`·`pbrTop15`를 같은 엔진으로 실행 — 품질 게이트의 효과를
  '종목 수를 줄인 것'과 분리한다.
- **Placebo(게이트 자체 효과 분리)**: TRAIN 선택 게이트(gate50)가 매달 제외한
  것과 같은 수를 PBR top-30에서 **ROE를 보지 않고 무작위로** 제외(시드 5개,
  1000+seed 고정)해 같은 엔진으로 실행.

## 2. baseline 재현

| 항목 | run_smoke("pbr_value_v1") | gate100 인메모리 | EW 벤치마크 |
|---|---|---|---:|
| full CAGR | 5.49% | 5.49% | 2.30% |
| full Sharpe | 0.519 | 0.519 | 0.230 |
| full MDD | -21.1% | -21.1% | -25.7% |
| closed | 777 | 777 | 5,726 |

gate100(=PBR top-30, 30개)이 실제 엔진과 byte-level로 동일 — overlay 실험의
선택 기반이 기존 정본 선택과 정확히 일치함을 다시 확인했다.

## 3. 결과 — 실측치

주 실행 결과(전체기간 2016-01-01~2026-08-14, 월별 MTM). TRAIN에서 선택된
gate는 **gate50**(TRAIN Sharpe 0.742).

| 항목 | 값 |
|---|---|
| CONDITIONS | PBR top30 + ROE gate {100%,70%,50%}; TRAIN 선택 → VALID/TEST 고정 |
| CAGR | **6.76%** (TRAIN 선택 gate50, 전체기간 실측) |
| SHARPE | **0.586** (같은 곡선) |
| MDD | **-19.4%** |
| WINRATE | **52.4%** (실제 계산값, N=431 체결 기준) |
| N | **431** (closed trades, 실제 체결 건수) |
| T-STAT | **1.91** (월별수익/0, 128개월) · **1.21** (EW 초과, 실제 계산) |
| REASON | TRAIN에서 Sharpe 1위로 선택된 gate50이 VALID·TEST에서 세 게이트 중 최하위(0.011/0.529)로 붕괴 — TRAIN→VALID 순위 완전 역전. 같은 N의 ROE 없는 PBR top-15와 placebo(무작위 축소)가 OOS에서 실제 ROE gate와 동등하거나 우월해, 관측된 개선은 품질 신호보다 표본 축소 효과로 설명됨. |

### 후보별 전체기간 성과 (실측)

| variant | avgSel/월 | tickers | CAGR | Sharpe | MDD | WINRATE | N(체결) | t(vs 0) | t(vs EW) |
|---|---|--:|---:|---:|---:|---:|---:|---:|---:|
| **gate50(TRAIN선택)** | 15.7 | 122 | **6.76%** | **0.586** | **-19.4%** | 52.4% | 431 | 1.91 | 1.21 |
| gate70 | 21.0 | 146 | 6.08% | 0.586 | -20.2% | 50.9% | 639 | 1.91 | 1.02 |
| gate100 | 29.7 | 172 | 5.49% | 0.519 | -21.1% | 51.1% | 777 | 1.69 | 1.02 |
| pbrTop21 (N-control) | 20.9 | 147 | 5.07% | 0.480 | -19.1% | 51.7% | 574 | 1.57 | 0.91 |
| pbrTop15 (N-control) | 15.0 | 122 | 6.94% | 0.613 | -14.3% | 52.6% | 432 | 2.00 | 1.50 |

비교군: EW full CAGR 2.30%·Sharpe 0.230·MDD -25.7%. PBR baseline(gate100)
CAGR 5.49%·Sharpe 0.519·MDD -21.1%.

### TRAIN / VALID / TEST별 Sharpe·MDD (별도 표)

TRAIN = 2016-01-01 ~ 2022-05-31 (78 스냅샷)
VALID = 2022-05-31 ~ 2023-12-28 (20 스냅샷)
TEST = 2023-12-28 ~ 2026-08-14 (33 스냅샷)

| variant | TRAIN Sharpe | TRAIN MDD | VALID Sharpe | VALID MDD | TEST Sharpe | TEST MDD |
|---|--:|--:|--:|--:|--:|--:|
| gate50 | **0.742** | -15.4% | **0.011** | -10.2% | **0.529** | -10.2% |
| gate70 | 0.693 | -20.2% | 0.071 | -10.5% | 0.626 | -9.9% |
| gate100 | 0.607 | -21.1% | 0.091 | -10.3% | 0.579 | -12.7% |
| pbrTop21 | 0.543 | -17.1% | 0.155 | -12.5% | 0.544 | -13.2% |
| pbrTop15 | 0.685 | -14.3% | **0.384** | -6.4% | **0.592** | -8.2% |
| EW | 0.451 | -17.9% | -0.161 | -16.0% | 0.144 | -13.3% |

### 순위 유지 여부 (세 게이트의 Sharpe 기준 순위)

| 구간 | 순위 (1→3) |
|---|---|
| TRAIN | [gate50, gate70, gate100] |
| VALID | [gate100, gate70, gate50] |
| TEST | [gate70, gate100, gate50] |

**TRAIN 1위(gate50)가 VALID에서 최하위, TEST에서도 최하위로 떨어진다** — 같은
실험 설계의 topN 실험에서 topN=100이 겪은 것과 동일한 TRAIN→OOS 순위 역전.
gate70도 TEST에서만 1위일 뿐 VALID에서는 baseline보다 낮아 게이트 간 순위가
구간별로 고정되지 않았다. VALID는 2022.5~2023.12 밸류 불리 국면(EW -0.161)으로
전부 어렵지만, 같은 N에서도 품질 신호가 방어해준 관측이 있던 pbrTop15(+0.384)와
대비된다.

## 4. 표본 축소 대조 (검증 4: 품질 게이트 vs 단순 N 축소)

gate70은 21개, gate50은 15개로 종목 수가 줄어든다. ROE 없이 같은 N을 뽑는
pbrTop21·pbrTop15와 비교:

| 비교 | TRAIN | VALID | TEST |
|---|---|---|---:|---:|
| gate70 (N≈21, ROE) | 0.693 | 0.071 | 0.626 |
| pbrTop21 (N≈21, PBR만) | 0.543 | **0.155** | 0.544 |
| gate50 (N≈15, ROE) | **0.742** | 0.011 | 0.529 |
| pbrTop15 (N≈15, PBR만) | 0.685 | **0.384** | **0.592** |

TRAIN에서는 ROE 게이트가 같은 N의 PBR만 뽑는 것보다 높지만(0.742 vs 0.685),
**VALID·TEST에서는 게이트 없이 PBR로만 줄인 쪽이 더 좋다**. 품질 게이트의
TRAIN 우위는 OOS에서 N-matched 대조를 이기지 못한다. gate50의 전체기간 개선
(CAGR 5.49%→6.76%, MDD -21.1%→-19.4%)은 대부분 '종목 수를 줄인 것'의 효과로
설명되며, pbrTop15가 같은 N에서 오히려 더 큰 개선(전체 Sharpe 0.613·MDD -14.3%)
을 낸다.

## 5. Placebo 대조 (검증 5: ROE 게이트 자체의 효과)

TRAIN 선택 gate50이 매달 제외하는 것과 같은 수(≈15개)를 무작위로 제외해
5시드(1000+seed)를 같은 엔진으로 실행:

| 지표 | 실제 gate50 | placebo 평균 (5시드) | placebo 범위 |
|---|---|---|---|
| TRAIN Sharpe | 0.742 | 0.638 | 0.558~0.813 |
| VALID Sharpe | **0.011** | 0.146 | 0.122~0.199 |
| TEST Sharpe | **0.529** | 0.674 | 0.535~0.913 |
| full CAGR | 6.76% | 6.56% | 5.78%~8.03% |
| full MDD | -19.4% | -19.2% | -16.2%~-25.8% |

- TRAIN에서 실제 gate50(0.742)이 placebo 평균(0.638)보다 높으나 placebo 한
  시드(0.813)가 이미 이를 넘어선다 — 게이트 선택이 운으로 가능한 범위.
- **OOS에선 placebo가 실제 게이트보다 평균적으로 높다**: VALID에서 placebo는
  전부 0.12 이상인데 실제는 0.011, TEST에서도 placebo 평균 0.674 vs 실제 0.529.
- 즉 'ROE로 고르고 남기는' 행위 자체보다 '15개로 줄이는' 크기 효과가 성과에서
  관측적으로 우세하며, ROE 게이트 고유의 OOS 개선은 placebo와 대조해도
  확인되지 않았다.

## 6. 2022년 집중도 (검증 3)

| variant | 2022 MTM 수익 | 2022 MDD | 2022 평균 보유종목 수 |
|---|---:|---:|---:|
| gate100 (baseline) | -1.8% | -11.6% | 29.7 |
| gate70 | +3.7% | -8.3% | 21.0 |
| gate50 (TRAIN선택) | -1.5% | -12.4% | 15.7 |
| pbrTop21 | -0.2% | -12.9% | 20.9 |
| pbrTop15 | +2.1% | -11.9% | 15.0 |

gate70은 2022에 유일하게 양(+) 수익(+3.7%, MDD -8.3%)으로 가장 많이 줄였으나,
**TRAIN에서 선택된 gate50은 baseline과 2022 성과가 거의 같았다**(-1.5% vs -1.8%,
MDD -12.4% vs -11.6%). 같은 N의 pbrTop15(+2.1%)마저 gate50보다 나았다 — '게이트가
2022 value trap을 줄인다'는 휴리스틱이 선택된 게이트에서는 관측되지 않았다.

## 7. 정리 (관측 사실, 판정 아님)

1. **TRAIN 선택 규칙으로는 ROE 게이트를 고를 수 없었다.** TRAIN Sharpe 1위
   (gate50)가 VALID·TEST에서 세 게이트 중 최하위로 붕괴하고 구간별 순위가
   역전된다.
2. **개선의 실체는 표본 축소로 설명된다.** 같은 N의 ROE 없는 PBR 상위
   (pbrTop15)가 OOS에서 더 좋거나 비슷했고, 무작위로 15개를 줄인 placebo 평균도
   실제 ROE 게이트 대비 OOS에서 낫거나 비슷했다. 품질 게이트 고유의 OOS 알파는
   이 실험의 관측 범위에서 확인되지 않았다.
3. TRAIN에서의 게이트 선택 효과(더 강한 필터=더 높은 TRAIN Sharpe: gate50
   0.742 > gate70 0.693 > gate100 0.607)는 순위 역전 방향으로 정확히 뒤집혔다.
4. 전체기간 풀링 성과(CAGR 6.76%)는 **결정 근거로 쓰지 않는다** — 이 실험이
   검증하는 것은 OOS에서의 순위·방향 유지였고 그것이 무너졌기 때문(§판정
   금지 규칙).
5. quote: 데이터 계약(pit, valuation-panel 선택 규칙, turnover20, a2a 수정주가,
   MTM 회계, 절대유동성 임계값, 연속보유, 비용), ROE는 factor-panel(quality-panel
   PIT 규칙) 재사용으로 완화 없음. production 파일 무변경.
6. 한계: 이 실험은 PBR **이미 선택된 30개 안에서** ROE로 걸러내는 설정만
   다룬다. 유니버스 전체에서 ROE로 먼저 걸러낸 뒤 PBR top-30을 만드는
   사전 필터 배치는 이 실험의 범위 밖이다(다른 `pbr_quality_vt_filter_oos.py`
   실험이 하위 20% 제외 방식을 다룬다 — 2026-09-06).

## 8. 재현

```
python research/strategy-lab/run_pbr_roe_quality_overlay_oos.py --placebo-seeds 5
```

출력:
`research/strategy-lab/reports/2026-09-06-pbr-roe-quality-overlay/pbr-roe-quality-overlay-oos.json`

실행 시각: 2026-09-06. 게이트 3개 + N-matched control 2개 + placebo 5시드를
같은 엔진(바 캐시 재사용, run_smoke 1회/변형)으로 실행. 각 변형의 선택은
기존 build_selection.py와 동일한 오프라인 로직(인메모리).