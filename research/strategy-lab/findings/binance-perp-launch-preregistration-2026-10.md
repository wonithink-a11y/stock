---
track: crypto
factor: binance-perp-launch
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["사건 = 바이낸스 USDⓈ-M 무기한 <BASE>USDT(또는 1000<BASE>USDT)의 첫 일봉 날 P, 그 코인의 바이낸스 USDT 현물이 P 보다 30일 이상 먼저 있었던 경우(기존 현물 코인에 숏 수단이 새로 생긴 경우)", "진입 P+1 00:00 UTC 현물 일봉 시가, FL7 7일 · FL30 30일, 관측 = 현물 코인 − BTC 수익, 같은 P 평균, 스테이블·레버리지 제외", "TRAIN 2019-09~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09(P 기준), 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "이미 현물로 거래되던 코인에 바이낸스 무기한 선물이 새로 생겨 공매도가 가능해지면, 그 다음 1주·1달 현물이 BTC 대비 빠지는가(Miller 1977 공매도 제약 가설)".
  같은 밤 신규 상장 BL7 ROBUST 와 다른 사건(새 코인이 아니라 새 숏 수단). 사용자 위임(2026-10-30 밤).
---

# 바이낸스 무기한 신규 상장(기존 현물 코인) → 현물 1주·1달 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 사건 정의·진입·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `binance-perp-launch-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/binance_perp_launch.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만 — 신규 상장 결과는 이미 봤다)

- Miller(1977): 의견이 갈리고 공매도가 막힌 자산은 낙관론자 가격으로 고평가된다 → 공매도 수단이 생기면 가격이 내려간다. 주식 옵션·공매도 허용 도입 연구가 다수(결과 엇갈림).
- 같은 밤 바이낸스 신규 상장 BL7(새 코인의 첫 주 약세) ROBUST. 많은 신규 코인은 상장일 전후로 무기한도 같이 생겨 두 효과가 섞인다 → **현물이 30일 이상 먼저 있던 코인만** 써서 '새 코인' 효과를 뗀다.
- 무기한 상장은 거래량·관심이 늘어난 코인을 골라 하는 경우가 많아(최근 급등 코인) 되돌림과 섞일 수 있다 → 기록 1 에서 상장 전 30일 BTC 대비 수익을 같이 본다.
- **현실적 기대: INFORMATION 또는 REJECT.**

## 1. 데이터

- 무기한 목록·첫 달: S3 `data/futures/um/monthly/klines/` 심볼별 1d 달 목록(binance_listing_perp 가 받은 perps.json 재사용 + 달 목록 새로). 첫 일봉 날 P = 첫 달 zip 의 첫 줄.
- 현물: `binance_listing` 의 months.json 으로 현물 첫 달 확인, P 앞뒤 달 현물 일봉을 data.binance.vision 에서 받는다(응답 달 대조, 교훈81).
- BTC: `cbprem/bn_btc.parquet` 00:00 UTC 시가. 저장 `data/crypto/perplaunch/`(gitignore).
- USDⓈ-M 무기한은 2019-09 부터 → TRAIN 은 2019-09 ~ 2022.

## 2. 정의

- 무기한 심볼 → base(1000 접두 제거, USDT 접미 제거). 현물 <base>USDT 첫 일봉 ≤ P − 30일 이어야 사건. P ≥ 2019-09-01, eligible(base).
- 관측 = [(S(P+1+h)/S(P+1) − 1) − (BTC 동일)] × 1e4, h = 7(FL7) · 30(FL30), S = 현물 일봉 시가. 같은 P 평균. 구간은 P 로.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261114), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0(s = TRAIN 부호). ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 사건일 수·코인 수 · gross · OOS 부트스트랩 95% · net · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · BTC 에 진 비율.

## 4. 기록 전용

1. 상장 전 30일(P−30 → P) BTC 대비 — 급등 코인을 골라 상장했나.
2. 상장 첫날(P → P+1).
3. 코인 단위 t.

## 5. 하지 않는 것

30일 조건·진입·보유 변경, 결과 뒤 상장 전 수익으로 거르기, 비용 변경, 구간 재절단.
