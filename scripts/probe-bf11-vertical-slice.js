#!/usr/bin/env node
/**
 * BF-1.1 최소 수직 슬라이스 정찰 — 1개 snapshot × 1~2종목.
 *   node scripts/probe-bf11-vertical-slice.js
 *
 * 이것은 수집도 백필도 아니다. data/backfill/scores/나 manifest에 아무것도 쓰지
 * 않는다 — 인수 조건을 통과했다는 뜻을 찍으면 안 되기 때문이다(교훈43). 목적은
 * 하나: "asOf 시점에 알 수 있었던 데이터만으로 실제 production score()까지
 * 연결되는가"를 실데이터로 확인하고, 사람이 읽을 수 있는 근거를 남기는 것.
 *
 * 이 스크립트 자체는 resolver.js·scoringEngine.js를 건드리지 않는다 — 배선(연결)만
 * 확인한다. (2026-08-12: 최초 실행에서 resolver.js의 fundamentals/fundamental
 * 필드명 불일치를 발견 → lib/a5/resolver.js에서 별도로 수정, 이 스크립트는 그
 * 수정을 검증하는 재실행 용도로도 쓴다. 같은 날 A5-3 부분 구현
 * (shareholderReturn·peg·technical) 이후에도 같은 snapshot으로 재검증했다.)
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

const ASOF = '2016-04-08';
const SAMPLE = [{ ticker: '005930', corp: '00126380', name: '삼성전자' }];

function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function findUniverse(ticker) {
  const a1a = readJsonl('data/backfill/universe/a1a/current.jsonl');
  return a1a.find((r) => r.ticker === ticker) || null;
}

function findFundamentals(corp) {
  // A3 파일은 fiscalYear 기준 연도별 분리다. asOf 이전 것만 있으면 되지만,
  // 어느 fiscalYear 파일에 asOf 이전 레코드가 들었는지 미리 알 수 없어 전부 훑는다.
  const dir = path.join(ROOT, 'data/backfill/fundamentals/a3');
  const files = fs.readdirSync(dir).filter((f) => /^\d{4}\.jsonl\.gz$/.test(f));
  const records = [];
  for (const f of files) {
    for (const r of readJsonl(`data/backfill/fundamentals/a3/${f}`)) {
      if (r.corp === corp) records.push(r);
    }
  }
  return records;
}

function findFundamentalsA3b(corp) {
  const dir = path.join(ROOT, 'data/backfill/fundamentals/a3b');
  const files = fs.readdirSync(dir).filter((f) => /^\d{4}\.jsonl\.gz$/.test(f));
  const records = [];
  for (const f of files) {
    for (const r of readJsonl(`data/backfill/fundamentals/a3b/${f}`)) {
      if (r.corp === corp) records.push(r);
    }
  }
  return records;
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
  // technical은 MA60·MACD(35일)가 필요해 연도 경계를 넘을 수 있다 — 전해까지 같이 읽는다.
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

    // 1. Universe
    const uni = findUniverse(ticker);
    entry.universe = uni
      ? { present: true, listedAt: uni.listedAt, listedBeforeAsOf: uni.listedAt <= ASOF }
      : { present: false };

    // 2. Fundamentals (A3) — corp 전체 이력을 넘기고 pitSelector가 asOf로 고른다
    const a3records = findFundamentals(corp);
    const a3bRecordsAll = findFundamentalsA3b(corp); // 이제 resolver에도 넣는다(shareholderReturn·peg 재료)

    // 3. Price
    const price = findPrice(ticker, ASOF);

    // 3b. Technical용 캔들 — asOf 이전만
    const candles = findCandles(ticker, ASOF);

    // 4. resolver.resolve() — 실제 프로덕션 리졸버, 변경 없이 그대로 호출.
    //    dividendEps·candles를 넘기면 shareholderReturn·peg·technical이 함께 열린다.
    const resolved = resolve({
      ticker, corp, asOf: ASOF, fundamentals: a3records, price,
      dividendEps: a3bRecordsAll, candles,
    });

    entry.pit = {
      totalRecordsForCorp: a3records.length,
      selectedFiscalYear: resolved.provenance.fundamentals ? resolved.provenance.fundamentals.fiscalYear : null,
      selectedAvailableFrom: resolved.provenance.fundamentals ? resolved.provenance.fundamentals.availableFrom : null,
      selectedRceptNo: resolved.provenance.fundamentals ? resolved.provenance.fundamentals.rceptNo : null,
      pitViolation: resolved.pitViolation,
      // asOf 이후 availableFrom을 가진 레코드가 있었는지, 그리고 그게 선택되지 않았는지를 명시적으로 보인다
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

    const asOfCompact = ASOF.replace(/-/g, '');
    entry.a3bPit = {
      totalRecordsForCorp: a3bRecordsAll.length,
      selectedFiscalYear: resolved.provenance.valuation ? resolved.provenance.valuation.fiscalYear : null,
      selectedAvailableFrom: resolved.provenance.valuation ? resolved.provenance.valuation.availableFrom : null,
      shareholderReturnYearsChecked: resolved.provenance.shareholderReturn
        ? resolved.provenance.shareholderReturn.yearsChecked : null,
      futureRecordsExcluded: a3bRecordsAll
        .filter((r) => r.availableFrom > asOfCompact)
        .map((r) => ({ fiscalYear: r.fiscalYear, availableFrom: r.availableFrom })),
    };

    entry.newFeatures = {
      shareholderReturn: resolved.stockData.fundamental.buybackOrDividendHistory,
      valuation: resolved.stockData.valuation,
      technical: resolved.stockData.technical,
    };

    // 5. resolver 출력을 그대로 score()에 넣는다 — resolver.js가 scoringEngine.js와
    //    같은 키 이름(fundamental, 단수)을 쓰므로 추가 매핑이 필요 없다.
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

    report.samples.push(entry);
  }

  const outPath = path.join(ROOT, 'scratch-bf11-vertical-slice.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log('결과 →', outPath);
  console.log(JSON.stringify(report, null, 2));
}

main();
