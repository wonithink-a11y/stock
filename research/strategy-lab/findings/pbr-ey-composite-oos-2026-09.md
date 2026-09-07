---
track: kr
factor: pbr_ey_composite_oos
subproject: pbr-value-v1 / earnings-yield (가치 팩터 50:50 composite 질문)
date: 2026-09-06
verdict: REJECT
criteria_version: oos-split-v1
conditions: ["유니버스=liquid(dv20>=1e8) ∩ (pbr & earnings_yield 존재) 교집합(83,013행·1,347종목)", "PBR=panel pbr(PIT valuation-panel) 저PBR 좋음(오름차순)", "EY=panel earnings_yield=1/per(PIT) 높을수록 좋음", "composite=0.5*(1-pbr_rank_pct)+0.5*ey_rank_pct (50:50 사전 고정, sweep 없음)", "top-decile EW 월 리밸런스 롱온리", "3구간 TRAIN<=2022-06-30 < VALID<=2024-01-01 < TEST", "비용 30bps(baseline)/50/65bps — 월 전량 교체 rule + turnover-aware 병기", "benchmark=교집합 EW", "TEST 후 weight/topN 재선택 없음"]
reason: >-
  50:50 composite은 TEST(31월)에서 CAGR 11.98%·Sharpe 0.705로 PBR 단독(13.63%·0.774)
  에 못 미치고, 단지 EY 단독(10.80%·0.654)보다 나은 수준에 그친다 — 세 단일·합성
  전략 중 TEST net30 CAGR·Sharpe 순위가 2위/2위로, 가장 좋은 단일 팩터를 능가하지
  못한다. TEST MDD(-14.8%)도 두 단일(-15.1/-14.4)의 중간, TEST WinRate(51.6%)는
  셋 중 최저다. PBR과 EY의 월별 rank 상관이 0.590(t=119.7)으로 매우 높고, 두
  신호가 같은 밸류 신호의 양면이라 top-decile 교집합(Jaccard)도 0.32 이상이다.
  즉 composite은 "평균값 대체"로 PBR의 정보를 희석시킬 뿐 진정한 분산 이득이
  없다. 사전 판정 기준("composite TEST가 최선 단일 팩터의 net30 CAGR·Sharpe를
  능가해야 KEEP")대로 REJECT한다.
cagr: 0.1198
sharpe: 0.705
mdd: -0.1483
win_rate: 0.5161
n: 31
t_stat: 6.117
stats:
  pbr_only_test: {cagr: 0.1363, sharpe: 0.774, mdd: -0.1513, win_rate: 0.5484, n: 31, ic_t: 5.784, excess_t: 1.762}
  ey_only_test: {cagr: 0.108, sharpe: 0.654, mdd: -0.1444, win_rate: 0.5484, n: 31, ic_t: 6.094, excess_t: 1.477}
  comp_test: {cagr: 0.1198, sharpe: 0.705, mdd: -0.1483, win_rate: 0.5161, n: 31, ic_t: 6.117, excess_t: 1.633}
  rank_corr_pbr_ey: {mean: 0.59016, t: 119.741, nMonths: 126}
  overlap_jaccard_topdecile: {pbr_vs_ey_test: 0.3269, pbr_vs_comp: 0.503, ey_vs_comp: 0.5743}
  comp_share_with_pbr: 0.667
  comp_share_with_ey: 0.728
  turnover_mean: {pbr: 0.1689, ey: 0.1551, comp: 0.1613}
---

# PBR + Earnings Yield 50:50 Composite — OOS (2026-09-06)

## 1. 실험 정의

기존 cross-sectional 연구(EY robustness·quality composite)와 동일한 방법·데이터
계약(PIT valuation-panel)으로, **PBR 단독 / EY 단독 / PBR+EY 50:50 합성**을 완전
동일한 universe·split·rebalance·cost 조건에서 비교해 composite이 단일 팩터 대비
OOS 포트폴리오 성과를 실제로 개선하는지 검증했다.

- **사전 고정**: weight=50:50, top-decile EW 월 리밸런스 롱온리, cost 30/50/65bps,
  benchmark=교집합 EW, 3구간(TRAIN≤2022-06-30 < VALID≤2024-01-01 < TEST). TEST
  결과 후 weight·topN 재선택 없음. 파라미터 선택·TRAIN 조건부 판단 없음.
- **유니버스**: `liquid(dv20≥1e8)` ∩ (pbr & earnings_yield 존재) 교집합 83,013행·
  1,347종목·126개월(월평균 단면 659종목). 이 교집합은 **full EY universe
  (83,088행)와 실질 동일**하므로 EY는 최종 robustness의 canonical 정의 그대로이고
  EY∩LOWMOM(13.32% 유니버스)은 전혀 혼용하지 않았다.
- **신호**: score_pbr = 1 − pbr.rank(pct)[저PBR=1] / score_ey = earnings_yield.
  rank(pct)[고EY=1] / composite = 0.5·score_pbr + 0.5·score_ey.

## 2. PBR-only / EY-only / PBR+EY 50:50 비교 — 가격 지표 (TEST, net 30bps)

| 항목 | PBR-only | EY-only | **PBR+EY 50:50** |
|---|---:|---:|---:|
| CAGR    | **13.63%** | 10.80% | 11.98% |
| SHARPE  | **0.774**  | 0.654  | 0.705  |
| MDD     | -15.1%    | -14.4% | -14.8% |
| WINRATE | **54.8%** | 54.8%  | 51.6%  |
| N       | 31        | 31     | 31     |
| T-STAT(IC) | 5.784  | 6.094  | **6.117** |
| excess t(EW) | **1.762** | 1.477 | 1.633 |
| REASON  | 최선 단일 | EY TEST 10.80%(canonical full-EY 10.79%와 일치) | PBR·EY 중간 — 최선 단일 능가 못함 |

composite은 **월별 IC t가 셋 중 최고(6.117)**이나, 이 IC 우위가 포트폴리오
순위로 이어지지 않는다. IC는 신호-수익률 관계의 일부만 보여주며, portfolio
return 기준 판단에서는 composite이 최선 단일(PBR)에 CAGR -1.65pp·Sharpe -0.069
만큼 뒤처진다.

## 3. TRAIN / VALID / TEST 성과 (net 30bps)

| 전략 | TRAIN CAGR | TRAIN Sharpe | VALID CAGR | VALID Sharpe | TEST CAGR | TEST Sharpe | TEST MDD |
|---|---:|---:|---:|---:|---:|---:|---:|
| PBR-only | 3.76% | 0.278 | 2.85% | 0.233 | **13.63%** | **0.774** | -15.1% |
| EY-only | -0.30% | 0.100 | 1.27% | 0.160 | 10.80% | 0.654 | -14.4% |
| **COMP 50:50** | 2.83% | 0.240 | 2.32% | 0.208 | 11.98% | 0.705 | -14.8% |

- 3구간 어느 곳에서도 composite이 **동시에** 두 단일을 이기지 않는다(모든 구간에서
  PBR과 EY 사이에 위치 — "평균값" 전략).
- TRAIN에서 EY만 음수였고, composite TRAIN이 PBR에 근접한 것은 EY(약한 +)가 PBR의
  음수 구간을 섞어 향상시킨 형태. 그러나 그 "향상"은 절대 기준에서 큰 의미가 없다
  (TRAIN CAGR 2.83% vs 3.76%).
- 구간 안정성: 세 전략 모두 3구간 순위가 유지되지 않고 TEST에서 재정렬된다. 단 이
  실험의 질문은 "composite 선택"이므로 구간별 순위가 아니라 
  **composite vs 최선 단일의 상대 위치**가 판단 기준이다.

## 4. 비용 및 turnover

월 전량 교체 기준(기존 rule) net CAGR (TEST):

| cost | PBR-only | EY-only | **COMP** |
|---|---:|---:|---:|
| 30bps | 13.63% | 10.80% | 11.98% |
| 50bps | 10.96% | 8.19% | 9.34% |
| 65bps | 8.99% | 6.27% | 7.40% |

- **실측 turnover**(월 교체분율): PBR 16.9%(p95 29.7%), EY 15.5%(p95 53.0%),
  composite 16.1%(p95 40.3%). composite 매월 보유 수 67.3종목 평균.
- composite는다른 단일과 비슷한 turnover라 **비용 측면 불이익 없음** — 그러나
  이득도 없음.
- **turnover-aware net**(실측 turnover로 비용 차감, 전체기간 124개월):
  PBR 30/50/65bps → 9.19%/8.74%/8.40% (Sharpe 0.526/0.507/0.492),
  EY → 5.74%/5.34%/5.04% (0.371/0.353/0.339),
  COMP → 8.16%/7.73%/7.41% (0.488/0.469/0.455).
  turnover-aware에서도 composite은 최선 단일(PBR)에 CAGR -1.0pp~-1.3pp·Sharpe
  -0.04~-0.05 뒤처진다.

## 5. factor correlation / portfolio overlap

- **rank 상관**: 월별 PBR-score ↔ EY-score Spearman 평균 **0.590**(126개월,
  t=119.7). 두 팩터는 서로 다른 입력(순이익 기반 per / 자본 기반 pbr)이지만
  결국 "저평가(밸류)" 한 축의 양면이라 강한 양의 상관. 상관이 낮아야 분산 이득이
  있는데 이 정도면 실질적으로 같은 신호다.
- **top-decile portfolio overlap (Jaccard)**:
  | 쌍 | ALL | TRAIN | VALID | TEST |
  |---|---|---:|---:|---:|
  | PBR ∩ EY | 0.317 | 0.285 | 0.432 | 0.327 |
  | PBR ∩ COMP | 0.503 | 0.474 | 0.592 | 0.521 |
  | EY ∩ COMP | 0.574 | 0.549 | 0.640 | 0.598 |
- composite top-decile은 평균적으로 PBR 종목의 **66.7%**·EY 종목의 **72.8%**를
  포함한다. 즉 composite 포트는 두 단일과 크게 겹쳐 "새로운 종목군"이 아니라
  기존 종목의 배합일 뿐이다. PBR∩EY 자체가 32% 겹치는 상태에서 composite은 추가
  정보를 실질적으로 제공하지 못한다.

## 6. 최종 verdict — REJECT

판정 기준(사전 고정): composite의 TEST net30 **CAGR과 Sharpe가 최선 단일 팩터를
능가하거나 실질 동등이어야 KEEP**; 열위 또는 차이가 판단 곤란하면 REJECT.

- TEST net30: COMP 11.98%/0.705 vs PBR 13.63%/0.774 → **CAGR -1.65pp, Sharpe
  -0.069로 최선 단일에 명백히 열위**. EY(10.80%/0.654)보다 나은 것만으로는 채택
  근거가 없다(기준은 "최선 단일" 대비).
- MDD 개선 없음(-14.8%은 두 단일의 중간), TEST WinRate가 셋 중 최저(51.6%),
  excess t도 PBR에 못 미침(1.633 vs 1.762).
- 상관 0.59·overlap 0.32 이상에서 알 수 있듯 **분산(α 추가) 없이 PBR 정보를
  희석**했을 뿐. turnover는 비슷해서 비용 불이익도, 이득도 없다.
- → **REJECT**: 50:50 고정 composite을 PBR 단독 대신 채택하지 않는다. (포트폴리오
  연구로서 EY 단독 10.80% TEST는 canonical 10.79%와 일치해 EY 정의·방법의 정합성은
  재확인됨.)

## 7. 다음 단계 제안

1. **PBR top-decile 단독 강도 재검증**: 본 실험에서 PBR-only(panel, top-decile)는
   TEST 13.63%/0.774로 기존 PBR 엔진 baseline(topN=30, 5.49%/0.519)보다 훨씬
   강했다. 패널·decile 방법론 기준으로 PBR 단독 OOS robustness(upstream 유니버스,
   size 잔차화, 업종중립)를 별도 실험으로 다룰 만하다(이 실험은 composite 판정이
   목적이라 결론으로 확장하지 않음).
2. **진짜 무상관 보강 팩터 탐색**: raw PBR과 raw EY는 상관 0.59로 중복이 크다.
   EY의 업종중립/잔차화 버전(sector_rel_earnings_yield 등)처럼 PBR과 de-correlated된
   EY 정의로 다시 composite를 평가하는 것이 의미 있는 후속이다.
3. 50:50 외 가중치는 이 실험 범위가 아니었으므로, REJECT 이후 "가중치 탐색이
   정당한가"는 별도 가설로 사전 설계 후 진행.

## 재현

```
python research/strategy-lab/09_pbr_ey_composite_oos.py
```

출력: `research/strategy-lab/reports/2026-09-06-pbr-ey-composite-oos/pbr-ey-composite-oos.json`
실행 시각: 2026-09-06, 약 10초. production 정책·엔진·selection.json·데이터 미수정.
commit/push 없음.