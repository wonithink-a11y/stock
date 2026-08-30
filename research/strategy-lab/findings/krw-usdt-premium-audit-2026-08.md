---
track: crypto
factor: krw-usdt-premium-audit
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: CONDITIONAL
criteria_version: backfill-v1
reason: "공통 11종목 1195일 확보·타임스탬프 1일 shift로 해결 가능하나 USDT/KRW 환율 데이터 전무로 김치프리미엄 계산 불가 - 환율 확보가 선결 조건"
---
# Step 29 — KRW/USDT Cross-Market Premium Audit

날짜: 2026-08-29 | 판정: **CONDITIONAL**

## 핵심 결과

### 1. 데이터 가용성

| 데이터 | 종목 수 | 기간 (2023-05-21~) | 비고 |
|---|---|---|---|
| **Upbit KRW daily** | 15개 | 11개 종목 1195일 (2023-05-21~2026-08-27) | MATIC 0행, OP 2025-07~, UNI 2024-10~ |
| **Binance USDT 1h→daily** | 28개 | **전 종목 2019~2020부터** (1195일+) | basis/1h mark_close 14:00 UTC → KST 24:00 재구성 |
| **공통 종목** | **14개** (MATIC 제외) | 11개 종목 1195일 완전 겹침 | MATIC은 KRW 데이터 없음 |
| **USDT/KRW 환율** | **없음** | — | **기존 데이터에 전혀 없음** |

### 2. 공통 종목 상세 (14개)

| 심볼 | KRW 시작 | USDT 시작 | 2023-05-21~ 공통일수 |
|---|---|---|---|
| BTC, ETH, XRP, ADA, DOGE, DOT, ATOM, AVAX, LINK, NEAR, ARB | 2023-05-21 | 2019-12~2020-02 | **1195일** |
| OP | 2025-07-28 | 2022-06-01 | 396일 |
| UNI | 2024-10-22 | 2020-09-17 | 675일 |
| MATIC | **데이터 없음** | 2019-12-23 | — |

### 3. 타임스탬프 정렬 문제 (Critical)

| 시장 | 데이터 시점 | 해석 |
|---|---|---|
| **Upbit KRW** | KST 00:00 (당일 00:00) | `candle_date_time_kst` 기준 일봉 종가 |
| **Binance USDT** | KST 24:00 (=UTC 15:00) | basis/1h 14:00 UTC 바 종가 = KST 24:00 마감 |

→ **KRW 00:00 종가 vs USDT 24:00 종가 = 24시간 시차 존재**  
동일 KST 날짜 `d`에 대해:
- KRW close(d) = KST d일 00:00 종가 (사실상 d-1일 종가)
- USDT close(d) = KST d일 24:00 종가 (d일 실제 종가)

**→ 동일 `date` 인덱스로 join 시 1일 시차 발생 → lookahead 위험**  
해결: KRW를 1일 shift하거나 USDT를 1일 shift하여 경제적 동시 시점 정렬 필요.

### 4. 환율 데이터 (Critical Blocker)

**기존 데이터에 USDT/KRW 환율 데이터 전혀 없음**  
- `data/crypto/`, `data/fx/`, 루트 어디에도 `usdtkrw` 파일 없음
- 프리미엄 공식 `KRW_premium = KRW_price / (USDT_price × USDTKRW) - 1` 계산 불가

### 5. 프리미엄 시뮬레이션 (환율=1 가정 시)

| 심볼 | mean premium | std | 비고 |
|---|---|---|---|
| BTC | **+1418%** | 64% | USD=KRW 1:1 가정 시 터무니없는 값 |
| ETH | +1418% | 67% | 실제 USD/KRW ≈ 1300~1400 적용 필요 |
| SOL | +1418% | 71% | 환율 곱셈 없으면 무의미 |

**→ 환율 데이터 없이는 김치프리미엄 계산 불가능**

---

## 판정: **CONDITIONAL**

### 조건부 통과 사유
| 조건 | 충족? | 비고 |
|---|---|---|
| 2023-05-21~ 공통 종목 ≥ 10개 | ✅ | 11개 종목 1195일 완전 겹침 |
| USDT 데이터 깊이 충분 | ✅ | 2019~ 전 종목 확보 |
| KRW 데이터 품질 | ⚠️ | OP/UNI 부분, MATIC 없음 |
| **환율 데이터 확보 필요** | ❌ | **필수 선결 과제** |
| 타임스탬프 정렬 해결 가능 | ✅ | 1일 shift로 해결 가능 |

### 해결 필요 사항 (PASS 조건)
1. **USDT/KRW 환율 데이터 확보** (외부 소스 조사·수집 필요)
   - 후보: 한국은행/한국수출입은행 환율 API, 코인마켓캡/코인게코 FX, 업비트/빗썸 KRW-USDT 마켓
2. **타임스탬프 정렬 규칙 확정**
   - 권장: KRW close(d) → shift(1) 하여 d일 24:00 기준과 맞춤 (또는 USDT를 shift(-1))
3. **MATIC 제외, OP/UNI 부분 구간 별도 처리**

---

## 다음 단계 권고

1. **Step 29.1** (별도 지시 시): USDT/KRW 환율 데이터 소스 조사·수집 (한은 ECOS, CoinGecko API 등)
2. **Step 29.2**: 정렬 규칙 적용 후 실제 김치프리미엄 시계열 생성 및 기초 통계
3. **Step 29.3**: 프리미엄의 예측력/회귀성 검증 (별도 지시 시)

---

## 산출물

- 신규: `krw_usdt_premium_audit.py`
- 신규: `findings/krw-usdt-premium-audit-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 대량 수집·백테스트·커밋 없음.