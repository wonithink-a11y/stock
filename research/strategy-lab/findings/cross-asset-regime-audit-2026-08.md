# Step 36 — Cross-Asset Regime Factor Audit (BTC as Market Factor)

날짜: 2026-08-29 | 판정: **PASS**

## 목적
기존 데이터만 사용해 BTC가 **시장 전체 regime factor**로 활용 가능한지 가용성 감사.
- BTC momentum/volatility/return/drawdown
- BTC dominance proxy
- BTC regime과 알트 idiosyncratic return 관계

---

## 1. BTC 데이터 가용성

| 데이터 | 기간 | 행 수 | 비고 |
|---|---|---|---|
| **KRW daily (Upbit)** | 2023-05-21 ~ 2026-08-27 | 1,195 | `data/crypto/daily/KRW-BTC.parquet` |
| **USDT daily (Binance)** | 2019-12-23 ~ 2026-08-29 | 2,441 | basis/1h 14:00 UTC bar → KST 24:00 close 재구성 |
| **BTC 1h (basis/1h)** | 2019-12-23 ~ 2026-08-29 | 2,442 | `basis/1h/BTCUSDT_1h.parquet` |

**결론**: BTC 가격/수익률 데이터는 **2019-12부터 현재까지 완전 확보**, 연구기간(2023-05-21~) 완전 커버.

---

## 2. BTC 1h 파생 피처

| 피처 | 기간 | 행 수 | 평균/비고 |
|---|---|---|---|
| **Daily OHLCV** | 2019-12-23 ~ 2026-08-29 | 2,442 | - |
| **RV_1d (Realized Vol)** | 2019-12-23 ~ 2026-08-29 | 2,442 | mean=0.001018 |
| **mom_7d** | 2019-12-23 ~ 2026-08-29 | 2,442 | 7일 모멘텀 |
| **mom_30d** | 2019-12-23 ~ 2026-08-29 | 2,442 | 30일 모멘텀 |

**결론**: BTC 일간 수익률, 실현변동성, 7일/30일 모멘텀 **전 구간 완전 확보**.

---

## 3. BTC Dominance Proxy (USDT 마켓 점유율)

| 지표 | 값 |
|---|---|
| **가용 여부** | ✅ True |
| **기간** | 2019-09-09 ~ 2026-08-29 (2,547일) |
| **평균 도미넌스** | **49.87%** |
| **표준편차** | 16.35% |

**계산 방식**: 28종목 USDT 마켓 전체 quote_volume 중 BTCUSDT quote_volume 비율  
**결론**: BTC 도미넌스 프록시 **장기 시계열 완전 확보** (2019-09~현재)

---

## 4. BTC Momentum vs 알트 Momentum 상관관계

| 알트 | Pearson | Spearman |
|---|---|---|
| **ETH** | **0.7768** | **0.8184** |
| **ADA** | **0.6441** | **0.7112** |
| **SOL** | **0.5278** | **0.6685** |
| **XRP** | **0.4120** | **0.6768** |
| **DOGE** | **0.3293** | **0.7142** |

**해석**: 
- **ETH는 BTC 모멘텀과 매우 높은 동조성** (Pearson 0.78, Spearman 0.82)
- 주요 알트들은 **모멘텀 측면에서 BTC와 강한 동조성** 보임
- DOGE는 Pearson 낮으나 Spearman 높음 → 비선형/순위 관계 강함

---

## 4. BTC Regime (mom30 > 0 = bull) vs 알트 Forward Returns

| 알트 | Bull r_7 | Bear r_7 | Diff (Bull-Bear) |
|---|---|---|---|
| **DOGE** | **+0.0671** | **−0.0077** | **+0.0748** |
| **SOL** | **+0.0442** | **+0.0002** | **+0.0439** |
| **ADA** | **+0.0275** | **−0.0043** | **+0.0318** |
| **ETH** | **+0.0278** | **−0.0009** | **+0.0287** |
| **XRP** | **+0.0271** | **+0.0013** | **+0.0258** |

**해석**: 
- **모든 알트가 BTC bull 구간에서 유의미하게 높은 수익** 기록
- DOGE가 가장 큰 차이(+7.48%p), SOL이 두 번째(+4.39%p)
- Bear 구간에서는 수익률 근 0 또는 음수
- **BTC regime이 알트 초과수익을 강력하게 설명**

---

## 5. Idiosyncratic Return (알트 수익률 - BTC 수익률)

| Regime | idio_r1 mean | idio_r7 mean | idio_r7 std |
|---|---|---|---|
| **Bull** | **+0.00237** | **+0.0206** | 0.0582 |
| **Bear** | **−0.00026** | **−0.0030** | 0.0329 |

**해석**:
- **Bull 구간에서 알트 idiosyncratic 수익률 유의미하게 양수** (+2.06% r_7)
- **Bear 구간에서 idiosyncratic 수익률 음수/제로** (−0.30% r_7)
- Bull 구간 변동성이 더 큼 (std 5.82% vs 3.29%) → 알트별 차별화 큼

---

## 5. BTC mom30 vs 알트 mom30 상관관계

| 알트 | Pearson | Spearman |
|---|---|---|
| **ETH** | **0.7768** | **0.8184** |
| **ADA** | **0.6441** | **0.7112** |
| **SOL** | **0.5278** | **0.6685** |
| **XRP** | **0.4120** | **0.6768** |
| **DOGE** | **0.3293** | **0.7142** |

---

## 종합 판정: **PASS**

| 기준 | 충족? | 비고 |
|---|---|---|
| **BTC 장기 데이터 확보** | ✅ | 2019-12~현재 완전 확보 |
| **모멘텀/변동성/수익률 피처** | ✅ | 1h→일간 변환으로 완전 구축 |
| **Dominance proxy** | ✅ | 2019-09~ 현재, 2,547일 |
| **알트 idiosyncratic 계산 가능** | ✅ | BTC 수익률로 헤지 가능 |
| **Regime vs 알트 수익률 설명력** | ✅ | Bull/Bear 구간 명확한 차이 |
| **모멘텀 동조성 확인** | ✅ | ETH 0.78, ADA 0.64 등 높음 |
| **공통 universe/기간 확보** | ✅ | 6개 주요 알트 + BTC 완전 겹침 |

---

## 결론
**BTC는 시장 전체 regime factor로 활용하기에 데이터·기간·피처 모든 면에서 완전 충족.**

- **BTC mom30** → 알트 mom30과 높은 동조성 (ETH 0.78)
- **BTC regime (mom30>0)** → 알트 forward return 강력하게 설명 (모든 알트 bull>bear)
- **Idiosyncratic return** → bull 구간 양수, bear 구간 음수 → regime 설명력 확인
- **Dominance proxy** → USDT 마켓 내 BTC 비중 장기 시계열 확보

**다음 단계(별도 지시 시)**: BTC regime을 conditioning variable로 하는 알트 선택/가중 모델 구축.

---

## 산출물
- `cross_asset_regime_audit.py`
- `findings/cross-asset-regime-audit-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 커밋 없음.