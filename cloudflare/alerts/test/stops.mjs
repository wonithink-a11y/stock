// 손절선 이탈 감시·엔진 멈춤 단위 시험.   node cloudflare/alerts/test/stops.mjs
import assert from 'node:assert/strict';
import { repeatDue, evalStops, deadmanDue, stopHit, stopLine, stopId } from '../src/core.js';

let n = 0; const t = (name, f) => { f(); n++; };
const MIN = 60000, T0 = Date.parse('2026-11-16T01:00:00Z');   // 월요일 10:00 KST
const kr = { market: 'KR', symbol: '005930', stop: 70000, name: '삼성전자' };

t('반복 간격: 처음 10분은 매분(10번), 이후 5분마다', () => {
  const sent = []; for (let m = 0; m <= 30; m++) if (repeatDue(m).send) sent.push([m, repeatDue(m).n]);
  assert.deepEqual(sent.slice(0, 10).map((x) => x[0]), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.deepEqual(sent.slice(10).map((x) => x[0]), [10, 15, 20, 25, 30]);
  assert.deepEqual(sent.map((x) => x[1]), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]);
  assert.equal(repeatDue(-1).send, false);
});

t('손절 판정: 기본은 이하, dir=above 는 이상, 경계 포함', () => {
  assert.equal(stopHit(kr, 70000), true); assert.equal(stopHit(kr, 70001), false);
  assert.equal(stopHit({ ...kr, dir: 'above', stop: 100 }, 100), true); assert.equal(stopHit({ ...kr, dir: 'above', stop: 100 }, 99), false);
});

t('이탈 시작 → 매분 반복 → 확인하면 멈춤 → 회복 알림 한 번', () => {
  const id = stopId(kr), P = (px) => ({ [id]: { px } });
  let r = evalStops([kr], P(71000), {}, {}, T0); assert.equal(r.alerts.length, 0); assert.equal(r.changed, false);     // 위쪽: 조용
  r = evalStops([kr], P(69900), r.breach, r.ack, T0 + MIN); assert.equal(r.alerts[0].kind, 'break'); assert.equal(r.alerts[0].n, 1); assert.equal(r.changed, true);
  let st = r;
  r = evalStops([kr], P(69800), st.breach, st.ack, T0 + 2 * MIN); assert.equal(r.alerts[0].kind, 'repeat'); assert.equal(r.alerts[0].n, 2); assert.equal(r.changed, false);
  r = evalStops([kr], P(69800), st.breach, { [id]: T0 + 3 * MIN }, T0 + 4 * MIN); assert.equal(r.alerts.length, 0);       // 확인함(ack ≥ breachAt)
  r = evalStops([kr], P(70500), st.breach, st.ack, T0 + 5 * MIN); assert.equal(r.alerts[0].kind, 'recover'); assert.deepEqual(r.breach, {});
});

t('확인은 그 이탈에만 유효: 회복 뒤 다시 이탈하면 새로 알린다', () => {
  const id = stopId(kr), P = (px) => ({ [id]: { px } });
  let r = evalStops([kr], P(69000), {}, {}, T0);
  r = evalStops([kr], P(69000), r.breach, { [id]: T0 + MIN }, T0 + 2 * MIN); assert.equal(r.alerts.length, 0);
  r = evalStops([kr], P(71000), r.breach, { [id]: T0 + MIN }, T0 + 3 * MIN); assert.equal(r.alerts[0].kind, 'recover'); assert.deepEqual(r.ack, {});
  r = evalStops([kr], P(69000), r.breach, r.ack, T0 + 4 * MIN); assert.equal(r.alerts[0].kind, 'break');
});

t('시세가 없으면(휴장·실패) 상태를 건드리지 않고, 목록에서 빠진 종목은 정리한다', () => {
  const id = stopId(kr);
  let r = evalStops([kr], { [id]: null }, { [id]: T0 }, {}, T0 + MIN); assert.equal(r.alerts.length, 0); assert.deepEqual(r.breach, { [id]: T0 });
  r = evalStops([], {}, { [id]: T0, 'US:X:1': T0 }, { [id]: T0 }, T0 + MIN); assert.deepEqual(r.breach, {}); assert.deepEqual(r.ack, {}); assert.equal(r.changed, true);
});

t('10분 뒤에는 5분 간격으로만 반복', () => {
  const id = stopId(kr); let r = { breach: { [id]: T0 }, ack: {} }; const got = [];
  for (let m = 1; m <= 20; m++) { const x = evalStops([kr], { [id]: { px: 69000 } }, r.breach, r.ack, T0 + m * MIN); if (x.alerts.length) got.push([m, x.alerts[0].n]); }
  assert.deepEqual(got.map((g) => g[0]), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20]);
});

t('메시지: 시세 나이 표시·회복 문구', () => {
  const s = { market: 'US', symbol: 'SVIX', stop: 12.5, name: 'SVIX', note: '1/4칸' };
  const m = stopLine({ kind: 'break', n: 3, s, px: 12.1, t: (T0 - 4 * MIN) / 1000, nowMs: T0 });
  assert.match(m, /SVIX\(SVIX\)|SVIX/); assert.match(m, /12\.10달러 ≤ 손절 12\.50달러/); assert.match(m, /3번째, 시세 4분 전/); assert.match(m, /1\/4칸/);
  assert.match(stopLine({ kind: 'recover', s, px: 13, nowMs: T0 }), /회복/);
});

t('엔진 멈춤: 하트비트 20분 초과 + 감시 목록 있을 때만, 30분마다 반복, 복귀 알림', () => {
  let dm = null, hb = T0, r;
  r = deadmanDue(1, hb, T0 + 19 * MIN, dm); assert.equal(r.send, false);
  r = deadmanDue(1, hb, T0 + 21 * MIN, dm); assert.equal(r.send, true); assert.equal(r.kind, 'down'); dm = r.dm;
  r = deadmanDue(1, hb, T0 + 40 * MIN, dm); assert.equal(r.send, false);                    // 같은 알림 반복 전
  r = deadmanDue(1, hb, T0 + 52 * MIN, dm); assert.equal(r.send, true); dm = r.dm;          // 30분 뒤 반복
  r = deadmanDue(1, T0 + 60 * MIN, T0 + 61 * MIN, dm); assert.equal(r.kind, 'up'); assert.equal(r.send, true); dm = r.dm;
  r = deadmanDue(1, T0 + 60 * MIN, T0 + 62 * MIN, dm); assert.equal(r.send, false);
  r = deadmanDue(0, null, T0 + 999 * MIN, null); assert.equal(r.send, false);               // 감시 목록 없음 → 조용(주말 외출 오탐 방지)
  r = deadmanDue(1, null, T0, null); assert.equal(r.send, true);                            // 하트비트가 한 번도 없음
});

console.log(`OK ${n}/${n}`);
