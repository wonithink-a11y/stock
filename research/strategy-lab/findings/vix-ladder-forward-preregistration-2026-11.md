---
track: global
factor: vix-ladder-forward
date: 2026-11-08
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["forward 기록 = vix-ladder-3x(나스닥·반도체 합성 3배)·vix-ladder-svix(SVIX 근사)·rv-ladder-kr-2x(코스닥) 규칙을 그대로, 신호일 ≥ 2026-11-02 사건", "기록 전용 매 실행 1줄 jsonl(자주 돌릴수록 좋음, 수 초)", "판정 = 닫힌 사건 ≥ 12 ∧ 12개월 경과 후 1회, 기준은 원 연구(평균 > 0 ∧ 이익 ≥ 75% ∧ 최악 ≥ −45%)", "그 전 --judge 는 코드가 거부(건수만 출력)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — 과거 표본에서 견딘 VIX·실현변동성 사다리 규칙이 앞으로의 새 사건에서도 같은 기준을 통과하는가. 현재 11-02 에 시작한 사건이 진행 중이다.
---

# VIX·실현변동성 사다리 forward 기록 — 사전등록 (2026-11-08)

규칙·문턱은 `vix-ladder-3x`·`vix-ladder-svix`·`rv-ladder-kr-2x` 사전등록과 같다(바꾸지 않는다). 사건 시작 ≥ 2026-11-02 만 forward 로 센다(그 이전은 연구 표본).
실행 `python research/strategy-lab/run_vix_ladder_forward.py` — Yahoo 공개 자료(수 초), 매 실행 한 줄을 `reports/2026-11-vix-ladder-forward/observations.jsonl` 에 추가(같은 기준일은 덮어쓴다).
`--judge` 는 닫힌 사건 12건 ∧ 첫 사건 2026-11-02 로부터 12개월(2027-11-02) 전에는 거부한다. 판정: 시장·규칙별 닫힌 사건에 원 연구 기준 적용, 모두 충족 → CONFIRMED, 일부 → INCONCLUSIVE, 아니면 REJECT.
동결: 이 커밋 뒤 문턱·창·셀·비용을 바꾸지 않는다.
