---
track: crypto
factor: crypto-feature-inventory
date: 2026-08-29
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "기존 crypto 데이터 스키마 전수 감사 - futures 거래활동 축(거래량·trade count·taker) 전체 부재가 최대 공백, 신규 수집 없음(인벤토리)"
---
# Step 22 — Existing Crypto Data Feature Inventory

날짜: 2026-08-29 | API 호출 없음 · 신규 수집 없음 · 기존 파일 수정 없음

## 스키마 감사 결과 (data/crypto/ 실제 parquet 전수)

### 1) `daily/` — Upbit KRW 일봉 (15종목)
- 컬럼: `open high low close volume` **(5개, 거래대금·trade count 없음)**
- 기간: 2023-05-21(KST 00:00, tz-naive KST) ~ 2026-08-27, 12종목 1195행.
- **커버리지 결손**: KRW-OP 396행(2025-07-28~), KRW-UNI 675행(2024-10-22~), **KRW-MATIC 0행(빈 파일)**.
- 결측: 존재 행에서 0. 주의: `volume` = base 코인 수량(Upbit `candle_acc_trade_volume`), **거래대금(`candle_acc_trade_price`)은 저장 안 됨**.

### 2) `4h/` — Upbit KRW 4h (15종목)
- 컬럼: 동일 5개. 기간: **2026-03-16 ~ 2026-08-27 (≈5.5개월, 988행)만 존재** — 짧은 창. MATIC 0행.

### 3) `funding/` — Binance USDT perp funding 8h (28종목, 28/28)
- 컬럼: `symbol, fundingRate, markPrice` (3개).
- **fundingRate 결측 0(완전)**, 상장일부터(BTC 2019-09-10~) 장기.
- **markPrice 초기 결측 최대 ~59.4%(BTC)** — 초기 구간만, 이후 완전.
- `_candidate_research.json`, `manifest.json` 있음. **funding 데이터에는 premium/index 가격 없음**(premium은 basis에서 파생).

### 4) `basis/8h/` — mark/index OHLC 8h + basis 파생 (28종목, 28/28)
- 컬럼 18: `time, mark_open/high/low/close, index_open/high/low/close, premium_open, premium_close, mark_minus_index_open, mark_minus_index_close, futuresPrice, indexPrice, basis, basisRate, annualizedBasisRate`.
- `index_*` 결측 0(완전). `mark_* / premium_* / mark_minus_index_*`는 **9/28 종목에서 초기 결측(최대 ~30.8%)** — mark kline 시작 시점 차이(기간 중단 아님).
- **`annualizedBasisRate` 전 종목 100% NaN**.
- `futuresPrice / indexPrice / basis / basisRate`: 19/28 종목 일부 결측(최대 ~30.8%) — Step 18 basis 엔드포인트 IP 밴 영향(성공 구간만 기록). 비밴 IP에서 재수집 가능.
- 기간: 상장~2026-08-29(BTC 8h 2019-12-23~, 7323행).

### 5) `basis/1h/` — mark/index OHLC 1h (28종목, 28/28)
- 컬럼 12: `time, mark_*, index_*, premium_open, premium_close, mark_minus_index_open`.
- index 완전, mark측 9/28 초기 NaN(동일 패턴). **장기**: BTC 2019-12-23 11:00~, 58,574행; 신규 상장 종목은 상장일부터(WLD 2023-07-24).
- **futures 28종목의 가장 깊은 가격/프리미엄 데이터 소스** (forward return 종가는 여기서 재구성).

## Feature 분류

### A — 이미 충분히 존재 (추가 수집 불필요)
| feature | 위치 | 상태 |
|---|---|---|
| Futures/USDT OHLC mark·index (1h·8h) | basis/1h, basis/8h | 28/28, 상장~ 장기 |
| premium (mark−index) | basis/8h·1h premium_*/mark_minus_index_* | 28/28 (9종목 초기 NaN 있음→B 병기) |
| funding rate | funding/ | 28/28, 결측 0, 장기 |
| KRW OHLCV | daily/ | 15종목(부분 커버 → B 병기) |

### B — 존재하나 품질/기간/coverage 확인 필요 (후속 검증 후보)
| feature | 상태 |
|---|---|
| basis / basisRate / futuresPrice−indexPrice (8h) | 19/28 일부 결측(Step 18 IP밴) → **비밴 IP 재수집 검증** |
| funding.markPrice | 초기 구간 ~59% 결측(BTC) |
| basis mark측 9/28 초기 NaN | 시작시점 편차(기간 중단 아님 — 병합 시 확인) |
| KRW 일봉 커버리지 | 15/28뿐, OP 2025-07~/UNI 2024-10~/MATIC 0행; 4h는 5.5개월 |

### C — 현재 데이터에 없음 (외부 소스 조사 후보)
| feature | 비고 |
|---|---|
| USDT futures **거래량(volume)** | 28종목 파켓에 없음 → Binance klines(장기) 후보 |
| **매매대금 quote volume/turnover** | futures/krw 모두 저장 안 됨 → 매수: Binance klines `quoteAssetVolume`(장기) |
| **trade count** | 전무 → Binance klines `numberOfTrades`(장기) 후보 |
| **taker buy base/quote** | 전무 → Binance klines `takerBuy*` (장기) 후보 |
| **KRW 거래대금** | Upbit daily에 없음 → `candle_acc_trade_price`로 재수집 가능 |
| annualizedBasisRate | 전 종목 100% NaN → 만기시간 산식 또는 생략 |
| Open Interest | Step 16에서 최근 30일 한정 확인 → **연구기간 기준 취득 불가** |
| Positioning(L/S ratio) | Step 21에서 4종 모두 최근 30일 한정 확인 → **취득 불가(FAIL)** |

## 결론 — "아직 실험 안 한 정보축" 우선순위

1. **USDT 28종목의 거래활동 축이 전부 부재**가 가장 큰 빈 구멍이다. futures klines 기반
   `volume(turnover=taker 매수 비율 포함)`, `trade count`, `quote volume`, `taker buy ratio`는
   **장기(상장~) 확보 가능** · funding/premium과 다른 정보축(후속 예측력 검증으로 독립성 판정).
   이미 저장된 futures OHLC와 동일 소스지만 **저장 안 된 필드**일 뿐이다 — 중복 판정 아님(미존재).
2. KRW `거래대금`은 Upbit가 제공하므로 일봉에 quote volume 추가만으로 **A→더 풍부**로 업그레이드 가능
   (14종목·완전 창 기준).
3. 기존 데이터로 즉시 할 수 있는 미실험: KRW `volume shock / 거래량 대비 가격변화`(15종목·B 커버리지),
   funding·premium·basis의 **상장 기간 전체 크로스코 봐** 등 — 이어지는 다음 단계에서 우선순위화.

## 산출물
- 신규: `crypto_feature_inventory.py` + `findings/crypto-feature-inventory-2026-08.{json,md}`.
- 기존 데이터/전략/findings 무수정. API 호출·다운로드·백테스트·커밋 없음.