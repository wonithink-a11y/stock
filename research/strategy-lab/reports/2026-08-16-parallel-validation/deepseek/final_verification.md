# 5DC-v1A-P same-bar 실험 — 최종 검증 정리 (confirmed/unconfirmed)

- 날짜: 2026-08-16
- 모델: deepseek (OpenCode, 독립 검증)
- 상태: 추가 재실행 없이 기존 증거 파일 기준 정리 완료
- 기준 저장소 상태: HEAD `940136b` (이전 세션 commit 기준 c140c26 이후 engine 변경 없음 확인)

---

## 1. 요약

| 항목 | 상태 | 판정 근거 |
|---|---|---|
| post-fix 재실행 closed=1,592 | **confirmed** | `5dc_v1a_p_samebar_rerun.json` (2회 실행 동일) |
| baseline closed=848 | **confirmed** | `ablation_b0_b3.json` B3 `tradeCount=848` |
| CAGR/MDD 변화 | **confirmed** | baseline vs rerun 직접 수치 |
| pre-fix replay가 baseline 848 재현 | **confirmed (구조적)** | replay json, 연도별 거래수 전 해 일치 |
| baseline engine commit=`b5fc50d` = code version | **unconfirmed (추정 아님, 사실상 불가)** | git에 strategy-lab 없음 |
| 848→1,592 차이가 same-bar fix 때문 | **confirmed** | 9b5355c 이후 runner.py 단일 변경, 신호/데이터/샘플 동일 |
| 기존 `same_bar_comparison.json`의 "fix 포함" 주장 | **기각 (confirmed 반증)** | git history 기반 |

---

## 2. 직접 증거 파일

### 2.1 848 → 1,592 거래 수 변화 — confirmed

- `reports/2026-08-14-5dc-v1a-p-baseline/ablation_b0_b3.json` → `B3_BB_plus_CCI_5DC_v1A_P.resultTable.tradeCount = 848`
- `reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_samebar_rerun.json` → `diag.closedPositionCount = 1592` (signalCount 28,791, portfolioEligibleTradeCount 25,735)
- 재실행을 2회 수행했고(10:01, 10:01) 두 결과 모두 `finalCash=28,471,028.93`, closed=1,592로 **동일 → 재현성 confirmed**

### 2.2 CAGR/MDD/승률/손익비 변화 — confirmed

| 지표 | baseline | post-fix rerun | Δ |
|---|---|---|---|
| closed | 848 | 1,592 | +744 (+87.7%) |
| CAGR | -1.21% | **-9.81%** | -8.60%p |
| MDD | -30.9% | **-75.0%** | -44.1%p |
| 승률 | 27.95% | 26.26% | -1.69%p |
| 손익비 | 2.45 | 2.27 | -0.18 |
| PF | 0.951 | 0.807 | -0.144 |
| Expectancy | -16,194 | -44,930 | -2.77배 |
| avgHolding | 34.7일 | 27.5일 | -7.2일 |

출처: baseline은 `ablation_b0_b3.json`/`5dc_v1a_p_smoke_verification.json` `7_resultTable`, post-fix는 `5dc_v1a_p_samebar_rerun.json` `resultTable`.
지표 계산 방식은 baseline과 동일(`realized-pnl-at-exit-event stepwise curve`).

### 2.3 pre-fix replay가 848 baseline 재현 — confirmed (구조적)

- `5dc_v1a_p_pre_post_scheduler_replay.json`:
  - pre-fix 로직 재적용(동일 resolved 25,735건): **closed=848, open-at-end=10**
  - post-fix 로직: **closed=1,592, open-at-end=0**
  - pre-fix CAGR -1.04% / MDD **-30.93%** (baseline MDD -30.93%와 소수점 14자리 일치)
- `5dc_v1a_p_yearly_comparison.json`: **전 13개년 거래 수 전부 일치** (2014: 58=58 … 2026: 41=41), netReturn/MDD도 소수점 3~4자리 수준으로 근접
- `5dc_v1a_p_baseline_sample_match.json`: baseline 검증의 cost 샘플 **20/20 건 shares·pnl 완전 일치**

**판정**: pre-fix replay는 baseline을 **구조적으로 재현**한다. 다만 finalEquity(87.58M vs 86.27M)와 CAGR(-1.04% vs -1.21%) 등 소수점 수준 지표는 **완전 일치하지 않음** — 이유는 §4 참고. 따라서 "완전 동일 재현"이 아니라 "구조적 동일성 재현 + 샘플 완전 일치"로 **confirmed**한다.

### 2.4 same-bar 거래 특성 — confirmed

- `5dc_v1a_p_samebar_rerun.json` `sameBarCensus`: 130건 / 1,592 = 8.2%, STOP 120 / TARGET 10, PnL 합 -33.7M
- `5dc_v1a_p_samebar_trace.json`: 130건 중 11건 = 종료 시점 stale open으로 흡수(open-at-end=10과 부합), 119건 = 이후 거래 청산에 병합(fusion)
- `5dc_v1a_p_fusion_analysis.json`: pre-fix open-at-end=10 (symbol 10개), stale cost basis 45.8M

---

## 3. baseline engine commit / provenance — Git history 기준 (추정 금지)

### 3.1 확정된 git 사실

| 항목 | 사실 | 확인 방법 |
|---|---|---|
| `b5fc50d` (2026-08-13 10:19 UTC, "chore: update disclosures + state from DART") | **strategy-lab 디렉터리·runner.py 미포함** | `git cat-file -e b5fc50d:research/strategy-lab/engine/runner.py` → fatal (미존재) |
| `9b5355c` (2026-08-14 19:11:58 KST) | strategy-lab 최초 커밋 + 5DC baseline 동결 | `git cat-file -e` → 존재 |
| `c140c26` (2026-08-14 19:11:59 KST) | same-bar 스케줄링 버그 수정 | `git log` |
| baseline 실행 시각 | runStartedAtUTC 2026-08-13T22:24:23 (b5fc50d 커밋 후 ~12h) | `5dc_v1a_p_smoke_verification.json` |

### 3.2 판정: baseline engine commit의 코드 버전 식별은 **불가능 (unconfirmed by design)**

- baseline verification json의 `engineGitCommit=b5fc50d`는 **그 시점의 HEAD**이지 **strategy-lab 코드 버전이 아니다**. strategy-lab은 b5fc50d에 없었고, baseline 실행(08-13 22:24 UTC)은 strategy-lab 최초 커밋(08-14 19:11 KST) **이전**에 이뤄졌다.
- 즉 baseline은 **커밋 이전의 로컬 working tree**에서 실행됐고, 그 상태는 git에서 복구할 수 없다.
- `docs/control/세션인수인계-2026-08-14-b.md`(정본, c140c26과 함께 커밋)가 이를 명시: "5DC baseline은 수정 전에 만들어졌으므로 실질적으로는 미결과", "5DC 재실행은 하지 않았음".
- **결론**: baseline의 정확한 engine 코드 버전은 **추정하지 않는다** (추정 금지 요청 준수). 확정된 것은 (a) baseline은 same-bar fix 이전 상태, (b) baseline 실행 당시 engine은 커밋되지 않아 재현 불가, (c) 현재 재실행은 `940136b`(c140c26 이후) 기준.

### 3.3 baseline과 현재 engine의 관계 — confirmed

- 9b5355c(최초 커밋, baseline 동결) 이후 strategy-lab engine 변경은 **`runner.py` same-bar fix 1건뿐** (`git log c140c26..HEAD -- research/strategy-lab/engine/runner.py research/strategy-lab/strategies/5dc_v1a_p/ ...` 결과 공백).
- 데이터·신호 동일성: manifest hash 동일(`sha256:9756e0737ea8c866`), universe hash 동일(`03f882...`, 캐시 키 `a0f2acb7...` 일치), policy hash 동일(`53e5cd07...`), **signalCount 28,791 동일**, cost 샘플 20/20 일치.
- 따라서 848→1,592 차이는 **runner.py scheduling 로직의 same-bar fix 단독**으로 설명됨 → **confirmed**.

---

## 4. baseline과 post-fix 결과의 관계 — 명확 구분

| 구분 | baseline (2026-08-14 동결) | post-fix rerun (이번 실험) |
|---|---|---|
| engine 상태 | same-bar fix **이전** (미커밋 로컬) | same-bar fix **이후** (`940136b`) |
| closed | 848 | 1,592 |
| open-at-end | 10 (구조적 재현 확인) | 0 |
| 같은-bar 처리 | exit 누락 → fusion/stale | 정상 청산 |
| 지표 | CAGR -1.21% / MDD -30.9% | CAGR -9.81% / MDD -75.0% |
| 위치 | `reports/2026-08-14-5dc-v1a-p-baseline/` | `reports/2026-08-16-parallel-validation/deepseek/` |

**핵심 관계**: baseline은 **same-bar fix의 버그를 포함한 결과**이고, post-fix rerun은 **fix 후의 참된 결과**다. 이는 세션 인수인계-2026-08-14-b.md의 TREND-BREAKOUT-v1 관찰(1,400→2,154, CAGR -8.3%→-12.25%, MDD -70.9%→-83.3%)과 **동일한 방향·동일한 메커니즘**이다. baseline과 post-fix의 차이는 **버그 수정의 효과**이지 전략 성과의 개선/악화 판단이 아니다.

### unconfirmed (추가 검증 필요)
- baseline finalEquity(86.27M) vs pre-fix replay finalEquity(87.58M)의 **소수점 수준 차이** — baseline의 정확한 코드 상태가 git에 없어 완전 재현 불가. 구조적 지표(closed 848, open 10, 연도별 거래수)는 일치하므로 영향 없음.
- baseline `tradesChecked=26,090`(검증 json) vs 재실행 `portfolioEligibleTradeCount=25,735` 차이(355건) — baseline 검증 스크립트(미커밋)의 독립 재계산으로 추정되나 확정 근거 부족 → **unconfirmed**.

---

## 5. 기존 보고서 오류 교정

`reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_same_bar_comparison.json`(기존 deepseek 세션 작성)의
**"baseline 이미 same-bar fix 포함(b5fc50d), 재실험 불가"** 주장은 **기각**한다.

반증(모두 git history·실측):
1. `b5fc50d`에 strategy-lab 파일 없음 → "b5fc50d가 runner.py fix 포함"은 사실 불가.
2. 세션 인수인계-2026-08-14-b.md가 baseline이 fix **이전**임을 명시.
3. 실측: pre-fix 로직 재적용 → 848 재현 (fix 전 동작이 848을 만들었음).

---

## 6. 파일 변경 내역 (이번 실험)

- **기존 파일 수정: 0건** (production·기존 baseline 보고서 모두 무수정)
- **신규 생성: 7건** (실험 코드/산출물) + **보고서 8건** (`reports/...`, gitignore 대상)
- 보고서 보완: 본 파일(`final_verification.md`)은 기존 파일 수정 없이 **신규 작성**으로 추가.

---

## 7. 판단 요청 사항 (사용자 결정 필요)

1. baseline `SUMMARY.md` B3 수치(848건·CAGR -1.21%)는 **fix 전 결과**이므로 갱신 여부 결정 필요.
2. 기존 `5dc_v1a_p_same_bar_comparison.json`의 오류 교정(삭제·정정 파일 추가) 여부.
3. 실험용 신규 파일(스크립트 7건·보고서)의 보존/삭제/ignore 처리.