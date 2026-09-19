---
track: kr
factor: followup-overnight-futures-crypto-hour
date: 2026-09-20
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["H-FON: KOSPI200 선물 front 밤사이(종가→익일 시가, 같은 계약) 2010-2015 미사용 구간 재현", "H-CH: 크립토 28종 EW UTC 시각별 1시간 수익, TRAIN 2020-2022 에서 |t|>=3 시각 선택 → VALID 2023 / TEST 2024-2026-08"]
reason: >-
  (1) short-horizon-phase3 보조표에서 2016~ 선물 밤사이 평균 +7.3bp·장중 −0.1bp 를 봤다(결과를 본 뒤 생긴 가설).
  2010~2015 는 아직 이 관점으로 안 봤으므로 거기서만 판정한다. (2) 크립토 단기 10셀 전부 REJECT 뒤, ChatGPT 목록 밖의
  저비용 후보인 시각 계절성을 TRAIN 선택 → OOS 검증 구조로 잰다.
---

# 후속 사전등록 (2026-09-20)

## H-FON — 선물 밤사이 보유 (2010-01-04 ~ 2015-12-31 만)
- overnight = open(t+1)/close(t)−1(같은 계약, 롤 제외), intraday = close/open−1. 비용 왕복 2.5bp(26,000원 ÷ 약 250pt×25만).
  2010~2015 지수가 200~290pt 라 비용은 **그날 가격으로** 계산한다.
- REPLICATED: overnight − 비용 평균 > 0 이고 t ≥ 2, **그리고** overnight 평균 > intraday 평균.
  PARTIAL: 앞 조건 중 하나. 아니면 NOT REPLICATED.
- 보조: 밤사이만 보유 vs 매수후보유 연율 수익·변동성·Sharpe(2010~2015, 2016~ 각각).

## H-CH — 크립토 UTC 시각 효과
- 코인별 1시간 수익 r_h = p[T+1h]/p[T]−1(mark_open), 시각 T 의 28종 EW 평균 → 시각(0~23)별 일자 관측.
- TRAIN(2020~2022)에서 |t| ≥ 3 인 시각만 선택(양이면 롱, 음이면 숏). 없으면 NO SIGNAL.
- 선택 시각 각각: VALID·TEST 부호 유지 AND OOS net(10bp) > 0 → ECONOMIC-보통, net(3bp) > 0 → ECONOMIC-무료이벤트,
  부호만 유지 → INFORMATION, 아니면 REJECT. (24시각 탐색의 대가는 |t|≥3 선택 문턱으로 치른다 — 24개 중 우연 |t|≥3 기대 ≈0.06개.)
- 하지 않는 것: 문턱·구간 변경, 결과 후 수정.
