---
track: crypto
factor: fear-greed
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["alternative.me Crypto Fear & Greed Index 일별(공개 API, 키 없음) 2018-02-01~", "사건 = 제공자 자신의 분류 'Extreme Fear'(s = +1, 역추세 롱) · 'Extreme Greed'(s = −1) — 문턱을 직접 고르지 않는다", "날짜 d 로 찍힌 값 → 진입 d+1 00:00 UTC 바이낸스 BTCUSDT 시가, F1 1일 · F7 7일 보유, 보유 중 새 사건 무시", "TRAIN 2018-02~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "크립토 공포·탐욕 지수가 '극단적 공포'면 사고 '극단적 탐욕'이면 판다는 통념이 다음 1·7일 BTC 에서 비용 뒤에도 맞는가".
  사용자 위임(2026-10-30 밤) 새 후보.
---

# 크립토 공포·탐욕 지수 극단 → BTC 1·7일 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·분류·보유·구간·비용·셀을 바꾸지 않는다. 결과는 `fear-greed-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/fear_greed.py`(다음 커밋).

## 0. 선행 지식 (결과 아닌 것만)

- 지수(0~100)는 변동성·거래량 모멘텀·소셜·도미넌스·검색 추세를 섞은 것(제공자 설명). 'Extreme Fear' 에서 사라는 것이 대표적 통념이다(버핏 문구의 크립토판). 수익을 잰 공개 백테스트는 블로그 수준만 봤다.
- 이 저장소: 이 지수를 쓴 연구 0건. 지수 구성 요소 중 변동성(DVOL·RV)·모멘텀 쪽 연구는 모두 REJECT 였다 → 겹칠 수 있다.
- 값의 시각: 제공자는 매일 00:00 UTC 에 그날 날짜로 값을 낸다고 하지만 정확한 산출 시각은 확인 못 함 → **하루 늦춰 d+1 00:00 진입**(미래 정보 차단 우선).
- 과거 값 사후 수정 여부 확인 못 함(PIT 아님 가능) → 한계.
- 가설 방향은 역추세(s: 공포 +1, 탐욕 −1)이나 판정은 TRAIN 부호를 따른다(음이면 추세 방향이 검정 대상).
- **현실적 기대: REJECT.** 극단 공포는 몇 주씩 이어지는 하락장에서 자주 나와 '떨어지는 칼'일 수 있다.

## 1. 데이터

- `GET https://api.alternative.me/fng/?limit=0&format=json` → (timestamp, value, value_classification). 저장 `data/crypto/sentiment/fng.json`(gitignore).
- BTC: `data/crypto/cbprem/bn_btc.parquet` 00:00 UTC 시가.

## 2. 정의

- 날짜 d(타임스탬프의 UTC 날짜)의 분류가 'Extreme Fear' 면 s = +1, 'Extreme Greed' 면 s = −1, 그 밖은 사건 아님.
- 진입 t0 = d+1 00:00 UTC, 관측 = s × (O(t0 + h일) / O(t0) − 1) bp, h = 1(F1) · 7(F7). 사건일 d 로 색인·구간 구분. 보유 중 그 셀의 새 사건은 받지 않는다.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261102), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호. ECONOMIC: 그리고 VALID+TEST net(10bp)·net(20bp) 평균 > 0. ROBUST: 그리고 net(10bp) t ≥ 2.
  TEST 관측 < 20 → 판정불가.
- 결과 표: 관측 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 칸 ~2023 / 2024 / 2025~ · 연도별 · 공포 롱 / 탐욕 숏 갈래.

## 4. 기록 전용 (판정 불사용)

1. 30일 보유 같은 정의.
2. 극단 구간의 첫날만(전날은 극단 아님) 사건으로 센 1·7일.
3. 업비트 KRW-BTC(국내 롱만 가능) — 공포 롱 갈래의 업비트 일봉 시가 수익.
4. 극단 일수 연도별, 지수와 DVOL·코인베이스 프리미엄 z 상관.

## 5. 하지 않는 것

분류 대신 숫자 문턱 쓰기, 보유 변경, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
