---
track: kr
factor: replication-s5-crypto-upshock
date: 2026-09-20
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["R-S5: phase2 S5 정의 그대로, 연구 창 이후 분봉 2026-08-27~09-18(17일, .cache/fwd_oos 격자)", "R-CUP: 크립토 일봉 2015-01~2019-12-15(yfinance 15종, 이후 폐물 코인 포함), 충격 후 1일 지속"]
reason: >-
  결과를 보고 생긴 두 가설을 안 본 표본에서만 판정한다. S5(급등 소진 → 30분 되돌림 50~78bp)는 롱 전용 계좌에서도
  '보유 종목 급등 시 매도 후 재매수'로 쓸 수 있는 유일한 형태라 재현이 중요하다. 크립토 단기 10셀에서 상승 충격 뒤
  지속(C2·C4·C7, 바닥선 미달)이 반복돼, 1시간 데이터가 없던 2015~2019 일봉에서 방향을 확인한다.
---

# 재현 사전등록 (2026-09-20)

## R-S5
- phase2 `s_events` 의 S5 정의·유니버스(liq_base ≥ 20억)·진입(c[j+1])·청산(+6봉)·초과수익 계산을 **코드 그대로** 쓰고,
  날짜만 2026-08-27 이후로 거른다. 일자 평균이 관측.
- REPLICATED: 되돌림 방향 초과수익 평균 > 0 AND t ≥ 2. PARTIAL: 평균 > 0, t < 2. 아니면 NOT REPLICATED.
- 보조(보유자 관점): 되돌림 gross − 30bp(매도 후 재매수 왕복) 평균.

## R-CUP
- 코인별 일간 r = close/전일 close − 1, σ = 직전 30일 r 표준편차(현재 제외, min 20).
  UP: r > 2σ → t 종가 롱, t+1 종가 청산. DN: r < −2σ → 숏(지속 방향). 코인별 비중첩(1일 보유라 자연히).
- 같은 날 이벤트는 평균해 한 관측. 비용 10bp 는 보조 표기.
- UP 이 핵심: REPLICATED = UP 평균 > 0 AND t ≥ 2. PARTIAL = 평균 > 0. 아니면 NOT REPLICATED. DN 은 보조.
