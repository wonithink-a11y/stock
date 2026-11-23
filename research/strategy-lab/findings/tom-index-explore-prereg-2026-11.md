---
track: us-kr
factor: turn-of-month-index
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["TOM = 그달 마지막 거래일 + 다음 달 첫 3거래일(4일), 지수 일수익", "칸 5 = 코스피·코스닥(야후 전 기간) · S&P500·나스닥100·러셀2000(1990~)", "검정 = TOM 일평균 − 나머지 일평균, Welch t 단측(높다)", "BH 10% 표본별: 국내 2 + 누적 kr 437 · 미국 3 + 누적 us 91", "확인(결과 전 고정): 미국 칸 통과 시 S&P500 1970~1989 단일 검정, 국내는 forward 로만"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "월말·월초 4거래일 지수 수익이 나머지 날보다 높은가(미국·국내)". 놀이터(turn_of_month_us_kr.py)에서 본 표본이라 post_hoc.
  기존 월말 연구(달러·국채·크립토)는 다른 자산. 경제성 기록: TOM 4일만 보유하는 ETF 전략의 월 net(왕복 5bp).
---

# 월말·월초(TOM) 지수 효과 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/tom_index_explore.py`(다음 커밋). 시기 칸(~2015 / 2016~23 / 2024 / 2025~)과 TOM 4일 묶음 평균·양수 비율을 기록. 판정 = 표본별 BH 10% ∧ 차 > 0 → '탐색 통과(사후)'.
