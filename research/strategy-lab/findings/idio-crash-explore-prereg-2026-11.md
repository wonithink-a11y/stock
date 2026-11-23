---
track: us-kr
factor: idiosyncratic-crash
date: 2026-11-24
verdict: PREREGISTERED
lane: E
criteria_version: RP-2.1
post_hoc: true
conditions: ["사건 = 유니버스 종목 종가가 직전 10거래일 최고 대비 −30% 이하(종목별 63일 간격) ∧ 같은 10일 시장 지수(^GSPC/^KS11) 낙폭 > −5%", "유니버스 = 미국 S&P500 PIT(2015~2026-09) · 국내 KRX 폐지 포함 20일 거래대금 상위 500(2016-02~)", "결과 = 사건일 종가 → 63거래일 종목 수익 − 유니버스 등가중 수익", "검정 = 월별 군집 t(같은 달 사건 평균을 한 점으로) — 방향 사전 고정: 미국 > 0(반등), 국내 < 0(지속 하락), 단측", "BH 10% 표본별: 미국 1 + 누적 us 120 · 국내 1 + 누적 kr 461", "21일은 기록 전용"]
reason: >-
  신호: (미측정) · 경제성: (미측정). RP-1.0 에서 '사후 분류라 규칙화 불가'로 WATCH(11-23)였던 '이벤트성 악재 급락 매수'를 기계적 대용으로 연다. 놀이터(idio_crash_us_kr.py)에서
  방향을 보고 정했으므로 post_hoc — 확인(C)을 독립 구간으로 바로 등록한다(idio-crash-confirm-prereg-2026-11).
---

# 종목 고유 급락 뒤 63일 — E 탐색 사전등록 (2026-11-24)
동결. 코드 `research/strategy-lab/idio_crash.py`. 기록 전용: 사건 단위 t·평균·중앙값·양수 비율, 시기 칸, 반도체 제외(국내).
