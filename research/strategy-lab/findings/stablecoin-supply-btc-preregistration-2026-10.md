---
track: crypto
factor: stablecoin-supply-btc
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["DefiLlama 공개 API 스테이블코인 전체 유통량(달러 연동, 일별 00:00 UTC, 2017-11~) — g(d) = ln(S_d / S_{d−7})", "z = (g − 직전 180일 평균) / 직전 180일 표준편차(현재 제외, 유효 90 이상), |z| ≥ 2 사건, 방향 = sign(z)", "진입 = d+1 00:00 UTC(값 공표 지연 대비 하루 늦춤) 바이낸스 BTCUSDT 시가, S1 1일 · S7 7일 보유, 보유 중 새 진입 없음", "TRAIN ~2022 / VALID 2023 / TEST 2024-01~2026-09, 바닥선 2셀 TRAIN 부호반전 500회 95%", "비용 왕복 10bp · 스트레스 20bp"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "스테이블코인(USDT·USDC 등) 발행이 평소보다 크게 늘거나 줄어든 주 다음 1·7일, BTC 는 그 방향(늘면 오름)으로 가는가".
  코인베이스 프리미엄 신호의 정체가 USDT/USD 괴리였다는 사후 진단(10-29)에서 이어진 새 질문 — 같은 표본을 다시 자른 것이 아니라 다른 자료(발행량)다. 사용자 요청 "다음 검증"(2026-10-30).
---

# 스테이블코인 발행량 → BTC 1·7일 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·문턱·구간·비용·셀을 바꾸지 않는다. 결과는 `stablecoin-supply-btc-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/stablecoin_supply_btc.py`(다음 커밋). 판정 함수는 `coinbase_premium.judge`(20401a4) 그대로.

## 0. 선행 지식 (결과 아닌 것만)

- 학술: Wei(2018, Economics Letters) — Tether 발행은 이후 BTC 수익에 영향 없음(거래량엔 영향, 동시적). Griffin·Shams 는 반대 주장(가격 떠받치기).
  기술 통계: 발행은 상승장에 몰린다(인과 방향 미정).
- 이 저장소: 스테이블코인 발행량을 신호로 쓴 적 없다(검색 0건). 코인베이스 프리미엄 C24(ECONOMIC)의 정체가 USDT/USD 괴리였다 — 발행량은 그와 다른 자료다.
- **현실적 기대: REJECT.** 발행은 수요를 뒤따르는 경우가 많아 이미 가격에 반영됐을 가능성이 크다.
- 자료 한계: DefiLlama 값은 나중에 보정될 수 있다(시점 기준 PIT 보장 없음). 하루 늦춘 진입으로 공표 지연만 막는다.

## 1. 자료

- `https://stablecoins.llama.fi/stablecoincharts/all` 의 `totalCirculatingUSD.peggedUSD`(전체 달러 연동). 기록용으로 USDT(id 1)·USDC(id 2) 개별.
- 바이낸스 현물 BTCUSDT 1시간 봉 시가(이미 받음, `cbprem/bn_btc.parquet`, ~2026-09-30) — 00:00 UTC 시가만 쓴다.
- 저장: `data/crypto/cbprem/stablecoin_*.json`(gitignore).

## 2. 정의·셀

- S_d = 날짜 d(00:00 UTC) 유통량. g(d) = ln(S_d / S_{d−7}). z(d) = (g(d) − μ) / σ, μ·σ = g 의 직전 180일(d 제외, 유효 90 이상).
- 사건: |z(d)| ≥ 2, 방향 s = sign(z). 진입 t0 = d+1 00:00 UTC, 수익 = s × (BN_open[t0 + h일] / BN_open[t0] − 1) bp.
- S1: h = 1일 · S7: h = 7일. 셀마다 보유 중(t0 ~ t0+h) 새 사건 무시. 가격이 없으면 그 사건을 뺀다.
- 판정 방향은 TRAIN 부호(음이면 '늘면 내림'이 검정 대상). 구간은 사건일 d 기준.

## 3. 판정 (coinbase-premium §4 와 같은 문장)

- 바닥선: 2셀 TRAIN 관측 부호반전 500회(seed 20261102), 셀 최대 |t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 같은 부호. ECONOMIC: 그리고 VALID+TEST net10·net20 > 0. ROBUST: 그리고 net10 t ≥ 2. TEST 사건 < 20 → 판정불가.
- 결과 표: 사건 수 · gross · OOS 부트스트랩 95% · net · 손익분기 · 시기 ~2023 / 2024 / 2025~ · 연도별 · 늘어남/줄어듦 갈래.

## 4. 기록 전용 (판정 불사용)

1. USDT 단독 · USDC 단독으로 같은 두 셀.
2. 겹치지 않는 주 단위 상관: g(주 끝) ↔ 다음 7일 BTC 수익(스피어만), 연도별.
3. 그 주 코인베이스 프리미엄 z 평균과 g 의 상관(같은 성분인지).
4. 사건 연도별 건수, 늘어남/줄어듦 비율.

## 5. 하지 않는 것

창(7·180일)·문턱·진입 지연·보유 변경, 결과 뒤 셀 추가, 특정 스테이블코인만 골라 판정, 같은 표본 재절단.
