#!/usr/bin/env node
/**
 * Buffett Quality 팩터(roe·roeConsistency·debtRatio·operatingMarginTrend)
 * 사전점검용 종목×월별 패널.
 *   node scripts/build-a5-quality-panel.js
 *
 * scripts/build-a5-valuation-panel.js와 골격은 같으나, 이 축은 A3(fundamentals)
 * 만으로 나오고 A3c/corporateActions(D4 우회식)를 안 거친다 — mergerSpinoff
 * 이력 종목 제외도 필요 없다(그건 valuation D4 파이프라인만의 문제,
 * docs/control/세션인수인계-2026-08-21-b.md §추가확인). resolver.js 무변경.
 * roeConsistency = min(roeHistory5y)는 lib/scoringEngine.js:115-118과 같은
 * 정의(운영 채점과 같은 식을 써야 백테스트가 운영을 검증한다는 원칙, 계약
 * 문서 참고).
 *
 * 진단/연구 전용. data/backfill/·manifest에 아무것도 쓰지 않는다(교훈43).
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));

const START = '2016-01-01';
const END = '2026-08-14';

function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function loadAllByCorp(dirRel) {
  const dir = path.join(ROOT, dirRel);
  const files = fs.readdirSync(dir).filter((f) => /^\d{4}\.jsonl\.gz$/.test(f));
  const byCorp = new Map();
  for (const f of files) {
    for (const r of readJsonl(`${dirRel}/${f}`)) {
      if (!byCorp.has(r.corp)) byCorp.set(r.corp, []);
      byCorp.get(r.corp).push(r);
    }
  }
  return byCorp;
}

function monthlyRebalanceDates(start, end) {
  const { tradingDays } = require(path.join(ROOT, 'data/backfill/calendar.json'));
  const inRange = tradingDays.filter((d) => d >= start && d <= end);
  const out = [];
  const seen = new Set();
  for (const d of inRange) {
    const ym = d.slice(0, 7);
    if (!seen.has(ym)) { seen.add(ym); out.push(d); }
  }
  return out;
}

function main() {
  const universe = readJsonl('data/backfill/universe/a1a/current.jsonl');
  const a3ByCorp = loadAllByCorp('data/backfill/fundamentals/a3');
  const rebalanceDates = monthlyRebalanceDates(START, END);
  console.log(`유니버스 ${universe.length}종목, 리밸런싱일 ${rebalanceDates.length}개월 (${rebalanceDates[0]} ~ ${rebalanceDates[rebalanceDates.length - 1]})`);

  const outDir = path.join(ROOT, 'research/strategy-lab/reports/2026-08-21-buffett-quality-precheck');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, 'quality-panel.jsonl');
  const out = fs.createWriteStream(outPath);

  let totalRows = 0, roeRows = 0;
  for (const { ticker, corp } of universe) {
    const a3 = a3ByCorp.get(corp) || [];
    if (a3.length === 0) continue;

    for (const asOf of rebalanceDates) {
      const resolved = resolve({ ticker, corp, asOf, fundamentals: a3 });
      const f = resolved.stockData.fundamental || {};
      totalRows += 1;
      if (typeof f.roe === 'number') roeRows += 1;
      const roeConsistency = Array.isArray(f.roeHistory5y) && f.roeHistory5y.length > 0
        ? Math.min(...f.roeHistory5y) : null;
      out.write(JSON.stringify({
        ticker, asOf, roe: f.roe ?? null, roeConsistency,
        debtRatio: f.debtRatio ?? null, operatingMarginTrend: f.operatingMarginTrend ?? null,
      }) + '\n');
    }
  }
  out.end();
  console.log(`저장 → ${outPath} (${totalRows}행, roe ${roeRows}행=${(roeRows / totalRows * 100).toFixed(1)}%)`);
}

main();
