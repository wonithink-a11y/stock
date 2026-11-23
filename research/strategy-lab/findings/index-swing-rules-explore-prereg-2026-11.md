---
track: us-kr
factor: index-swing-rules
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["규칙 A Connors 3일 고저: 종가 > 200일 SMA ∧ 종가 < 5일 SMA ∧ 3일 연속 고가·저가 모두 하락 → 종가 매수, 종가 > 5일 SMA 인 날 종가 매도", "규칙 B 이평 타이밍(ictword 글): 종가가 20일 SMA 아래→위 돌파 → 종가 매수, 종가 < 10일 SMA 인 날 종가 매도", "지수 = S&P500·나스닥100·러셀2000(1990~) · 코스피·코스닥(야후 전 기간), 규칙 2 × 지수 5 = 10칸(놀이터에서 본 칸 전부)", "검정 = 거래 수익 vs 같은 평균 보유일 아무 때 수익, Welch t 단측(높다)", "BH 10% 표본별: 미국 6 + 누적 us 156 · 국내 4 + 누적 kr 496, 거래 ≥ 5", "확인(C): 미국 칸 통과 시 S&P500 1970~1989 단일 검정(단측 p ≤ 0.05) — 이 구간은 RSI2·Double 7 확인에 이어 세 번째 사용 · 국내 칸 통과 시 forward 36개월 ∧ 거래 25건"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 출처 = therobusttrader(3일 고저, 밤샘 수집 #30) · ictword.tistory(코스피200 20일선 매수·10일선 매도, #17). 놀이터(research/sandbox/blog_rules_index2.py)에서 본 뒤라 post_hoc.
  A 는 RSI2·Double 7(둘 다 1970~89 확인 REJECT)과 같은 단기 반등 계열이라 기대는 REJECT.
---
# 지수 스윙 규칙 2종 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/index_swing_explore.py`. 기록: 승률·노출·연 net(왕복 5bp)·보유 대비, 시기 칸(~2015 / 2016~23 / 2024 / 2025~).
국내 forward 는 통과 칸이 있을 때 별도 사전등록 파일로 연다(판정 시점 = 36개월 ∧ 거래 25건, 코드가 그 전 --judge 거부).
이 커밋 뒤 규칙·창·지수·비용을 바꾸지 않는다.
