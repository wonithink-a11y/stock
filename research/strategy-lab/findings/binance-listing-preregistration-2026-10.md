---
track: crypto
factor: binance-listing
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["data.binance.vision 현물 월별 일봉 목록 전체(상장폐지 심볼 포함 — 생존편향 없음)", "사건 = 바이낸스에 처음 나타난 코인(USDT·BTC·BNB·BUSD 어느 마켓에도 그 전 달 기록 없음)이 USDT 마켓으로 시작, 상장일 L = USDT 첫 일봉 날", "진입 L+1 00:00 UTC 시가(첫날 혼란 제외), BL7 7일 · BL30 30일 보유, 관측 = 코인 수익 − 같은 창 BTC 수익, 같은 상장일 여러 코인은 평균 하나", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09(L 기준), 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "바이낸스에 새로 상장된 코인은 상장 다음 날부터 1주·1달 동안 BTC 보다 덜 오르는가(더 오르는가)".
  업비트 상장 연구(U1 상장 뒤 7일 숏, TRAIN t 2.36 < 바닥선 2.49 로 REJECT · forward 진행 중)의 바이낸스판 — 상폐 코인까지 남은 새 표본. 사용자 위임(2026-10-30 밤).
---

# 바이낸스 신규 상장 → 다음 1주·1달(BTC 대비) — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 사건 정의·진입·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `binance-listing-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/binance_listing.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- 업비트 KRW 상장(upbit-krw-listing, 10-18): U1 상장 뒤 7일 숏 TRAIN t 2.36 < 바닥선 2.49 → REJECT, forward 기록 중. 실행 가능성 점검에서 상장일 바이낸스 무기한 보유 88%.
- 통념·보고: 거래소 신규 상장 코인(특히 런치풀·에어드롭 물량)은 상장 직후 고평가 → 몇 주에 걸쳐 빠진다(공개 분석 다수, 수치 미확인).
- data.binance.vision 은 **상장폐지 심볼의 과거 일봉도 남긴다** → 생존편향이 없다(이 저장소 알트 연구 대부분의 한계였다).
- 숏은 무기한 선물이 있어야 하고 상장 초기엔 차입·수수료가 비쌀 수 있다 → 비용 10bp 는 낙관적. '사지 않는다'의 근거로서의 값이 크다.
- **현실적 기대: INFORMATION 이상**(사전 확률이 높은 편) — 다만 TRAIN 2018~2022 의 상장 성격(IEO·DeFi)과 2024~ (런치풀·밈)이 달라 부호가 갈릴 수 있다.

## 1. 데이터

- 목록: `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data/spot/monthly/klines/&delimiter=/`(페이지 넘김) → 심볼 전부.
- 심볼마다 `…/klines/<SYM>/1d/` 목록 → 있는 달. 코인(base) = 심볼에서 마켓 접미사(USDT·BTC·BNB·BUSD)를 뗀 것. 레버리지 토큰(UP·DOWN·BULL·BEAR 로 끝남)·스테이블(USDC·BUSD·TUSD·FDUSD·USDP·DAI·PAX·EUR·GBP·AUD 등)은 제외.
- 사건 코인의 USDT 일봉: 첫 달·다음 달·그다음 달 zip(`data.binance.vision/data/spot/monthly/klines/<SYM>USDT/1d/…`). 응답 일봉 날짜가 요청한 달 안인지 확인(교훈81).
- BTC: `cbprem/bn_btc.parquet` 00:00 UTC 시가. 저장 `data/crypto/listing/`(gitignore).

## 2. 정의

- 코인 b 의 첫 달 = USDT·BTC·BNB·BUSD 마켓 중 가장 이른 일봉 달. **사건 = b 의 USDT 마켓 첫 달 == b 의 첫 달**(바이낸스 첫 등장이 USDT 마켓 포함). L = 그 USDT 첫 일봉 날짜.
- 2018-01 이전 첫 달인 코인 제외(자료 시작 2017-08 전후는 '처음'을 가릴 수 없다).
- 진입 t0 = L+1 00:00 UTC(그 코인의 L+1 일봉 시가), 관측 = [(P(t0+h)/P(t0) − 1) − (BTC(t0+h)/BTC(t0) − 1)] × 1e4, h = 7(BL7) · 30(BL30). 가격이 없으면(그 전 상폐 등) 그 사건 제외 — 제외 수를 기록한다.
- 같은 L 의 여러 코인은 평균해 관측 하나. 구간은 L 로 가른다.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261110), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0(s = TRAIN 부호). ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 상장일 수·코인 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 중앙값·음의 비율.

## 4. 기록 전용 (판정 불사용)

1. 상장 첫날 수익(L 시가 → L+1 시가) 분포.
2. 코인 단위(평균 안 냄) t, BTC 를 빼지 않은 원수익.
3. 7·30일 사이 상장폐지·자료 끊김 수.
4. 연도별 사건 수.

## 5. 하지 않는 것

사건 정의(마켓 목록·제외 규칙)·진입 시점·보유 변경, 런치풀 여부 등 결과 뒤 분류 추가, 비용 변경, 구간 재절단.
