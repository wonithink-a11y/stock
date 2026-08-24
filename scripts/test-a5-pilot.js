#!/usr/bin/env node
/**
 * scripts/build-a5-pilot.js의 computeForward() 회귀 — fwdStatus 5분기
 * (FUTURE>EXIT>MISSING>HALTED>OK, 설계안 §2)를 합성 데이터로 확인한다.
 * 네트워크·실데이터 없이 돈다.
 */
'use strict';

const { computeForward } = require('./build-a5-pilot');

const tradingDays = [];
for (let i = 0; i < 30; i++) tradingDays.push(`2026-01-${String(i + 1).padStart(2, '0')}`);
const dateIndex = new Map(tradingDays.map((d, i) => [d, i]));
const prices = {
  '2026-01-01': { close: 100, volume: 1000 },
  '2026-01-21': { close: 110, volume: 1000 }, // +20 offset → OK
};
const findPrice = (t, d) => prices[d] || null;

let ok = true;
const chk = (cond, msg) => { console.log((cond ? '  OK  ' : '  FAIL') + '  ' + msg); if (!cond) ok = false; };

// FUTURE: horizon이 캘린더 끝을 넘으면 FUTURE
{
  const r = computeForward({ ticker: 'X', asOf: tradingDays[25], exitAtConfirmed: null,
    tradingDays, dateIndex, findPrice, snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'FUTURE' && r.fwd.d20 === null, 'FUTURE: horizon이 캘린더 끝을 넘으면 FUTURE');
}
// EXIT: 목표일이 exitAtConfirmed 이후
{
  const r = computeForward({ ticker: 'X', asOf: '2026-01-01', exitAtConfirmed: '2026-01-10',
    tradingDays, dateIndex, findPrice, snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'EXIT' && r.fwd.d20 === null, 'EXIT: 목표일이 exitAtConfirmed 이후면 EXIT');
}
// MISSING: 가격 자체가 없음
{
  const r = computeForward({ ticker: 'X', asOf: '2026-01-01', exitAtConfirmed: null,
    tradingDays, dateIndex, findPrice: () => null, snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'MISSING' && r.fwd.d20 === null, 'MISSING: 목표일 가격이 없으면 MISSING');
}
// HALTED: volume 0인 날이 끼면(returnTransition requireBothVolumePositive)
{
  const r = computeForward({ ticker: 'X', asOf: '2026-01-01', exitAtConfirmed: null,
    tradingDays, dateIndex, findPrice: () => ({ close: 100, volume: 0 }), snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'HALTED' && r.fwd.d20 === null, 'HALTED: volume 0인 날이 끼면 HALTED');
}
// OK: 정상 수익률
{
  const r = computeForward({ ticker: 'X', asOf: '2026-01-01', exitAtConfirmed: null,
    tradingDays, dateIndex, findPrice, snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'OK' && r.fwd.d20 === 0.1, 'OK: (110-100)/100 = 0.1');
}
// 우선순위: EXIT가 MISSING보다 먼저(목표일 가격도 없고 exitAtConfirmed도 지났을 때)
{
  const r = computeForward({ ticker: 'X', asOf: '2026-01-01', exitAtConfirmed: '2026-01-02',
    tradingDays, dateIndex, findPrice: () => null, snapshotPrice: { close: 100, volume: 1000 } });
  chk(r.fwdStatus.d20 === 'EXIT', '우선순위: EXIT가 MISSING보다 먼저 판정된다');
}

console.log(ok ? '\n전체 통과' : '\n실패');
process.exit(ok ? 0 : 1);
