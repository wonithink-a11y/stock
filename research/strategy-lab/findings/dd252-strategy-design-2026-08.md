---
track: kr
factor: dd252-strategy-design
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "DD252 전략화 설계문서 - 6M horizon·skip-1m·월간 리밸런스·top-30·MERGED 유니버스 정의, 거래비용 포함 백테스트 및 승격은 다음 단계"
---
# DD252 전략화 설계 — Strategy Lab 검증용 (2026-08)

> **범위**: 이 문서는 **설계 문서**다. 코드 구현·백테스트 실행·production 변경은
> 포함하지 않는다. 아래 파라미터 중 "기본 후보"로 표시된 값은 연구 결과에서
> 정당화된 출발점이지 확정이 아니며, §5의 검증 통과 후에만 조정 근거가 생긴다.
> 최종 채택 판단은 Claude와 사용자의 몫이다.

---

## 0. 확정된 연구 사실 (이 문서의 유일한 근거)

| # | 사실 | 수치 | 출처 |
|---|---|---|---|
| F1 | feature 정의 | `dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1` | dd_factor_followup_study.py |
| F2 | 6M horizon 유효 | MERGED 일별 IC +0.068 (t=32.6), D10-D1 월간 +0.0385 (NWT 2.08, ρ=0.94) | dd252-survivorship-results.json |
| F3 | horizon 프로필 | d20 -0.007(NWT -1.3) → d60 +0.007(0.65) → **d80 +0.0155(1.01)** → **d120 +0.0385(2.08)** — 유의성은 ~4M부터 | dd-followup-results.json |
| F4 | 1M 효과 없음 | 위 d20 행. 1M 홀딩 구조로는 활용 불가 | 〃 |
| F5 | Momentum12M과 독립 | 직교화 IC(mom 통제 후) d120 +0.099 (t=50.8) — 비직교화보다 강함. 역방향 잔차 IC는 음수(-0.064) | 〃 |
| F6 | survivorship robust | A1A_A1B_MERGED에서 효과 유지(IC +0.068 vs A1A +0.062), 연도별 2018~2026 9년 연속 양수 스프레드 | dd252-survivorship-results.json |
| F7 | 유동성 조건부 | liq20 tercile별 6M 스프레드 low -0.0148(NWT -0.86) / mid +0.0476(2.87) / high +0.0926(4.63) — **저유동성에서 죽음** | dd-followup-results.json |
| F8 | 절대 유동성 플로어 | amt20 ≥ 1억원: 스프레드 +0.0452 (NWT 2.47), 표본 90% 유지 | 〃 |
| F9 | skip-1m 우월 | raw dd252 대비 IC 0.066 vs 0.053, NWT 2.63 vs 2.27 — skip 변형 채택 근거 | 〃 |
| F10 | 미검증 영역 | 거래비용·실행(t+1 open 체결)·top-N 집중 포트폴리오 성과는 **아직 어떤 것도 계산 안 됨** | - |

F1~F9는 모두 종가 기반 정보력 연구(decile/IC) 결과다. "D10-D1 스프레드"는
롱숏 개념이고, 실제 롱온리 top-N 전략 성과는 별도로 존재하지 않는다 — 그것이
이 설계의 다음 단계가 존재하는 이유다.

---

## 1. Signal definition

```
dd_252_skip1m[t] = close[t-21] / max{ close[s] : s ∈ [t-252, t-21] } - 1
```

- 분자: 21거래일 전 종가 (JT J=12,K=1 관례의 skip 월 — F9)
- 분모: [t-252 .. t-21] 구간(232세션) 최고 종가
- 값의 의미: **0에 가까울수록 최근 고점 부근** → 매수 측. 깊은 음수 = 최대 낙폭.
- 최초 유효 시점: 티커당 세션 273개(252+21) 확보 후.
- 가격 원천: A2a adjusted close (+ 백테스트 시 상장폐지분 A2b 병합). unadjusted 금지.
- 변형 금지: 창 길이(252/232), skip(21)은 F1 고정. 창 감도 분석은 별도 단계.

## 2. PIT-safe 계산 시점

- 신호값은 **t까지 관측된 데이터만** 사용하며, 실질 입력은 전부 `≤ t-21` 시점 종가다.
- rolling 연산은 전부 backward(shift + trailing max) — 절단 재계산 일치 검증
  (앞 60% 재계산 == 전체 계열, dev=0)을 구현에 내장한다. 기존 연구 스크립트
  (`dd252_survivorship_study.py::pit_truncation_check`)과 동일한 단언.
- 당일 종가 신호를 당일 수익률에 쓰지 않는다: **신호는 t 종가 확정 후 산출,
  진입은 t+1 시가** (repo 백테스트 공통 관례, LOWMOM60/CAND1과 동일).
  주의: 기존 정보력 연구는 t 종가→t+h 종가였으므로 전략 백테스트 수치는 연구
  수치보다 약간 불리한 방향으로 나올 수 있다(1세션 지연) — 예상 내 차이다.

## 3. Rebalance frequency

- **월 1회**, 각 달 첫 거래일(TradingCalendar 기준)에 신호 갱신·신규 코호트 편성.
- 기존 Momentum12M/MACD/DD 연구 전체가 월간 리밸런스 관례이고, F2~F3의 증거도
  월간 횡단면에서 나왔다. 주간/일간 리백테스트는 이번 단계에서 하지 않는다.

## 4. Holding period

- **기본: 120거래일(≈6M)**, 월 1회 신규 cohort 진입 → 6개 cohort가 동시에 존재.
  매월 가장 오래된 cohort(120세션 경과)를 청산하고 신규 cohort 진입.
  자금은 6개 cohort에 **동일 비중(1/6씩)**으로 배분.
- 민감도 변형: **80거래일(≈4M)** — F3에서 유의성이 시작되는 최소 horizon.
  코호트 5개, 자금 1/5씩.
- 20/60거래일 홀딩은 F4(1M 무효)·F3(d60 NWT 0.65)로 기각 — 테스트 목록에서 제외.
- Phase 1 백테스트는 H∈{80,120} 두 가지만. 논오버랩(분기 전량교체) 변형은
  오버랩 효과 분리가 필요해질 때의 진단 도구로만 남긴다.

## 5. Universe

- **백테스트: A1A_A1B_MERGED** (생존 + 상장폐지, `UniverseProvider(include_delisted=True)`
  + A2a + A2b, quality-excluded 제외 — lowmom60_survivorship.py 방식 그대로).
  A1A_ONLY 병행 실행은 survivorship 게이지용으로만 남긴다(F6 재확인).
- 라이브 적용 시에는 자동으로 현재 상장 종목만 대상이 된다(상장폐지 종목은
  매수 대상이 될 수 없음) — 백테스트와 라이브의 차이는 이 구조가 흡수한다.
- 자격 요건(각 리밸런스일 t): ① dd 신호 유효(히스토리 ≥ 273세션) ② t와 t+1에
  가격 존재(진입 가능) ③ §6 유동성 제약 충족.
- 상장폐지 처리: 보유 중 마지막 세션 이후 가격 소실 시 **마지막 유효 종가 강제
  청산 + 비용 부과** (명시적 규칙, 백테스트 구현 시 필수). NaN-drop으로 묻지 않는다.

## 6. Liquidity constraint

- **기본(후보): amt20 ≥ 1억원** — amt20 = 20거래일 평균 거래대금(KRX 전체,
  PIT rolling). F8의 절대 컷을 그대로 쓴다.
- 근거: F7 — 저유동 tercile에서 신호가 죽고(mid/high에서만 유효) PBR·LOWMOM60에서
  반복된 "저유동성 아티팩트" 함정을 사전에 차단.
- Arm A(단독 baseline)만 플로어 없이 돌려 **필터의 기여분을 정량화**한다(§4 arms).
- 상대 tercile 버전(mid+high만)은 민감도로 1회 확인. 기본은 절대 컷(운영 단순성).

## 7. Position selection / ranking

- 자격 종목을 `dd_252_skip1m` **내림차순** 정렬(고점에 가까울수록 상위) →
  **top-N = 30** 선정, 코호트 내 **동일가중**(1/N).
- N 민감도 {15, 30, 50} — 30은 REV20/LOWMOM60-v1과 같은 repo 관례값이라 기본.
- 동점 처리: amt20 내림차순 → ticker 오름차순(결정론적).
- **동일 종목 재선정 정책**: 다음 리밸런스에서 이미 보유 중인 종목이 다시 top-30에
  들어오는 경우, **기존 cohort의 holding schedule을 그대로 유지**하고
  신규 cohort에서는 동일 종목을 중복 선정하지 않음(다음 순위 종목으로 채움).
  이는 cohort 간 독립성을 보장하고 결정론적 tie-break를 유지한다.
- D10-D1 스프레드(+3.85%p/6M, F2)는 롱숏 개념이므로 롱온리 top-30 성과는 이보다
  낮을 것이어야 정상이다. 기대치를 스프레드에 맞추지 않는다 — 측정이 목적.

## 8. Momentum12M 결합 시 역할 — 등가가중 금지

연구 사실: mom252 raw IC는 이 유니버스에서 **음수**(잔차 IC -0.064, F5),
dd252는 양수. 단순 평균 결합은 서로를 상쇄한다. 따라서:

1. **먼저 DD252 단독(Arm A)을 baseline으로 확정한다.** 모든 arm은 A 대비
   증분(incremental)으로만 평가한다.
2. Momentum12M은 결합 변수가 아니라 **통제변수/보조 ranking**으로만 검증한다:
   - **B-arm(주 설계)**: 리밸런스일마다 dd_252_skip1m 랭크를 mom252 랭크에
     교차회귀한 **잔차 랭크**로 정렬(top-N). F5의 직교화 IC(+0.099)를 그대로
     전략화한 것 — "mom이 설명하는 성분을 빼고 남은 dd 고유 정보"로 선정.
   - B2(robustness 참고용): mom252 상위 decile(반전으로 가장 불리한 군) 제외 후
     dd 랭킹. 등가가중 결합은 어느 단계에서도 하지 않는다.
3. B-arm이 A 대비 유의한 개선을 못 보면 momentum 결합 라인은 폐기한다
   (독립성은 이미 확인됐으므로 실패 시 결론은 "개선 여지 없음"이지 "독립성 오류"가 아니다).

## 9. Benchmark / baseline

| benchmark | 정의 | 용도 |
|---|---|---|
| BM1 (주) | 자격 유니버스(같은 필터) 전체 **동일가중 월 mtm** | 신호 기여 = 전략 - BM1. 필터 효과 분리 |
| BM2 | 무필터 전 유니버스 EW | 유동성 플로어 자체의 기여분 |
| BM3 (참고) | LOWMOM60-v1 (기존 내부 후보) | 상대 경쟁력 맥락. 직접 비교 대상 아님 |
| 지표 | D10-D1 롱숏 스프레드 IR | 전략이 아니라 **신호 품질 추적**용 |

핵심 판정은 "전략 - BM1" 순액 기준이다. 절대 CAGR만으로 판단하지 않는다.

## 10. 다음 검증 단계 (거래비용 포함)

실행 순서(각 단계 끝나고 결과 보고 → 다음 단계 go/no-go):

1. **Gross 백테스트** — Arm A, MERGED, H∈{80,120}, N=30, 비용 0.
   산출: CAGR/MDD/Sharpe, 연도별, 코호트별 기여, 실현 turnover.
2. **Net 백테스트** — 왕복 30bps(repo 관례) 적용. staggered 구조의 회전율은
   H=120일 때 **월 16.7% one-way / 33.3% two-way** (6개 cohort 중 매월 1개 교체)
   수준이므로 비용 부담은 낮은 편이지만 실측이 기준이다. 손익분기 bps 산출.
3. **Arm 비교** — B/B2/C/D를 A 대비 증분으로 평가(§4). 최종 조합 arm은
   개별 증분이 확인된 뒤 별도 설계.
4. **민감도** — N∈{15,30,50}, 플로우 ±, H∈{80,120}, minPrice 5000 옵션.
5. **SMOKE → 엔진 검증** (§7 절차). 승격 판정은 Claude/사용자.

**승격 기준(제안)**: net CAGR − BM1 ≥ +3%p, MDD가 BM1 대비 열화 아님,
양수 연도 ≥ 70%, turnover 실측이 비용 가정과 2배 이상 괴리 없음. 미달 시
"조건부 보류"로 남기고 원인 decomposition부터 다시.

## 11. Survivorship-safe 검증 범위

- 모든 백테스트는 **MERGED 기준으로 먼저** 돌린다. A1A_ONLY는 bias 게이지로만
  병행(두 패널 차이 = 생존편향 크기 추정).
- 상장폐지 청산 규칙(§5)을 적용해야 MERGED 패널의 의미가 살아난다 — 규칙 없는
  NaN-drop 백테스트는 survivorship-safe라고 부르지 않는다.
- A2b 커버리지 한계(수집된 508/1,223종목)는 lowmom60 때와 동일하게 caveat으로
  명시한다.

## 12. Strategy Lab 엔진 적용 변경사항

**원칙: production(scoringEngine·resolver·config/policies) 무변경.** DD252는
가격 단독 파생 factor라 valuation 패널(A5 resolve)이 필요 없다 — LOWMOM60-v1
선례와 같은 유형이다.

| 항목 | 내용 | 신규/재사용 |
|---|---|---|
| `strategies/dd252_v1/build_selection.py` | MERGED bars → 월별 리밸런스일별 자격 필터 + dd 랭킹 top-N + arm별 변형(B잔차/C플로어/D-vol제외) 계산 → `selection.json` | 신규 (lowmom60 build_selection 패턴 복제) |
| `strategies/dd252_v1/rule.py` | engine Strategy 계약(compute_features/generate_signals) — selection.json 조회형, `_HOLD_COL="dd252HoldSessions"` | 신규 (lowmom60 rule.py 패턴) |
| `strategies/dd252_v1/policy.json` | holdSessions=120(기본), stopDistanceFormula=×100(스탑 미사용), tieBreak | 신규 |
| `run_dd252_v1.py` | **LOWMOM60 패턴의 custom runner**로 구현 — `engine.runner.run_smoke()` 대신 월별 cohort 회계(6개 동시 보유, 1/6 자금 배분) 직접 처리 + engine.metrics 산출 | 신규 (run_lowmom60_v1.py 패턴 확장) |
| 보유 만기 | 개별 포지션 120세션(기본) 만기 자동 청산. `run_smoke`의 `maxHoldingSessions`만으로는 staggered cohort 불가하므로 custom runner에서 별도 관리 | 신규 |
| 동일 종목 재선정 | §7 정책 적용: 기존 보유 종목은 cohort schedule 유지, 신규 cohort에서 중복 제외 | 신규 |
| 확인 필요 사항 | ① cohort 자금 배분(1/6) 로직이 engine 계좌 구조와 정합하는지 ② 동일 종목 재선정 시 slot 처리(§7 정책) 구현 검증 | 구현 전 결정 |
| 테스트 | `tests/test_dd252_v1.py` — PIT 계약(절단 일치), 재현성, selection 스키마 | 신규 (test_lowmom60_v1.py 패턴) |
| 금지 | scoringEngine/resolver/config/policies 수정, 새 데이터 수집 | - |

---

## 13. 검증 대상 Arms (별도 설계 — 이번 단계에서 백테스트하지 않음)

공통: MERGED 유니버스, 월간 리밸런스, top-30 동일가중, t+1 open 진입,
H=120(기본)/80(민감도). Arm 간 비교는 **A 대비 증분**으로만 한다.

| Arm | 이름 | 정의 | 검증 목적 | 근거 |
|---|---|---|---|---|
| **A** | DD252 단독 (baseline) | 자격 = 히스토리≥273세션 + 진입가능. 필터 없음. dd 내림차순 top-30 | 순수 신호의 롱온리 성능. 모든 증분의 기준선 | F2 |
| **B** | DD252 + Momentum12M control | 자격 = A와 동일. 랭킹만 dd\|mom252 랭크-잔차로 교체. (B2: mom252 상위 decile 제외 변형) | mom 통제가 롱온리 top-N에서도 증분을 주는지 | F5 |
| **C** | DD252 + liquidity floor | A + amt20 ≥ 1억원 | 플로어의 순증분(비용 절감·낙폭괴물 배제 효과 포함) | F7·F8 |
| **D** | DD252 + extreme-vol exclusion | A + vol20 상위 decile 제외 (vol20 = log(close).diff().rolling(20).std(), repo 기존 정의) | 초고변동 종목 제거 증분 | **가설 — 아직 미검증**. 저유동성·급락 군집이 dd 하위와 겹친다는 관찰에서 출발 |

- D는 유일하게 선행 연구가 없는 arm임을 명시한다 — 결과가 A와 같아도 이상하지 않다.
- B·C·D는 각각 A와만 비교하고, 상호 조합(B∩C∩D)은 개별 증분 확인 후 별도 설계.
- 성공 판정은 §10 승격 기준을 arm별로 적용한다.

---

## 14. 미해결 질문 / 리스크

1. 롱온리 top-30에서 스프레드가 얼마나 남는지 — D10 전체가 아니라 꼬리 30종목이라
   집중도·종목 특성이 다르다(측정 전까지 기대치 보유 금지).
2. 최근 스프레드 크기 집중(MERGED d120 월간 스프레드: 2024 +0.086 / 2025 +0.072 /
   2026 +0.242) — 최근 구간이 pooled 수치를 끌어올림.
   연도별 cutoff(예: 2023년까지 sub-period) 안정성을 백테스트에서 함께 본다.
3. 2016-17년은 MERGED에서 음수 스프레드(-0.038/-0.004) — 초기 구간 약세는 사실.
   "9년 연속 양수"와 함께 항상 함께 보고한다.
4. A2b 부분 커버리지, t+1 open 실행 gap, 상장폐지 청산 가격 현실성 — 모두 §10 단계에서
   실측으로 닫는다.
5. 본 문서의 모든 파라미터는 Claude·사용자 검토 전까지는 초안이다.
