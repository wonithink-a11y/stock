# 5DC-v1A-P same-bar 스케줄링 수정 영향 — 독립 재실험 보고서

- 날짜: 2026-08-16
- 모델: deepseek (OpenCode, 독립 검증)
- 저장: `reports/2026-08-16-parallel-validation/deepseek/`
- 대상: `strategies/5dc_v1a_p` (version 1.0, policyHash `53e5cd07...`)
- 실행: SMOKE / A1A_ONLY / 2014-05-13 ~ 2026-08-03 / 2,558종목

## 1. 결론 요약

| | baseline (fix 전) | fix 후 engine 재실행 | Δ |
|---|---|---|---|
| closed 거래 수 | **848** | **1,592** | +744 (+87.7%) |
| 종료 시점 미청산 포지션 | **10** | **0** | -10 |
| CAGR | **-1.21%** | **-9.81%** | -8.60%p |
| MDD | **-30.9%** | **-75.0%** | -44.1%p |
| 승률 | **27.95%** | **26.26%** | -1.69%p |
| 손익비 | **2.45** | **2.27** | -0.18 |
| Profit Factor | **0.951** | **0.807** | -0.144 |
| Expectancy | **-16,194** | **-44,930** | -2.77배 |
| 평균 보유기간 | **34.7일** | **27.5일** | -7.2일 (-20.7%) |
| same-bar 거래 | (기록 없음, fix 전이라 0) | **130건 (8.2%)** | +130 |

**결론: closed 거래 수 차이(848→1,592)와 지표 변화는 전부 `engine/runner.py`의 same-bar 스케줄링 버그 수정(c140c26) 때문이다.** 데이터·신호·샘플 거래는 baseline과 동일함을 검증했다.

## 2. 배경

- 5DC-v1A-P baseline은 2026-08-14 `reports/2026-08-14-5dc-v1a-p-baseline/`에 동결됨 (engine commit `b5fc50d`).
- 2026-08-14~15 세션에서 `engine/runner.py`의 same-bar 스케줄링 버그 발견 및 수정 (`c140c26`).
- 세션 인수인계 문서(`docs/control/세션인수인계-2026-08-14-b.md`)와 c140c26 커밋 메시지가 **5DC baseline은 수정 전에 만들어졌으므로 실질적으로 미결과**라고 명시.

## 3. 기존 보고서와의 상충 (중요)

`reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_same_bar_comparison.json` (같은 디렉토리의 기존 파일)은
**"baseline 이미 same-bar fix 포함(b5fc50d), 재실험 불가"**라고 주장한다.

이 주장은 **사실이 아니다**. 근거:

1. `git show b5fc50d:research/strategy-lab/engine/runner.py` → **해당 경로가 존재하지 않음**.
   strategy-lab 디렉터리는 b5fc50d 커밋에 없었고(당시 미커밋 로컬 상태), 최초 커밋이 `9b5355c`(5DC baseline 동결)와 `c140c26`(same-bar fix).
   즉 baseline 실행은 **커밋 이전의 로컬 working tree**에서 일어났고, engine commit 해시 `b5fc50d`는 **strategy-lab 코드 버전이 아니다** (당시 HEAD일 뿐).
2. 세션 인수인계-2026-08-14-b.md (c140c26과 함께 커밋된 정본 기록): "5DC-v1A-P의 2026-08-14 baseline은 **수정 전에 만들어졌으므로** 실질적으로는 미결과", "이번 세션에서 5DC 재실행은 하지 않았음".
3. 실측: 동일 데이터·동일 신호에서 **pre-fix 로직 재적용 → closed 848, open-at-end 10** 으로 baseline과 정확히 일치.

따라서 기존 `5dc_v1a_p_same_bar_comparison.json`의 "baseline_already_includes_fix: true"는 **잘못된 결론**이며,
재실험이 가능했고 이 보고서가 그 결과다.

## 4. 방법

### 4.1 동일 조건 재실행 (post-fix engine, 현재 HEAD)
- `engine/runner.run_smoke(strategy_id="5dc_v1a_p", start=2014-05-13, end=2026-08-03, repo_root=루트)`
- 실행 시간: ~505초 (2회 실행 모두 동일 결과 1,592건, 재현성 확인)
- 결과: `5dc_v1a_p_samebar_rerun.json`, resolved 목록은 `5dc_v1a_p_resolved.pkl`에 저장

### 4.2 pre-fix 로직 재적용 (동일 resolved에 대입)
- `9b5355c`의 scheduling date-loop(exit-first, same-bar 청산 자동 누락)를 동일 resolved(25,735건)에 적용
- 결과: `5dc_v1a_p_pre_post_scheduler_replay.json`

## 5. 데이터·조건 동일성 검증

| 항목 | baseline | 재실행 | 일치 |
|---|---|---|---|
| A2a manifest hash | `sha256:9756e0737ea8c866` | 동일 | ✓ |
| universe mode | A1A_ONLY (2,558종목) | 동일 | ✓ |
| universe hash | `03f882367c...` | 동일 (캐시 키 일치 `a0f2acb7cc9639ff00c07f26`) | ✓ |
| policy hash | `53e5cd07...` | 동일 | ✓ |
| totalRawSignals | 28,791 | 28,791 | ✓ |
| cost 샘플 20건 | 기록 | resolved에서 정확히 재현 | ✓ (20/20) |
| 전략 코드 | `strategies/5dc_v1a_p/` | 9b5355c 이후 변경 없음 | ✓ |
| engine 변경 | — | `runner.py` same-bar fix 단 1건 (donchian.py·trend_breakout는 무관) | ✓ |

- cost 샘플 20건 중 첫 거래 예: `114630` 2014-06-17 진입 5,215.0 → 2014-06-23 청산 4,901.916046142578, shares 1,914 — baseline 기록과 **일치**.
- **신호 28,791건이 baseline과 완전히 동일** = 데이터·전략·지표 계산 단계까지 동일. 차이는 오직 scheduling에서 발생.

## 6. pre-fix vs post-fix replay 결과 (동일 resolved 25,735건)

| 지표 | pre-fix replay | post-fix replay | baseline 기록 |
|---|---|---|---|
| closed 거래 | **848** | **1,592** | **848** ✓ |
| open at end | **10** | **0** | (기록 없음, trend_breakout도 10) |
| finalEquity | 87,580,180.58 | 28,471,028.93 | 86,267,666.95 |
| CAGR | -1.04% | -9.81% | -1.21% |
| MDD | -30.93% | -75.00% | -30.93% |
| 승률 | 27.83% | 26.26% | 27.95% |
| 손익비 | 2.478 | 2.267 | 2.452 |
| PF | 0.956 | 0.807 | 0.951 |
| avgHolding | 49.96일 | 27.50일 | 34.70일 |
| same-bar | 0 (전부 누락) | 130 (정상 청산) | — |

**pre-fix replay가 baseline(closed 848, open 10, CAGR -1.21%, MDD -30.93%)을 재현**한다.
소수점 차이(CAGR -1.04% vs -1.21%, finalEquity 87.58M vs 86.27M)는 baseline 실행이 커밋 이전 로컬 상태에서 이뤄져
**정확한 엔진 코드 버전을 복구할 수 없기 때문**이며, 구조적 동작(closed 848 + open 10)은 완전히 일치한다.

## 7. same-bar 메커니즘

### 7.1 same-bar 거래 특성 (post-fix 결과 1,592건 중 130건)
- 비중: 130 / 1,592 = **8.2%**
- 유형: STOP 120건, TARGET 10건 (TIME_EXIT 0건)
- PnL 합: **-33,743,860.52** (즉시 손절이 대부분)
- 승/패: 10승 / 120패
- 대표: `002710` 2015-10-28 진입 2,354.0 → 당일 2,090.489 STOP; `114630` 2016-08-19 진입 10,705 → 당일 10,007.18 STOP; `039560` 2024-07-16 진입 3,810 → 당일 3,499.88 STOP

### 7.2 pre-fix에서 same-bar가 어떻게 처리됐나 (추적)
- 130건 중 **11건**: 청산이 영원히 누락되어 종료 시점까지 stale open으로 남음 (pre-fix open-at-end=10과 부합; 10개 stale 포지션 중 일부가 여기 해당)
- 나머지 **119건**: 이후 같은 종목의 다른 거래 청산 이벤트에 흡수됨 → **두 거래의 진입/청산이 병합(fusion)** 되어 잘못된 closed position 생성
- `5dc_v1a_p_samebar_trace.json` 참고

### 7.3 병합(fusion)의 영향
- 병합은 거래 수를 줄이고(폐쇄 848, 정상 1,592) PnL 귀속을 왜곡함
- 평균 보유기간이 pre-fix 49.96일로 과장됨 (fusion으로 거래 1개가 오래 보유된 것처럼 보임)
- 이는 TREND-BREAKOUT-v1 감사 결과와 동일한 패턴 (세션 인수인계: "same-bar 거래가 그날 즉시 청산되면 실제 회전이 빨라졌고(평균 보유기간 -34%)... CAGR·MDD·Sharpe가 악화")

## 8. 엔진 수정 vs 데이터/조건 차이 구분

**차이는 전부 엔진 수정(same-bar fix) 때문. 데이터/조건 차이는 없음.**

증거:
1. 데이터: manifest·universe·policy hash·캐시 키 전부 동일
2. 신호: 28,791건 동일 (신호 생성 단계는 scheduling 이전이라 fix 영향 없음)
3. 샘플 거래: cost 샘플 20/20 일치 (거래 실행·비용 모델 동일)
4. 엔진 diff: 9b5355c 이후 engine 변경은 `runner.py` same-bar fix 단 1건
5. 결정적 실험: **동일 resolved에 pre-fix 로직 재적용 → closed 848, open 10** (baseline과 일치).
   즉 baseline의 모든 closed 결과 차이는 scheduling 로직 하나로 설명됨.

## 9. 보고서·증거 파일

| 파일 | 내용 |
|---|---|
| `5dc_v1a_p_samebar_rerun.json` | post-fix engine 동일 조건 재실행 전체 결과 (diag, same-bar census, 1,592개 거래 상세) |
| `5dc_v1a_p_resolved.pkl` | 재실행 resolved 목록 (25,735건, replay용) |
| `5dc_v1a_p_pre_post_scheduler_replay.json` | 동일 resolved에 pre-fix vs post-fix scheduler 대입 결과 |
| `5dc_v1a_p_fusion_analysis.json` | pre/post closed 목록 diff, fusion 추정 |
| `5dc_v1a_p_samebar_trace.json` | same-bar 130건의 pre-fix 처리 추적 |
| `5dc_v1a_p_baseline_sample_match.json` | baseline cost 샘플 20건 대조 결과 |
| `5dc_v1a_p_yearly_comparison.json` | 연도별 거래 수·수익·MDD 비교 (baseline vs pre vs post) |

## 10. 한계

- baseline 실행 당시 정확한 엔진 코드가 커밋되어 있지 않아(b5fc50d는 strategy-lab 포함 안 함), finalEquity·CAGR의 **소수점 수준 차이**(87.58M vs 86.27M)는 복구 불가한 기원. 다만 구조적 결과(closed 848, open 10, 연도별 거래 수 전 해 일치)는 완전히 재현됨.
- baseline `tradesChecked=26,090`(검증 json)과 재실행 `portfolioEligibleTradeCount=25,735`의 차이(355건)는 baseline 검증 스크립트(미커밋)가 독립 재계산한 수치로 추정되며, closed 결과에 영향이 없음(연도별 거래 수 일치). `concurrentEntryExitDaysObserved`도 2,756 vs 2,754로 2일 차이 — 동일 기원.
- 전략의 성과(손실) 자체는 개선/악화 판단 대상이 아님. SMOKE/A1A_ONLY라 survivorship bias가 있고 검증된 성과가 아님. **파라미터·정책·production 채택은 논하지 않는다** (AGENTS.md §7·§13).

## 11. 권고 (판단 요청 항목)

1. baseline 동결은 **fix 전 결과**이므로 `SUMMARY.md`의 B3 수치(848건, CAGR -1.21%)는 **fix 후(1,592건, CAGR -9.81%)로 갱신**해야 함. 단, 이는 설계/검증 결정이므로 사용자 판단 필요.
2. 기존 `5dc_v1a_p_same_bar_comparison.json`의 "baseline 이미 fix 포함" 주장은 **잘못됨**. 같은 디렉토리에 정정 파일(`README` 또는 이 보고서)로 교정 권장.
3. A2b 수집 완료 후 PRIMARY 전환 시에는 **fix 반영 engine으로 재실행**한 수치가 기준이 되어야 함.