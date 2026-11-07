// 등락률 알림·마감 요약·네이버 시세 파싱 단위 시험(파이썬 정본이 없는 새 로직).   node cloudflare/alerts/test/unit.mjs
import assert from 'node:assert/strict';
import { moveLevel, checkMoves, digestMessage, parseNaverQuote, pctChange, vixLevel, checkVixLevel } from '../src/core.js';

let n = 0; const t = (name, f) => { f(); n++; };

t('단계 계산(±10%)', () => {
  assert.equal(moveLevel(9.99), 0); assert.equal(moveLevel(10), 1); assert.equal(moveLevel(24.9), 2);
  assert.equal(moveLevel(-10.1), -1); assert.equal(moveLevel(-3), 0) ;
});

t('등락률 알림: 5% 는 조용, 10% 넘으면 한 번, 같은 단계는 다시 안 울림', () => {
  const D = '2026-11-09'; let st = null;
  let r = checkMoves([{ symbol: 'SOXL', px: 105, prev: 100 }], st, D); assert.equal(r.alerts.length, 0); st = r.state;     // +5%
  r = checkMoves([{ symbol: 'SOXL', px: 110.5, prev: 100 }], st, D); assert.equal(r.alerts.length, 1); st = r.state;     // +10.5% → 1단계
  assert.match(r.alerts[0], /SOXL \+10\.50%[\s\S]*10% 단계 상승/);
  r = checkMoves([{ symbol: 'SOXL', px: 112, prev: 100 }], st, D); assert.equal(r.alerts.length, 0); st = r.state;         // 같은 1단계
  r = checkMoves([{ symbol: 'SOXL', px: 120.1, prev: 100 }], st, D); assert.equal(r.alerts.length, 1); st = r.state;     // +20% → 2단계
  r = checkMoves([{ symbol: 'SOXL', px: 89, prev: 100 }], st, D); assert.equal(r.alerts.length, 1);                       // 방향 반전 → 다시
  assert.match(r.alerts[0], /SOXL −11\.00%[\s\S]*하락/);
});

t('등락률 알림: 날짜가 바뀌면 단계를 비운다 · 종목별로 따로', () => {
  let r = checkMoves([{ symbol: 'SVIX', px: 111, prev: 100 }, { symbol: 'SOXL', px: 101, prev: 100 }], null, '2026-11-09');
  assert.equal(r.alerts.length, 1); assert.match(r.alerts[0], /SVIX/);
  r = checkMoves([{ symbol: 'SVIX', px: 111, prev: 100 }], r.state, '2026-11-10');   // 다음 날 같은 폭 → 다시 울린다
  assert.equal(r.alerts.length, 1);
});

t('장중 VIX 단계(20·25·30…): 전일 종가의 단계보다 높을 때만, 하루 한 번씩', () => {
  assert.equal(vixLevel(19.99), 0); assert.equal(vixLevel(20), 20); assert.equal(vixLevel(24.9), 20); assert.equal(vixLevel(30.2), 30);
  const D = '2026-11-09'; let r = checkVixLevel(19.5, 18, null, D); assert.equal(r.msg, null);                       // 20 미만
  r = checkVixLevel(20.4, 18, r.state, D); assert.match(r.msg, /VIX 20\.40 — 20 단계/); const st = r.state;          // 20 처음 도달
  assert.equal(checkVixLevel(21, 18, st, D).msg, null);                                                               // 같은 단계 반복 없음
  r = checkVixLevel(25.1, 18, st, D); assert.match(r.msg, /25 단계/);                                                  // 25 도달
  assert.equal(checkVixLevel(21, 22, null, '2026-11-10').msg, null);                                                  // 전일 종가(22)가 이미 20 단계 → 20 대는 조용
  assert.match(checkVixLevel(25.5, 22, null, '2026-11-10').msg, /25 단계/);                                            // 전일보다 높은 25 는 알림
  assert.equal(checkVixLevel(24, 22, { date: '2026-11-10', level: 25 }, '2026-11-10').msg, null);                      // 내려갔다 다시 올라도 같은 날 같은 단계는 안 울림
});

t('마감 요약 형식', () => {
  const m = digestMessage('마감 요약 미국', '11-06', [{ label: 'S&P500', px: 7376.86, prev: 7353.73 }, { label: 'SOXL', px: 45.97, prev: 40.87 }]);
  assert.equal(m, '[마감 요약 미국] 11-06\nS&P500 7,376.86 (+0.31%)\nSOXL 45.97 (+12.48%)');
  assert.equal(pctChange(90, 100), -10);
});

t('네이버 시세: 오늘 봉이면 {px, prev}, 휴장이면 null', () => {
  const xml = '<item data="20261105|1|1|1|11090|5" />\n<item data="20261106|1|1|1|10510|5" />';
  assert.deepEqual(parseNaverQuote(xml, new Date('2026-11-06T06:40:00Z')), { px: 10510, prev: 11090 });
  assert.equal(parseNaverQuote(xml, new Date('2026-11-07T06:40:00Z')), null);
  assert.equal(parseNaverQuote('<item data="20261106|1|1|1|10510|5" />', new Date('2026-11-06T06:40:00Z')), null);   // 전일 봉 없음
});

console.log(`OK ${n}/${n}`);
