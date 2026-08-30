---
track: crypto
factor: crypto-s2-12-asset-oos
verdict: UNCLASSIFIED
original_verdict: WEAK
criteria_version: backfill-v1
conditions: ["bb_squeeze_vol_v1", "12asset_universe"]
reason: "ADD5 신규 5종목 OOS에서 ARB·ATOM·AVAX·LINK 외 NEAR 의존 추가, 12종목 TEST가 CORE7보다 열위, 종목/이벤트 제거 시 음수 반전 - WEAK"
cagr: -3.17
sharpe: -0.23
n: 9
---
# Crypto S2 12종목 독립 OOS 검증 (Step 11)

- 전략: `bb_squeeze_vol_v1` (파라미터·로직 무변경, 최적화 없음)
- 유니버스: CORE7(기존 7종목) + ADD5(ARB/ATOM/AVAX/LINK/NEAR) = ALL12. OP/UNI/MATIC 제외.
- 분할: S1-S6와 동일 TRAIN/VALID/TEST (stored results.json splits_daily와 parity 검증 통과)
- 방식: 별도 runner로 12종목 유니버스 전달. 공용 러너·전략 코드·엔진 무수정. 결과는 별도 파일로 저장.
- 재현검증: CORE7 재계산 == stored results.json 비트 동일 (모든 기간, cost 1x)

## 1. 기간별 성과 매트릭스 (base cost)

| 유니버스 | 구간 | CAGR | MDD | Sharpe | PF | Win% | 거래수 |
|----------|------|------|-----|--------|-----|------|--------|
| CORE7   | FULL  | +5.48% | -13.78% | 0.73 | 2.03 | 50.0% | 20 |
| CORE7   | TRAIN | +6.71% | -2.66% | 1.41 | 3.86 | 62.5% | 8 |
| CORE7   | VALID | +0.56% | -11.47% | 0.11 | 1.05 | 25.0% | 4 |
| CORE7   | TEST  | +5.67% | -8.98% | 0.63 | 1.72 | 50.0% | 8 |
| ADD5    | FULL  | -0.23% | -18.50% | 0.02 | 0.98 | 30.4% | 23 |
| ADD5    | TRAIN | +1.67% | -11.48% | 0.26 | 1.25 | 30.0% | 10 |
| ADD5    | VALID | -2.78% | -9.00% | -0.18 | 0.79 | 25.0% | 4 |
| ADD5    | TEST  | -3.17% | -10.35% | -0.23 | 0.76 | 33.3% | 9 |
| ALL12   | FULL  | +4.05% | -21.91% | 0.37 | 1.30 | 39.5% | 43 |
| ALL12   | TRAIN | +6.17% | -10.61% | 0.71 | 1.72 | 44.4% | 18 |
| ALL12   | VALID | -1.60% | -16.06% | 0.01 | 0.93 | 25.0% | 8 |
| ALL12   | TEST  | +2.51% | -15.09% | 0.23 | 1.13 | 41.2% | 17 |

### TEST Total Return / Calmar 요약

| 유니버스 | TEST Total Return | TEST Calmar | TEST NetPnL(M) |
|----------|------------------|-------------|----------------|
| CORE7   | +4.60% | 0.63 | +460 |
| ADD5    | -2.59% | -0.31 | -259 |
| ALL12   | +2.04% | 0.17 | +204 |

## 2. 비용 sweep (CAGR)

| 유니버스 | 구간 | 0x | 1x | 2x | 4x |
|----------|------|----|----|----|----|
| CORE7   | FULL | +5.70% | +5.48% | +5.29% | +4.90% |
| CORE7   | TEST | +5.99% | +5.67% | +5.35% | +4.58% |
| ADD5    | FULL | -0.04% | -0.23% | -0.42% | -0.81% |
| ADD5    | TEST | -2.86% | -3.17% | -3.48% | -4.08% |
| ALL12   | FULL | +4.42% | +4.05% | +3.71% | +3.03% |
| ALL12   | TEST | +3.09% | +2.51% | +1.93% | +0.79% |

## 3. TEST 종목별 PnL / 거래수

### CORE7

| 종목 | 거래수 | NetPnL(M) | Win% | TEST PnL 대비 기여 |
|------|--------|-----------|------|--------------------|
| KRW-BTC  | 2 | +119 | 50% | +26% |
| KRW-ETH  | 1 | -132 | 0% | -29% |
| KRW-SOL  | 2 | +170 | 50% | +37% |
| KRW-XRP  | 0 | +0 | - | +0% |
| KRW-ADA  | 1 | -258 | 0% | -56% |
| KRW-DOGE | 2 | +561 | 100% | +122% |
| KRW-DOT  | 0 | +0 | - | +0% |

### ADD5

| 종목 | 거래수 | NetPnL(M) | Win% | TEST PnL 대비 기여 |
|------|--------|-----------|------|--------------------|
| KRW-ARB  | 2 | -204 | 50% | +79% |
| KRW-ATOM | 2 | -423 | 0% | +163% |
| KRW-AVAX | 1 | -151 | 0% | +58% |
| KRW-LINK | 2 | -270 | 0% | +104% |
| KRW-NEAR | 2 | +789 | 100% | -304% |

### ALL12

| 종목 | 거래수 | NetPnL(M) | Win% | TEST PnL 대비 기여 |
|------|--------|-----------|------|--------------------|
| KRW-BTC  | 2 | +128 | 50% | +63% |
| KRW-ETH  | 1 | -106 | 0% | -52% |
| KRW-SOL  | 2 | +192 | 50% | +94% |
| KRW-XRP  | 0 | +0 | - | +0% |
| KRW-ADA  | 1 | -258 | 0% | -126% |
| KRW-DOGE | 2 | +499 | 100% | +244% |
| KRW-DOT  | 0 | +0 | - | +0% |
| KRW-ARB  | 2 | -196 | 50% | -96% |
| KRW-ATOM | 2 | -405 | 0% | -198% |
| KRW-AVAX | 1 | -114 | 0% | -56% |
| KRW-LINK | 2 | -235 | 0% | -115% |
| KRW-NEAR | 2 | +699 | 100% | +342% |

### FULL 종목별 (ALL12) — 신규 5종목에서 S2 실제 활동

| 종목 | 거래수 | NetPnL(M) | Win% |
|------|--------|-----------|------|
| KRW-BTC  | 4 | +282 | 50% |
| KRW-ETH  | 2 | -309 | 0% |
| KRW-SOL  | 4 | +270 | 50% |
| KRW-XRP  | 2 | +10 | 50% |
| KRW-ADA  | 1 | -287 | 0% |
| KRW-DOGE | 5 | +1,178 | 80% |
| KRW-DOT  | 2 | +261 | 50% |
| KRW-ARB  | 5 | -914 | 20% |
| KRW-ATOM | 5 | -471 | 20% |
| KRW-AVAX | 3 | -480 | 0% |
| KRW-LINK | 7 | +298 | 29% |
| KRW-NEAR | 3 | +1,547 | 100% |

- 시그널 발생량(FULL, 코인별): KRW-BTC=4, KRW-ETH=2, KRW-SOL=4, KRW-XRP=2, KRW-ADA=1, KRW-DOGE=6, KRW-DOT=2, KRW-ARB=6, KRW-ATOM=5, KRW-AVAX=4, KRW-LINK=8, KRW-NEAR=3

## 4. Leave-one-asset-out (ALL12 TEST)

| 제외 종목 | CAGR | Sharpe | NetPnL(M) | 거래수 |
|-----------|------|--------|-----------|--------|
| (없음, baseline) | +2.51% | 0.23 | +204 | 17 |
| KRW-BTC  | +1.03% | 0.14 | (본 종목 TEST PnL +128M) | 15 |
| KRW-ETH  | +3.94% | 0.33 | (본 종목 TEST PnL -106M) | 16 |
| KRW-SOL  | +0.25% | 0.09 | (본 종목 TEST PnL +192M) | 15 |
| KRW-XRP  | +2.51% | 0.23 | (본 종목 TEST PnL +0M) | 17 |
| KRW-ADA  | +5.94% | 0.44 | (본 종목 TEST PnL -258M) | 16 |
| KRW-DOGE | -3.72% | -0.19 | (본 종목 TEST PnL +499M) | 15 |
| KRW-DOT  | +2.51% | 0.23 | (본 종목 TEST PnL +0M) | 17 |
| KRW-ARB  | +5.26% | 0.41 | (본 종목 TEST PnL -196M) | 15 |
| KRW-ATOM | +6.73% | 0.50 | (본 종목 TEST PnL -405M) | 15 |
| KRW-AVAX | +4.77% | 0.37 | (본 종목 TEST PnL -114M) | 16 |
| KRW-LINK | +6.58% | 0.50 | (본 종목 TEST PnL -235M) | 15 |
| KRW-NEAR | -6.70% | -0.41 | (본 종목 TEST PnL +699M) | 15 |

## 5. Leave-one-event-out (ALL12 TEST)

| 제외 진입일 | CAGR | Sharpe | NetPnL(M) | 거래수 |
|-------------|------|--------|-----------|--------|
| (없음, baseline) | +2.51% | 0.23 | +204 | 17 |
| 2025-12-10 | +5.94% | 0.44 | -258 | 16 |
| 2026-01-04 | +3.47% | 0.30 | -182 | 16 |
| 2026-01-06 | +8.58% | 0.67 | -438 | 13 |
| 2026-02-17 | +5.73% | 0.43 | -223 | 16 |
| 2026-02-26 | -3.79% | -0.19 | +399 | 16 |
| 2026-03-17 | -2.35% | -0.07 | +167 | 17 |
| 2026-04-17 | +3.53% | 0.30 | -213 | 17 |
| 2026-05-07 | -1.47% | -0.02 | +299 | 16 |
| 2026-07-10 | +5.79% | 0.43 | -238 | 16 |
| 2026-08-20 | -8.33% | -0.55 | +890 | 13 |

### 2026-08-20 / DOGE 제거 전후 (명시 사례)

| 케이스 | CAGR | Sharpe | NetPnL(M) | 거래수 |
|--------|------|--------|-----------|--------|
| ALL12 baseline | +2.51% | 0.23 | +204 | 17 |
| 2026-08-20 제거(ALL12) | -8.33% | -0.55 | +890 (해당 event PnL) | 13 |
| KRW-DOGE 제거(ALL12) | -3.72% | -0.19 | +499 (본 종목 PnL) | 15 |
| CORE7 baseline (재산출) | +5.67% | 0.63 | +460 | 8 |
| 2026-08-20 제거(CORE7) | -5.09% | -0.70 |  | 5 |

## 6. 최종 판정

- 1. ADD5 TEST: CAGR=-3.17% Sharpe=-0.23 PF=0.76 N=9 vs CORE7 TEST CAGR=+5.67% N=8
- 2. ADD5 FULL: CAGR=-0.23% N=23 (신규 종목에서 S2 활동량 확인)
- 3. 판정 근거: ADD5-TEST 양수=False, ALL12-TEST 양수=True, 2026-08-20 제거 후 양수=False, DOGE 제거 후 양수=False
- 4. ADD5 TEST -3.17%/PF0.76/N9 (신규 5종목 중 ARB·ATOM·AVAX·LINK 4종목 합 -1,048M vs NEAR +789M 1종목만 수익)
- ALL12-remove-2026-08-20: CAGR=-8.33% Sharpe=-0.55 N=13
- ALL12-remove-DOGE: CAGR=-3.72% Sharpe=-0.19 N=15

### 판정: **WEAK**

- ADD5 TEST -3.17%/PF0.76/N9 (신규 5종목 중 ARB·ATOM·AVAX·LINK 4종목 합 -1,048M vs NEAR +789M 1종목만 수익). 12종목 TEST(+2.51%)는 CORE7(+5.67%)보다 열위이며, 2026-08-20 제거 시 -8.33%, DOGE 제거 시 -3.72%, NEAR 제거 -6.70%로 음수 반전 → 종목/이벤트 의존이 줄어들지 않았고 오히려 신규 NEAR 의존이 추가됨. 비용 4x에서 +0.79%로 간신히 양수.

## 부록. 방법·재현

- 러너: `crypto_s2_12asset_oos_validation.py` (별도 파일, 기존 파일 무수정)
- 데이터: `data/crypto/daily/` 12종목, 전부 2023-05-21~2026-08-27 전체기간 (OP/UNI/MATIC 제외)
- S2 모듈: `strategies/crypto/bb_squeeze_vol_v1/` 로드·무변경, 파라미터 baseline 그대로
- 비용: base 5/5/5 bps, sweep은 동일 배율. Portfolio max 5, equal weight.