---
track: crypto
factor: order-flow-imbalance-audit
date: 2026-08-29
verdict: KEEP
criteria_version: backfill-v1
conditions: ["taker_buy_ratio", "buy_sell_imbalance", "binance_klines", "activity_data"]
reason: "기존 activity/ 데이터와 Binance klines로 order-flow imbalance를 2023-05-21부터 장기 확보 가능함을 감사로 확인 - 판정 PASS"
---
# Step 34 — Order-Flow Imbalance Data Audit

날짜: 2026-08-29 | 판정: **PASS**

## 목적
기존 `activity/` 데이터와 Binance 공개 API에서 **order-flow imbalance** 데이터가
2023-05-21부터 현재까지 장기 확보 가능한지 가용성 감사.

---

## 1. 기존 `activity/` 데이터 (이미 수집 완료)

| 필드 | 존재 여부 | 비고 |
|---|---|---|
| `taker_buy_quote_asset_volume` | ✅ 28종목 모두 | quote 기준 매수 체결량 |
| `taker_buy_base_asset_volume` | ✅ 28종목 모두 | base 기준 매수 체결량 |
| `quote_asset_volume` | ✅ 28종목 모두 | 총 거래대금 |
| `volume` | ✅ 28종목 모두 | 총 거래량 (base) |
| `number_of_trades` | ✅ 28종목 모두 | 체결 건수 |

| 지표 | 값 (대표 7종목 평균) |
|---|---|
| taker buy ratio (quote) | ~0.49~0.50 (약간 매도 우위) |
| taker buy ratio (base) | ~0.49~0.50 |
| 누적 imbalance (quote) | -0.5% ~ -3.3% (전체 기간 매도 우위) |

**역사적 깊이**: 2019-09(BTC) ~ 2026-08-28 (전 종목 2019-2020년부터)
- 28종목 모두 2023-05-21 이전 데이터 **완전 확보**

---

## 2. Binance 공개 API 프로브 결과

| 엔드포인트 | 상태 | 주요 필드 | 역사적 깊이 |
|---|---|---|---|
| `/fapi/v1/klines` | ⚠️ 프로브 에러 / 이력 조회 **OK** | open, high, low, close, volume, **quoteAssetVolume, numberOfTrades, takerBuyBaseAssetVolume, takerBuyQuoteAssetVolume** | **2023-01-01부터 OK** (earliest_ts=1672531200000) |
| `/futures/data/takerlongshortRatio` | ✅ OK | `buySellRatio`, `buyVol`, `sellVol`, `timestamp` | 미확인 (probe만) |
| `/futures/data/globalLongShortAccountRatio` | ✅ OK | `longAccount`, `shortAccount`, `longShortRatio`, `symbol`, `timestamp` | 미확인 |
| `/futures/data/topLongShortAccountRatio` | ✅ OK | `longAccount`, `shortAccount`, `longShortRatio`, `symbol`, `timestamp` | 미확인 |
| `/futures/data/topLongShortPositionRatio` | ✅ OK | `longAccount`, `shortAccount`, `longShortRatio`, `symbol`, `timestamp` | 미확인 |

### 핵심 발견
1. **`/fapi/v1/klines`**가 **가장 완전한 order-flow 소스**: 1h 봉 단위로 taker buy volume(base/quote), 총 거래량/대금, 체결건수 모두 포함
2. **역사적 깊이 충분**: 2023-01-01부터 조회 가능 → **2023-05-21 연구기간 완전 커버**
3. **takerlongshortRatio 등 futures/data 계열**: taker long/short ratio 제공 가능, 단 역사적 깊이 미확인 (30일 제한 가능성)

---

## 3. 파생 가능한 order-flow 피처 (기존 activity 데이터로 즉시 계산 가능)

| 피처 | 공식 | 기존 데이터로 계산 가능? |
|---|---|---|
| **taker buy ratio (quote)** | `taker_buy_quote_asset_volume / quote_asset_volume` | ✅ |
| **taker buy ratio (base)** | `taker_buy_base_asset_volume / volume` | ✅ |
| **buy/sell volume imbalance (quote)** | `(buy_vol - sell_vol) / quote_vol` | ✅ |
| **buy/sell volume imbalance (base)** | `(buy_vol - sell_vol) / volume` | ✅ |
| **imbalance change (3d/7d/30d)** | rolling change | ✅ |
| **rolling 3d/7d/30d imbalance** | rolling mean | ✅ |
| **imbalance z-score (30d)** | (imbalance - mean_30d) / std_30d | ✅ |
| **taker buy volume change** | pct_change | ✅ |

**모든 피처 기존 `activity/` 1h → KST daily 집계로 즉시 계산 가능**

---

## 4. 품질 체크 (대표 7종목)

| 심볼 | taker_buy_ratio_q | 누적 imbalance_q | 데이터 시작 |
|---|---|---|---|
| BTCUSDT | 0.4975 | -0.0050 | 2019-09-08 |
| ETHUSDT | 0.4955 | -0.0103 | 2019-11-27 |
| SOLUSDT | 0.4903 | -0.0168 | 2020-09-14 |
| XRPUSDT | 0.4878 | -0.0246 | 2020-01-06 |
| ADAUSDT | 0.4895 | -0.0270 | 2020-01-31 |
| DOGEUSDT | 0.4874 | -0.0234 | 2020-07-10 |
| DOTUSDT | 0.4869 | -0.0334 | 2020-08-22 |

- 전체적으로 **taker buy ratio ≈ 0.49~0.50** (약간 매도 우위)
- 누적 imbalance 음수 → 전체 기간 매도 압력 우세
- 결측/이상치 없음 (taker buy volume 필드 모두 완전)

---

## 5. 판정: **PASS**

### PASS 근거
| 기준 | 충족? | 비고 |
|---|---|---|
| **2023-05-21 이전 데이터 존재** | ✅ | 전 종목 2019-2020년부터 |
| **전 28종목 커버리지** | ✅ | activity/ 28개 모두 필드 완비 |
| **필수 필드 완비** | ✅ | taker buy base/quote, volume, quote_vol, trades |
| **장기 역사적 깊이** | ✅ | 2019-2020 ~ 2026-08 (6~7년) |
| **파생 피처 계산 가능** | ✅ | ratio, imbalance, change, z-score 모두 즉시 계산 |
| **API 실시간 보완 가능** | ✅ | klines, takerlongshortRatio 등 공개 API 제공 |

### 제약사항
- `futures/data/*` 계열 엔드포인트는 30일 제한 가능성 (Step 21/28과 동일) → **klines 사용 권장**
- klines 프로브 시 일시적 400 에러 발생 가능 → 재시도 로직 필요

---

## 5. 결론 및 권고

**기존 `activity/` 데이터만으로도 28종목 전체에 대해 2023-05-21부터 현재까지
완전한 order-flow imbalance 연구가 즉시 가능함.**

별도 API 수집 없이 기존 파라켓 파일로 다음 피처 즉시 생성 가능:
- `taker_buy_ratio_q`, `taker_buy_ratio_b`
- `imbalance_q`, `imbalance_b`
- `imbalance_chg_3d/7d/30d`, `imbalance_z_30d`
- `buy_vol_chg`, `sell_vol_chg`

**다음 단계(별도 지시 시)**: `order_flow_features.py` 생성 → 예측력 검증 (Step 33 스타일)

---

## 산출물
- `order_flow_imbalance_audit.py`
- `findings/order-flow-imbalance-audit-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.
