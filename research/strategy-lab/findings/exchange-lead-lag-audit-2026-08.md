---
track: crypto
factor: exchange-lead-lag-audit
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: CONDITIONAL
criteria_version: backfill-v1
reason: "Daily lead-lag 연구 가능(KRW shift(1) 필수·14종목 1195일), 4h는 5.5개월 표본 부족, 1h는 KRW 데이터 없음 - 데이터 감사 결과"
---
# Step 30 — Exchange Lead-Lag Audit (Upbit KRW ↔ Binance USDT)

날짜: 2026-08-29 | 판정: **CONDITIONAL**

## 핵심 결과

### 1. 데이터 가용성

| 데이터 | 종목 | 기간 | 비고 |
|---|---|---|---|
| **Upbit KRW daily** | 15개 | 11개 1195일 (2023-05-21~) | MATIC 0행, OP 2025-07~, UNI 2024-10~ |
| **Upbit KRW 4h** | 15개 | **2026-03-16~ (≈5.5개월, 988바)** | 짧은 창 |
| **Binance USDT 1h→daily** | 28개 | 2019-12~ (전 종목) | basis/1h mark_close 14:00 UTC → KST 24:00 |
| **Binance USDT 1h→4h** | 28개 | 2019-12~ (전 종목) | KST 4h 리샘플 가능 |

### 2. 공통 종목 및 기간

| 해상도 | 공통 종목 | 공통 기간 (2023-05-21~) | 종목 수 |
|---|---|---|---|
| **Daily** | 14개 (MATIC 제외) | 11개 1195일, OP 396일, UNI 675일 | **14개** |
| **4h** | 14개 | **2026-03-16~ (≈5.5개월, 988바)** | 14개 |
| **1h** | — | — | **KRW 1h 데이터 없음** |

### 3. 타임스탬프 정렬 (Critical)

| 시장 | 데이터 시점 | 정렬 필요 작업 |
|---|---|---|
| **Upbit KRW daily** | KST 00:00 (당일 00:00) | `shift(1)` 하여 24:00 기준과 맞춤 |
| **Binance USDT daily** | KST 24:00 (=14:00 UTC 바 종가) | 기준 시점 (이미 24:00) |
| **Upbit KRW 4h** | KST 00,04,08,12,16,20시 | UTC 변환(-9h) 후 비교 |
| **Binance USDT 4h** | KST 00,04,08,12,16,20시 (리샘플) | KST 그대로 비교 가능 |

**→ Daily: KRW shift(1) 필요 (1일 시차)**  
**→ 4h: KRW를 UTC(-9h) 변환 후 비교 가능**

### 4. Lead-Lag 연구 가능성

| 해상도 | 가능 여부 | 공통 기간 | 제약 |
|---|---|---|---|
| **Daily** | ✅ 가능 | 11개 종목 1195일 | **KRW shift(1) 필수** |
| **4h** | ✅ 가능 (제약) | 2026-03-16~ (5.5개월, 988바) | **기간 매우 짧음** |
| **1h** | ❌ 불가 | — | KRW 1h 데이터 없음 |

---

## 판정: **CONDITIONAL**

### 통과 조건
| 기준 | 충족? | 비고 |
|---|---|---|
| Daily lead-lag 연구 가능 | ✅ | 14개 종목, 1195일 (KRW shift(1) 적용 시) |
| 4h lead-lag 연구 가능 | ⚠️ | **기간 5.5개월만** (2026-03-16~) |
| 1h lead-lag 연구 가능 | ❌ | KRW 1h 데이터 없음 |
| 장기 연구기간 확보 | ⚠️ | Daily는 충분, 4h는 매우 짧음 |

### 핵심 제약
1. **Daily**: KRW 00:00 vs USDT 24:00 → **KRW shift(1) 필수** (lookahead 방지)
2. **4h**: KRW 4h 데이터가 **2026-03-16부터만 존재** → 장기 연구 불가
3. **1h**: KRW 1h 데이터 없음 → 고빈도 lead-lag 불가

### 권고
- **Daily lead-lag 연구는 즉시 가능** (KRW shift(1) 적용 후 Granger causality, VAR 등 적용)
- **4h 연구는 2026년 이후만 가능** → 표본 부족으로 통계적 유의성 제한적
- **1h 연구 불가** → 향후 Upbit 1h 데이터 수집 필요 시 별도 추진

---

## 산출물
- 신규: `exchange_lead_lag_audit.py`
- 신규: `findings/exchange-lead-lag-audit-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 대량 수집·백테스트·커밋 없음.