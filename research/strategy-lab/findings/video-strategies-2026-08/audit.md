---
track: kr
factor: video-strategies-audit
date: 2026-08-22
verdict: UNCLASSIFIED
conditions: ["A 등급 7개 signal study 완료", "전체 엔진 통합 백테스트 미실행", "threshold 최적화 없음"]
reason: "Video 전략 V1~V8 feasibility audit - A/B/C 분류 및 A등급 실행 현황을 요약하나 단일 판정 없음"
criteria_version: backfill-v1
---

# Video 전략 후보 V1~V8 — Feasibility Audit (2026-08-22)

> **소급 감사임을 명시한다.** 지시는 "코드 작성 전" 감사였으나 실제로는
> V1~V8 signal study가 선행 완료된 상태다(세션 로그: 2026-08-22). 본 문서는
> 이미 수행한 작업의 데이터 원천·PIT 위험·기존 전략과의 겹침을 소급해 기록하고
> A/B/C로 분류한다. [OBSERVED]/[UNSPECIFIED] 구분은 각 findings 문서와 동일하게
> 유지된다. threshold 최적화(데이터 마이닝)는 어느 단계에서도 하지 않았고,
> 엔진 통합 백테스트도 실행하지 않았다.

## 요약

| 전략 | 등급 | 상태 | T+1 / T+5 / T+10 / T+20 초과수익 (%p) | 판정 |
|---|---|---|---|---|
| V1 MA 5/25/75 눌림 | **A** | 스터디 완료 | +0.043 / +0.018 / +0.035 / −0.073 | ≈0 |
| V2 FVG Pullback | **A** | 완료 | −0.071 / −0.131 / −0.124 / −0.223 | 음수 |
| V3 BB+RSI | **A** | 완료(entryClose) | +0.072 / +0.372 / +0.512 / **+1.007** | ★ 흥미로움 |
| V4 Fib+S/R | **B** | 1차 관측만 | (−0.063 / −0.060 / −0.036 / −0.130) | swing 정의 미정 |
| V5 수급 Divergence | **A** | 완료·재현 MATCH | divA +0.039 / +0.096 / +0.121 / +0.122 | 방향 일치·비용미달 |
| V6 동시순매수+매집가5% | **A** | 완료 | +0.058 / +0.103 / +0.124 / **+0.178** | ★ 흥미로움 |
| V7 EOD 스캐너 | **A** | 완료 | S3 +0.110 / −0.107 / −0.318 / (미측정) | T+1 한정 |
| V8 대금상위+돌파 | **A** | 완료(A/B 비교) | A안 +0.193 / +0.072 / +0.135 / +0.210 | 필터 악화 → 가치 없음 |

## 공통 데이터 원천 (파일/컬럼)

| 원천 | 경로 | 컬럼/내용 | 사용 전략 |
|---|---|---|---|
| A4 연구 패널 | `research/strategy-lab/data/a4/a4-research-dataset.parquet` | close, total_amount, total_volume, foreign_nb_1d/5d/20d, inst_nb_*, indiv_nb_*, net_* (투자자별), fwd_d20/60/120 등 35컬럼 | 전 전략 유니버스(2,558종목), V5/V7 수급·대금 |
| A2a OHLC 캐시 | `research/strategy-lab/.cache/a2a_parquet/{2016..2026}.parquet` | ticker, date, open, high, low, close, volume | V1(MA)·V2(FVG)·V3(BB/RSI)·V4(OHLC)·V7(pos20)·V8(Donchian) |
| 원본 수급 백필 | `data/backfill/supplyDemand/a4/{year}.jsonl.gz` | 투자자별 buyAmount/**buyVolume**/sellAmount/sellVolume | V6 매집단가 재현 |
| 추출 캐시 | `research/strategy-lab/.cache/v6_acc_price/` | 일별 외국인+기관 총매수 금액/수량 | V6 |
| 기존 전략 | `strategies/trend_breakout_v1`, `strategies/5dc_v1a_p` | Donchian20 엣지 / BB20±2σ+CCI20(−100 회복)+ATR14 RiskSpec | 비교 기준 |

## 전략별 감사

### V1 MA 5/25/75 Pullback — A
- feature: close(a4 패널) → SMA 5/25/75, 엣지 트리거 `close[t]>ma5[t] & close[t−1]≤ma5[t−1]`
- PIT: 없음 — rolling MA 인과, 신호일 t 종가 판정. 체결은 t+1 open(이벤트 근사 한계 공통)
- 겹침: 없음(trend_breakout_v1은 돌파, V1은 되돌림 반등 — 반대편 가족)
- 결과 ≈0, 양(-) 초과수익은 2020·2021·2026 집중

### V2 FVG Pullback — A
- feature: high/low/close(a2a 캐시) — 3봉 갭 `low[k]>high[k−2]` + 터치 반등 엣지
- PIT: 없음 — FVG 형성·터치 모두 확정 봉 기준, leg당 1회 발화
- 겹침: 없음
- 결과 전 호른즈 음수

### V3 Bollinger + RSI — A ★
- feature: high/low/close(a2a 캐시) — BB(20±2σ, ddof=1), RSI14 Wilder; 하단 이탈+RSI≤30 진입,
  상단 종가 돌파 청산(T+20 센서링으로 부분 반영)
- PIT: 없음 — 지표·트리거 모두 t 종가까지 데이터만 사용
- 겹침: **5dc_v1a_p와 부분 겹침** — 같은 BB(20,2σ)+오실레이터 과매도 회복 가족.
  다만 트리거 다름: 5DC는 `Close>BB_mid & CCI −100 상향회복`(회복 확인형),
  V3 entryClose는 `Close<BB_lower & RSI≤30`(이탈 즉시형). BB 파라미터가 동일하므로
  엔진 통합 전 5DC와의 독립성 검토 필요
- 결과: 유일하게 전 호른즈 양수·연도 안정(T+5 11개 해 중 10개 양수)

### V4 Fibonacci + 지지/저항 — B
- feature: OHLC(a2a 캐시) — 데이터는 충분
- PIT: look-ahead는 차단됐으나 **swing 탐지 정의 자체가 ASSUMPTION** — 대칭창 pivot(L=3,
  k+L 확정)이라는 임시 선택이 swing 형태를 결정. zigzag %역치·ATTR 창 등 다른 정의면
  leg 구성이 달라져 결과가 바뀔 수 있음(지시서 명시 "핵심 리스크")
- 겹침: 없음(되돌림 계열이나 fib confluence 고유)
- 등급 근거: 1차 관측(findings/v4-fib-sr, 음수)은 존재하나 설계 결정 없이는 확정 불가 → B
- 재개 조건: parked.md 참조

### V5 외국인 vs 기관 5일 Divergence — A
- feature: a4 패널 `foreign_nb_5d`, `inst_nb_5d` (rolling 5, min_periods=1)
- PIT: 창에 당일 포함 — 투자자별 수급은 장마감 확정이므로 t 종가 판정 가능. 없음
- 겹침: V6 baseline(동시 순매수)과 같은 수급 가족이나 조건 상반(divergence vs co-movement).
  기존 20d 조합 분석과 정합(audit.md 참조)
- 재현 검증: 저장 수치 전량 MATCH. divA 양수(비용 30bp 미달), divB 음수

### V6 외국인+기관 동시 순매수 + 매집가 +5% — A ★
- feature: a4 패널(nb_5d, close) + 원본 백필(jsonl.gz의 buyAmount/buyVolume) →
  매집단가=직전 5거래일 총매수금액 합÷총매수수량 합(gross buy VWAP, 임시 정의)
- DATA GAP 판정: **아님** — 패널엔 금액만 있지만 원본에 금액·수량 모두 존재(원문 대조 4/4)
- PIT: 매집단가 창에 당일(t) 포함 + `close[t]≤1.05×매집가` — 장마감 EOD 판정으로 일관. 없음
- 겹침: V5·V7-S3와 수급 가족. V6이 세 개 중 유일하게 T+20까지 양수(+0.178%p, T+5 11개 해 전부 양수)

### V7 종가베팅 EOD 스캐너 — A
- feature: a4 패널(total_amount 백분위, *_nb_1d) + a2a 캐시(pos20)
- PIT: 모든 feature는 t 종가 시점 산출 가능(당일 횡단면 백분위 포함). **체결 시점 질문**:
  실거래라면 t+1 open 진입 — 이벤트 스터디(t→t+h close-to-close)는 이 격차를 포함하는
  근사치임을 문서화. look-ahead 없음
- 겹침: S3(동시순매수+대금상위)는 V6·V5와 수급 가족, 대금 필터는 V8과 공유
- 구조적 발견: "+개인"은 어떤 방향으로든 무정보 — f>0&i>0인 107만 행 중 개인 순매수 0건
  (공집합), 순매도는 항상참. 영상 feature 목록을 AND 필터로 구현 불가 → composite 점수
  해석 등 설계 논점 잔존(관측 자체는 완결)

### V8 거래대금 상위 + 저항선 돌파 — A
- feature: a2a 캐시(high→Donchian20 당일 제외) + a4 total_amount(당일 백분위)
- PIT: Donchian 단일 shift 계약 준수(engine/indicators/donchian.py와 수학적 동일 확인),
  엣지 트리거. 없음
- 겹침: **trend_breakout_v1과 직접 겹침** — variantA가 그 신호와 등가(검증 완료)
- 판정: 거래대금 상위 필터는 incremental value 없음(네 호른즈 전부 악화, T+20 음(-) 해 4→7개)

## Phase 2 현황 — A등급 실행

A등급 7개 전부 signal study 완료(T+1/5/10/20 forward return, 날짜 매칭 벤치마크 대비
초과수익, 승률). **전체 엔진 통합 백테스트는 실행하지 않았다**(승인 사항).

지시 기준("비단조하지 않고 유의미")에 해당하는 결과:
- **V3**: 전 호른즈 양수·연도 안정. 단 5dc_v1a_p와 BB 지표 겹침 → 독립성 검토 필요
- **V6**: 필터 기여 확인(baseline 대비 T+20 +0.063→+0.178%p), 연도 안정 최상위

여기서 멈추고 사람 보고로 이행. 나머지(V1 ≈0, V2/V4 음수, V5 방향일치·비용미달,
V7 T+1 한정, V8 필터 무가치)는 엔진 통합 후보에서 제외 제안.

## 지시 준수 확인

- [OBSERVED]만 규칙으로 취급 — [UNSPECIFIED]는 전부 "임시 정의"로 문서 분리 유지
- threshold 최적화 없음 — 영상 원본 수치(RSI30, +5%, 2R, +10/+20%) 그대로 1차 검증
- 엔진 통합 백테스트 미실행 — 소규모 검증 스크립트(무작위 샘플 재계산)만 사용
