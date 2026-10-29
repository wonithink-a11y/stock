---
track: crypto
factor: kimchi-premium-hourly
date: 2026-10-29
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["KP(T) = 업비트 KRW-BTC 시가[T] ÷ (바이낸스 BTCUSDT 시가[T] × 원/달러[직전 영업일, FRED DEXKOUS]) − 1, 1시간 격자", "z = 직전 720시간 대비(유효 360 이상) — coinbase_premium.zscore 그대로, |z| ≥ 2 사건, 24시간(C4 는 4시간) 차단", "K4 4시간 · K24 24시간 보유, 수익 = 바이낸스 현물 BTCUSDT open→open, 방향 = TRAIN 부호", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01~2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "한국 프리미엄(김치 프리미엄)이 평소보다 크게 높거나 낮을 때 BTC 가 다음 4·24시간 어느 쪽으로 가는가".
  김치 프리미엄 30일 연구(kimchi-premium, NONE)와 보유 기간이 다른 새 질문. 코인베이스 프리미엄 C24 와 같은 틀. 사용자 요청 "남은 후보 중 다음 검증"(2026-10-29).
---

# 김치 프리미엄 → BTC 4·24시간 — 사전등록 (2026-10-29)

> **동결.** 이 커밋 이후 정의·창·문턱·구간·비용·셀을 바꾸지 않는다. 결과는 `kimchi-premium-hourly-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/kimchi_premium_hourly.py`(다음 커밋). z·사건·판정 함수는 `coinbase_premium.py`(20401a4) 그대로 부른다.

## 0. 선행 지식 (결과 아닌 것만)

- 김치 프리미엄 30일(2026-10-09): KPH·KPL 모두 NONE(구간 부호 갈림). 하루 단위 이하는 잰 적 없다.
- 코인베이스 프리미엄 C24 는 ECONOMIC(프리미엄 방향으로 간다)이었고 신호 대부분이 USDT/USD 괴리였다. 김치 프리미엄도 바이낸스 USDT 가격을 쓰므로
  **같은 USDT 성분이 들어간다** — 두 신호의 상관을 기록한다(§4). 같은 성분이면 새 정보가 아니다.
- 방향 가설은 정하지 않는다: 국내 개인 과열(높을 때 되돌림)과 국내 수요 선행(높을 때 지속) 둘 다 그럴듯하다 — TRAIN 부호가 검정 방향을 정한다.
- 현실적 기대: REJECT 또는 코인베이스 신호의 그림자(상관 높음).

## 1. 자료

- 업비트 KRW-BTC 1시간 봉 시가(이미 받음, `cbprem/alts/upbit_btc.parquet`) · 바이낸스 현물 BTCUSDT 1시간 봉 시가(`cbprem/bn_btc.parquet`).
- FRED DEXKOUS(원/달러, 뉴욕 정오 기준 일별). T 의 UTC 날짜보다 **앞선** 마지막 관측값을 쓴다(그날 값은 그날 밤에야 생긴다 — 30일 연구와 같은 처리).
  주의: H.10 은 주 단위로 공표돼 실시간에는 며칠 늦을 수 있다 — 실매매로 갈 경우 실시간 환율로 다시 재야 한다(한계에 적는다).
- 저장: `data/crypto/cbprem/fx_dexkous.csv`(gitignore).

## 2. 정의·셀

- KP(T) = UP_open[T] / (BN_open[T] × FX) − 1. 하나라도 없으면 없음.
- z(T) = `coinbase_premium.zscore(KP)`. 사건 = |z| ≥ 2, 방향 d = sign(z), 수익 = d × (BN_open[T+h] / BN_open[T] − 1) — `coinbase_premium.events` 그대로.
- K4: h = 4 · K24: h = 24. 판정 방향은 TRAIN 부호(음이면 되돌림 방향이 검정 대상).

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261031), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 가 TRAIN 과 같은 부호. ECONOMIC: 그리고 VALID+TEST net10·net20 평균 > 0. ROBUST: 그리고 net10 t ≥ 2.
- 결과 표: 사건 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 ~2023 / 2024 / 2025~ · 연도별.

## 4. 기록 전용 (판정 불사용)

1. 김치 z 와 코인베이스 z(같은 시각)의 상관 · 두 사건 집합이 24시간 안에 겹치는 비율.
2. 업비트 체결 롱 갈래: 검정 방향이 롱인 사건(지속이면 z ≥ 2, 되돌림이면 z ≤ −2)만 업비트 KRW-BTC open→open 24h, net10.
3. 업비트 KRW-USDT 로 정의한 환율 없는 김치(업비트 KRW-BTC ÷ (바이낸스 BTCUSDT × 업비트 KRW-USDT) − 1, 자료가 있는 2024 중반 이후)로 같은 두 셀.
4. 원값 KP 분포·연평균.

## 5. 하지 않는 것

z 창·문턱·보유 변경, 환율 시차 변경, 결과 뒤 셀 추가, 코인베이스 신호와 결합한 규칙 만들기(새 사전등록으로만).
