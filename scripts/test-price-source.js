#!/usr/bin/env node
/**
 * lib/a5/priceSource.js 회귀 — A2a·A2b 통합 조회.
 *   node scripts/test-price-source.js
 *
 * data/backfill/은 건드리지 않는다(규칙 4) — OS temp에 픽스처를 직접 쓰고 root
 * 오버라이드로 그쪽만 읽게 한다. 지키려는 것: **A2a에 있으면 A2a, 없으면 A2b**,
 * asOf 이후 날짜는 절대 새어 들어오지 않는다(candles의 PIT 경계).
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const ROOT = path.join(__dirname, '..');
const { findPrice, findCandles, _clearCache } = require(path.join(ROOT, 'lib/a5/priceSource'));

let passed = 0, failed = 0;
function ok(name, cond, detail) {
  if (cond) { passed++; console.log(`  OK    ${name}`); }
  else { failed++; console.log(`  FAIL  ${name}${detail ? '  — ' + detail : ''}`); }
}

const FIXTURE_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'price-source-test-'));

function writeYear(source, year, rows) {
  const dir = path.join(FIXTURE_ROOT, 'data/backfill/price', source);
  fs.mkdirSync(dir, { recursive: true });
  const body = rows.map((r) => JSON.stringify(r)).join('\n') + '\n';
  fs.writeFileSync(path.join(dir, `${year}.jsonl.gz`), zlib.gzipSync(body));
}

function row(ticker, date, close) {
  return { ticker, date, open: close, high: close, low: close, close, volume: 1000 };
}

// 001: A2a 전용 종목(현재 상장)
writeYear('a2a', 2016, [row('000001', '2016-01-04', 100), row('000001', '2016-01-05', 101)]);
// 002: A2b 전용 종목(폐지)
writeYear('a2b', 2016, [row('000002', '2016-01-04', 200), row('000002', '2016-01-05', 202)]);

console.log('[findPrice — A2a·A2b 통합 조회]');
{
  const p = findPrice('000001', '2016-01-04', { root: FIXTURE_ROOT });
  ok('A2a 종목이 A2a에서 조회됨', p && p.close === 100 && p.source === 'a2a', JSON.stringify(p));
}
{
  const p = findPrice('000002', '2016-01-04', { root: FIXTURE_ROOT });
  ok('A2b 종목이 A2b로 폴백됨', p && p.close === 200 && p.source === 'a2b', JSON.stringify(p));
}
{
  const p = findPrice('999999', '2016-01-04', { root: FIXTURE_ROOT });
  ok('어느 소스에도 없으면 null', p === null, JSON.stringify(p));
}
{
  const p = findPrice('000001', '2016-01-06', { root: FIXTURE_ROOT }); // 해당 날짜 레코드 없음
  ok('종목은 있지만 그 날짜 레코드가 없으면 null', p === null, JSON.stringify(p));
}

console.log('[findCandles — asOf PIT 경계]');
{
  const { source, candles } = findCandles('000001', '2016-01-04', 260, { root: FIXTURE_ROOT });
  ok('asOf 이전(포함) 캔들만 포함', candles.every((c) => c.date <= '2016-01-04'), JSON.stringify(candles));
  ok('asOf 이후 레코드(01-05)는 제외됨', !candles.some((c) => c.date === '2016-01-05'), JSON.stringify(candles));
  ok('source가 a2a로 식별됨', source === 'a2a');
}
{
  const { candles } = findCandles('000002', '2016-01-05', 260, { root: FIXTURE_ROOT });
  ok('A2b 종목도 캔들 조회됨(2건)', candles.length === 2, JSON.stringify(candles));
}
{
  _clearCache();
  const { candles } = findCandles('000001', '2016-01-04', 1, { root: FIXTURE_ROOT });
  ok('windowDays로 최근 N건만 자름', candles.length === 1 && candles[0].date === '2016-01-04', JSON.stringify(candles));
}

fs.rmSync(FIXTURE_ROOT, { recursive: true, force: true });

console.log(`\n총 ${passed + failed}건 — 통과 ${passed}, 실패 ${failed}`);
if (failed > 0) process.exit(1);
