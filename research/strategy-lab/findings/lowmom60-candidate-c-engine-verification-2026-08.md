---
track: kr
factor: lowmom60-candidate-c
date: 2026-08-24
verdict: HOLD
criteria_version: backfill-v1
conditions: ["lowmom60","absolute_liquidity_filter","continuousHoldOnRenewal"]
reason: "실제 엔진에서 사전점검 대비 낙폭 큼(+13.9%→+5.09% CAGR, MDD -27.77%) - 버그 신호 없으나 채택할 만큼 강하진 않아 연구 후보(production 미확정)"
cagr: 5.09
mdd: -27.77
sharpe: 0.77
win_rate: 46.9
n: 2437
---

# LOWMOM60 Candidate C — 실제 엔진 검증 (2026-08-24)

## 배경

CLAUDE.md "다음" 트랙: "LOWMOM60+기관수급(ChatGPT A/B/C)은 겹침판정·연속보유
수정이 이제 적용 가능해졌으나 아직 미착수." 재개 전에 코드를 직접 확인한
결과, 실제로 검증까지 끝난 건 **후보 C(저모멘텀+절대유동성필터)**뿐이었다
— 후보 A/B(저모멘텀+실제 A4 기관/외국인 20D 순매수 결합)는 필터/순위 결합
방식이 이 프로젝트 어디에도 구체적으로 정의된 적이 없다(원 ChatGPT 제안
원문 미보존). 사용자 확인 후 C만 구현.

## 만든 것

`strategies/lowmom60_v1/`(policy.json·build_selection.py·rule.py) —
`pbr_value_v1`과 완전히 같은 패턴(오프라인 selection.json + engine 무변경).
`lowmom60_institutional_eligible_precheck_v2_absolute.py`(decile IC t=5.24,
top30 CAGR +13.90%)가 검증한 설계를 그대로 재구현 — 새 로직 발명 없음.
PBR이 겪은 고정 21일 근사 문제(홀딩 세션 오차로 CAGR 손실)를 처음부터
정확 계산(`build_selection.py`의 `hold_sessions_by_date`)으로 피했고,
`scheduling.continuousHoldOnRenewal: true`도 처음부터 켰다.

## 실제 엔진 결과 (2016-01~2026-08, A1A_ONLY, 전체 유니버스)

```
                    사전점검(오프라인 근사)   실제 엔진
CAGR                +13.90%                 +5.09%
MDD                 —                       -27.77%
Sharpe              —                       0.77
거래 수              —                       2,437건 (승률 46.9%)
```

## 판정

**사전점검 대비 낙폭이 크다**(13.90%→5.09%, 약 37% 잔존) — PBR도 같은
구조(precheck +7.06% → 실제 엔진 CAGR ~2.95~4.89%, 어느 시점 fix 상태
기준이냐에 따라 다름)를 이미 겪었다. 정확한 holdSessions 계산·연속보유
병합을 처음부터 적용했는데도 낙폭이 남는다는 건, 이 낙폭이 그 두 가지
(PBR이 처음 겪었던 문제들) 때문이 아니라 **실제 포트폴리오 회계 자체**
(공유 현금·정수 주식수·같은날 현금 재사용 금지·슬롯 경쟁)가 구조적으로
오프라인 EW 근사보다 불리하다는 뜻으로 보인다 — 버그 신호는 없다(회귀
전체 138건 통과, unit test로 selection.json 계약 자체도 확인됨).

CAGR은 양(+)이고 Sharpe 0.77도 나쁘지 않지만, MDD -27.77%가 상당히 깊다.
**"채택할 만큼 강하다"고 보긴 이르다** — PBR과 마찬가지로 "연구 가치 있는
후보, production alpha 미확정"으로 분류한다. 다음에 필요한 건 새 스윕이
아니라(이미 여러 팩터에서 반복된 패턴) 이 결과를 갖고 무엇을 할지 판단
— 예: TREND-BREAKOUT-v1·5DC-v1A-P와 상관/타이밍 독립성 확인, 또는
여기서 멈추고 다른 트랙으로 이동.

## 코드 위치 (로컬 미커밋 — PBR과 동일 관례)

`research/strategy-lab/strategies/lowmom60_v1/`(policy.json·
build_selection.py·rule.py·selection.json) ·
`research/strategy-lab/run_lowmom60_v1.py` ·
`research/strategy-lab/tests/test_lowmom60_v1.py`(4건, 전체 회귀에 포함돼
138건 전부 통과 확인됨) ·
`research/strategy-lab/reports/2026-08-24-lowmom60-v1-smoke/run.json`(실행
산출물).

이 findings 문서만 committed — 코드는 PBR과 같은 이유로 로컬에 남긴다
(재현성 사슬 완성 전까지는 "연구 후보"이지 "production 승격"이 아니다).
