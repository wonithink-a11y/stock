---
track: crypto
factor: liquidation-data-audit
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: FAIL
criteria_version: backfill-v1
reason: "Binance 청산 이력 공개 API 없음(forceOrders 401 인증필수·liquidationOrders 404) - historical 조회 불가로 기존 연구 결합 불가"
---
# Step 28 — Binance Liquidation Historical Data 감사

날짜: 2026-08-29 | 판정: **FAIL**

## 테스트 대상 엔드포인트

| endpoint | URL | 인증 | 결과 |
|---|---|---|---|
| `forceOrders` | `GET /fapi/v1/forceOrders` | **필수 (API key)** | **401 Unauthorized** (code -2014) |
| `liquidationOrders` | `GET /fapi/v1/liquidationOrders` | 불명 | **404 Not Found** |

## 상세 결과

### 1. `forceOrders` (`/fapi/v1/forceOrders`)
- **인증 필수**: 모든 호출이 `401` 반환, `code=-2014 "API-key format invalid."`
- 공개 API 아님 → **API key 보유 계정만 조회 가능**
- 시간 경계(probe) 전부 401 → **historical depth 확인 불가**
- 28종목 coverage 0/28 (전부 401)

### 2. `liquidationOrders` (`/fapi/v1/liquidationOrders`)
- **엔드포인트 없음**: 모든 호출이 `404 Not Found` (HTML 에러 페이지 반환)
- Binance 공개 API 문서에도 해당 엔드포인트 없음 (v1/v2 모두)
- 28종목 coverage 0/28 (전부 404)

## 핵심 판정 근거

| 기준 | 결과 |
|---|---|
| **공개 API로 historical 조회 가능** | ❌ (인증 필수 또는 엔드포인트 미존재) |
| **2023-05-21 이전 데이터 조회** | ❌ (엔드포인트 접근 불가) |
| **28종목 공통 사용 가능** | ❌ (0/28) |
| **startTime/endTime pagination** | ❌ (접근 불가) |
| **rate limit / ban 여부** | N/A (접근 불가) |
| **주요 필드 (time, symbol, side, price, qty, notional) 확인** | ❌ (응답 없음) |

## 결론

**Binance USDS-M Futures 공개 API에는 청산(Liquidation) 이력 데이터를 무료·비인증으로 조회할 수 있는 엔드포인트가 존재하지 않는다.**

- `forceOrders`는 **private endpoint**로 API key·서명 필수 → 공개 연구용 불가
- `liquidationOrders`는 **존재하지 않음** (문서·실제 API 모두)
- 대안: WebSocket 스트림(`/fapi/v1/stream?streams=...@forceOrders`)로 실시간 수신만 가능 — **historical backfill 불가**

## 연구 가능성

**현재 형태로는 기존 연구(2023-05-21~현재)와 결합 불가 → FAIL.**

장기 청산 데이터가 필요하다면:
1. **유료 데이터 벤더**(Kaiko, CryptoCompare, Amberdata 등) 구매
2. **자체 수집**: WebSocket 실시간 구독 후 적재 (과거 데이터는 소급 불가)
3. **타 거래소**: Bybit, OKX 등은 공개 liquidation history API 제공 여부 별도 확인 필요

## 산출물

- 신규: `liquidation_data_audit.py`
- 신규: `findings/liquidation-data-audit-2026-08.{json,md}`
- 기존 데이터/전략/findings 무수정, 백테스트·커밋 없음.