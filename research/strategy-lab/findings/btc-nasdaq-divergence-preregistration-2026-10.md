---
track: crypto
factor: btc-nasdaq-divergence
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["나스닥100(^NDX, Yahoo 일봉 종가 = 뉴욕 16:00) · BTC = 같은 순간(뉴욕 16:00 → UTC, 서머타임 자동) 바이낸스 BTCUSDT 1시간 봉 시가", "거래일 t 의 잔차 e = BTC 5거래일 수익 − β × NDX 5거래일 수익, β = 직전 120거래일 일수익 회귀(현재 창 제외)", "z = e / 직전 250거래일 e 의 표준편차(현재 제외, 유효 150), |z| ≥ 2 → s = −sign(z)(뒤처진 BTC 가 따라잡는다)", "N5 5거래일 · N1 1거래일 보유(BTC 단독, 뉴욕 16:00 → 16:00), 보유 중 새 사건 무시", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%, 비용 10bp · 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "비트코인이 지난 한 주 나스닥이 설명하는 만큼보다 크게 뒤처지거나(앞서거나) 했을 때, 다음 1·5거래일 그 괴리를 되돌리는가".
  사용자 위임(2026-10-30 밤) 새 후보 — 크립토와 미국 주식의 관계를 쓰는 첫 연구.
---

# BTC–나스닥 괴리 되돌림 → BTC 1·5거래일 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·문턱·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `btc-nasdaq-divergence-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/btc_nasdaq_divergence.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- 2020 이후 BTC 와 나스닥의 상관이 커졌다는 보고가 많다(IMF 2022 등). 상관이 크면 단기 괴리가 되돌려질 수도, 크립토 고유 뉴스라 지속될 수도 있다 — TRAIN 부호가 정한다.
- 이 저장소: 크립토 연구는 전부 크립토 내부 변수였다. 미국 주식을 쓰는 것은 처음. 같은 계열 국내 연구: 밤사이 SOX → 한국 반도체 시초가 REJECT.
- 2018~2019 는 상관이 낮아 β 가 0 근처였을 것 — 그때 잔차는 사실상 BTC 5일 수익(단기 되돌림 검정)이 된다. 이 점을 결과 해석에 반영한다.
- 미국 휴장일은 거래일이 아니므로 그날은 신호·청산 시각이 아니다. BTC 는 그 사이에도 움직인다(5거래일 = 달력 7일 안팎).
- **현실적 기대: REJECT.**

## 1. 데이터

- `GET https://query1.finance.yahoo.com/v8/finance/chart/^NDX?period1=…&period2=…&interval=1d` → 거래일·종가. 저장 `data/crypto/xasset/ndx.json`(gitignore).
- BTC: `data/crypto/cbprem/bn_btc.parquet` 1시간 봉 open. 거래일 t 의 BTC 가격 = 그날 뉴욕 16:00 에 해당하는 UTC 정각 봉의 시가.

## 2. 정의

- 거래일 t 일수익 a_t(BTC), n_t(NDX) = 직전 거래일 대비. 5일 수익 A_t = Π(1+a) − 1(t−4..t), N_t 동일.
- β_t = cov(a, n)/var(n), 표본 = t−124..t−5 (120거래일, 현재 5일 창 제외, 유효 100).
- e_t = A_t − β_t × N_t. σ_t = e 의 t−254..t−5 표준편차(유효 150). z_t = e_t / σ_t.
- |z_t| ≥ 2 → s = −sign(z_t). 진입 = t 의 BTC 가격(뉴욕 16:00), 관측 = s × (BTC(t+h) / BTC(t) − 1) bp, h = 5(N5) · 1(N1) 거래일. 사건일 t 로 색인·구간. 보유 중 그 셀 새 사건 무시.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261111), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0. ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 관측 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · BTC 뒤처짐(롱)/앞섬(숏) 갈래.

## 4. 기록 전용 (판정 불사용)

1. β 연도별 평균, BTC–NDX 일수익 상관 연도별.
2. β 를 0 으로 둔 같은 셀(순수 BTC 5일 되돌림) — 나스닥이 더하는 것이 있는가.
3. 업비트로 할 수 있는 롱 갈래만의 N5.

## 5. 하지 않는 것

창(5·120·250)·문턱·보유 변경, 다른 지수(S&P500·SOX)로 바꾸기, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
