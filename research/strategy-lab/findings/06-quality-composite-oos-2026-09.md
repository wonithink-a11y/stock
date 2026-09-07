---
track: kr
factor: quality-composite-oos
date: 2026-09-06
verdict: HOLD
criteria_version: v1
conditions: ["QCOMP = roe+op_margin+net_margin+debt_ratio(저)+current_ratio+roe_consistency+op_margin_trend 7종 동일가중 월별 pct-rank 평균 (성과 계산 전 사전 고정)", "retention 제외 — 커버리지 60.7%로 교집합 붕괴(46% TRAIN) 우려, 성과 아님", "월 리밸런스 / dv20>=1e8 절대 유동성 게이트 / min_names=30 / top decile 롱온리 / 3구간 매개변수 동일"]
reason: "횡단면 IC 는 3구간 전부 양(+)·부호일관·유의(TRAIN t=3.82 → VALID 4.24 → TEST 7.82, 오히려 강해짐)로 '사전정의 다개 quality 결합의 예측력'을 지지한다. 그러나 실현 가능한 상위 decile 전략은 TEST(t=2.98, null p95=1.60 초과)에서만 난수선을 넘고 TRAIN(t=-0.45)은 오히려 음 — 'TRAIN 강→TEST 붕괴'의 역방향으로 '최근 기간 전용' 신호다. 또 ROE 조건부 잔차 IC 3구간 전부 ~0 이라 'composite 이 ROE 를 넘어서는 독립 정보'는 아니다(상위 decile 페어 차 t=0.17~1.18 미유의)."
cagr: 8.91
sharpe: 0.52
mdd: -21.8
win_rate: 58.1
n: 31
t_stat: 2.98
stats:
  full: {cagr: 1.67, sharpe: 0.185, mdd: -36.8, win_rate: 56.2, nMonths: 112, excess_t: 1.461, max_single_year_pct: 51.4}
  train: {cagr: -3.0, sharpe: -0.02, mdd: -36.8, win_rate: 54.0, nMonths: 63, excess_t: -0.452, mean_excess_pct: -0.105}
  valid: {cagr: 6.46, sharpe: 0.396, mdd: -15.0, win_rate: 61.1, nMonths: 18, excess_t: 0.897, mean_excess_pct: 0.283}
  test: {cagr: 8.91, sharpe: 0.517, mdd: -21.8, win_rate: 58.1, nMonths: 31, excess_t: 2.976, mean_excess_pct: 0.944}
  ic: {train: {mean: 0.0342, t: 3.82}, valid: {mean: 0.0544, t: 4.24}, test: {mean: 0.0851, t: 7.82}}
  spread_d10_d1: {train: {pct: 0.035, t: 0.10}, valid: {pct: 0.297, t: 0.48}, test: {pct: 1.974, t: 3.18}}
  roe_alone: {train: {cagr: -4.4, excess_t: -1.611}, valid: {cagr: 3.79, excess_t: 0.334}, test: {cagr: 5.84, excess_t: 2.416}}
  independence_vs_roe: {residual_ic_train_t: 0.77, residual_ic_valid_t: 0.10, residual_ic_test_t: 1.36, paired_excess_diff_test_t: 0.78}
  null_bar95: {train: 1.92, valid: 1.79, test: 1.60}
  test_years_excess_pct: {2024: 1.19, 2025: 0.49, 2026: 1.30}
---

# 06 — Quality Composite Factor OOS (2026-09-06)

## 실험 설계 (사전 정의 — 성과 계산 전에 전부 고정)

- **핵심 질문**: 단일 ROE 필터 대신 여러 quality 신호를 사전 정의된 방식으로 묶으면
  한국 주식의 횡단면 예측력이 독립적으로 유지되는가.
- **사후 선택 금지**: 좋았던 quality 변수만 골라서 다시 조합하지 않는다. composite
  멤버·가중·decile 임계·3구간 분할을 실험 전에 확정했다.
- **QCOMP** (동일가중 월별 pct-rank 평균, 양=좋음):
  `roe(high) + op_margin(high) + net_margin(high) + debt_ratio(low) + current_ratio(high) + roe_consistency(high) + op_margin_trend(high)`.
- **retention 제외**: 데이터 커버리지 60.7%(probe 2026-09-06)라 7종+retention
  교집합이 TRAIN 에서 46.5%로 붕괴한다. 성과가 아니라 데이터 가용성 기준의 사전 결정
  (타 팩터는 구간별 커버리지 88~97%).
- 랭킹 규약: sweep_combos.py 와 동일 — 팩터별 자기 non-NaN 집합 안에서 pct-rank
  후 방향 적용, 동일가중 평균. 적격 종목 = 선택 팩터 전부 존재(liquid).
- 매개변수: 월 리밸런스, dv20>=1e8 절대 게이트, min_names=30, 상위 decile 롱온리,
  **3구간( TRAIN<=2022-06-30 < VALID<=2024-01-01 < TEST ) 전부 동일**.
- 데이터: `data/factor-panel/kr-monthly-v1.parquet` (233,240행 liquid, fwd1m = 다음
  영업일 종가 진입 → 익월 첫 세션 종가 청산).

## 결과 요약

| 지표 | ROE 단독 | QCOMP | QCOMP decile spread |
|---|---|---|---|
| TRAIN IC | +0.026 (t=3.17) | +0.034 (t=3.82) | — |
| VALID IC | +0.053 (t=3.71) | +0.054 (t=4.24) | — |
| TEST IC | +0.087 (t=6.32) | +0.085 (t=7.82) | — |
| TRAIN top-decile 초과 | -0.317%/월 (t=-1.61) | -0.105%/월 (t=-0.45) | +0.035% (t=0.10) |
| VALID top-decile 초과 | +0.137%/월 (t=0.33) | +0.283%/월 (t=0.90) | +0.297% (t=0.48) |
| TEST top-decile 초과 | +0.735%/월 (t=2.42) | **+0.944%/월 (t=2.98)** | **+1.974% (t=3.18)** |

상위 decile 백테스트 성과(비용 30bps 왕복 고정 차감, 절대수익):

| 구간 | ROE CAGR/Sharpe/MDD/승률 | QCOMP CAGR/Sharpe/MDD/승률 |
|---|---|---|
| TRAIN | -4.40% / -0.08 / -42.7% / 53% | -3.00% / -0.02 / -36.8% / 54% |
| VALID | +3.79% / 0.27 / -17.7% / 56% | +6.46% / 0.40 / -15.0% / 61% |
| TEST | +5.84% / 0.37 / -21.5% / 52% | **+8.91% / 0.52 / -21.8% / 58%** |

## 핵심 판독 3가지

**① 사전정의 composite 의 횡단면 IC 는 살아 있고 오히려 강해진다.**
IC(월별 Spearman, score↔fwd1m)가 TRAIN/VALID/TEST 에서 +0.034/+0.054/+0.085 로
부호일관·전 구간 유의며 단조 증가다. 난수선 통과 여부와 무관하게 3구간 패널 IC t
(3.82/4.24/7.82)는 전부 임계 2.0 을 크게 넘는다. 여기까지만 보면 "quality 복수
결합이 PBR value trap 을 낮추는 재료다" 는 가설 방향을 지지한다.

**② 그러나 실현 가능한 상위 decile 전략은 TEST 에서만 운을 넘는다.**
난수 귀무분포(월내 fwd1m shuffle, 같은 규칙 그대로, 200회)의 95분위는
TRAIN 1.92 / VALID 1.79 / TEST 1.60. 관측 top-decile 초과 t 는 TRAIN -0.45,
VALID 0.90, TEST 2.98. **TEST 만** p95 를 넘는다(최대값 2.81 도 초과). TRAIN 은
IC 가 +0.034·t3.82 인데 **전략으로는 음수**다 — "아는 것"과 "돈이 되는 것"이 다른
전형(이 프로젝트가 반복 경험한 함정). VALID 는 18개월이라 t 검정력이 약하다.

**③ composite 은 ROE 를 넘어서는 독립 정보는 아니다.**
- QCOMP 랭크를 ROE 랭크에 회귀한 잔차의 IC: TRAIN t=0.77 / VALID 0.10 / TEST 1.36
  → 3구간 전부 ~0.
- 상위 decile 페어 비교(QCOMP−ROE 초과): TRAIN +0.188%p(t=1.18), VALID +0.060 (0.17),
  TEST +0.182 (0.78) → 차이가 없거나 미유의.
- 다만 "QCOMP−ROE(6종) 단독"도 TEST 에서 +0.889%/월(t=2.75) 로 거의 전체 QCOMP
  수준 — **TEST 의 신호는 ROE 홀로가 아니라 6종이 실은 것이다.** ROE 단독 TEST
  초과 0.735% vs QCOMP 0.944% 이나 페어 t 가 0.78 이라 차이는 운 구간.

## 왜 HOLD 인가

| 게이트 | 값 | 판정 |
|---|---|---|
| IC 부호일관 (3구간) | + / + / + | 통과 |
| 상위 decile 초과 t | TRAIN -0.45(VALID 0.90) | **미달** (TEST 만 2.98 통과) |
| 연도집중도(전체) | 51.4% (2024) | 40% 초과 → KEEP 아님 |
| TEST 연내 분산 | 2024 +1.19/2025 +0.49/2026 +1.30% | TEST 내 단일연도 편중 아님 |
| ROE 대비 독립 정보 | 잔차 IC ~0, 페어 차 미유의 | 미충족 |
| 난수선(전략) | TEST만 통과 | 조건부 |

결론: **"사전정의 quality composite 의 횡단면 예측력" 자체는 관측으로 살아
있지만(IC 3구간 일관)·유의·강화), (a) 실현 전략으로는 최근 기간(TEST) 전용이고
(b) ROE 대비 독립 알고 있는 정보가 없다.** 이 두 가지 때문에 KEEP 도 REJECT 도
단언할 수 없다. 특히 ③이 중요하다 — 이 실험의 원래 질문("묶으면 ROE 단독보다
독립적으로 강한가"→ 그런 의미의 독립성은 없다)에 대한 부정적 관측이다.

## 실측 메모

- 전체기간(TRAIN+VALID+TEST, 112개월) 상위 decile: CAGR 1.67%, Sharpe 0.19,
  MDD -36.8%, 승률 56.2%, 초과 t=1.46 — **전체기간으로는 운과 구분 안 됨**.
  TEST-전용 신호는 앞서 PBR 가치주류가 겪은 것과 같은 "최근 기간 편중" 패턴이다.
- 회전율 반영 비용(왕복 20bp 설정, turnover ~0.07): 초과 +0.248%/월에서
  10bp 슬립 ≈ +0.048%, 20bp 슬립 ≈ -0.152%/월. **슬리피지에 소멸하는 마진이다.**
- PBR value trap 완화 목적의 PBR×QCOMP combos 는 이번 범위 밖 — 별도 실험으로
  지정돼 있다(실행 안 함).

## 산출물

- 스크립트: `research/strategy-lab/quality_composite_oos.py`,
  `quality_composite_diag.py`, `quality_composite_independence.py`
- 수치 원본: `research/strategy-lab/reports/2026-09-06-quality-composite-oos/quality-composite-oos.json`