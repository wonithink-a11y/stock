---
track: us
factor: true-bottom-aapl-breadth
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["true-bottom-explore-prereg-2026-11 과 같은 4칸·같은 결과·같은 대조(시드 20261124)", "바뀐 것 하나: 칸당 최소 사건 10 → 5 (RP-2.1)", "BH 10%, 가족 = 시험 칸 + 누적 us 41(1차 시도 4칸 포함)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). **사후 재실행** — 1차(true-bottom-explore-results-2026-11, INCONCLUSIVE)에서 n 5~9 칸의 결과를 본 뒤 사용자 지시로 최소 사건을 5로 낮춰 같은 격자를 다시 돌린다.
  통과해도 '탐색 통과(사후)'이며, 확인은 독립 표본(2016 이전 자료 또는 forward)으로만 한다.
---

# 진바닥 조건 — E 탐색 재실행(사후, RP-2.1) 사전등록 (2026-11-24)

> **사후 표시.** 결과를 이미 본 칸들이다. 이 재실행이 주는 정보는 "기준 5건이면 보정 뒤에도 남는가"뿐이고, 1차의 결과 지식이 섞여 있다.

1. 질문·자료·격자·결과·대조: 1차 사전등록(f4b5c5df)과 동일. 코드 `true_bottom_explore.py --min-events 5 --prior 41`(인자만 추가, 계산 동일).
2. 판정: 사건 ≥ 5 인 칸 전부를 시험으로 센다. BH 10%(가족 = 시험 칸 + 누적 41) ∧ 평균 > 무작위 → '탐색 통과(사후)'. 5~9건 칸은 '소표본'.
3. 동결: 이 커밋 뒤 바꾸지 않는다. 더 바꾸면 또 새 시도(누적 K 증가).
