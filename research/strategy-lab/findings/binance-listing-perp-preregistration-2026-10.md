---
track: crypto
factor: binance-listing-perp
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["사건 = binance-listing BL7 과 같은 547건(c776835 정의 그대로) 중 진입 시각(L+1 00:00 UTC)에 바이낸스 USDⓈ-M 무기한(<BASE>USDT 또는 1000<BASE>USDT) 일봉이 있는 것", "숏 7일: 무기한 일봉 시가 L+1 → L+8, BTC 무기한(BTCUSDT) 같은 창 대비, 보유 중 펀딩(8시간 등 공시된 모든 정산)을 숏 쪽에서 더하고 빼기", "관측 = 상장일 평균 [−(코인 수익 − BTC 수익) + Σ 펀딩율] × 1e4 − 비용", "비용 왕복 10bp(테이커 4bp×2 + 슬리피지) · 스트레스 30bp", "구간 TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09, 판정 = 실행 가능성(아래 §3)"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "바이낸스 신규 상장 7일 약세(BL7 ROBUST)를 무기한 선물 숏으로 실제로 잡을 수 있는가 — 무기한이 있는 비율, 펀딩 비용을 내고도 남는가".
  BL7 결과(9e0be5a)를 본 뒤의 실행 가능성 검증이다 — 신호 자체를 다시 판정하지 않는다. 사용자 위임(2026-10-30 밤).
---

# 바이낸스 신규 상장 7일 숏 — 무기한 선물 실행 가능성 — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 사건·진입·보유·펀딩 처리·비용·판정을 바꾸지 않는다. 결과는 `binance-listing-perp-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/binance_listing_perp.py`(다음 커밋).

## 0. 이미 본 것

- BL7(현물, BTC 대비, 비용 10bp) ROBUST: TRAIN −933 · VALID −647 · TEST −1,151bp. 이 연구는 **같은 사건을 다른 수단(무기한)으로 재는 것**이라 결과가 같은 쪽일 가능성이 높다.
  값은 '얼마나 잃느냐'(펀딩·무기한 없음·가격 차)에 있다. 신호 판정은 다시 하지 않는다.
- 상장 초기 무기한 펀딩은 숏이 몰려 크게 음(숏이 지불)일 수 있다는 것이 통념 — 여기서 잰다.

## 1. 데이터

- 무기한 목록: `s3 … data.binance.vision?prefix=data/futures/um/monthly/klines/&delimiter=/`. 일봉 `data/futures/um/monthly/klines/<SYM>/1d/<SYM>-1d-YYYY-MM.zip`.
- 펀딩: `data/futures/um/monthly/fundingRate/<SYM>/<SYM>-fundingRate-YYYY-MM.zip`(calc_time, funding_interval_hours, last_funding_rate).
- BTC 무기한 BTCUSDT 같은 방식. 저장 `data/crypto/listing_perp/`(gitignore). 응답 달 대조(교훈81).
- 심볼 매칭: `<BASE>USDT` 가 있으면 그것, 없으면 `1000<BASE>USDT`(가격 배수는 수익률에 영향 없음). 그 밖 이름 바뀐 무기한은 매칭하지 않는다(커버리지에서 빠짐).

## 2. 정의

- t0 = L+1 00:00 UTC, t1 = t0 + 7일. 무기한 일봉 시가 P(t0)·P(t1) 둘 다 있어야 사건 포함(없으면 '무기한 없음'으로 센다).
- 코인 수익 r = P(t1)/P(t0) − 1, BTC 무기한 수익 b 동일 창. 펀딩 F = Σ(정산 시각 ∈ (t0, t1]) last_funding_rate(양이면 롱이 숏에게 지급 → 숏 수입).
- 관측 = [−(r − b) + F] × 1e4 bp(BTC 쪽 롱의 펀딩은 무시 — 작다). 같은 L 은 평균.

## 3. 판정 (실행 가능성)

- **실행 가능(EXECUTABLE)**: 무기한 커버리지(무기한 있는 사건 / 547)를 기록하고, 무기한 있는 사건에서 VALID+TEST 평균 관측 − 10bp > 0 ∧ t ≥ 2 ∧ 30bp 스트레스에서도 > 0 ∧ TEST 단독 평균 − 10bp > 0.
- **부분(PARTIAL)**: 위 평균 > 0 이나 t < 2 또는 TEST 단독 ≤ 0.
- **실행 불가(NOT EXECUTABLE)**: 평균 − 10bp ≤ 0, 또는 VALID+TEST 무기한 있는 사건 < 30.
- TRAIN 은 기록만(무기한 상장이 드물던 시기).
- 결과 표: 커버리지(구간별) · 현물 BL7 vs 무기한 가격만 vs 펀딩 포함 · 평균 펀딩(7일 합) · 펀딩이 숏에 불리했던 비율 · 시기 칸 ~2023 / 2024 / 2025~.

## 4. 기록 전용

1. 진입 시점에 무기한이 현물보다 먼저 있었던 비율(프리마켓 상장).
2. 펀딩 정산 주기(1·4·8시간) 분포.
3. 무기한·현물 시가 괴리(진입 시각 베이시스).

## 5. 하지 않는 것

보유·진입 변경, 펀딩 처리 변경, 결과 뒤 코인 거르기(유동성·시총 등), 비용 변경. 실제 숏 운용은 🔴 사용자 GO + 별도 설계.
