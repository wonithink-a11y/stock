---
track: kr
factor: kr-overnight-holding
date: 2026-09-20
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["A2a 2016-01~2026-08, liq(직전20일 평균 거래대금) >= 20억", "종가 단일가 매수 → 익일 시가 단일가 매도, 매일", "3셀: rv20 상위 20% / ret20 상위 20% / 둘 다", "TRAIN 2016-2020 / VALID 2021-2022 / TEST 2023-", "왕복 30bp, 스트레스 40bp", "일자 부호반전 바닥선 500회"]
reason: >-
  short-horizon-phase3 추가 분해에서 장중(시가→종가) 하락 편향이 고변동(rv20 Q5 −36bp)·최근 급등(ret20 Q5 −35bp)
  종목에 몰린다는 것을 봤다. 장중 편향의 짝인 밤사이(종가→익일 시가) 수익률은 이 분위들에서 아직 보지 않았다.
  그 밤사이 수익이 왕복 비용을 넘는지 — "밤에만 보유" 전략의 성립 여부 — 를 결과 전에 고정한다.
---

# KR 밤사이 보유 — 사전등록 (2026-09-20)

- 정의(phase3 P3-X 와 동일): overnight = open(t+1)/close(t) − 1(연속 거래일, |r|>30% 제외).
  rv20 = 직전 20일 일간수익률 표준편차(t 미포함), ret20 = close(t−1)/close(t−21) − 1. **분위는 t 의 종가 전 정보만.**
  (실거래에서는 t 종가 단일가 주문 시점에 t 의 종가를 모르므로, t 당일 수익을 쓰지 않는 이 정의가 PIT 다.)
- 셀: N1 = rv20 상위 20% EW / N2 = ret20 상위 20% EW / N3 = 두 조건 동시 EW. 매일 전량 교체.
- 일자별 EW 평균이 관측 단위. 비용 차감 = 평균 − 30bp(스트레스 40bp).
- 판정(1·2차와 같은 골격): INFORMATION = TRAIN |t| ≥ 바닥선 & VALID·TEST 같은 부호.
  ECONOMIC = 그리고 VALID+TEST net(30bp·40bp) > 0. ROBUST = 그리고 VALID+TEST net(30bp) t ≥ 2.
- 보조: 연도별 net, 유동성 ≥200억 한정 결과(판정 없음).
- 하지 않는 것: 분위 경계·보유기간·필터 변경, 결과 후 셀 추가.
