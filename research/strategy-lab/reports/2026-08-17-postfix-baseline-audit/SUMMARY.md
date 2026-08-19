# 5DC-v1A-P Post-fix Clean Baseline Audit + 성과 구조 분해

- 날짜: 2026-08-17
- 모델: deepseek (OpenCode, 독립 검증)
- 목적: same-bar fix 반영 engine으로 실행된 5DC-v1A-P 결과(1,592 closed)가 "전략 연구용 정상 baseline"으로 사용 가능한지 독립 검증 + 성과 구조 분해
- 산출물: `research/strategy-lab/reports/2026-08-17-postfix-baseline-audit/`
- 기준 산출물: `reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_samebar_rerun.json` (재실행 2회, 동일 결과)

---

## 0. 감사 범위와 신뢰도 기준

- 검증 대상 수치의 출처는 전부 `5dc_v1a_p_samebar_rerun.json`(strategyId `5dc_v1a_p`)에서 직접 확인했다.
- 같은 디렉터리에 있는 `full_smoke_result.pkl` 기반 수치(241건 same-bar 등)는 **TREND-BREAKOUT-v1** 산출물이므로 5DC 감사에 사용하지 않았다 (`5dc_v1a_p_cause_decomposition_final_verification.md` §4에서 모집단 구분 완료).
- CONFIRMED / DERIVED / UNCONFIRMED / NOT AVAILABLE 을 §9에 구분했다.
- production 코드·기존 산출물·전략 파라미터는 수정하지 않았다.

---

## 1. Post-fix 결과 정본 확인 — CONFIRMED

출처: `5dc_v1a_p_samebar_rerun.json`
- `diag.closedPositionCount = 1592` / `allTrades` 배열 길이 = 1,592 (직접 계수)
- `resultTable.cagr = -0.0980531` → **CAGR -9.81%**
- `resultTable.mdd = -0.7500017` → **MDD -75.0%**
- `resultTable.winRate = 0.262563` → **승률 26.26%** (418승 / 1,174패, 직접 계수 일치)
- `resultTable.winLossRatio = 2.2666` → **손익비 2.27** (avgWin 715,629 / |avgLoss| 315,726)
- `resultTable.avgHoldingPeriod = 27.497` → **avgHolding 27.5일**
- 부가: PF 0.807, Expectancy -44,930, finalEquity 28,471,029

### 1.1 수치의 계산 경로 (재현 검증)

- equity curve 정의: **realized-pnl-at-exit-event stepwise** (`resultTable.equityCurveMethod`).
  `initial_capital + 누적 closed pnl`, exit 이벤트마다 step. 보유 중 MTM 없음.
- 직접 재구성: 1,592건을 exit_date 순 정렬 후 초기자본 100M에 pnl 누적
  → finalEquity **28,471,028.93** (기록값과 0.00 차이 일치)
  → MDD **-75.0002%** (기록 -75.00017% 일치)
  → CAGR: curve[0] = (2014-06-23, 99,371,712), curve[-1] = (2026-08-03, 28,471,029),
    years = 12.112, 계산값 **-9.8053%** (기록 -9.8053% 정확 일치)
- **주의(방법적 한계)**: CAGR의 기준점은 기간 시작(2014-05-13, 100M)이 아니라 **첫 번째 exit 이벤트(2014-06-23, 첫 거래 반영 후 equity)**다. baseline(848)도 동일 방식이므로 비교 자체는 일관되지만, 독립 계산 시 참고해야 할 규약이다.
- 재현성: rerun은 2회 실행(각 ~505초), 두 결과 모두 finalCash=28,471,028.93, closed=1,592로 동일.

---

## 2. 거래 무결성 검사 — CONFIRMED (이상치 0건)

출처: `integrity.json` (전수 검사 결과)

| 항목 | 결과 |
|---|---|
| entry_date <= exit_date | 0건 위반 |
| 동일 position entry/exit 일관성 (PnL 공식 검증) | **0건 불일치** |
| 동일 symbol stale fusion 재발 | **없음** (일 단위 재구성으로 동일 심볼 동시 보유 0건) |
| 한 position에 복수 entry 합쳐진 흔적 | 없음 (심볼별 중첩 구간 0건) |
| 종료 시점 open position 수 | 0 |
| closed + open 관계 | closed 1,592 / open 0 (합계 1,592) |
| 중복 거래 (symbol, entry, exit) | 0건 |
| 비정상 음수/0 가격·수량·PnL | 0건 |
| max_positions 위반 | **0건** (최대 동시 10, policy maxPositions=10, 2014-06-19 관측) |

- PnL 공식 검증: `(exit_price - entry_price) * shares - entry_cost - exit_cost`, 비용 **15bps 왕복 30bps** (policy.json `entryCostBps/exitCostBps=15`).
  전 1,592건에서 재계산값과 기록값 차이 **0.00원** (불일치 0건) — 5DC 결과에는 TREND-BREAKOUT에서 문제됐던 비용 하드코딩(5bps) 오류가 없다.

---

## 3. Same-bar 정상화 확인 — CONFIRMED

출처: `samebar_impact.json`, `5dc_v1a_p_samebar_rerun.json` `sameBarCensus`

- **모집단 확인**: `runIdentification.strategyId = "5dc_v1a_p"` (다른 전략 pkl 아님)
- same-bar 전체 건수: **130 / 1,592 = 8.17%**
- 유형별: **STOP 120 / TARGET 10** (TIME_EXIT 0)
- same-bar PnL 합: **-33,743,860.52** (전체 실현 손실 -71.53M의 **47.2%**)
- same-bar 승률: 10/130 = **7.69%** (즉시 손절이 대부분)
- same-bar 평균 PnL: **-259,568**
- **pre-fix 0 → post-fix 130 모집단 일치**: replay json에서 pre_fix `sameBarTrades=0`, post_fix `sameBarTrades=130` — 모집단 동일(동일 resolved 25,735건에 pre/post 로직 대입). "pre-fix 0"은 same-bar 거래가 130건 모두 exit 누락된 결과이며, post-fix에서 정상 청산된 모집단이다.
- **전체 거래/PnL/MDD 영향** (DERIVED — 동일 산출물에서 계산):
  - same-bar 제외 시: 승률 26.26% → 27.91%, final equity 28.47M → 62.21M, **MDD -75.0% → -46.6%**
  - 즉 보고된 -75% MDD의 상당 부분이 same-bar 즉시 손절 130건(특히 2026년 분포)에서 직접 파생된다.

---

## 4. Position / cash / equity 무결성 — CONFIRMED

- **finalCash = 28,471,028.93 == finalEquity = 28,471,028.93** (차이 < 1e-6). 종료 시 open 0이므로 cash=equity 정합.
- **equity = initial 100M + 누적 실현 PnL (-71.53M) = 28.47M** — 정확히 성립. 거래 PnL과 무관한 비정상 증감 구간 없음.
- equity curve 저장 여부: **산출물에 equity_curve 배열은 없다**. `resultTable.equityCurveMethod` 정의만 존재하고, 필자는 위 §1.1 방식으로 재구성해 finalEquity/MDD/CAGR을 정확히 재현했다. (재구성 방법·정의를 이 보고서 §1.1에 명시)
- **TREND-BREAKOUT 61M artifact와의 구분**: 그 artifact는 `compute_annual_from_pickle.py`가 TREND-BREAKOUT pkl을 **exit-first로 재구성**해 same-bar 241건 청산을 누락 → 2025년 강세장 MTM 급등(61.2M→127.3M, +107.77%)으로 equity를 부풀린 것. 5DC post-fix는 runner가 직접 산출한 closed_positions를 사용하고 equity를 realized stepwise로만 구성하므로 같은 경로의 artifact가 구조적으로 발생할 수 없다. (5DC에서 유사 재구성 시도는 금지·미수행)
- MDD 창(출처 `5dc_v1a_p_cause_decomposition.json`): post-fix peak **2015-05-22 (113.88M, +13.9%)** → trough **2026-08-03 (28.47M)**. peak 대비 -75.0% 일치. (참고: post-fix vs pre-fix equity 발산은 2015-12-09 첫 -5M부터 종료일 -59.11M까지 단조 하락 — 절대 equity 자체는 아님)

---

## 5. 연도별 성과 분해 — CONFIRMED

출처: `yearly_breakdown.json` (직접 계산, `5dc_v1a_p_yearly_comparison.json`의 netReturn과 13개년 전부 일치 확인)

| 연도 | 거래 | 승률 | grossWin | grossLoss | netPnL | PF | 평균PnL | 평균보유(일) | 연말equity | 연MDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 69 | 34.8% | 25.7M | -20.9M | +4.81M | 1.23 | +69,667 | 24.0 | 104.8M | -6.1% |
| 2015 | 125 | 28.0% | 40.3M | -48.4M | -8.13M | 0.83 | -65,045 | 29.0 | 96.7M | -15.1% |
| 2016 | 108 | 25.0% | 23.5M | -31.3M | -7.77M | 0.75 | -71,957 | 32.4 | 88.9M | -11.9% |
| 2017 | 101 | 27.7% | 12.7M | -20.5M | -7.77M | 0.62 | -76,915 | 38.9 | 81.1M | -10.6% |
| 2018 | 124 | 19.4% | 18.9M | -32.4M | -13.47M | 0.58 | -108,654 | 26.3 | 67.7M | -18.7% |
| 2019 | 107 | 30.8% | 18.9M | -19.7M | -0.87M | 0.96 | -8,095 | 34.6 | 66.8M | -11.5% |
| 2020 | 136 | 28.7% | 34.1M | -30.3M | +3.81M | 1.13 | +27,984 | 27.0 | 70.6M | -25.3% |
| 2021 | 156 | 32.1% | 42.5M | -36.7M | +5.84M | 1.16 | +37,462 | 23.4 | 76.4M | -12.4% |
| 2022 | 134 | 20.1% | 17.5M | -35.0M | -17.54M | 0.50 | -130,908 | 26.6 | 58.9M | -24.1% |
| 2023 | 144 | 27.8% | 19.6M | -24.3M | -4.63M | 0.81 | -32,178 | 24.3 | 54.3M | -15.8% |
| 2024 | 140 | 25.7% | 17.6M | -22.2M | -4.69M | 0.79 | -33,491 | 26.0 | 49.6M | -17.4% |
| 2025 | 100 | 35.0% | 14.7M | -13.1M | +1.57M | 1.12 | +15,718 | 36.5 | 51.2M | -5.6% |
| 2026 | 148 | 13.5% | 13.2M | -35.9M | **-22.68M** | 0.37 | -153,270 | 16.4 | 28.5M | **-47.9%** |

- **-75% MDD 형성 기간**: 전체 구간 최대 drawdown은 peak 2015-05-22(113.9M) → trough 2026-08-03(28.5M)로 **11년에 걸친 누적 하락**이다. 연단위 최대 낙폭은 **2026년 -47.9%** (1월~8월 단기간 급락)와 2022년 -24.1%.
- 2026년은 부분 연도(2026-08-03 종료)인데도 148건으로 연간 거래량이 많았고(최대 2021년 156건 다음) 승률 13.5%로 최저. same-bar STOP/TARGET 130건은 연도 전반에 분포하되 **2026년 26건(전체 20%)이 최대 집중**(2020년·2022년 각 17건, 2025년 8건)이며 2026년 same-bar PnL -5.67M가 연간 급락에 기여 — §7과 함께 고려해야 한다.
- 이익 연도: 2014, 2020, 2021, 2025 (4년 / 13년). PF > 1인 연도만.

---

## 6. 성과의 거래 집중도 — CONFIRMED (구조적 취약점 없음, 광범위 손실)

출처: `concentration.json`

- **상위 이익 거래 비중**: Top 10 = 24.3M (grossWin 299.1M의 8.1%), Top 20 = 43.8M (14.6%), Top 50 = 88.5M (29.6%)
- **상위 손실 거래 비중**: Top 10 = -12.6M (grossLoss -370.7M의 3.4%), Top 50 = -43.4M (11.7%)
- 손익 분포: 승 418 / 패 1,174 / 제로 0.
  - >2M 15건, 1M~2M 84건, 0.5M~1M 156건, 0~0.5M 163건
  - -0.5M~0 **1,020건**, -1M~-0.5M 144건, -2M~-1M 9건, <-2M 1건
- 월별: 양수 72/146개월. 최악 월 2026-06(-10.4M), 2022-06(-9.5M), 2015-11(-7.7M), 2020-03(-7.7M), 2026-07(-7.3M). 음수 월 합 -181.6M vs 양수 월 합 +110.1M.
- 종목별: 고유 864종목. 최악 009190(-2.65M), 최우수 006890(+3.66M). 최악 5종목 = grossLoss의 2.9%, 최우수 5종목 = grossWin의 4.6% — **소수 종목 집중 없음**.
- **구조 판단**: 성과는 소수 거래가 아니라 **1,020건의 소액 손실(-0.5M~0)이 쌓여** 형성된다. PF<1(0.807)과 승률 26.3%가 전 구간·전 종목에 광범위하게 퍼져 있어 단일 이벤트 기인이 아니다.

---

## 7. 시장환경/기간별 성과 — 기간 분해 (regime 분류는 미사용)

출처: `period_breakdown.json`
- regime 데이터는 현재 계약상 정의가 없으므로 **임의의 regime 분류를 만들지 않고 단순 기간 분해만 수행**했다.

| 기간 | 거래 | 승률 | grossWin | grossLoss | netPnL | PF | start→end equity | MDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2014~2016 | 302 | 28.5% | 89.5M | -100.6M | -11.09M | 0.89 | 100.0M→88.9M | -24.6% |
| 2017~2019 | 332 | 25.6% | 50.5M | -72.6M | -22.11M | 0.70 | 88.9M→66.8M | -27.1% |
| 2020~2022 | 426 | 27.2% | 94.1M | -102.0M | -7.89M | 0.92 | 66.8M→58.9M | -32.0% |
| 2023~2026 | 532 | 24.6% | 65.1M | -95.5M | **-30.43M** | 0.68 | 58.9M→28.5M | **-54.1%** |

- 모든 구간에서 손실. 상대적으로 2020~2022가 최선(PF 0.92), 2017~2019와 2023~2026이 최악.
- 2023~2026의 -54.1% MDD는 2026년 급락(-47.9%)이 결정적 기여. same-bar 130건은 연도 전반에 분포하나 **2026년 단일 연도 26건으로 최대 집중**(2024~2026 합 46건, 2023~2026 합 56건)이라 2026년 손실·급락을 직접 악화.

---

## 8. 기존 848 baseline과 비교 — 비교 가능하되 before/after 해석 금지

출처: baseline `ablation_b0_b3.json` B3, post-fix `5dc_v1a_p_samebar_rerun.json`, replay `5dc_v1a_p_pre_post_scheduler_replay.json`

| 지표 | baseline (848, fix 전·buggy) | pre-fix replay | post-fix (1,592) |
|---|---:|---:|---:|
| 거래 수 | 848 | 848 | **1,592** (+87.7%) |
| 거래 기간 | 2014-05-13~2026-08-03 | 동일 | 동일 |
| same-bar | (기록 없음, 누락) | 0 | **130 (8.2%)** |
| fusion | 있음 (버그) | 있음 (재현) | **없음** |
| 종료 시점 open | 10 | 10 | **0** |
| 승률 | 27.95% | 27.83% | 26.26% |
| 손익비 | 2.45 | 2.48 | 2.27 |
| PF | 0.951 | 0.956 | 0.807 |
| 실현 PnL | -13.73M | -12.42M | **-71.53M** |
| CAGR | -1.21% | -1.04% | **-9.81%** |
| MDD | -30.9% | -30.93% | **-75.0%** |
| avgHolding | 34.7일 | 50.0일 | 27.5일 |

**변화 원인 설명** (왜 +744건 / 성과 왜곡인가):

1. **same-bar fix 단일 원인** (기존 검증 재확인): 동일 데이터(manifest hash 동일)·동일 신호(28,791)·동일 정책(policyHash 동일)·동일 resolved에 pre-fix 로직 재적용 → **closed 848, open 10 일치** (replay json에 기록), 연도별 거래수 13개년 일치는 deepseek 세션 실측 보고 (replay json에는 연도별 저장 안 됨 → 재확인하려면 재실행 필요). 9b5355c 이후 engine 변경은 runner.py same-bar fix 1건뿐.
2. **거래 수 증가 메커니즘**: pre-fix에서 same-bar exit이 누락되어 (a) 64건 진입 차단(never_admitted), (b) 56건이 stale 포지션과 fusion 병합, (c) 10건 종료 시점까지 stale open 잔존. post-fix는 이 130건이 정상 청산되고 슬롯이 해제되어 **+614건** 추가 진입·청산 발생 → 1,592.
3. **PnL/MDD 왜곡**: pre-fix fusion이 +2,096만원의 "조작 이익"을 기록(fused 56건 `fused_pre_pnl_sum +20.96M`, post_true_split -13.75M → 왜곡 -34.71M). plus same-bar 직접 손실 -33.74M, cascade -4.41M. waterfall 검증: -59.11M 차이 중 same-bar 직접 손실 + fusion 조작 이익 제거 소계 -54.70M = **92.54%** 가 same-bar fix 직접 효과, 나머지 -4.41M(7.5%)는 share 규모·슬롯·현금 cascade.
4. **avgHolding 감소**: fusion 제거로 보유기간 과장(50.0일)이 정상화(27.5일).
5. **주의**: baseline(848)은 **buggy engine 결과**이므로 위 표를 "전략 before/after 성능 비교"로 해석해서는 안 된다. baseline 수치는 더 이상 정본이 아니며, 세션인수인계-2026-08-14-b.md가 "실질적으로 미결과"로 명시한 것과 일치.

---

## 9. 독립 검증 가능성 평가

| 항목 | 상태 | 근거 |
|---|---|---|
| 1,592 / CAGR -9.81% / MDD -75.0% / 승률 26.26% / 손익비 2.27 / avgHolding 27.5일 | **CONFIRMED** | rerun json 전수 재계산·재구성 일치 (finalEquity·MDD·CAGR 0.00 차이) |
| 거래 무결성 (날짜·가격·수량·PnL·중복·max_positions) | **CONFIRMED** | 전수 검사 0건 위반, PnL 공식 100% 일치 |
| same-bar 130건 / STOP 120 / TARGET 10 / PnL -33.74M | **CONFIRMED** | sameBarCensus + 직접 계수 |
| pre-fix 0 → post-fix 130 모집단 | **CONFIRMED** | replay json 동일 resolved 대입 (pre 0 / post 130) |
| cash = equity = initial + 실현 PnL | **CONFIRMED** | diff < 1e-6 |
| equity curve 정의·재구성 | **CONFIRMED (정의 문서화) / 산출물엔 배열 없음(NOT AVAILABLE)** | resultTable.equityCurveMethod + 재구성 재현 |
| 연도별·기간별·집중도 | **CONFIRMED** | yearly/period/concentration json (기존 yearly json과 13개년 일치) |
| same-bar 제외 효과 (승률 27.9%, MDD -46.6%, equity 62.2M) | **DERIVED** | 동일 산출물에서 필터링 계산 (산출물에 직접 저장 안 된 값) |
| -75% MDD 창 (peak 2015-05-22 / trough 2026-08-03) | **CONFIRMED** | cause_decomposition.json equity_mdd_propagation |
| baseline 848이 fix 전 결과 | **CONFIRMED (구조적)** | pre-fix replay closed 848·open 10·MDD -30.93%·cost 20/20 일치. 단 finalEquity/CAGR은 소수점 불일치(87.58M vs 86.27M, -1.04% vs -1.21%) |
| baseline engine 정확 코드 버전 | **UNCONFIRMED** | b5fc50d에 strategy-lab 미포함, 미커밋 상태라 복구 불가 (추정 안 함) |
| baseline tradesChecked 26,090 vs 25,735 차이 (355건) | **UNCONFIRMED** | 미커밋 검증 스크립트 기원으로 추정되나 확정 근거 부족. 이 수치는 closed 결과(848/1,592)·MDD·승률·cost에 영향 없음 |
| fusion partner 완전 매칭 (56건) | **UNCONFIRMED (부분)** | partner_count 대부분 0, 다만 +20.96M은 pre-fix 실제 기록값이라 결론 영향 없음 |
| cascade -4.41M 단일 거래 분해 | **UNCONFIRMED** | 잔차로 단일 원인 분리 불가 (공통 716건 중 95.4% share 상이 증거 포함, 기존 보고서와 동일 한계) |

---

## 10. 최종 판단

### **B. BASELINE WITH CAVEATS**

**핵심 감사 결론: post-fix 결과의 데이터·엔진·성과 계산 무결성은 CONFIRMED다.** 산출물의 모든 수치가 독립 재계산으로 정확히 재현되고(§1.1), 거래 무결성 전수 검사에 이상치가 없으며(§2), same-bar·fusion 정상화가 확인됐고(§3), equity는 거래 PnL과 정합한다(§4). 성과 구조도 명확히 분해됐다(§5~7): 전 구간·전 종목 광범위 손실에 same-bar 즉시 손절과 2026년 급락이 악화 요인.

그러나 "전략 연구용 정상 baseline"으로 승격하기 전에 다음 caveat를 명시해야 한다:

1. **CLEAN은 "데이터 정상"이지 "성과 정상"이 아니다.** CAGR -9.81%, MDD -75%는 전략 성과가 구조적으로 부정적임을 보여준다. 연구 baseline으로 쓸 때는 "실패 사례 baseline"으로서의 용도(성과 구조 분석·개선 방향)로 한정해야 한다.
2. **SMOKE / A1A_ONLY survivorship bias 내재** (산출물 warning에 문서화). validated performance가 아니며 A2b 완료 전 PRIMARY 전환·파라미터 최적화 베이스로 쓰면 안 된다.
3. **CAGR 기준점 규약**: 첫 exit 이벤트(2014-06-23) 기준이라 기간 시작(100M) 기준 CAGR(-9.77%)과 다르다. 비교 시 이 정의를 고정해야 한다.
4. **미해결 unconfirmed 항목**: baseline engine 코드 버전(복구 불가), resolved 355건 차이, cascade 잔차, fusion partner 매칭 — 이 항목들은 본 post-fix 결과 자체의 정합성에는 영향이 없으나, 엄밀한 baseline 승격 전에 기록으로 남겨야 한다.
5. **기존 848 baseline은 폐기·구분 필요**: buggy 결과이므로 정본 취급을 중단하고, 이 post-fix 결과(1,592)를 새로운 참조점으로 사용하되 SUMMARY.md 등 기존 정본 수치는 **사용자 승인 후에만** 갱신한다 (AGENTS.md §13 준수).

**사용 가능 범위**: 전략 연구용 (동일 engine·동일 policy·동일 데이터 조건에서의) 성과 구조 분석 baseline으로 사용 가능. 단, 위 caveat 1~4를 보고서에 명시하고, survivorship bias와 SMOKE 한계를 감안한 해석만 허용한다.

---

## 부록 A. 산출물

- `research/strategy-lab/reports/2026-08-17-postfix-baseline-audit/`
  - `SUMMARY.md` (본 보고서)
  - `integrity.json` — 거래 무결성 전수 검사
  - `samebar_impact.json` — same-bar 130건 집계·영향
  - `yearly_breakdown.json` — 연도별 분해
  - `period_breakdown.json` — 기간별 분해
  - `concentration.json` — 집중도·분포

## 부록 B. 1차 산출물 (기존, 수정 안 함)

- `reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_samebar_rerun.json` — post-fix rerun 정본 (2회 실행)
- `.../5dc_v1a_p_pre_post_scheduler_replay.json` — pre/post replay
- `.../5dc_v1a_p_yearly_comparison.json` — 연도별 비교
- `.../5dc_v1a_p_cause_decomposition.json` — 원인 분해·MDD 창
- `.../5dc_v1a_p_fusion_pnl_distortion.json` — fusion 왜곡
- `.../5dc_v1a_p_baseline_sample_match.json` — baseline cost 샘플 20/20 일치
- `reports/2026-08-14-5dc-v1a-p-baseline/` — 기존 848 baseline (buggy, 폐기 대상으로 구분)
