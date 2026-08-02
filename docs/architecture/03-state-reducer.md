# State Reducer — 아키텍처 계약

## 목적
공시 등 외부 이벤트를 종목별 "현재 상태"로 환원한다. 이벤트(발생 시점의 사실)와
상태(지금 유효한 결과)를 분리해, RiskPenalty·TradingPolicy가 원시 공시를 몰라도
`currentState`만 보고 판단할 수 있게 한다.

## 입력 계약 (Event Schema)
```json
{
  "eventId": "dart:2026071500123",
  "ticker": "005930",
  "type": "MANAGEMENT_DESIGNATION",
  "occurredAt": "2026-07-15T00:00:00+09:00",
  "source": "dart",
  "payload": { "reportNm": "관리종목지정" }
}
```
`occurredAt`은 ISO8601 필수. `type`은 소스별 classifier가 생성, Reducer는 원문을 직접 해석하지 않는다.

## 출력 계약 (State Schema)
```json
{
  "ticker": "005930",
  "listingStatus": "NORMAL",
  "tradingState": "NORMAL",
  "riskStates": ["MEZZANINE_ACTIVE"],
  "activeMeta": [{ "code": "MEZZANINE_ACTIVE", "activatedAt": "2026-07-15T00:00:00+09:00", "ttlDays": 30 }],
  "updatedAt": "2026-07-15T00:00:00+09:00"
}
```
전체 이벤트 이력은 `data/state-history/{ticker}.jsonl`(append-only)에 별도 보관.

## activeMeta 키 규칙
`code` 단독이 유니크 키. 동일 code 다건 동시추적이 필요해지면 (code, sourceEventId) 등 복합키로 전환 — 별도 STEP.

## Reducer Invariants
- REDUCE-001 동일 이벤트 N회 적용 = 1회 적용 (멱등성)
- REDUCE-002 미매핑 event.type은 상태 불변
- REDUCE-003 계약 위반 시 즉시 throw
- REDUCE-004 activeMeta는 code 오름차순 정렬
- REDUCE-005 prevState는 { riskStates: array, activeMeta: array } 형태 필수

## 비목표
TTL 계산(`stateExpirer.js` 책임) · RiskPenalty 계산 · TradingPolicy 판정 · 파일 I/O · 날짜 포맷 변환(Event Builder 책임) — 전부 Reducer가 하지 않음.

## Event Builder Contract
**Input**: 소스별 원시 공시. **Output**: Event | null.
**Responsibilities**: type 결정, occurredAt ISO8601 변환, eventId 생성, 필수필드 검증, 무관 공시는 null.
**Never**: state 변경, RiskPenalty/TradingPolicy 계산, 파일 I/O.
기준 구현: `lib/eventBuilders/dart.js`. 새 소스는 동일 시그니처로 `lib/eventBuilders/{source}.js` 추가.

## Acceptance Criteria
`scripts/test-state-infrastructure.js` 참조.
