#!/usr/bin/env node
/**
 * A5-3 D4 — V7 최종 수직 슬라이스 (docs/A5-3-peg-조정기준-결정브리프.md §6).
 *   node scripts/probe-v7-vertical-slice.js
 *
 * BF-1.1이 2016-04-08/005930으로 밟은 경로(scripts/probe-bf11-vertical-slice.js)를
 * 다시 밟되, per·pbr·peg가 실제로 붙는 asOf·종목으로 한다 — 005930/2016-04-08은
 * A3c FY2015가 EMPTY라 §1.3 때문에 부적합하다고 브리프가 이미 밝혔다.
 * Universe→PIT→가격(raw+adj)→resolver→운영 score()까지 실데이터로 연결한다.
 *
 * 진단 전용. data/backfill/scores/나 manifest에 아무것도 쓰지 않는다(교훈43).
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
const { score } = require(path.join(ROOT, 'lib/scoringEngine'));
const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));

// 005930 FY2018 split(20180131 공시, ×49.47)이 A3c 원자료에 이미 반영된 뒤 —
// FY2017(prev)은 아직 분할 전 raw. per·pbr은 채워지고 epsGrowthRate는
// 정직하게 유보되는 경계 사례(§1.3과 다른 방식으로 유용한 실측).
const ASOF = '2019-06-03';
const A3D_CATEGORIES = [
  'split', 'reverseOrConsolidation', 'bonusIssue', 'capitalReductionFree',
  'capitalReductionPaid', 'capitalReductionUnknown', 'rightsOfferingThirdParty',
  'rightsOfferingShareholders', 'mergerSpinoff',
];
const SAMPLE = [
  // 005930: A3d에 2016 mergerSpinoff(회사분할결정)가 걸려 있어 그 이후 전
  // 회계연도가 MERGER_UNHANDLED로 영구 유보된다 — capitalReal 유보 게이트가
  // 실데이터에서 실제로 어떻게 작동하는지 보여주는 사례.
  { ticker: '005930', corp: '00126380', name: '삼성전자' },
  // 002100: A3d 전 카테고리에 사건 0건, 발행주식수 2개년 동일 — valuation
  // (per·epsGrowthRate·pbr) 전부가 실제로 채워지는 정상 경로 확인용.
  { ticker: '002100', corp: '00101433', name: '경농' },
];

function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function findUniverse(ticker) {
  const a1a = readJsonl('data/backfill/universe/a1a/current.jsonl');
  return a1a.find((r) => r.ticker === ticker) || null;
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

function findPrice(ticker, date) {
  const year = date.slice(0, 4);
  const rows = readJsonl(`data/backfill/price/a2a/${year}.jsonl.gz`);
  return rows.find((r) => r.ticker === ticker && r.date === date) || null;
}

/** asOf 이전(포함) 최근 windowDays 거래일 캔들. technical 축 검증용. */
function findCandles(ticker, asOf, windowDays = 260) {
  const asOfYear = Number(asOf.slice(0, 4));
  const rows = [];
  for (const year of [asOfYear - 1, asOfYear]) {
    const p = path.join(ROOT, `data/backfill/price/a2a/${year}.jsonl.gz`);
    if (!fs.existsSync(p)) continue;
    for (const r of readJsonl(`data/backfill/price/a2a/${year}.jsonl.gz`)) {
      if (r.ticker === ticker && r.date <= asOf) rows.push(r);
    }
  }
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return rows.slice(-windowDays).map((r) => ({ date: r.date, close: r.close, volume: r.volume }));
}

function main() {
  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');
  const report = { asOf: ASOF, generatedAt: new Date().toISOString(), samples: [] };

  for (const { ticker, corp, name } of SAMPLE) {
    const entry = { ticker, corp, name };

    const uni = findUniverse(ticker);
    entry.universe = uni
      ? { present: true, listedAt: uni.listedAt, listedBeforeAsOf: uni.listedAt <= ASOF }
      : { present: false };

    const a3records = findByCorpAcrossYears('data/backfill/fundamentals/a3', corp);
    const a3bRecordsAll = findByCorpAcrossYears('data/backfill/fundamentals/a3b', corp);
    const a3cRecordsAll = findByCorpAcrossYears('data/backfill/fundamentals/a3c', corp);
    const corporateActions = findCorporateActions(corp);

    const price = findPrice(ticker, ASOF);
    const candles = findCandles(ticker, ASOF);

    // 실제 프로덕션 리졸버, 변경 없이 그대로 호출. sharesOutstanding(A3c)와
    // corporateActions(A3d)를 함께 넘겨야 valuation(D4)이 열린다(resolver.js 주석).
    const resolved = resolve({
      ticker, corp, asOf: ASOF, fundamentals: a3records, price,
      dividendEps: a3bRecordsAll, candles,
      sharesOutstanding: a3cRecordsAll, corporateActions,
    });

    entry.pit = {
      totalRecordsForCorp: a3records.length,
      selectedFiscalYear: resolved.provenance.fundamentals ? resolved.provenance.fundamentals.fiscalYear : null,
      selectedAvailableFrom: resolved.provenance.fundamentals ? resolved.provenance.fundamentals.availableFrom : null,
      pitViolation: resolved.pitViolation,
      futureRecordsExcluded: a3records
        .filter((r) => r.availableFrom > ASOF)
        .map((r) => ({ fiscalYear: r.fiscalYear, availableFrom: r.availableFrom })),
    };

    entry.price = price
      ? { date: price.date, close: price.close, matchesAsOf: price.date === ASOF }
      : { found: false };

    entry.candles = {
      count: candles.length,
      firstDate: candles[0] ? candles[0].date : null,
      lastDate: candles[candles.length - 1] ? candles[candles.length - 1].date : null,
      allBeforeOrOnAsOf: candles.every((c) => c.date <= ASOF),
    };

    entry.a3c = {
      totalRecordsForCorp: a3cRecordsAll.length,
      corporateActionsCount: corporateActions.length,
      corporateActionsUsed: corporateActions.map((e) => ({
        category: e.category, disclosureDate: e.disclosureDate, multiplier: e.multiplier,
      })),
    };

    entry.newFeatures = {
      shareholderReturn: resolved.stockData.fundamental.buybackOrDividendHistory,
      valuation: resolved.stockData.valuation,
      valuationProvenance: resolved.provenance.valuation || null,
      technical: resolved.stockData.technical,
    };

    // resolver 출력을 그대로 score()에 넣는다.
    const stockData = {
      ticker, name,
      dataCutoff: ASOF,
      state: null,
      ...resolved.stockData,
    };
    let result;
    try {
      result = score(stockData, criteria, policies);
    } catch (err) {
      result = { error: err.message };
    }

    entry.score = result.error
      ? { error: result.error }
      : {
          finalScore: result.result.finalScore,
          components: result.result.components,
          confidence: result.result.confidence,
          flags: result.result.flags,
        };

    entry.valuationConnected = !!(resolved.stockData.valuation
      && (resolved.stockData.valuation.per !== null || resolved.stockData.valuation.pbr !== null));

    report.samples.push(entry);
  }

  const outPath = path.join(ROOT, 'scratch-v7-vertical-slice.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log('결과 →', outPath);
  console.log(JSON.stringify(report, null, 2));
}

main();
