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
 * resolver.js·scoringEngine.js는 건드리지 않는다. 여기서 하는 것은 배선(연결)뿐이다.
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
    const a3bRecordsAll = findFundamentalsA3b(corp); // 참고용. resolver에 넣지 않는다.

    // 3. Price
    const price = findPrice(ticker, ASOF);

    // 4. resolver.resolve() — 실제 프로덕션 리졸버, 변경 없이 그대로 호출
    const resolved = resolve({ ticker, corp, asOf: ASOF, fundamentals: a3records, price });

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

    entry.a3bAvailableButUnused = a3bRecordsAll
      .filter((r) => r.availableFrom <= ASOF.replace(/-/g, ''))
      .map((r) => ({ fiscalYear: r.fiscalYear, eps: r.eps, dividendPerShare: r.dividendPerShare }));

    // 5. resolver 출력을 "있는 그대로" score()에 넣으면 무슨 일이 나는지 (키 불일치 확인용)
    const asIsStockData = {
      ticker, name,
      dataCutoff: ASOF,
      state: null,
      ...resolved.stockData, // fundamentals(복수) 키만 붙는다. scoringEngine은 fundamental(단수)을 읽는다
    };
    let asIsResult;
    try {
      asIsResult = score(asIsStockData, criteria, policies);
    } catch (err) {
      asIsResult = { error: err.message };
    }

    // 6. resolver.js는 건드리지 않되, 이 스크립트 안에서만 키를 정확히 매핑해 실제
    //    production score()가 진짜 데이터를 받으면 어떻게 되는지 확인한다.
    //    valuation/technical/supplyDemand는 의도적으로 넣지 않는다 — 미구축 상태 그대로 둔다.
    const wiredStockData = {
      ticker, name,
      dataCutoff: ASOF,
      state: null,
      fundamental: resolved.stockData.fundamentals, // resolver(복수) → scoringEngine(단수) 매핑
    };
    let wiredResult;
    try {
      wiredResult = score(wiredStockData, criteria, policies);
    } catch (err) {
      wiredResult = { error: err.message };
    }

    entry.scoreAsIs = asIsResult.error
      ? { error: asIsResult.error }
      : {
          finalScore: asIsResult.result.finalScore,
          components: asIsResult.result.components,
          confidence: asIsResult.result.confidence,
        };

    entry.scoreWired = wiredResult.error
      ? { error: wiredResult.error }
      : {
          finalScore: wiredResult.result.finalScore,
          components: wiredResult.result.components,
          confidence: wiredResult.result.confidence,
          flags: wiredResult.result.flags,
        };

    report.samples.push(entry);
  }

  const outPath = path.join(ROOT, 'scratch-bf11-vertical-slice.json');
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  console.log('결과 →', outPath);
  console.log(JSON.stringify(report, null, 2));
}

main();
