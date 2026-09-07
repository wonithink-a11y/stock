---
track: kr
factor: pbr_topn_strength
subproject: pbr-value-v1 (top-N 강도 질문)
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: oos-split-v1
conditions: ["topN={10,20,30,50,100}", "TRAIN 선택 → VALID/TEST 고정", "저PBR 오름차순", "turnover20>=1억 절대유동성", "월별 리밸런스", "MTM 회계", "연속보유 병합", "비용 30bps 왕복·슬리피지 0"]
reason: >-
  TRAIN(2016-01~2022-05) Sharpe 1위로 선택된 topN=100(TRAIN Sharpe 0.757)이
  VALID(2022-05~2023-12)에서 5개 후보 중 최하위(-0.149)로 붕괴해 순위가 완전히
  역전 - TRAIN→VALID 순위 유지에 실패했다. 유일하게 세 구간 전부 Sharpe>0인
  topN=10(0.623/0.726/0.695)은 TRAIN 2위라 선택되지 않았고, 지침대로 사후
  재선택하지 않아 그대로 보고한다. topN=30 기본 baseline(0.607/0.091/0.579)도
  VALID에서 사실상 평평·TEST에서 회복. 플라시보(순위 셔플, topN=100) 대비
  TEST(+0.749 vs -0.427)에서는 실제 신호의 우위가 남아 있으나 VALID에서는
  없었다. 전체기간 월별초과수익 t(EW 대비)는 5개 후보 전부 2 미만.
cagr: 0.0605
sharpe: 0.6136
mdd: -0.1534
win_rate: 0.537
n: 2231
t_stat: 2.0042
stats:
  split_boundaries: {TRAIN: "2016-01-01 ~ 2022-05-31", VALID: "2022-05-31 ~ 2023-12-28", TEST: "2023-12-28 ~ 2026-08-14"}
  train_selected_topN: 100
  selection_metric: sharpe (TRAIN 한정)
  train_rank_by_sharpe: [100, 10, 30, 50, 20]
  valid_rank_by_sharpe: [10, 20, 30, 50, 100]
  test_rank_by_sharpe: [50, 100, 10, 30, 20]
  tstat_vs_ew: 1.2046
  placebo_topN100: {cagr: 0.023, sharpe: 0.2478, mdd: -0.2357, win_rate: 0.4491, n: 11480, tstat_vs_ew: -0.1347, train_sharpe: 0.6693, valid_sharpe: -0.1027, test_sharpe: -0.4268}
  baseline_top30_full: {cagr: 0.0549, sharpe: 0.5189, mdd: -0.2109, closed: 777}
  ew_full: {cagr: 0.023, sharpe: 0.2303, mdd: -0.2572}
---

# PBR top-N 강도 — TRAIN 선택 → VALID/TEST 고정 (2026-09-06)

## 0. 질문과 사전 고정 조건

기존 저PBR 신호(pbr_value_v1, turnover20≥1억 절대유동성, 월별 리밸런싱)에서
"언제 살까"가 아니라 **얼마나 강한 PBR 상위집합(몇 개)을 보유해야 하는가**를
검증한다. `topN ∈ {10, 20, 30, 50, 100}` 이며, PBR 방향은 기존 저PBR(오름차순)을
그대로 쓴다. **TRAIN에서만 topN을 선택**하고 VALID·TEST에서는 TRAIN에서 선택된
값을 고정해 보고만 한다. 전체기간 성과로 사후 선택하지 않고, TEST 결과를 보고
topN을 다시 고르지 않는다.

## 1. 방법 (기존 엔진·데이터 재사용, 새 엔진 없음)

- **재사용**: engine.runner.run_smoke(rule_module=...) + pbr_vs_ew_monthly_mtm의
  `schedule_with_monthly_mtm`(월말 시가평가 MTM)·`curve_metrics`·`split_snapshots`·
  `monthly_return_tstats`. production 정책 파일·엔진·selection.json은 **수정하지
  않았다** — topN별 선택을 인메모리로 만들어 rule.module로 넣는
  run_pbr_combined_oos_validation.py 방식.
- **선택 로직**: build_selection.py와 동일 — valuation-panel(pbr, PIT-safe,
  resolve() 규칙 기반) × a2a bars에서 turnover20(종가×거래량, 20일 롤링 평균,
  리밸런싱일 시점) ≥ 1억, 그 달 PBR 오름차순 상위 N. holdSessions는 다음
  리밸런싱일까지 실제 거래일수(마지막 달 폴백 21)로 엔진 제약과 동일하게 계산.
- **포트폴리오**: topN 후보를 자르지 않도록 `maxPositions = topN` 설치(공정 비교
  필수 — topN=100을 maxPositions=30으로 돌리면 의미가 없다). 그 외 initialCapital
  1억, equalWeight, 정수 주식수, sameDayCashReuse=false, 연속보유 병합, 비용
  15bps/측(왕복 30bps)·슬리피지 0 — 전부 기존 정책 그대로.
- **구간 분할**: 월별 MTM 스냅샷(129개 = 시작점 + 128월말)을 시간순 60/15/25%로
  분할. 각 구간은 그 구간 첫 스냅샷을 t0으로, 그 구간 자체의 등락만 본다(CAND1·
  Opening Fade·pbr-combined의 기존 분할 원리).
- **비교군**: (a) 기존 PBR baseline topN=30 — 실제 엔진 run_smoke("pbr_value_v1")
  그대로, (b) EW 벤치마크 ew_benchmark_liquid_v1(같은 유동성 유니버스 전부).
- **플라시보**: TRAIN 선택 topN=100에 대해 매달 PBR 순위를 그 달 내에서 셔플
  (permutation null, seed 고정)한 같은 보유 구조를 같은 엔진으로 실행해
  "선택된 크기에만 기인하는 성과"와 구분했다.

## 2. baseline 재현 (현재 정본 데이터 기준)

기존 PBR baseline을 현재 커밋된 정본(selection.json이 2026-09 리밸런싱까지
확장된 상태, `62c376b` 2026-09-04)으로 재실행했다.

| 항목 | run_smoke("pbr_value_v1") 직접 재실행 | 동일 데이터 topN=30 인메모리 | pinned 2026-09-02 report |
|---|---|---|---|
| full CAGR | 5.49% | 5.49% | 4.72% |
| full Sharpe | 0.519 | 0.519 | 0.456 |
| full MDD | -21.1% | -21.1% | -21.7% |
| closed | 777 | 777 | 756 |

차이는 **데이터 상태**(데이터 계약) 차이다: pinned 2026-09-02 report는 2026-09
리밸런싱 확장 이전 selection.json(127개월) 기준이고, 지금 정본은 9월 확장
(128개월)까지 포함한다. 인메모리 topN=30이 실제 엔진 재실행과 byte-level로
같은 결과를 내므로(둘 다 CAGR 5.49%·Sharpe 0.519·777종목) 인메모리 선택 로직이
현재 정본 선택과 정확히 일치함을 확인했다. 이후 모든 지표는 현재 정본 기준이다.

## 3. 결과 — 실측치

주 실행 결과(전체기간 2016-01-01~2026-08-14, 월별 MTM):

| 항목 | 값 |
|---|---|
| CONDITIONS | topN={10,20,30,50,100}; TRAIN 선택 → VALID/TEST 고정 |
| CAGR | **6.05%** (TRAIN 선택 topN=100, 전체기간 실측) |
| SHARPE | **0.614** (같은 곡선) |
| MDD | **-15.3%** |
| WINRATE | **53.7%** (실제 계산값, N=2,231 체결 기준) |
| N | **2,231** (closed trades, 실제 체결 건수) |
| T-STAT | **2.00** (월별수익/0, 128개월) · **1.20** (EW 초과, 실제 계산) |
| REASON | TRAIN에서 Sharpe 1위로 선택된 topN=100이 VALID에서 5후보 중 최하위(-0.149)로 붕괴 — TRAIN→VALID 순위가 완전 역전, OOS에서 선택 유지 실패. topN=10이 유일하게 전 구간 양수였으나 TRAIN 2위라 선택 안 됨(사후 재선택 안 함). |

### 후보별 전체기간 성과 (실측)

| topN | avgSel/월 | tickers | CAGR | Sharpe | MDD | WINRATE | N(체결) | t(vs 0) | t(vs EW) |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 10 | 10.0 | 91 | 8.05% | 0.659 | -18.4% | 52.4% | 296 | 2.15 | 1.72 |
| 20 | 19.9 | 135 | 5.25% | 0.492 | -18.6% | 51.0% | 547 | 1.61 | 0.98 |
| 30 | 29.7 | 172 | 5.49% | 0.519 | -21.1% | 51.1% | 777 | 1.69 | 1.02 |
| 50 | 49.4 | 259 | 5.60% | 0.549 | -18.3% | 51.9% | 1,173 | 1.79 | 1.04 |
| **100** | 98.6 | 409 | **6.05%** | **0.614** | **-15.3%** | 53.7% | 2,231 | 2.00 | 1.20 |

비교군: EW 벤치마크 full CAGR 2.30%·Sharpe 0.230·MDD -25.7% / PBR baseline
topN=30 full CAGR 5.49%·Sharpe 0.519·MDD -21.1%.

### TRAIN / VALID / TEST별 CAGR·Sharpe·MDD (별도 표)

TRAIN = 2016-01-01 ~ 2022-05-31 (78 스냅샷)
VALID = 2022-05-31 ~ 2023-12-28 (20 스냅샷)
TEST = 2023-12-28 ~ 2026-08-14 (33 스냅샷)

| topN | TRAIN CAGR | TRAIN Sharpe | TRAIN MDD | VALID CAGR | VALID Sharpe | VALID MDD | TEST CAGR | TEST Sharpe | TEST MDD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 7.82% | 0.623 | -18.4% | 9.58% | **0.726** | -7.7% | 7.71% | 0.695 | -11.6% |
| 20 | 5.90% | 0.549 | -18.6% | 1.71% | 0.190 | -10.1% | 5.84% | 0.553 | -14.7% |
| 30 | 6.80% | 0.607 | -21.1% | 0.39% | 0.091 | -10.3% | 5.50% | 0.579 | -12.7% |
| 50 | 6.17% | 0.585 | -18.3% | -0.80% | -0.008 | -10.0% | 8.18% | **0.852** | -10.6% |
| **100** | **8.04%** | **0.757** | -15.3% | **-2.17%** | **-0.149** | -9.5% | 6.45% | 0.749 | -9.8% |
| EW | 4.49% | 0.451 | -17.9% | -3.96% | -0.161 | -16.0% | 0.99% | 0.144 | -25.7% |

### 순위 유지 여부 (5개 후보의 Sharpe 기준 순위)

| 구간 | 순위 (1→5) |
|---|---|
| TRAIN | [100, 10, 30, 50, 20] |
| VALID | [10, 20, 30, 50, 100] |
| TEST | [50, 100, 10, 30, 20] |

**TRAIN 1위(topN=100)가 VALID에서 최하위(-0.149, 유일한 큰 음수)로 떨어진다**
— 선택 기준(Sharpe)으로 본 순위가 TRAIN→VALID에서 완전 역전했다. VALID는
2022.5~2023.12 밸류 불리 국면으로 EW도 -0.161로 음수였으나, 같은 국면에서
topN=10은 +0.726으로 1위를 지켰다. TEST에서는 topN=100이 다시 +0.749로 2위로
회복해 "VALID만 이상한가"라는 의문도 있으나, 이 실험의 사전 규칙상 TEST를 보고
다시 고르지 않는다. 순위 자체가 구간별로 고정되지 않았다(3개 구간 3종의 순위).

## 4. 플라시보 대조 (선택된 topN=100에 대한 permutation null)

PBR 순위를 매달 셔플한 불리한 유사 샘플(topN=100, seed 고정)을 같은 엔진으로 실행:

| 항목 | 실제 topN=100 | 플라시보 topN=100 (순위 셔플) |
|---|---|---|
| full CAGR | 6.05% | 2.30% |
| full Sharpe | 0.614 | 0.248 |
| full MDD | -15.3% | -23.6% |
| TRAIN Sharpe | 0.757 | 0.669 |
| VALID Sharpe | -0.149 | -0.103 |
| TEST Sharpe | 0.749 | **-0.427** |
| WINRATE | 53.7% | 44.9% |
| N | 2,231 | 11,480 |
| t (vs EW) | 1.20 | -0.13 |

- TRAIN에서 실제 신호(0.757)와 플라시보(0.669)의 Sharpe 차이는 0.09 정도로
  **얇다** — "topN=100을 큰 폭으로 보유"라는 설정 자체가 TRAIN에서 운으로도
  높은 Sharpe를 만들 수 있는 구조라는 뜻이다(플라시보도 TRAIN Sharpe 0.67).
- VALID에서는 실제(-0.149)와 플라시보(-0.103) 모두 음수로, 이 구간에서 topN=100
  설정의 열위는 신호의 존재 여부와 무관했다.
- TEST에서는 실제(+0.749)가 플라시보(-0.427)를 크게 앞선다 — 최근 구간에서
  저PBR 신호의 정보가 플라시보와 구분되는 유일한 지점.

## 5. 정리 (관측 사실, 판정 아님)

1. **TRAIN 선택 규칙으로는 topN을 고를 수 없었다.** TRAIN Sharpe 1위(topN=100)가
   VALID에서 5후보 중 최하위로 붕괴하고, 구간별 순위가 뒤바뀐다.
2. **관측상 유일하게 전 구간 Sharpe>0인 후보는 topN=10** (0.623/0.726/0.695,
   TRAIN 2위·VALID 1위·TEST 3위). 강한 상위집합을 오래 보유할수록(값을 희석할수록)
   VALID에서 취약해지는 패턴이 보인다. 단 이 지침대로 **사후 재선택하지 않으므로**
   이 문장은 "TRAIN 선택이 아니었으면"이라는 대안 역사적 관측이다.
3. 선택한 topN=100의 전체기간 월별 초과수익은 t≈1.20(EW 대비)으로 이 프로젝트의
   통상 유의성 기준(t≥2)에 미달이며, 플라시보와의 차이도 TEST 구간에서만 관측된다.
4. 전체기간 풀링 성과(CAGR 6.05%)는 **결정 근거로 쓰지 않는다** — 이 실험은
   OOS에서의 순위 유지가 목적이었고 그것이 무너졌기 때문(§판정 금지 규칙).
5. quote: 데이터 계약(pit, valuation-panel 선택 규칙, turnover20, a2a 수정주가,
   MTM 회계, 절대유동성 임계값, 연속보유, 비용) 완화 없음.

## 6. 재현

```
python research/strategy-lab/run_pbr_topn_strength_oos.py     # topN 그리드 + baseline/EW 재현
python research/strategy-lab/run_pbr_topn_placebo_oos.py      # 플라시보 (permutation null, topN=100)
```

출력:
`research/strategy-lab/reports/2026-09-06-pbr-topn-strength-oos/pbr-topn-strength-oos.json`
`research/strategy-lab/reports/2026-09-06-pbr-topn-strength-oos/pbr-topn-placebo.json`

실행 시각: 2026-09-06, 각 topN 하나당 run_smoke 전체기간 1회(바 캐시 재사용).