---
track: crypto
factor: coinbase-listing
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["코인베이스 공개 products 목록(상장폐지 포함) 중 USD 마켓, 상장일 C = 그 마켓의 첫 일봉 날짜(00:00 UTC)", "사건 = C 보다 30일 이상 먼저 바이낸스 USDT 현물에서 거래되던 코인(이미 거래되던 코인이 코인베이스에 추가된 경우), 스테이블·레버리지 제외(binance_listing 규칙)", "진입 C+1 00:00 UTC 바이낸스 USDT 일봉 시가, CL7 7일 · CL30 30일, 관측 = 코인 − BTC 수익, 같은 C 는 평균", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "이미 바이낸스에서 거래되던 코인이 코인베이스에 새로 상장되면('코인베이스 효과') 그 다음 날부터 1주·1달 BTC 대비 어느 쪽으로 가는가".
  바이낸스 신규 상장 BL7 ROBUST(같은 밤) 뒤 '상장 효과'의 다른 표본. 사용자 위임(2026-10-30 밤).
---

# 코인베이스 상장 → 다음 1주·1달(BTC 대비, 바이낸스 가격) — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 사건 정의·진입·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `coinbase-listing-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/coinbase_listing.py`(다음 커밋).

## 0. 이미 본 것·선행 지식

- 같은 밤 바이낸스 신규 상장 BL7 ROBUST(상장 다음 날부터 7일 BTC 대비 −9~12%), 무기한 숏 EXECUTABLE. 그 결과를 본 뒤의 **다른 표본**이다 — 질문(상장 뒤 약세)은 같은 계열이라 사전 확률이 높다는 점을 숨기지 않는다.
- '코인베이스 효과': 코인베이스 상장 발표·개시 때 가격이 튄다는 통념(2017~2021 사례 다수). 발표 시각 자료는 없어 **거래 개시일(첫 일봉)** 로만 잰다 — 발표 뒤 이미 오른 뒤일 수 있다.
- 바이낸스 신규 상장과 달리 '처음 생긴 코인'이 아니라 '이미 거래되던 코인의 새 판로'다. 차이가 결과에 드러날 수 있다.
- 코인베이스 products 는 상폐 마켓도 준다 → 생존편향이 작다(바이낸스 일봉도 상폐 포함).
- **현실적 기대: INFORMATION 이상 또는 REJECT** — 바이낸스 상장보다 효과가 작을 것.

## 1. 데이터

- `GET https://api.exchange.coinbase.com/products`(키 없음) → USD 마켓 전부(online·delisted). 마켓마다 `candles?granularity=86400` 를 2016-01 부터 300일씩 조회해 첫 일봉 날짜 C(응답 날짜가 요청 구간 안인지 확인, 교훈81).
- 바이낸스: `data.binance.vision` 의 <BASE>USDT 월별 일봉(binance_listing 이 받아 둔 months.json 으로 존재 달 확인) — C 가 든 달과 그 앞뒤 달.
- BTC: `cbprem/bn_btc.parquet` 00:00 UTC 시가. 저장 `data/crypto/cblisting/`(gitignore).

## 2. 정의

- 코인 b(코인베이스 base, 바이낸스 base 와 같은 이름일 때만 매칭)의 C. 사건 조건: 바이낸스 <b>USDT 첫 일봉 ≤ C − 30일, b 가 스테이블·레버리지가 아님(binance_listing.eligible), C ≥ 2018-01-01.
- t0 = C+1 00:00 UTC, 관측 = [(P(t0+h)/P(t0) − 1) − (BTC(t0+h)/BTC(t0) − 1)] × 1e4, h = 7(CL7) · 30(CL30). 같은 C 의 여러 코인은 평균. 구간은 C 로.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261112), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0(s = TRAIN 부호). ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 상장일 수·코인 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · BTC 에 진 비율.

## 4. 기록 전용 (판정 불사용)

1. 상장 전 7일(C−7 → C) BTC 대비 — 발표 뒤 미리 올랐는가.
2. 상장 첫날(C → C+1) BTC 대비.
3. 코인 단위 t, 코인베이스에서 나중에 상폐된 마켓 비율.

## 5. 하지 않는 것

사건 정의(30일 조건·이름 매칭)·진입·보유 변경, 결과 뒤 코인 거르기, 비용 변경, 구간 재절단.
