'use strict';
const assert = require('assert');
const { classify } = require('../lib/eventClassifiers/dart');
const { reduce } = require('../lib/stateReducer');
const { buildEvent } = require('../lib/eventBuilders/dart');
const stateMapPolicy = require('../config/policies/stateMap.v1.json');

const base = { ticker: '005930', listingStatus: 'NORMAL', tradingState: 'NORMAL', riskStates: [], activeMeta: [] };
const iso = (d) => `${d}T00:00:00+09:00`;

// classify()
assert.strictEqual(classify('관리종목지정'), 'MANAGEMENT_DESIGNATION');
assert.strictEqual(classify('관리종목지정해제'), 'MANAGEMENT_RELEASE');
assert.strictEqual(classify('매매거래정지'), 'TRADING_HALT');
assert.strictEqual(classify('매매거래정지해제'), 'TRADING_RESUME');
assert.strictEqual(classify('상장폐지실질심사대상결정'), 'DELISTING_REVIEW');
assert.strictEqual(classify('현금ㆍ현물배당결정'), null);

// 지정 → 해제 원상복구
let s = reduce(base, { type: 'MANAGEMENT_DESIGNATION', occurredAt: iso('2026-07-01') }, stateMapPolicy);
assert.strictEqual(s.listingStatus, 'MANAGED');
s = reduce(s, { type: 'MANAGEMENT_RELEASE', occurredAt: iso('2026-07-15') }, stateMapPolicy);
assert.strictEqual(s.listingStatus, 'NORMAL');

// TTL 메타데이터
s = reduce(base, { type: 'MEZZANINE_ISSUED', occurredAt: iso('2026-07-15') }, stateMapPolicy);
assert.deepStrictEqual(s.riskStates, ['MEZZANINE_ACTIVE']);
assert.strictEqual(s.activeMeta[0].ttlDays, 30);

// 매핑 없는 이벤트 → 상태 불변
assert.deepStrictEqual(reduce(base, { type: 'UNKNOWN', occurredAt: iso('2026-07-01') }, stateMapPolicy), base);

// remove 경로 + remove→remove 멱등성
let w = reduce(base, { type: 'INVESTMENT_WARNING', occurredAt: iso('2026-07-01') }, stateMapPolicy);
assert.deepStrictEqual(w.riskStates, ['INVESTMENT_WARNING']);
w = reduce(w, { type: 'INVESTMENT_WARNING_RELEASE', occurredAt: iso('2026-07-10') }, stateMapPolicy);
assert.deepStrictEqual(w.riskStates, []);
const w2 = reduce(w, { type: 'INVESTMENT_WARNING_RELEASE', occurredAt: iso('2026-07-11') }, stateMapPolicy);
assert.deepStrictEqual(w2.riskStates, []);

// 동일 이벤트(add) 중복 적용 → 증식 없음
const mezzEvent = { type: 'MEZZANINE_ISSUED', occurredAt: iso('2026-07-15') };
let m1 = reduce(base, mezzEvent, stateMapPolicy);
let m2 = reduce(m1, mezzEvent, stateMapPolicy);
assert.strictEqual(m2.riskStates.length, 1);
assert.strictEqual(m2.activeMeta.length, 1);

// 잘못된 입력 → 즉시 실패
assert.throws(() => reduce(base, { type: 'X' }, null));
assert.throws(() => reduce(base, {}, stateMapPolicy));
assert.throws(() => reduce(base, { type: 'MEZZANINE_ISSUED' }, stateMapPolicy));
assert.throws(() => reduce({ ticker: '005930' }, { type: 'MEZZANINE_ISSUED', occurredAt: iso('2026-07-01') }, stateMapPolicy));

// buildEvent() 계약 검증
assert.throws(() => buildEvent({ stock_code: '005930', rcept_no: '1', report_nm: '관리종목지정', rcept_dt: '202607' }));
assert.throws(() => buildEvent({ rcept_no: '1', report_nm: '관리종목지정', rcept_dt: '20260701' }));
assert.throws(() => buildEvent({ stock_code: '005930', report_nm: '관리종목지정', rcept_dt: '20260701' }));

const built = buildEvent({ stock_code: '005930', rcept_no: '2026071500123', report_nm: '관리종목지정', rcept_dt: '20260715' });
assert.strictEqual(built.type, 'MANAGEMENT_DESIGNATION');
assert.strictEqual(built.occurredAt, '2026-07-15T00:00:00+09:00');
assert.strictEqual(built.eventId, 'dart:2026071500123');

console.log('✅ State Infrastructure 전체 통과');
