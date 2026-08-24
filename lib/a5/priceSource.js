/**
 * BF-1.1 10년 백필용 통합 가격 조회 — A2a(현재 상장분) 우선, 없으면 A2b(폐지분).
 *
 * 운영 스코어링(A5o)은 이 모듈을 쓰지 않는다 — 라이브 가격을 별도 경로로 받는다
 * (docs/BF-1.1-백필계약.md §2 "운영(A5o)/연구(A5) 분리" 확정). 이 모듈은 과거 시점
 * 유니버스 재구성(A5, 폐지종목 포함)에서만 쓰인다 — 한 종목의 전체 역사는 A2a·A2b
 * 어느 한쪽에만 있다(현재 상장 여부로 갈린 두 소스), 연도별로 갈리지 않는다.
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const DEFAULT_ROOT = path.join(__dirname, '..', '..');

const yearCache = new Map(); // `${root}:${source}:${year}` -> Map(ticker -> 오름차순 레코드 배열)

function readJsonl(absPath) {
  const buf = fs.readFileSync(absPath);
  const text = absPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function loadYear(root, source, year) {
  const key = `${root}:${source}:${year}`;
  if (yearCache.has(key)) return yearCache.get(key);
  const absPath = path.join(root, `data/backfill/price/${source}/${year}.jsonl.gz`);
  const byTicker = new Map();
  if (fs.existsSync(absPath)) {
    for (const r of readJsonl(absPath)) {
      if (!byTicker.has(r.ticker)) byTicker.set(r.ticker, []);
      byTicker.get(r.ticker).push(r);
    }
    for (const rows of byTicker.values()) rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  }
  yearCache.set(key, byTicker);
  return byTicker;
}

function rowsFor(root, ticker, year) {
  const a2a = loadYear(root, 'a2a', year).get(ticker);
  if (a2a) return { rows: a2a, source: 'a2a' };
  const a2b = loadYear(root, 'a2b', year).get(ticker);
  if (a2b) return { rows: a2b, source: 'a2b' };
  return { rows: [], source: null };
}

/** 특정 날짜의 가격. 없으면 null. root는 테스트용 오버라이드(기본: 저장소 루트). */
function findPrice(ticker, date, { root = DEFAULT_ROOT } = {}) {
  const year = date.slice(0, 4);
  const { rows, source } = rowsFor(root, ticker, year);
  const r = rows.find((row) => row.date === date);
  return r ? { date: r.date, open: r.open, high: r.high, low: r.low, close: r.close, volume: r.volume, source } : null;
}

/** asOf 이전(포함) 최근 windowDays 거래일 캔들. MA60·MACD 등 technical 축용. */
function findCandles(ticker, asOf, windowDays = 260, { root = DEFAULT_ROOT } = {}) {
  const asOfYear = Number(asOf.slice(0, 4));
  const rows = [];
  let source = null;
  for (const year of [asOfYear - 1, asOfYear]) {
    const r = rowsFor(root, ticker, year);
    if (r.source) source = r.source;
    for (const row of r.rows) if (row.date <= asOf) rows.push(row);
  }
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return { source, candles: rows.slice(-windowDays).map((r) => ({ date: r.date, close: r.close, volume: r.volume })) };
}

/** 테스트 전용: 연도 캐시 초기화(같은 root에 다른 픽스처를 다시 쓸 때). */
function _clearCache() {
  yearCache.clear();
}

module.exports = { findPrice, findCandles, _clearCache };
