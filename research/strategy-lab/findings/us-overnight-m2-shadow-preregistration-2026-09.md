---
track: kr
factor: us-overnight-m2-shadow
date: 2026-09-29
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["M2(갭 잔차 → 장중 지속) 정의·계산 코드 그대로(us_overnight_study.py, 결과 56d5ef58)", "forward 창: 신호일 ≥ 2026-09-28(결과 표본 끝 2026-09-23 다음 거래일) · 반사실, 주문 없음", "매일 시가에 sign(e) 방향 선물 1계약 → 종가, 비용 왕복 1.4bp", "판정: 처음 250 거래일 1회(net > 0 ∧ t ≥ 2.0 → KEEP 후보 · net ≤ 0 → REJECT · 그 외 500일 1회 연장)"]
reason: >-
  신호: (forward 미측정) · 경제성: (forward 미측정). 결과 연구에서 M2 는 INFORMATION(t 3.02)이었으나 2011~2017 net −0.4bp 로 ECONOMIC 미달,
  2018~ 에만 +8.3bp/일. "최근 구간의 효과가 앞으로도 이어지는가"를 **본 적 없는 날로만** 가른다. 실주문 없음.
---

# M2 갭 잔차 지속 — forward 그림자 사전등록 (2026-09-29)

> **동결(2026-09-29 사용자 GO "M2 그림자 사전등록해줘").** 이 커밋 이후 규칙·창·판정 조건을 바꾸지 않는다.

## 0. 이 문서를 쓰는 시점의 지식 (블라인드가 아니다)

- 2012-01~2026-09-23 전 표본 결과를 봤다(`us-overnight-kospi-intraday-results-2026-09.md`): 전 기간 net +4.8bp(t 2.74) · 2011~17 −0.4bp · 2018~ +8.3bp(t 3.11).
  그래서 **판정 자료는 2026-09-28 이후만** 쓴다. 과거 자료는 지표 계산(z 창 252·갭 회귀 252)에만 쓰고 관측에 섞지 않는다.

## 1. 동결한 것

| 항목 | 값 |
|---|---|
| 신호 | `e_t = g_t − ĝ_t` — g = 선물 front 시가 갭(같은 계약), ĝ = 직전 252 거래일 `g ~ U` 회귀 예측, U = 미국 4종(^SOX·^NDX·^GSPC·EWY) 밤사이 누적 z 평균(직전 252일 표준편차). 전부 `us_overnight_study.py` 함수 그대로 |
| 방향 | **+1 × sign(e_t)** — 결과 연구의 c 부호(+)로 고정. e = 0 이면 관측 없음 |
| 거래(반사실) | 시가 진입 → 종가 청산, 선물 1계약. 관측값 gross = sign(e) × (C/O − 1) (bp), net = gross − 1.4bp |
| forward 창 | **신호일 ≥ 2026-09-28**. 롤 날(시가 갭이 정의되지 않는 날)은 관측 없음 |
| 데이터 | 선물 일봉 `collect_kospi200_daily_krx.py` 증분(로컬) · 미국 4종 yfinance 는 **실행마다 새로 받는다**(`.cache/us_overnight/us_close_shadow.csv`) |
| 관측 로그 | `research/strategy-lab/reports/2026-09-us-overnight-shadow/observations.jsonl`(커밋한다) — 1행 = 1거래일: date · U · g · ĝ · e · pos · gross_bp · net_bp · us_days |

## 2. 판정 (결과 전 고정, 1회)

- **시점: 관측 250 거래일**(≈ 2027-10). 그 전엔 **기록만** 한다(중간 숫자로 판정·중단하지 않는다).
- **KEEP 후보**: 처음 250일 평균 net > 0 **그리고** t ≥ **2.0**(셀 1개).
- **REJECT**: 평균 net ≤ 0.
- **INCONCLUSIVE-EXTEND**: 그 외 → **500일까지 1회만** 연장, 처음 500일로 같은 규칙. KEEP 이 아니면 INCONCLUSIVE 로 종결.
- KEEP 후보여도 **채택이 아니다** — 모의 주문·RV20 규칙과의 결합은 🔴 별도 GO.

## 3. 검출력 — 솔직한 기대치

2018~ 일별 net 표준편차가 약 122bp 라 250일 평균의 표준오차가 약 **7.7bp**. t ≥ 2 를 넘으려면 net 이 약 **+15bp** 이상이어야 한다.
2018~ 수준(+8.3bp)이 이어져도 250일 t ≈ 1.1, 500일 t ≈ 1.5 — **KEEP 은 어렵고, 현실적 결과는 INCONCLUSIVE 또는 REJECT.**
이 그림자의 실질 가치는 **효과가 사라졌는지(REJECT)를 싸게 잡는 것**이다.

## 4. 운영

- 실행: `python research/strategy-lab/run_us_overnight_shadow.py` — 선물 증분 수집 → 미국 4종 새로 받기 → 새 거래일만 기록(같은 날짜 중복 안 함).
  미국 자료를 못 받으면 관측하지 않는다.
- 주기: **월 1회**, ETF·O2b·부분 익절 그림자와 같은 월간 점검(매월 1~5일). 첫 관측은 2026-10-01 점검에서 9월 말까지분.
