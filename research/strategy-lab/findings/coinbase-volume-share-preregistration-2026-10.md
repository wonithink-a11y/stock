---
track: crypto
factor: coinbase-volume-share
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["코인베이스 BTC-USD 일봉(공개 candles granularity 86400, 00:00 UTC) 거래량 · 바이낸스 BTCUSDT 1시간 봉 원본(cbprem/raw) 일 거래량, 둘 다 BTC 개수", "C = ln(코인베이스 7일 거래량 / 바이낸스 7일 거래량), z = 직전 180일(현재 제외, 유효 90) 대비 — upbit-turnover U1 과 같은 틀", "|z| ≥ 2 → z 방향(TRAIN 부호로 검정), 진입 d+1 00:00 UTC 바이낸스 시가, 7일 보유(CV7) · 1일 보유(CV1), 보유 중 새 사건 무시", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "전 세계 BTC 거래 중 코인베이스(미국) 비중이 평소보다 크게 늘거나 줄 때 다음 1·7일 BTC 는 어느 쪽으로 가는가".
  가격 괴리(코인베이스 프리미엄, ECONOMIC)가 아니라 참여량 쪽의 미국 수요 지표. 사용자 위임(2026-10-30 밤) 새 후보.
---

# 코인베이스 거래량 비중 → BTC 1·7일 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·문턱·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `coinbase-volume-share-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/coinbase_volume_share.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만 — 아래 둘은 이미 봤다)

- 코인베이스 프리미엄 C24(가격 괴리 → 24시간) ECONOMIC, 정체는 대부분 USDT/USD 괴리.
- 오늘 업비트 비중 U1(같은 틀, 업비트 ÷ 바이낸스) REJECT(TRAIN t 1.52, 방향은 비중↑ → 상승). 이 연구는 그 틀을 **미리 정해 둔 그대로** 코인베이스에 적용한다(창·문턱·보유를 결과 보고 고르지 않으려고 U1 을 복사).
- 거래소 비중은 거래소별 수수료 정책(바이낸스 0 수수료 행사 2022-07 ~ 2023-03 등)·상장 변화에 크게 흔들린다 → z(직전 180일 대비)가 일부 흡수하지만 구조 변화 사건이 '신호'로 잡힐 수 있다. 한계로 적는다.
- **현실적 기대: REJECT.** 7일 사건은 1년 몇 건.

## 1. 데이터

- 코인베이스: `GET https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400&start=…&end=…`(300일씩), 행 = [시작 초, low, high, open, close, volume]. 응답 날짜가 요청 구간 안인지 확인(교훈81). 2017-06 ~ 2026-09. 저장 `data/crypto/cbvol/cb_btc_daily.parquet`(gitignore).
- 바이낸스: `cbprem/raw/BTCUSDT-1h-*.zip` 5번째 열(거래량 BTC), UTC 날짜별 합(봉 20개 이상). 수익: `cbprem/bn_btc.parquet` 00:00 UTC 시가.

## 2. 정의

- C(d) = ln( Σ_{d−6..d} CB 거래량 / Σ_{d−6..d} BN 거래량 ), 7일 중 하나라도 없으면 결측. day d 값은 d+1 00:00 UTC 에 확정.
- z(d) = (C(d) − 직전 180일 평균) / 표준편차(현재 제외, 유효 90). |z| ≥ 2 → s = sign(z).
- 관측 = s × (O(d+1+h)/O(d+1) − 1) bp, h = 7(CV7) · 1(CV1). 사건일 d 로 색인·구간 구분. 보유 중 그 셀의 새 사건 무시.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261109), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) > 0. ROBUST: 그리고 net(10bp) t ≥ 2. TEST 관측 < 20 → 판정불가.
- 결과 표: 관측 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 비중↑/비중↓ 갈래.

## 4. 기록 전용 (판정 불사용)

1. z 와 코인베이스 프리미엄 z(일 평균)·업비트 비중 z(U1) 상관.
2. 업비트 KRW-BTC 일봉 시가로 잰 CV7.
3. 사건 연도별 수.

## 5. 하지 않는 것

창(7·180일)·문턱(2)·보유 변경, 거래대금(달러) 기준으로 바꾸기, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
