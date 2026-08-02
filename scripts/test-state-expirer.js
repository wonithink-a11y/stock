#!/usr/bin/env node
/**
 * STEP3 stateExpirer 회귀 테스트
 *   node scripts/test-state-expirer.js
 *
 * 만료는 Reducer가 아니라 이 모듈만 수행한다. REDUCE-007이 activatedAt을 고정하므로
 * 여기가 틀리면 위험 상태가 영구히 남거나(감점 과잉) 새 위험이 즉시 사라진다(감점 누락).
 */
'use strict';
const assert = require('assert');
const { reduce, initState } = require('../lib/stateReducer');
const { expireState } = require('../lib/stateExpirer');
const P = require('../config/policies/stateMap.v1.json');

const iso = (d) => `${d}T00:00:00+09:00`;
const ev = (type, date, key, id) => ({ type, occurredAt: iso(date), sortKey: key, eventId: id });
const day = (n) =>
  new Date(Date.parse(iso('2026-07-01')) + n * 86400000 + 9 * 3600e3)
    .toISOString().replace(/\.\d{3}Z$/, '+09:00');

let s = reduce(initState('005930'), ev('MEZZANINE_ISSUED', '2026-07-01', '20260701:P:00', 'p'), P);
s = reduce(s, ev('INVESTMENT_WARNING', '2026-07-02', '20260702:Q:00', 'q'), P);   // ttlDays 없음

// ---- 만료 경계 (ttlDays 30) ----
assert.strictEqual(expireState(s, day(29)), s);                     // 미만료 → 동일 참조 = 파일 쓰기 없음
const gone = expireState(s, day(30));                               // 정확히 30일차에 만료
assert.deepStrictEqual(gone.riskStates, ['INVESTMENT_WARNING']);    // TTL 없는 위험은 남는다
assert.deepStrictEqual(gone.activeMeta.map((m) => m.code), ['INVESTMENT_WARNING']);
assert.strictEqual(expireState(gone, day(60)), gone);               // 멱등

// ---- 커서 보호: 만료는 이벤트가 아니다 (REDUCE-006 단조 증가 유지) ----
assert.strictEqual(gone.lastSortKey, s.lastSortKey);
assert.strictEqual(gone.lastEventId, s.lastEventId);
assert.strictEqual(gone.updatedAt, day(30));

// ---- ttlDays 규약: null/undefined만 "만료 없음", 0은 즉시 만료 ----
const mk = (ttlDays) => ({
  ...s, riskStates: ['X_ACTIVE'],
  activeMeta: [{ code: 'X_ACTIVE', activatedAt: iso('2026-07-01'), ttlDays }],
});
assert.deepStrictEqual(expireState(mk(0), day(0)).riskStates, []);      // 0 = 즉시 만료
assert.deepStrictEqual(expireState(mk(null), day(999)).riskStates, ['X_ACTIVE']);
assert.deepStrictEqual(expireState(mk(undefined), day(999)).riskStates, ['X_ACTIVE']);

// ---- 삭제보다 보존 ----
// meta가 없는 riskStates(구버전·수동 주입)는 만료 대상이 아니다
const orphan = { ...s, riskStates: [...s.riskStates, 'LEGACY_RISK'] };
assert.ok(expireState(orphan, day(30)).riskStates.includes('LEGACY_RISK'));
// activatedAt 판독 불가 → 유지. 파싱 실패로 위험을 지우지 않는다
const bad = { ...s, activeMeta: [{ code: 'MEZZANINE_ACTIVE', activatedAt: 'x', ttlDays: 30 }] };
assert.strictEqual(expireState(bad, day(999)), bad);

// ---- 잘못된 입력 → 즉시 실패 ----
assert.throws(() => expireState(s, 'not-a-date'));
assert.throws(() => expireState({ ticker: '005930' }, day(0)));
assert.throws(() => expireState({ ...s, riskStates: null }, day(0)));

console.log('✅ stateExpirer 전체 통과');
