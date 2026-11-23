---
track: us
factor: rsi2-index-short-reversal
date: 2026-11-24
verdict: PREREGISTERED
lane: C
criteria_version: RP-2.1
conditions: ["확인 표본 = S&P500(^GSPC 종가) 1970-01-01~1989-12-31 진입 — 탐색(1990~)·놀이터 어디서도 안 쓴 구간", "주 규칙 R1 = RSI(2)<10 ∧ 종가>200일 SMA, 5일 보유·겹침 제거(rsi2_index_explore.py --confirm R1, 코드 69587bc7)", "단측 p ≤ 0.05 ∧ 평균 > 무작위 ∧ n ≥ 5 → 확인됨", "R2(추세 무관)는 기록 전용"]
reason: >-
  신호: (미측정) · 경제성: (미측정). RP-2.1 확인(C) — 탐색(rsi2-index-explore, 사후)에서 S&P500 R1·R2 통과. 주 규칙 R1 하나만 독립 구간 1970~1989 에서 한 번 시험.
---

# RSI2 S&P500 확인(C) 사전등록 (2026-11-24)

동결. 실행: `python research/strategy-lab/rsi2_index_explore.py --confirm R1` (기록 전용으로 `--confirm R2` 도 돌린다).
확인돼도 점수·매매·알림 반영은 🔴 별도 GO. 경제성(ETF 5bp)은 기록하되 판정은 신호로만.
