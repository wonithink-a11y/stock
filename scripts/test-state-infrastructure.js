'use strict';
/**
 * @file scripts/test-state-infrastructure.js
 * State Infrastructure Test Script
 */
const assert = require('assert');
const { classify } = require('../lib/eventClassifiers/dart');
const { buildEvents } = require('../lib/eventBuilders/dart');
const { reduce, initState } = require('../lib/stateReducer');
const P = require('../config/policies/stateMap.v1.json');

const iso = (d) => `${d}T00:00:00+09:00`;
const ev = (type, date, key, id) => ({ type, occurredAt: iso(date), sortKey: key, eventId: id });
const base = () => initState('005930');

// ---- classify(): 배열 반환 ----
assert.deepStrictEqual(classify('관리종목지정'), ['MANAGEMENT_DESIGNATION']);
assert.deepStrictEqual(classify('관리종목지정해제'), ['MANAGEMENT_RELEASE']);
assert.deepStrictEqual(classify('관리종목지정예고'), ['MANAGEMENT_DESIGNATION_PENDING']);
assert.deepStrictEqual(classify('매매거래정지'), ['TRADING_HALT']);
assert.deepStrictEqual(classify('매매거래정지해제'), ['TRADING_RESUME']);
assert.deepStrictEqual(classify('상장폐지실질심사대상결정'), ['DELISTING_REVIEW']);
assert.deepStrictEqual(classify('상장폐지이의신청'), ['DELISTING_REVIEW_PENDING']);   // 회귀 방지 핵심
assert.deepStrictEqual(classify('상장폐지사유해소'), ['DELISTING_REVIEW_RELEASE']);
assert.deepStrictEqual(classify('관리종목지정및매매거래정지'),
  ['MANAGEMENT_DESIGNATION', 'TRADING_HALT']);                             // 복합 공시
assert.deepStrictEqual(classify('현금ㆍ현물배당결정'), []);
assert.deepStrictEqual(classify(null), []);

// ---- 지정 → 해제 원상복구 ----
let s = reduce(base(), ev('MANAGEMENT_DESIGNATION', '2026-07-01', '20260701:A:00', 'a'), P);
assert.strictEqual(s.listingStatus, 'MANAGED');
assert.strictEqual(s.schemaVersion, 'ST-1.0');
s = reduce(s, ev('MANAGEMENT_RELEASE', '2026-07-15', '20260715:B:00', 'b'), P);
assert.strictEqual(s.listingStatus, 'NORMAL');

// ---- REDUCE-006: 역순 이벤트 무시 ----
const fwd = reduce(base(), ev('MANAGEMENT_DESIGNATION', '2026-07-01', '20260701:A:00', 'a'), P);
const back = reduce(fwd, ev('MANAGEMENT_RELEASE', '2026-06-01', '20260601:B:00', 'b'), P);
assert.strictEqual(back.listingStatus, 'MANAGED');
assert.strictEqual(back, fwd);                               // 동일 참조 = 무변경

// ---- 재실행 멱등 (같은 sortKey 재적용) ----
const again = reduce(fwd, ev('MANAGEMENT_DESIGNATION', '2026-07-01', '20260701:A:00', 'a'), P);
assert.strictEqual(again, fwd);

// ---- 미매핑 이벤트: 상태 불변 + 커서만 전진 ----
const pend = reduce(base(), ev('MANAGEMENT_DESIGNATION_PENDING', '2026-07-02', '20260702:C:00', 'c'), P);
assert.strictEqual(pend.listingStatus, 'NORMAL');
assert.strictEqual(pend.lastSortKey, '20260702:C:00');

// ---- TTL 메타데이터 ----
const mz = reduce(base(), ev('MEZZANINE_ISSUED', '2026-07-15', '20260715:D:00', 'd'), P);
assert.deepStrictEqual(mz.riskStates, ['MEZZANINE_ACTIVE']);
assert.strictEqual(mz.activeMeta[0].ttlDays, 30);

// ---- remove 경로 + 멱등성 ----
let w = reduce(base(), ev('INVESTMENT_WARNING', '2026-07-01', '20260701:E:00', 'e'), P);
assert.deepStrictEqual(w.riskStates, ['INVESTMENT_WARNING']);
w = reduce(w, ev('INVESTMENT_WARNING_RELEASE', '2026-07-10', '20260710:F:00', 'f'), P);
assert.deepStrictEqual(w.riskStates, []);
w = reduce(w, ev('INVESTMENT_WARNING_RELEASE', '2026-07-11', '20260711:G:00', 'g'), P);
assert.deepStrictEqual(w.riskStates, []);

// ---- DELISTING_REVIEW 복귀 경로 (SM-1.1) ----
let d = reduce(base(), ev('DELISTING_REVIEW', '2026-07-01', '20260701:H:00', 'h'), P);
assert.strictEqual(d.tradingState, 'DELISTING_REVIEW');
d = reduce(d, ev('DELISTING_REVIEW_RELEASE', '2026-07-20', '20260720:I:00', 'i'), P);
assert.strictEqual(d.tradingState, 'NORMAL');

// ---- 잘못된 입력 → 즉시 실패 ----
assert.throws(() => reduce(base(), ev('X', '2026-07-01', 'k', 'x'), null));
assert.throws(() => reduce(base(), {}, P));
assert.throws(() => reduce(base(), { type: 'MEZZANINE_ISSUED' }, P));
assert.throws(() => reduce(base(), { type: 'MEZZANINE_ISSUED', occurredAt: iso('2026-07-01') }, P)); // sortKey 누락
assert.throws(() => reduce({ ticker: '005930' }, ev('MEZZANINE_ISSUED', '2026-07-01', 'k', 'x'), P));

// ---- buildEvents() 계약 ----
assert.throws(() => buildEvents({ stock_code: '005930', rcept_no: '1', report_nm: '관리종목지정', rcept_dt: '202607' }));
assert.throws(() => buildEvents({ rcept_no: '1', report_nm: '관리종목지정', rcept_dt: '20260701' }));
assert.throws(() => buildEvents({ stock_code: '005930', report_nm: '관리종목지정', rcept_dt: '20260701' }));

const built = buildEvents({ stock_code: '005930', rcept_no: '2026071500123',
  report_nm: '관리종목지정 및 매매거래정지', rcept_dt: '20260715' });
assert.strictEqual(built.length, 2);
assert.strictEqual(built[0].eventId, 'dart:2026071500123#0');
assert.strictEqual(built[1].eventId, 'dart:2026071500123#1');   // eventId 충돌 방지
assert.strictEqual(built[0].sortKey, '20260715:2026071500123:00');
assert.strictEqual(built[1].sortKey, '20260715:2026071500123:01');
assert.strictEqual(built[0].occurredAt, '2026-07-15T00:00:00+09:00');
assert.strictEqual(built[0].eventSchemaVersion, 'EV-1.0');
assert.strictEqual(built[0].classifierVersion, 'DC-1.2');
assert.deepStrictEqual(buildEvents({ stock_code: '005930', rcept_no: '1',
  report_nm: '현금배당결정', rcept_dt: '20260715' }), []);

// ---- 복합 공시 순차 적용 ----
let c = base();
for (const e of built) c = reduce(c, e, P);
assert.strictEqual(c.listingStatus, 'MANAGED');
assert.strictEqual(c.tradingState, 'HALTED');

console.log('✅ State Infrastructure 전체 통과');
