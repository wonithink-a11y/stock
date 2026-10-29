---
track: crypto
factor: coinbase-premium
date: 2026-10-29
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["코인베이스 BTC-USD 1시간 봉(api.exchange.coinbase.com 공개 candles) ÷ 바이낸스 현물 BTCUSDT 1시간 봉(data.binance.vision) − 1 = 프리미엄", "z = (P − 직전 720시간 평균) / 직전 720시간 표준편차(현재 제외, 유효 360 이상), |z| ≥ 2 에서 z 방향으로 진입", "C4 4시간 · C24 24시간 보유, 보유 중 새 진입 없음, 사건 = 한 관측", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "수익 = 바이낸스 현물 BTCUSDT open→open, 비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "코인베이스 가격이 바이낸스보다 평소보다 크게 높을(낮을) 때 — 미국 수요의 흔적 — BTC 가 다음 4·24시간 그 방향으로 가는가".
  사용자 요청(2026-10-29) 후보 6개 중 2번, 사용자 GO.
---

# 코인베이스 프리미엄 → BTC 4·24시간 — 사전등록 (2026-10-29)

> **동결.** 이 커밋 이후 정의·창·문턱·구간·비용·셀을 바꾸지 않는다. 결과는 `coinbase-premium-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/coinbase_premium.py`(다음 커밋, 해시는 결과 파일 머리말에 적는다).

## 0. 선행 지식 (결과 아닌 것만)

- 외부: 코인베이스 프리미엄은 지표 설명만 있다(BGeometrics·TradingView — 양 = 미국·기관 매수, 음 = 미국 매도). **수익을 잰 백테스트를 찾지 못했다.**
  원값이 시끄러워 평활해서 본다는 설명이 있다 → 여기서는 직전 30일 대비 z 로 정규화한다.
- 이 저장소: 코인베이스 0건. 가까운 것 — 김치 프리미엄 → BTC 30일 NONE(구간 부호 갈림), 바이낸스↔업비트 일봉 선후행 FAIL,
  크립토 24시간 충격 → 12시간 지속 C7(t 1.75, 세 구간 양이나 바닥선 미달). 프리미엄은 **미국 장중 급등의 부산물**일 수 있다 — 그러면 C7 의 그림자다(§5 기록 2).
- 정의상 프리미엄에는 **USDT/USD 괴리**가 섞인다(공개 지표들도 BTC-USD vs BTCUSDT 로 잰다). 보정본은 기록 전용(§5 기록 1).
- **현실적 기대: REJECT.** 거래소 간 차익이 빠르게 메우는 값이고, 공개 지표라 남아 있으면 이상하다.

## 1. 데이터

- 코인베이스: `GET https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=3600` (키 없음, 300개씩), 2018-01-01 ~ 2026-10-01 UTC.
  행 = [시작시각, low, high, open, close, volume]. 거래가 없던 시간은 행이 없다(채우지 않는다).
- 바이낸스: `data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/` 월 파일, 같은 기간.
- 기록 전용 보정: 코인베이스 USDT-USD 1시간 봉(상장 이후만).
- 저장: `research/strategy-lab/data/crypto/cbprem/`(gitignore). 응답 봉의 시각이 요청 구간 안인지 확인하고, 중복·구간 밖은 진단 파일에 센다.

## 2. 정의

- T = 정각(UTC). P(T) = CB_close[T−1h 봉] / BN_close[T−1h 봉] − 1 (둘 다 T 에 끝나는 봉). 하나라도 없으면 P(T) 없음.
- μ, σ = P 의 [T−720h, T−1h] 평균·표준편차(유효 360 이상). z(T) = (P(T) − μ) / σ.
- 진입 T: |z(T)| ≥ 2, 방향 d = sign(z). 수익 = d × (BN_open[T + h] / BN_open[T] − 1) (bp).
  BN_open[T] 는 T 에 시작하는 봉의 시가 — 신호가 쓰는 종가와 같은 순간이다(1시간 늦춘 진입은 기록 2).
- 보유 h 동안은 새 진입을 받지 않는다(셀마다 따로). 진입·청산 가격이 없으면 그 사건을 뺀다.

## 3. 셀

| 셀 | 보유 h | 통계량 |
|---|---|---|
| C4 | 4시간 | 사건별 d × 수익 bp |
| C24 | 24시간 | 사건별 d × 수익 bp |

가설 방향은 양(+) — 프리미엄 방향으로 간다. 판정은 TRAIN 부호를 따른다(TRAIN 음이면 되돌림 방향이 검정 대상, 무기한으로 숏 가능).

## 4. 판정 (crypto-weekend-reversal §3 과 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261029), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호.
- ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) 평균 > 0. ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 관측 수 · gross 평균 · OOS 부트스트랩 95% 구간 · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 롱/숏 갈래.

## 5. 기록 전용 (판정 불사용)

1. USDT 보정 프리미엄 P' = CB_BTC-USD / (BN_BTCUSDT × CB_USDT-USD) − 1 로 같은 두 셀(보정 가능한 기간만).
2. 1시간 늦춘 진입(BN_open[T+1h] → BN_open[T+1h+h]) 두 셀 · z 와 직전 4·24시간 BTC 수익의 상관(C7 그림자 점검).
3. 1시간 보유 셀(비용 대비 참고).
4. 롱만(z ≥ 2, 업비트 현물로 할 수 있는 갈래) · 숏만 갈래 따로.
5. 원값 P 의 분포(분위수)·연도별 평균, 진입 사건 수 연도별.

## 6. 하지 않는 것

z 창(720h)·문턱(2)·보유(4·24h) 변경, 평활 방식 추가, 다른 코인 추가, 결과 뒤 셀 추가, 비용 변경, 기간 재절단.
되돌림 방향 결과가 나와도 판정은 §4 그대로이며, 새 용도는 새 사전등록으로만.
