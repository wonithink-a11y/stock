---
track: us-kr
factor: pre-holiday-index
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["연휴 = 다음 거래일까지 평일 휴장 ≥ 2(국내) / ≥ 1(미국)", "칸 4 = 국내 코스피·코스닥 '연휴 직전 거래일 하루 수익' · 미국 S&P500·나스닥100(1990~) '연휴 직전 3거래일 누적'", "검정 = 사건 수익 vs 같은 길이 전체 구간 수익, Welch t 단측(높다)", "BH 10% 표본별: 국내 2 + 누적 kr 447 · 미국 2 + 누적 us 102", "확인: 미국 통과 시 S&P500 1970~1989 단일 검정 / 국내는 forward(사건 연 2~4회라 60개월)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "설·추석 같은 긴 연휴 직전 거래일에 국내 지수가 오르는가(미국은 3일 연휴 직전 3일)". 놀이터(long_holiday_kr_us.py)에서 본 표본이라 post_hoc.
---

# 연휴 직전 지수 효과 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/holiday_index_explore.py`. 시기 칸(~2015 / 2016~23 / 2024 / 2025~), net(ETF 왕복 5bp) 기록. 판정 = 표본별 BH 10% ∧ 차 > 0 → '탐색 통과(사후)'.
