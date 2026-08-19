# 5DC-v1A-P 성과 부진 원인 분리 실험 설계안
# (전략 구조 문제 vs A1A_ONLY 표본/survivorship bias)

- 날짜: 2026-08-17
- 모델: deepseek (OpenCode, 독립 검증)
- 목적: post-fix rerun 결과(-9.81% CAGR / -75% MDD)가 ① 전략 자체의 구조적 문제인지
  ② A1A_ONLY 표본·survivorship bias 영향인지, A2b 정상 인수 가정 하에 **다음 실험에서
  분리할 수 있게 하는 설계안**을 작성한다. 새 전략을 만드는 것이 아니라 원인을 분리하는
  실험 설계가 본 보고서의 산출물이다.
- 제약: 코드·정책·전략 파라미터·기존 산출물은 수정하지 않는다. 신규 보고서만 저장한다.
- 저장 위치: `research/strategy-lab/reports/2026-08-17-survivorship-attribution-design/`

---

## 0. 요약 (판정 로직)

현재 데이터만으로 **방향성(추정)**은 확정할 수 있고, **크기(정량)**는 A2b가 필요하다.

- survivorship bias의 방향은 A1A_ONLY 결과를 **부풀리는(낙관적으로 만드는) 방향**이다
  (상장폐지 종목 = 성과 부진 종목을 표본에서 제외 → 제외된 종목이 전략에 더했을 손실이
  사라진다). 따라서 **"A1A_ONLY라서 성과가 나빠 보인다"는 해석은 방향상 성립하지 않는다.**
  관측된 -9.81%/-75%는 오히려 **전체 유니버스 실행 결과의 상한(optimistic bound)**일
  가능성이 높다.
- 즉, 현 데이터만으로도 "전략 구조 문제" 가설이 "표본 문제" 가설보다 우선한다는 **방향성
  논거**를 세울 수 있다. 다만 크기와 실제 거래 결과(slot 경쟁·신호 대체 효과)는 예측이
  불가능하므로, A2b 수집 후 동일 5DC를 병합 유니버스로 재실행해 정량 비교해야 확정된다.
- 이 보고서는 그 "동일 5DC를 어떤 조건으로 재실행해야 공정 비교가 되는가"를 정의한다.

---

## 1. 현재 상태 실측 요약 (이 보고서에서 직접 확인한 것)

### 1.1 유니버스
- **A1a (현재 상장, KIND)**: `data/backfill/universe/a1a/current.jsonl` = **2,578종목**
  (KOSPI/KOSDAQ 보통주, SPAC·KONEX 제외). 모든 종목 `exitAt=null, source=A1A`.
- **A1b (상장폐지 후보)**: `data/backfill/universe/a1b/delisted.jsonl` = **1,223종목**,
  **전부 `exitAt=null, exitReason=UNKNOWN`, `source=DART_CORPCODE_DIFF`**.
  - `_diagnostics.json`: `exitReasonPending=true`, `listingHistoryUnverified=true`.
  - `dartModifyDateByYear`: 2017:576, 2018:35, 2019:32, 2020:39, 2021:28, 2022:69,
    2023:73, 2024:121, 2025:105, 2026:145. **dartModifyDate는 폐지일이 아니다**
    (DART 레코드 최종 수정일, A2b 정책이 명시) — 폐지 시점 추정에 쓸 수 없다.

### 1.2 가격 데이터 (survivorship의 구조적 요인)
- **A2a (현재 상장 종목 가격)**: 연도별 파일 2014-2026, **전체 2,559종목**.
  - A1a와 교집합 = **2,558종목**.
  - A1b와 교집합 = **043090 1종목뿐**.
  - A1a 2,578 중 A2a에 없는 20종목 = `price-quality-excluded.jsonl.gz`의 20종목과
    **정확히 일치** (UNADJUSTED_CORPORATE_ACTION 18, TRANSIENT_PRICE_SPIKE 2).
  - **결론: A2a는 사실상 "생존자 전용" 가격 데이터다. 상장폐지 종목의 가격이 없다.**
    → post-fix rerun의 2,558종목 스캔(manifestHash 9756e0737ea8c866) 자체가
    survivorship-biased 표본이다.
- **A2b (폐지분 가격)**: `data/backfill/price/a2b/` **없음 (미수집)**.
  - 정책(PR-1.5) 인수 조건: minTickersWithData=600, minTickersInAnalysisWindow=550,
    exitAtMissing=0, exitAtNotTradingDay=0, emptyRateWarn=0.55.
  - 정찰 전수 실측: 확보 631 / 분석 구간 내 572. → **분석 구간에 약 572종목의
    상장폐지 종목이 추가될 것으로 예상** (현재 2,558 대비 **약 +22%**).

### 1.3 post-fix rerun 실측
- `5dc_v1a_p_samebar_rerun.json` (2회 실행 동일): runClass SMOKE, universeMode A1A_ONLY,
  period 2014-05-13 ~ 2026-08-03, engine CURRENT_HEAD(c140c26+), elapsed 505s.
- closed 1,592 / open 0, unique symbols **864종목**, **전부 A1a** (A1b 종목 0).
- exitTypeCounts(신호·기구 수준): STOP 18,901 / TARGET 6,638 / TIME_EXIT 2,800.
- CAGR -9.8053%, MDD -75.0002%, finalEquity 28,471,028.93 (직접 재현, 정확 일치).
- 거래 심볼의 상장 연도 분포: 2014-05-13 이전 상장 1,440건 / 이후 상장 152건
  → 전략은 대부분 오래된 "생존 기업"을 거래했다.

---

## 2. A1A_ONLY universe의 한계 정리 (분석 1)

| # | 한계 | 근거 | 영향 |
|---|------|------|------|
| L1 | **상장폐지 종목이 전략의 거래 후보에서 통째로 빠짐** | A2a에 A1b 가격 없음(043090 제외) | 폐지 종목이 냈을 신호·거래·손익이 전혀 반영 안 됨 |
| L2 | **상장폐지 시점(exitAt) 미확정** | A1b 전부 exitAt=null, UNKNOWN | 폐지 직전 구간의 point-in-time 처리가 불가능 |
| L3 | **폐지 후보 규모가 표본의 ~1/3** | A1b 1,223 vs A1a 2,578 | 누락된 종목군이 단순히 작지 않음 (분석 구간 내 약 572종목, +22%) |
| L4 | A1a listedAt은 "현재 종목코드 기준 상장일" | A2a 정책 `expectedRows.basisNote` | 코스피↔코스닥 이전상장 등에서 가격 이력이 listedAt보다 길 수 있음 — PIT 게이트로 못 씀 (이미 관측: 거래 23건이 listedAt 이전 진입, 이전상장 이력 때문에 정상으로 판단됨) |
| L5 | A2a의 adjusted 경로만 존재 | `source.adjusted=true` | 폐지 종목은 adjusted 이력이 없어 A2a에서 원천 차단 (A2b는 KIS FID_ORG_ADJ_PRC=0) |

---

## 3. survivorship bias: 추정 가능 / 불가 매트릭스 (분석 2)

### 3.1 현재 데이터로 **추정 가능한 것** (방향·구조)
| 항목 | 추정 | 근거 |
|------|------|------|
| 편향의 방향 | **부풀리는 방향 (optimistic)** | A1A_ONLY는 상장폐지(=성과 부진) 종목을 제외. LONG_ONLY 전략의 경우 제외된 종목은 대부분 손실 거래였을 것 → 포함하면 손실이 늘어 성과가 더 나빠진다. 따라서 관측 성과는 전체 유니버스 결과의 상한. |
| 누락 규모 | 분석 구간 내 약 **572종목 추가** (기존 대비 +22%) | A2b 정찰 전수 실측 631 확보 / 572 구간 내 (정책 주석) |
| 전략이 폐지 종목을 거래했을 가능성 | 높음 | exitTypeCounts의 STOP 18,901은 신호 수준. 폐지 종목은 대부분 하락 추세 → CCI -100 회복 신호 후 STOP 즉시손절이 반복됐을 개연성 |
| A1A_ONLY가 "-75% MDD의 원인"이라는 해석 | **방향상 기각** | 편향 방향이 성과를 부풀리므로, "표본 때문에 나빠 보인다"는 논리는 성립 어려움. 구조 문제가 우선 |

### 3.2 현재 데이터로 **추정 불가능한 것** (정량·거래 수준)
| 항목 | 이유 |
|------|------|
| 폐지 종목이 냈을 **정확한 신호 수·거래 수·손익** | 폐지 종목 가격 데이터 없음 (A2b 필요) |
| **slot 경쟁 효과** (최대 10 포지션) | 폐지 종목 신호가 추가되면 기존 종목의 진입이 밀려날 수 있고, 그 결과는 부호·크기 모두 예측 불가 |
| **신호 대체·겹침(overlap) 효과** | 동일 심볼 overlap 처리 로직에 폐지 종목이 추가되면 변경 |
| **MDD·CAGR의 실제 변화량** | 거래 수준 시뮬레이션 필요 |
| 폐지 **시점 분포** (2014-2026 중 언제 폐지됐는지) | dartModifyDate는 폐지일이 아님, exitAt 미확정 |
| A1a↔A1b 경계의 시간 가변성 (예: 043090) | 043090은 A2a 가격이 있지만 A1b로 분류됨 — 컬렉션 시점 차이·이관으로 생긴 경계 사례 |

---

## 4. 실험 설계안 — A2b 정상 인수 가정 (분석 3·4)

### 4.1 전제 (실험 가능 조건)
1. **A2b 수집·finalize 완료**: `data/backfill/price/a2b/{YYYY}.jsonl.gz` +
   `delisted-exit.jsonl.gz`(exitAt 확정값) + 인수 조건 통과
   (minTickersWithData>=600, minTickersInAnalysisWindow>=550, exitAt 4종=0).
2. **A1b exitAt 확정** = lastTradedDate (`exitAtSource: "lastTradedDate"`).
   → 상장폐지 종목의 거래 가능 구간 = [firstTraded, exitAt].
3. **A1a 가격은 그대로 A2a 사용** (A1a 종목을 A2b로 바꾸지 않는다 — 가격 소스 변화를
   유니버스 변화와 분리하기 위함). A1b 종목만 A2b 사용.

### 4.2 **고정 조건** (A1A_ONLY 실행과 동일해야 공정 비교 성립)
| 영역 | 고정값 |
|------|--------|
| 전략 | `strategies/5dc_v1a_p` (policy.json 1.0, contractFrozenAt 2026-08-14) **변경 금지** |
| 파라미터 | BB 20/2.0 close, CCI 20/-100 typicalPrice, ATR 14 Wilder, 신호 `Close>BB_mid ∧ CCI[t-1]≤-100 ∧ CCI[t]>-100`, 익일 시가 진입, stop=2*ATR, target=entry+3*stop, RR 3.0, maxHolding 60세션, sameBarRule STOP_FIRST, cost 15bps×2, slippage 0, maxPositions 10, equalWeight, fractionalShares false, sameDayCashReuse false, tieBreak ticker_ascending, 초기자본 100M |
| 엔진 | **CURRENT_HEAD(c140c26+)** — same-bar fix 포함 동일 코드. A1A_ONLY 실행과 엔진 커밋이 달라지면 비교 무효 |
| 캘린더 | `data/backfill/calendar.json` 동일 |
| 기간 | 2014-05-13 ~ 2026-08-03 (post-fix rerun과 동일) |
| 비용·실행 | CostModel 15/15/0bps, next_session_open 채결, gap 규칙 동일 |
| 포트폴리오 | PortfolioConfig 동일 (위 파라미터) |
| 스케줄링 | `_schedule_portfolio` 동일 (same-bar 처리 포함) |
| 지표 계산 | realized-pnl-at-exit-event stepwise (CAGR/MDD/winRate/WLR/PF/avgHolding/Sortino/Calmar 동일 함수) |
| 신호→거래 파이프라인 | compute_features → generate_signals → build_order → simulate_trade → dedup(overlap) → process_day 순서 동일 |
| A1a 가격 데이터 | A2a (같은 연도 파일·같은 manifest) |
| **PIT** | 신호는 t 종가 확정 후, 진입은 다음 세션 시가, ATR은 t 기준. 폐지 종목은 exitAt 이후 신호·진입 금지 |

### 4.3 **변경 조건** (실험 변수)
| 변수 | A1A_ONLY (기준) | 병합 실행 (실험) |
|------|-----------------|------------------|
| universe mode | `A1A_ONLY` (include_delisted=False) | `A1A_A1B_MERGED` (include_delisted=True) |
| 가격 데이터 | A2a (A1a만) | A2a(A1a) + **A2b(A1b)** |
| 거래 후보 | 2,558종목 | 2,558 + ~572(구간 내 폐지) 종목 |
| runClass | SMOKE | **PRIMARY 후보** (price_coverage_report `fullyCovered` 통과 시) |
| 폐지 종목 PIT | 해당 없음 | [firstTraded, exitAt] 내에서만 신호·거래. exitAt 이후 미포함 |

> **핵심**: 유니버스·가격 소스 **딱 두 가지만** 바꾼다. 나머지는 전부 고정. 이게 "공정
> 비교"의 정의다. 특히 A1a 종목의 가격을 A2a로 유지하는 것이 중요하다 — A2b를 A1a에도
> 적용하면 "유니버스 확장"과 "가격 소스 변경"이 뒤섞여 어느 쪽이 성과를 바꿨는지 분리할
> 수 없게 된다.

### 4.4 실행 절차
1. `UniverseProvider(repo_root=..., include_delisted=True)` — 이미 구현됨
   (test_universe.py의 merged mode 테스트 존재).
2. A1b 가격 공급: A2b 디렉터리를 읽는 프로바이더를 A2aProvider와 같은 계약으로 추가
   (현재 코드에 없음 → **실행 시점에 구현 필요. 이 보고서는 설계만, 구현 안 함**).
3. `runner.run_smoke`의 `assert params["universe"]["mode"] == "A1A_ONLY"` 를
   병합 모드 허용으로 확장 (PRIMARY 요구조건 §11 — **config 변경이며 rewrite 아님**이
   runner.py docstring에 명시됨).
4. A1b 종목의 거래 가능 구간을 `[firstTraded, exitAt]`으로 제한:
   - 신호가 exitAt 이후거나, 진입일이 exitAt 이후면 신호 폐기.
   - 보유 중 exitAt 도달 시 해당 세션에 강제 청산(또는 가격 데이터가 exitAt에서 끝나므로
     자연 종료) — **어느 쪽으로 할지 사전 정의 필요** (아래 4.5).
5. 동일 지표 함수로 계산해 post-fix rerun 결과와 **테이블로 나란히 비교**.

### 4.5 사전 정의가 필요한 판정 지점 (설계 시 결정 보류 항목)
| 지점 | 옵션 | 비고 |
|------|------|------|
| 폐지 종목의 exitAt 시점 청산 처리 | (a) exitAt 세션에 강제 TIME_EXIT, (b) 가격 데이터가 거기서 끝나므로 자연 종료로 취급 | (b)가 A2b 데이터 구조와 일치하지만, 포트폴리오에 "미청산 보유"가 남는지 명시 확인 필요 |
| exitAt 이후 신호 | (a) 생성 금지, (b) 생성 후 진입 불가로 skip | 결과 동일해야 하며, diag의 skippedReasons에 반영 |
| stillTradingSuspect (마지막 거래일이 캘린더 끝 근처) | 043090과 같은 사례를 폐지로 처리 vs 생존으로 처리 | A2b 진단의 WARN 항목 — 5거래일 이내 거래 종목은 폐지가 아니라 거래 중일 수 있음. **실험 전에 이 경계 사례를 확정해야 함** |
| A1b ∩ A2a (043090) | A1b로 분류해 exitAt 적용 vs A1a 가격(A2a)을 그대로 사용 | 전략이 043090을 0회 거래했으므로 현재 영향 없음. 다만 병합 실행에서 어느 소스를 우선할지 규칙 필요 |

---

## 5. 비교 지표와 판정 기준 (실험 후 해석 규칙)

| 지표 | 값 | 해석 |
|------|-----|------|
| ΔCAGR = 병합 - A1A_ONLY | < 0 (더 나쁨) | 폐지 종목이 손실 추가 → 구조 문제 확증 + A1A_ONLY는 상한이었음을 실증 |
| ΔMDD = 병합 - A1A_ONLY | 더 깊음 | 동일 |
| ΔtradeCount | ~+수백 건 | 폐지 종목 신호의 실제 진입 수 (0이면 "신호 대체" 때문에 영향이 없었다는 것) |
| ΔSTOP 비율 | 폐지 거래의 STOP 비율 | 폐지 종목의 손실 구조 확인 |
| 병합 실행의 폐지 종목 거래 손익 | 합계 | survivorship이 실제로 제거한 손실의 크기 |

**판정 논리**:
- 병합 결과가 A1A_ONLY와 비슷하거나 더 나쁨 → **"표본 문제" 가설 기각. 전략 구조 문제
  확정** (방향성 논거와 일치).
- 병합 결과가 현저히 더 좋음 → 폐지 종목이 net positive였다는 뜻 (반직관적) → 이 경우만
  "표본이 성과를 왜곡했다"가 지지되며, 그 원인을 추가 분석해야 함.
- **핵심**: 어느 쪽이든 "-75% MDD가 survivorship bias 때문이다"는 방향상 성립하지 않는다는
  것이 이 설계의 전제 검증이며, 실험이 그 정량을 제공한다.

---

## 6. 현재 데이터로 즉시 수행한 추가 분석 (분석 5)

### 6.1 A2a = 생존자 전용 가격 데이터 (확정)
- A2a 2,559종목 중 A1b 소속은 **043090 단 1종목**. 나머지 2,558은 전부 A1a.
- A1a 중 A2a에 없는 20종목 = quality-excluded 20종목과 정확히 일치 (실측).

### 6.2 폐지 종목 추가 규모 (예상 +22%)
- 분석 구간(2014-05-13 이후) 내 폐지 종목 ≈ 572 (A2b 정찰 실측).
- 2,558 → ~3,130종목 예상. 유니버스 확장이 미미하지 않음.

### 6.3 post-fix 거래는 전부 생존자
- 864 고유 심볼 전부 A1a. A1b 교집합 = ∅. → 관측 성과는 "생존자만 거래"한 결과.

### 6.4 043090 경계 사례
- A1b 소속이지만 A2a에 2014-2026 전체 가격 존재 (2,998행), post-fix에서 0회 거래.
- dartModifyDate 2026-04-01, 2026-07 말 가격 1,140→228→300 급락 — 최근 폐지 사례로 보임.
- 병합 실행 시 소스 우선 규칙(4.5)이 필요한 이유를 실증.

### 6.5 방향성 검산 (논리)
- LONG_ONLY 전략 + 폐지 종목 제외 → 편향 방향은 성과 상향.
- 관측 -9.81%가 상한이라면, 전체 유니버스 결과는 ≤ -9.81% (더 나쁨)일 가능성.
- 따라서 "-75% MDD는 표본 때문"이라는 해석은 방향상 지지되지 않음. **전략 구조 문제
  가설이 우선이며, A2b 실험으로 정량만 보완하면 된다.**

---

## 7. 열린 질문 / 추가 검증 필요

1. **A1b 1,223의 폐지 시점 분포**: dartModifyDate로는 못 잰다. A2b firstTraded/lastTraded가
   유일한 실측이다. 실험 전에 A2b 진단의 `tickersInAnalysisWindow`(기대 550+)를 확인.
2. **A1b quality-excluded·빈 응답**: 구간 밖 폐지(48.4%)는 전략과 무관하므로 실험에서
   자연 제외. 다만 빈 응답과 실패를 구분하는 A2b 게이트가 통과해야 함.
3. **043090 처리**: 경계 사례 규칙을 실험 전에 결정 (4.5).
4. **A2b가 A1a 종목을 포함하는지**: 정책상 A2b는 A1b 후보만 수집. A1a를 A2b로 섞으면
   비교가 오염되므로, 실험 전에 `a2b` 산출물에 A1a 종목이 없는지 확인.
5. **runner 확장 필요성**: 병합 실행은 현재 코드로 불가(A1A_ONLY assert). A2b 인수 후
   config 확장이 선행돼야 하며, 이는 이 보고서의 범위(설계) 밖 구현 작업임.

---

## 8. 승인 필요 사항 (이 보고서는 설계만, 실행 아님)

- [ ] A2b 수집·finalize (KIS 시크릿 준비, 워크플로 `price-a2b.yml`)
- [ ] 병합 유니버스 + A2b 가격 공급 코드 추가 (runner 확장, config 변경)
- [ ] 4.5의 판정 지점 4건 결정
- [ ] 실험 결과 보고서 저장 위치 결정

이 설계안은 코드·정책·기존 산출물을 수정하지 않았다. 실행은 위 항목이 승인된 뒤에만
가능하다.