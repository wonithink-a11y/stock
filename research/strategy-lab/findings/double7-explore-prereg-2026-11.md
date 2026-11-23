---
track: us-kr
factor: double7-mean-reversion
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["Double 7(Connors): 종가 > 200일 SMA ∧ 종가 ≤ 7일 최저 종가 → 그 종가 매수, 종가 ≥ 7일 최고 종가인 날 종가 매도(겹침 없음)", "지수 = S&P500·나스닥100·러셀2000(1990~) · 코스피·코스닥(전 기간)", "검정 = 거래 수익 평균 − 같은 평균 보유일 아무 때 수익 평균, t 단측(높다)", "BH 10% 표본별: 미국 3 + 누적 us 145 · 국내 2 + 누적 kr 489, 거래 ≥ 5", "확인(C): 미국 칸 통과 시 S&P500 1970~1989 단일 검정(단측 p ≤ 0.05)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 출처 = backtestedstrategies.com Connors Double 7(밤샘 수집 #29). 놀이터(blog_rules_index.py)에서 본 뒤라 post_hoc.
  RSI2 지수(확인 REJECT)와 같은 단기 반등 계열 — 다른 진입·청산 정의.
---
# Double 7 지수 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/double7_explore.py`. 기록: 승률·노출·연 net(왕복 5bp)·보유 대비.
