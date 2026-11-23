---
track: kr
factor: turn-of-month-index
date: 2026-11-24
verdict: PREREGISTERED
lane: C
criteria_version: RP-2.1
conditions: ["확인(C) forward — 2026-12-01 이후 코스피·코스닥 일수익만", "TOM 정의·검정은 탐색과 동일(tom_index_explore.py, Welch t 단측)", "판정 시점 = 36개월 경과 후 한 번, 지수별 단측 p ≤ 0.05 ∧ 차 > 0 → 확인됨", "그 전 --forward --judge 는 거부(개월 수만 출력)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 국내 TOM 탐색 통과(사후, tom-index-explore-results-2026-11)를 겹치지 않는 미래 자료로 확인한다. 실행 `python research/strategy-lab/tom_index_explore.py --forward [--judge]`.
---

# 국내 TOM forward 확인 사전등록 (2026-11-24)
동결. 중간 성과를 보고 정의·창·기간을 바꾸지 않는다. 36개월 전 판정 금지(코드가 거부). 확인돼도 점수·매매·알림 반영은 🔴 별도 GO.
