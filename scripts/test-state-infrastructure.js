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

// ---- REDUCE-007: 같은 위험 재발생 시 TTL 재설정 금지 ----
// 유상증자결정 → 발행가액 → 청약결과 → 발행결과가 두 달에 걸쳐 들어와도 만료 기준일은 첫 건이다.
let ro = reduce(base(), ev('RIGHTS_OFFERING', '2026-07-01', '20260701:J:00', 'j'), P);
const firstActivatedAt = ro.activeMeta[0].activatedAt;
assert.strictEqual(firstActivatedAt, iso('2026-07-01'));
for (const [date, key, id] of [['2026-07-20', '20260720:K:00', 'k'],
                               ['2026-08-05', '20260805:L:00', 'l'],
                               ['2026-08-25', '20260825:M:00', 'm']]) {
  const prev = ro;
  ro = reduce(ro, ev('RIGHTS_OFFERING', date, key, id), P);
  assert.notStrictEqual(ro, prev);                        // 이벤트는 기록된다(appendHistory 실행)
  assert.strictEqual(ro.lastSortKey, key);                // 커서는 전진한다
  assert.strictEqual(ro.updatedAt, iso(date));
}
assert.strictEqual(ro.activeMeta.length, 1);
assert.strictEqual(ro.activeMeta[0].activatedAt, firstActivatedAt);  // TTL 기준일 불변
assert.strictEqual(ro.activeMeta[0].ttlDays, 30);
// 해제 후 재발생은 새 activatedAt이어야 한다
let ro2 = reduce(base(), ev('MEZZANINE_ISSUED', '2026-07-01', '20260701:N:00', 'n'), P);
ro2 = { ...ro2, riskStates: [], activeMeta: [] };          // stateExpirer가 만료시킨 상황
ro2 = reduce(ro2, ev('MEZZANINE_ISSUED', '2026-09-01', '20260901:O:00', 'o'), P);
assert.strictEqual(ro2.activeMeta[0].activatedAt, iso('2026-09-01'));

// ---- STEP3 stateExpirer: TTL 만료 ----
const { expireState } = require('../lib/stateExpirer');
const day = (n) => new Date(Date.parse(iso('2026-07-01')) + n * 86400000 + 9 * 3600e3).toISOString().replace(/\.\d{3}Z$/, '+09:00');
let ex = reduce(base(), ev('MEZZANINE_ISSUED', '2026-07-01', '20260701:P:00', 'p'), P);
ex = reduce(ex, ev('INVESTMENT_WARNING', '2026-07-02', '20260702:Q:00', 'q'), P);   // ttlDays 없음
assert.strictEqual(expireState(ex, day(29)), ex);                       // 미만료 → 동일 참조 = 쓰기 없음
const gone = expireState(ex, day(30));                                  // 정확히 30일차에 만료
assert.deepStrictEqual(gone.riskStates, ['INVESTMENT_WARNING']);        // TTL 없는 위험은 남는다
assert.deepStrictEqual(gone.activeMeta.map((m) => m.code), ['INVESTMENT_WARNING']);
assert.strictEqual(gone.lastSortKey, ex.lastSortKey);                   // 이벤트 커서 불변(REDUCE-006 보호)
assert.strictEqual(gone.updatedAt, day(30));
assert.strictEqual(expireState(gone, day(60)), gone);                   // 멱등
// meta 없는 riskStates는 임의 삭제하지 않는다
const orphan = { ...ex, riskStates: [...ex.riskStates, 'LEGACY_RISK'] };
assert.ok(expireState(orphan, day(30)).riskStates.includes('LEGACY_RISK'));
// activatedAt 판독 불가 → 유지
const bad = { ...ex, activeMeta: [{ code: 'MEZZANINE_ACTIVE', activatedAt: 'x', ttlDays: 30 }] };
assert.strictEqual(expireState(bad, day(999)), bad);
assert.throws(() => expireState(ex, 'not-a-date'));

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
assert.strictEqual(built[0].classifierVersion, 'DC-1.3');
assert.deepStrictEqual(buildEvents({ stock_code: '005930', rcept_no: '1',
  report_nm: '현금배당결정', rcept_dt: '20260715' }), []);

// ---- 복합 공시 순차 적용 ----
let c = base();
for (const e of built) c = reduce(c, e, P);
assert.strictEqual(c.listingStatus, 'MANAGED');
assert.strictEqual(c.tradingState, 'HALTED');

console.log('✅ State Infrastructure 전체 통과');
