---
track: kr
factor: pbr-quality-vt-filter-oos
date: 2026-09-06
verdict: UNCLASSIFIED
criteria_version: v1
conditions: ["QCOMP = 06(quality-composite-oos)과 동일 정의 — roe+op_margin+net_margin+debt_ratio(역)+current_ratio+roe_consistency+op_margin_trend 7종 월별 pct-rank 동일가중, retention 제외", "PBR = 기존 pbr_value_v1 정의(valuation-panel pbr 오름차순, Top-N=30)", "Quality 는 PBR score 에 합산하지 않고 하위 20% 제외 이진 필터로만 사용 — QCOMP 결측 종목은 제외하지 않음", "유니버스 = data/factor-panel/kr-monthly-v1.parquet, liquid(dv20>=1e8) + pbr>0, 2026-09-06 패널 버전", "월별 리밸런스 EW 패널 백테스트(fwd1m) — 엔진 풀 백테스트 아님", "비용 = 월별 turnover x 왕복 30bp, 슬리피지 미포함", "매개변수(member·topN=30·cutoff 20%·liquid) 3구간 고정, TEST 보고 후 변경 없음, 스윕 없음"]
reason: >-
  "하위 Quality 20% 제외"가 PBR Top-30 포트폴리오를 개선한다는 증거 없음. 필터는 매월
  보유의 20~27%를 실제로 바꾸는데(Jaccard TRAIN 0.577 / VALID 0.723 / TEST 0.668,
  제거 평균 8.28 / 4.89 / 6.06종) 성과는 TRAIN 소폭 개선(Sharpe 0.209->0.254, MDD
  -44.4->-43.0, excess t 0.17->0.56) / TEST 소폭 열위(0.742->0.737, excess t
  1.093->1.031)로 전 구간 일관 효과가 없다. value trap 진단은 TRAIN 에서 가설과 정반대 —
  제외 대상의 fwd1m(+0.700%/월)이 잔여(+0.380%)보다 높았다(spread t=+1.49). TEST 에서만
  방향이 맞고(-0.02 vs +0.47) t=-0.95 로 미유의. QCOMP IC 는 06 과 같은 패턴으로 TEST
  에서만 강하지만(TRAIN t=0.81 -> TEST t=4.99) 이진 필터로 PBR 에 덧씌우면 남는 기여가
  거의 없다. rule_discovery_criteria.json v1 성숙도 게이트(TRAIN excess t >=2.0 /
  VALID >=1.5) 미달로 기준 미달 관측치. 06(HOLD)과 충돌하지 않는다 — 그쪽은 단독 알파,
  이쪽은 PBR 필터로의 쓰임을 물었고 답이 다를 뿐이다.
cagr: 12.70
sharpe: 0.737
mdd: -16.8
win_rate: 53.3
n: 30
t_stat: 1.03
stats:
  train: {baseline: {cagr: 2.12, sharpe: 0.209, mdd: -44.4, win_rate: 55.6, n: 63, excess_t: 0.17, turnover: 0.197}, filtered: {cagr: 3.24, sharpe: 0.254, mdd: -43.0, win_rate: 58.7, n: 63, excess_t: 0.56, turnover: 0.203}}
  valid: {baseline: {cagr: 5.05, sharpe: 0.330, mdd: -11.2, win_rate: 52.9, n: 17, excess_t: 0.77, turnover: 0.159}, filtered: {cagr: 5.34, sharpe: 0.342, mdd: -11.7, win_rate: 52.9, n: 17, excess_t: 0.87, turnover: 0.145}}
  test: {baseline: {cagr: 12.60, sharpe: 0.742, mdd: -17.5, win_rate: 53.3, n: 30, excess_t: 1.09, turnover: 0.233}, filtered: {cagr: 12.70, sharpe: 0.737, mdd: -16.8, win_rate: 53.3, n: 30, excess_t: 1.03, turnover: 0.241}}
  overlap: {train: {removed_avg: 8.28, jaccard: 0.577}, valid: {removed_avg: 4.89, jaccard: 0.723}, test: {removed_avg: 6.06, jaccard: 0.668}}
  ic_pbr: {train: {mean: -0.0567, t: -3.79}, valid: {mean: -0.0563, t: -2.29}, test: {mean: -0.0980, t: -3.74}}
  ic_qcomp: {train: {mean: 0.0077, t: 0.81}, valid: {mean: 0.0289, t: 1.71}, test: {mean: 0.0499, t: 4.99}}
  value_trap_spread_pct: {train: {excluded: 0.700, retained: 0.380, spread: 0.320, t: 1.49}, valid: {excluded: 0.739, retained: 0.765, spread: -0.026, t: -0.06}, test: {excluded: 0.019, retained: 0.474, spread: -0.454, t: -0.95}}
---

# Quality as PBR Value-Trap Filter OOS (2026-09-06)

실험 정의(MD 2026-09-06): Quality Composite 이 독립 알파인지가 아니라,
PBR 포트폴리오의 **value trap 제거로 위험조정성과를 개선하는지** 검증한다.
06(Quality Composite OOS)의 QCOMP 정의를 그대로 쓰고, PBR 정의는 기존
`pbr_value_v1`(valuation-panel pbr 오름차순, Top-N=30, liquid 게이트)을 그대로
쓴다. Quality 는 PBR score 에 합산하지 않고 **하위 20% 제외 필터로만** 사용한다.

## 사전 고정 규칙 (성과 계산 전 확정)

- 유니버스: `data/factor-panel/kr-monthly-v1.parquet`, `liquid`
  (dv20>=1e8) + `pbr>0`, 월별 스냅샷 (2026-09-06 패널 버전)
- QCOMP: 06 과 동일 — `roe·op_margin·net_margin·debt_ratio(역)·current_ratio·
  roe_consistency·op_margin_trend` 각각을 월별 크로스섹션(전체 liquid)에서
  pct-rank 후 방향 적용 동일가중. retention 제외(06 과 동일, 커버리지 이유).
- Filter: 각 월 PBR 적격집합 중 QCOMP 스코어가 있는 종목의 하위 20% 제외 →
  잔여에서 PBR 오름차순 상위 30. 스코어 없는 종목은 quintile 로 제외하지
  않음. 매개변수(member·topN=30·cutoff 20%·liquid) 3구간 고정, TEST 보고 후
  변경 없음.
- 비용: 월별 turnover × 왕복 30bp (policy cost, 슬리피지 미포함 보수 가정).

## 판정 요약

**REASON / verdict: UNCLASSIFIED — "하위 Quality 20% 제외"가 PBR Top-30
포트폴리오를 개선한다는 증거 없음.** 필터는 매월 포트폴리오 구성 ~20~27%를
바꾸는데(Jaccard TRAIN 0.577 / VALID 0.723 / TEST 0.668), 성과는 TRAIN
소폭 개선(Sharpe 0.209→0.254, MDD -44.4→-43.0, excess t 0.17→0.56)과 TEST
소폭 열위(Sharpe 0.742→0.737, excess t 1.093→1.031)로 전 구간에 걸친 일관
효과가 없다. 반직관적으로 TRAIN 에서 제외된 "하위 Quality" 종목의 fwd1m 평균
(+0.70%/월)이 잔여(+0.38%)보다 더 높았다(spread t=+1.49) — value trap 가설과
정반대 신호. TEST 에서만 제외 대상이 잔여보다 낮은 전방수익(-0.02 vs +0.47,
t=-0.95)을 보였으나 필터 적용 포트폴리오의 improvement 는 미미했다.

→ 06 결과와 일관: QCOMP IC 는 TEST 에서 강함(아래 IC 재계산)이지만, 그 신호를
"하위 20% 제외"라는 이진 필터로 PBR 포트폴리오에 덧씌우면 남는 기여가 거의
없다. 성숙도 게이트(TRAIN ≥2.0 / VALID ≥1.5 / TEST ≥1.5, 부호일관) 기준
미달 등급.

## 측정 결과 (실측 수치)

### 포트폴리오 비교 — 보고 순서: CAGR → Sharpe → MDD → WINRATE → N → T-STAT → REASON

TRAIN (63개월):
- baseline : CAGR 2.12% · Sharpe 0.209 · MDD -44.4% · WinRate 55.6% · N=63 · excess t 0.17
- filtered : CAGR 3.24% · Sharpe 0.254 · MDD -43.0% · WinRate 58.7% · N=63 · excess t 0.56

VALID (17개월):
- baseline : CAGR 5.05% · Sharpe 0.330 · MDD -11.2% · WinRate 52.9% · N=17 · excess t 0.77
- filtered : CAGR 5.34% · Sharpe 0.342 · MDD -11.7% · WinRate 52.9% · N=17 · excess t 0.87

TEST (30개월):
- baseline : CAGR 12.60% · Sharpe 0.742 · MDD -17.5% · WinRate 53.3% · N=30 · excess t 1.09
- filtered : CAGR 12.70% · Sharpe 0.737 · MDD -16.8% · WinRate 53.3% · N=30 · excess t 1.03

excess = 포트폴리오 fwd1m EW − 해당 월 PBR 적격집합 EW. 비용 반영은 월별
turnover × 30bp 왕복으로 계산한 net 기준(위 수치). turnover:
TRAIN 0.197→0.203 / VALID 0.159→0.145 / TEST 0.233→0.241 (filter 가 회전율을
의미 있게 늘리지 않음).

### 필터가 실제로 무엇을 바꿨는가 (overlap)

월별 baseline‑filtered 보유 30종목 교체 규모:
- TRAIN: 제거 평균 8.28종, Jaccard 0.577, 63/64개월 변화
- VALID: 제거 평균 4.89종, Jaccard 0.723, 18/18개월 변화
- TEST:  제거 평균 6.06종, Jaccard 0.668, 31/31개월 변화

→ 포트폴리오는 만지지만 성과는 거의 안 움직임.

### IC (월별 Spearman, PBR 적격집합 기준)

- PBR IC (baseline 적격): TRAIN -0.0567 t=-3.79 / VALID -0.0563 t=-2.29 / TEST -0.0980 t=-3.74
  → PBR 자체의 value 효과는 전 구간 유의(오름차순 가치 신호 일관).
- QCOMP IC (filtered 적격): TRAIN +0.0077 t=0.81 / VALID +0.0289 t=1.71 / TEST +0.0499 t=4.99
  → QCOMP 는 TEST 에서만 보강된 신호(06 과 동일 패턴: TRAIN 미약 → TEST 강화).

### value trap 진단 (제외 대상 vs 잔여, fwd1m 평균)

- TRAIN: 제외 +0.700%/월 vs 잔여 +0.380%  → spread +0.320, t=+1.49 (가설 반대)
- VALID: 제외 +0.739% vs 잔여 +0.765%      → spread -0.026, t=-0.06
- TEST:  제외 +0.019% vs 잔여 +0.474%      → spread -0.454, t=-0.95 (가설 방향만)

→ "PBR 하위에서 Quality 나쁜 종목이 수익을 깎는다"는 신호는 TEST 에서만
방향이 맞고 통계적으로 미유의. TRAIN 에서는 정반대.

## 방법론 메모

- 패널 기반 월별 재균형 EW (fwd1m), 엔진 풀 백테스트 아님 — 06 과 동일 기준.
  회전율·비용은 패널 보유 집합 교체율 × 30bp 로 근사. 실제 실행 엔진
  검증(run_pbr_topn_strength 계열)은 이 실험 범위 밖.
- cutoff 를 비롯한 매개변수는 실험이 명시한 단일값(spec)으로 고정했고, 스윕·
  튜닝 없음. TEST 결과를 보고 나서 결정 변경 없음.
- 산출물: `reports/2026-09-06-pbr-quality-vt-filter/pbr-quality-vt-filter-oos.json`,
  코드 `pbr_quality_vt_filter_oos.py`.

## 정본 기준 대조

- 06(Quality Composite OOS, HOLD): QCOMP 단독 상위 decile 은 TEST 에서만
  난수선 통과. 본 실험은 "단독 알파"가 아니라 "PBR 필터"로의 쓰임을 확인한
  것 — 결론이 충돌하지 않는다(필터 기여 없음 + TEST 에서의 QCOMP 신호는 06과
  동일 방향).
- rule_discovery_criteria.json v1: excess t 기준 TRAIN <2.0, VALID <1.5 모두
  미달 → 기준 미달 관측치.