---
track: kr
factor: pre-holiday-index
date: 2026-11-24
verdict: PREREGISTERED
lane: C
criteria_version: RP-2.1
conditions: ["확인(C) forward — 2026-12-01 이후 코스닥 긴 연휴(평일 휴장 ≥2) 직전 거래일 하루 수익", "정의·검정은 탐색과 동일(holiday_index_explore.py, Welch t 단측)", "판정 = 60개월 경과 ∧ 사건 ≥ 8 뒤 한 번, 단측 p ≤ 0.05 ∧ 평균 > 기준 → 확인됨", "그 전 --forward --judge 거부"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 코스닥 연휴 직전 효과(탐색 통과·사후)를 미래 자료로 확인. 실행 `python research/strategy-lab/holiday_index_explore.py --forward [--judge]`.
---

# 코스닥 연휴 직전 forward 확인 사전등록 (2026-11-24)
동결. 중간 성과로 정의·기간을 바꾸지 않는다. 확인돼도 점수·매매·알림 반영은 🔴 별도 GO.
