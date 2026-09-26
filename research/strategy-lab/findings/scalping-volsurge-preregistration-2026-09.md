---
track: crypto
factor: scalping-volsurge
date: 2026-09-27
verdict: PREREGISTERED
criteria_version: research-only (결과 전 등록 — 코드 futures/scalping_volsurge.py 와 같은 커밋)
depends_on: findings/scalping-candidates-preregistration-2026-09.md
conditions: ["바이낸스 현물 1분봉 BTCUSDT(TRAIN 2018~2021 · OOS 2022-01~) · ETHUSDT(2018-01~)", "12셀 = 급증 배수 2 x 보유 3 x 봉 방향 2", "바닥선 = 신호 순환 이동 200회 최대 |t| 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  스캘핑 후보 ③(거래량 급증 모멘텀)을 크립토 1분봉 규칙으로 처음 잰다. 국내는 3B(고유동성 엣지 0)로 닫혔고,
  크립토에서는 워뇨띠 탐색의 ML 특징(5분 격자)·R2(15분 역추세+거래량 2배, 검증 −0.7bp)로만 들어갔다 — '급증 분의 방향을 따라간다'는
  단일 규칙은 없다. 1차(VWAP 밴드) 결과를 본 뒤 쓰지만 이 가설의 수치는 모른다. EMA 5분 스캘핑은 EMA 9/21 교차 FAIL
  (github-strategy-reproduction)·단일 지표 폐기 원칙으로 열지 않는다.
---

# 크립토 1분봉 거래량 급증 모멘텀 — 사전등록 (2026-09-27)

## 1. 사건

```
급증 배수   ratio_t = 분 거래량 / 직전 60분 거래량 중앙값(현재 분 제외).  ratio_t > m,  m ∈ {5, 10}
방향        U = 급증 분이 양봉(종가 > 시가) → 롱 · D = 음봉 → 숏
체결·청산   다음 분 시가 체결, h ∈ {5, 15, 60} 분 뒤 시가 청산. 같은 셀 안 비중첩
```

2 × 3 × 2 = **12셀**. 통계량 = 셀 방향 수익의 t. 양 = 모멘텀, 음 = 반전(TRAIN 부호가 정한다).

## 2. 절차·판정

`scalping-candidates-preregistration-2026-09.md` §1 V 와 **같다** — TRAIN(BTC 2018~21) |t| 최대 셀 하나 → 순환 이동 바닥선 200회 →
선택 셀만 BTC OOS(2022-01~)·ETH(2018-01~) 한 번씩, 이동 대조 대비 초과. INFORMATION / ECONOMIC / ROBUST / REJECT 조건도 같다.
비용 왕복 10bp(바이낸스 테이커·업비트 현물 편도 5bp) · 스트레스 20bp. D(숏)는 무기한 선물 전제.

## 3. 한계·하지 않는 것

- 1분 거래량 급증은 대개 큰 봉과 같이 온다 — 다음 분 시가 체결은 이미 움직인 뒤다(보수적).
- 배수·기준 창·보유·비용의 사후 변경, 셀 추가, 다른 코인으로 표본 늘리기, 테이커 매수비율을 결과 뒤에 덧붙이기 — 안 한다.
- REJECT 면 크립토 분봉 거래량 급증 계열을 5분·15분봉으로 다시 시험하지 않는다.

재현: `python research/strategy-lab/futures/scalping_volsurge.py`(`--selftest` 4/4). 결과 → `scalping-volsurge-results-2026-09.{md,json}`.
