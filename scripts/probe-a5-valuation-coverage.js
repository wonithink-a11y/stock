#!/usr/bin/env node
/**
 * A5-3 D4 밸류에이션(peg/pbr)을 Strategy Lab에 결합하기 전 저비용 사전점검
 * (docs/control/세션인수인계-2026-08-21-b.md §3, 사용자 승인 "저비용 사전점검부터").
 *   node scripts/probe-a5-valuation-coverage.js
 *
 * 묻는 질문 하나: resolver.resolve()를 실제로 돌리면 (a) capitalReal류 유보
 * 게이트가 커버리지를 얼마나 깎는지, (b) pbr이 유동성/시총과 무관하게 남는
 * 신호인지 — 감을 잡는다. 소표본(≈60종목 × 최근 24개월), 로컬 데이터만
 * 사용(DART 등 외부 호출 없음). scripts/probe-v7-vertical-slice.js의 로더를
 * 재사용한다. 진단 전용 — data/backfill/·manifest에 아무것도 쓰지 않는다(교훈43).
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));

const A3D_CATEGORIES = [
  'split', 'reverseOrConsolidation', 'bonusIssue', 'capitalReductionFree',
  'capitalReductionPaid', 'capitalReductionUnknown', 'rightsOfferingThirdParty',
  'rightsOfferingShareholders', 'mergerSpinoff',
];
// V7(005930/002100)·GO-5(034020/065170/079650/000860/014200/000050) 검증에
// 이미 쓴 기업행위 경계 사례 — capitalReal 유보가 실제로 얼마나 자주 걸리는지
// 보려면 이런 종목이 표본에 있어야 한다.
const EDGE_CASE_TICKERS = ['005930', '002100', '034020', '065170', '079650', '000860', '014200', '000050'];
const SAMPLE_STRIDE = 50; // 2,578종목에서 대략 51개 + 위 엣지케이스 = 소표본
const YEARS = [2024, 2025, 2026];
const CALENDAR_TICKER = '005930'; // 월별 asOf(거래일) 추출용 — 연속 상장·매일 거래

function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function findByCorpAcrossYears(dirRel, corp) {
  const dir = path.join(ROOT, dirRel);
  const files = fs.readdirSync(dir).filter((f) => /^\d{4}\.jsonl\.gz$/.test(f));
  const records = [];
  for (const f of files) {
    for (const r of readJsonl(`${dirRel}/${f}`)) {
      if (r.corp === corp) records.push(r);
    }
  }
  return records;
}

function findCorporateActions(corp) {
  let events = [];
  for (const cat of A3D_CATEGORIES) {
    const rows = readJsonl(`data/backfill/fundamentals/a3d/${cat}.jsonl.gz`)
      .filter((r) => r.corp === corp)
      .map((r) => ({ ...r, category: cat }));
    events = events.concat(rows);
  }
  return events;
}

/** 연도별 A2a를 한 번씩만 읽어 `ticker|date` → row 색인. 반복 호출당 전체 파일
 *  재파싱을 피한다(50종목×24개월을 그대로 하면 파일을 1,200번 다시 읽게 된다). */
function buildPriceIndex(years) {
  const idx = new Map();
  const datesByYear = new Map();
  for (const year of years) {
    const p = `data/backfill/price/a2a/${year}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    const dates = [];
    for (const r of readJsonl(p)) {
      idx.set(`${r.ticker}|${r.date}`, r);
      if (r.ticker === CALENDAR_TICKER) dates.push(r.date);
    }
    datesByYear.set(year, dates.sort());
  }
  return { idx, datesByYear };
}

function monthlyAsOfDates(datesByYear, years, maxMonths = 24) {
  const out = [];
  for (const year of years) {
    const dates = datesByYear.get(year) || [];
    const byMonth = new Map();
    for (const d of dates) byMonth.set(d.slice(0, 7), d); // 마지막 값이 그 달 최종거래일로 남는다(정렬됨)
    for (const ym of Array.from(byMonth.keys()).sort()) out.push(byMonth.get(ym));
  }
  return out.slice(-maxMonths);
}

function buildSample() {
  const universe = readJsonl('data/backfill/universe/a1a/current.jsonl').sort((a, b) => (a.ticker < b.ticker ? -1 : 1));
  const byTicker = new Map(universe.map((u) => [u.ticker, u]));
  const strided = universe.filter((_, i) => i % SAMPLE_STRIDE === 0);
  const tickers = new Set(strided.map((u) => u.ticker));
  for (const t of EDGE_CASE_TICKERS) if (byTicker.has(t)) tickers.add(t);
  return [...tickers].map((t) => byTicker.get(t));
}

function main() {
  const sample = buildSample();
  const { idx: priceIdx, datesByYear } = buildPriceIndex(YEARS);
  const asOfDates = monthlyAsOfDates(datesByYear, YEARS);

  console.log(`표본 ${sample.length}종목 × ${asOfDates.length}개월 asOf`);

  const rows = [];
  for (const { ticker, corp, name } of sample) {
    const a3 = findByCorpAcrossYears('data/backfill/fundamentals/a3', corp);
    const a3c = findByCorpAcrossYears('data/backfill/fundamentals/a3c', corp);
    const corporateActions = findCorporateActions(corp);
    const hasCapitalRealEvent = corporateActions.some((e) => e.category === 'mergerSpinoff');

    for (const asOf of asOfDates) {
      const price = priceIdx.get(`${ticker}|${asOf}`) || null;
      if (!price) continue; // 그 달 거래정지 등으로 정확히 그 날짜 캔들이 없음 — 유보 대상이 아니라 표본 제외

      const resolved = resolve({
        ticker, corp, asOf, fundamentals: a3, price,
        sharesOutstanding: a3c, corporateActions,
      });
      const val = resolved.stockData.valuation || {};
      const shares = resolved.provenance.valuation ? resolved.provenance.valuation.sharesOutstanding.cur : null;
      const marketCap = (shares && shares.value) ? shares.value * price.close : null;

      rows.push({
        ticker, name, asOf,
        per: val.per ?? null, pbr: val.pbr ?? null, epsGrowthRate: val.epsGrowthRate ?? null,
        marketCap, sharesWithheldBy: shares ? shares.withheldBy : null,
        hasCapitalRealEvent,
      });
    }
  }

  const total = rows.length;
  const pbrCovered = rows.filter((r) => r.pbr !== null).length;
  const withheldCounts = {};
  for (const r of rows) {
    if (r.pbr === null) {
      const key = r.sharesWithheldBy || 'OTHER_NULL';
      withheldCounts[key] = (withheldCounts[key] || 0) + 1;
    }
  }
  const capitalRealRows = rows.filter((r) => r.hasCapitalRealEvent);
  const capitalRealCovered = capitalRealRows.filter((r) => r.pbr !== null).length;
  const nonCapitalRealRows = rows.filter((r) => !r.hasCapitalRealEvent);
  const nonCapitalRealCovered = nonCapitalRealRows.filter((r) => r.pbr !== null).length;

  const summary = {
    generatedAt: new Date().toISOString(),
    sampleTickers: sample.length,
    asOfMonths: asOfDates.length,
    totalObservations: total,
    pbrCoverage: total ? round(pbrCovered / total) : null,
    withheldReasonCounts: withheldCounts,
    capitalRealEventTickers: {
      tickerCount: new Set(capitalRealRows.map((r) => r.ticker)).size,
      observations: capitalRealRows.length,
      pbrCoverage: capitalRealRows.length ? round(capitalRealCovered / capitalRealRows.length) : null,
    },
    nonCapitalRealEventTickers: {
      tickerCount: new Set(nonCapitalRealRows.map((r) => r.ticker)).size,
      observations: nonCapitalRealRows.length,
      pbrCoverage: nonCapitalRealRows.length ? round(nonCapitalRealCovered / nonCapitalRealRows.length) : null,
    },
  };

  function round(x) { return Math.round(x * 1000) / 1000; }

  const outDir = path.join(ROOT, 'research/strategy-lab/reports/2026-08-21-a5-valuation-precheck');
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, 'coverage-summary.json'), JSON.stringify(summary, null, 2));
  fs.writeFileSync(path.join(outDir, 'coverage-panel.jsonl'), rows.map((r) => JSON.stringify(r)).join('\n'));

  console.log(JSON.stringify(summary, null, 2));
  console.log('panel →', path.join(outDir, 'coverage-panel.jsonl'), `(${rows.length}행)`);
}

main();
