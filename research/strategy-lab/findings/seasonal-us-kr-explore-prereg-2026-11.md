---
track: us-kr
factor: seasonal-index
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: false
conditions: ["H1 Sell in May = 11~4월 월수익 평균 − 5~10월 월수익 평균(지수 가격, 월말 종가), Welch t 단측(11~4월 높다)", "H2 연말 = 추수감사절(11월 넷째 목) 다음 거래일 시가 대용 = 추수감사절 전 거래일 종가 → 1월 둘째 거래일 종가, 해마다 1건 vs 같은 해 같은 길이 다른 구간 평균(그해 나머지 날을 같은 길이로 자른 블록들)", "지수 = S&P500·나스닥100·러셀2000(1990~) · 코스피·코스닥(야후 전 기간) → 2가설×5 = 10칸", "BH 10% 표본별: 미국 6 + 누적 us 110 · 국내 4 + 누적 kr 453, 칸당 사건 ≥ 5", "확인(C) 결과 전 고정: 미국 칸이 통과한 가설만 S&P500 1970~1989 단일 검정(둘 다면 각 0.025)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). RP-1.0 에서 막혔던 두 계절성(장부 11-17 Sell in May SKIP 문1 · 11-22 연말 강세 WATCH 문5)을 RP-2.1 탐색으로 연다.
  Sell in May 는 놀이터에서 본 적 없음(post_hoc 아님). 연말은 놀이터의 '산타 12/22~ 7일'과 창이 겹쳐 부분적으로 본 셈이라 결과 문서에 적는다.
---

# 계절성 두 가지(Sell in May · 연말 강세) 미국·국내 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/seasonal_explore.py`. 기록 전용: 시기 칸, 경제성(H1 = 11~4월만 보유 ETF 연 2회 왕복 5bp, H2 = 연 1회 5bp).
국내 H1 은 etf-timing-family(KODEX 200, HAL REJECT)와 겹친다 — 지수판·긴 표본이라는 점만 다르다.
