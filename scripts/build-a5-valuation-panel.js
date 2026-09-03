#!/usr/bin/env node
/**
 * A5-3 D4 밸류에이션(pbr) 팩터 사전점검용 종목×월별 패널 (사전점검 2단계).
 *   node scripts/build-a5-valuation-panel.js
 *
 * 1단계(scripts/probe-a5-valuation-coverage.js)가 mergerSpinoff 공시 이력이
 * 있는 종목에서 pbr이 사실상 전멸(2.4%)한다는 걸 확인했다(사용자 승인,
 * 세션인수인계-2026-08-21-b.md §3) — 그 종목군을 통째로 제외하고 나머지
 * 유니버스로 pbr 팩터 신호(저PBR 초과수익 존재 여부, 유동성 통제 후에도
 * 남는지)를 재는 패널을 만든다. resolver.js·게이트 로직은 무변경.
 *
 * 리밸런싱일은 lowmom60_robustness.py와 같은 정의(매월 첫 거래일,
 * data/backfill/calendar.json 기준)를 그대로 써서 Python 쪽과 조인 가능하게
 * 맞춘다. 기간도 기존 Strategy Lab 백테스트와 동일(2016-01-01~2026-08-14).
 *
 * 2026-08-21 확장: Lynch GARP/PEG 사전점검(peg=per/epsGrowthRate, debtRatio
 * 필터)도 이 패널을 그대로 쓴다 — pbr precheck는 기존 필드만 읽으므로 하위
 * 호환. epsGrowthRate·debtRatio는 val/fundamental에서 그냥 더 뽑는 것뿐,
 * 조인·PIT 로직은 무변경.
 *
 * 진단/연구 전용. data/backfill/·manifest에 아무것도 쓰지 않는다(교훈43).
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
const START = '2016-01-01';
// 기본값은 최초 사전점검과 동일 기간(lowmom60_robustness.py와 맞춤). 월별
// 라이브 리밸런싱 리프레시(Paper Trading Engine 4단계)에서는
// `node scripts/build-a5-valuation-panel.js --end 2026-09-02`처럼 CLI로
// 넘겨 그 시점까지 재계산한다 - data/backfill/price/a2a가 그 날짜까지
// 먼저 갱신돼 있어야 한다(A2a는 workflow_dispatch 수동 트리거, 상시 갱신
// 아님). 로직은 무변경, 종료일만 바뀐다.
const argEnd = process.argv.find((a) => a.startsWith('--end='))?.split('=')[1]
  || (process.argv.includes('--end') ? process.argv[process.argv.indexOf('--end') + 1] : null);
const END = argEnd || '2026-08-14';

function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

/** dirRel의 모든 연도 파일을 한 번씩만 훑어 corp별로 묶는다(교훈: 티커마다
 *  다시 읽으면 유니버스 규모에서 파일을 수만 번 다시 여는 꼴이 된다). */
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

function loadCorporateActionsByCorp() {
  const byCorp = new Map();
  for (const cat of A3D_CATEGORIES) {
    for (const r of readJsonl(`data/backfill/fundamentals/a3d/${cat}.jsonl.gz`)) {
      const ev = { ...r, category: cat };
      if (!byCorp.has(r.corp)) byCorp.set(r.corp, []);
      byCorp.get(r.corp).push(ev);
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
  const corpActionsByCorp = loadCorporateActionsByCorp();
  const mergerSpinoffCorps = new Set();
  for (const [corp, events] of corpActionsByCorp.entries()) {
    if (events.some((e) => e.category === 'mergerSpinoff')) mergerSpinoffCorps.add(corp);
  }

  const eligible = universe.filter((u) => !mergerSpinoffCorps.has(u.corp));
  const excluded = universe.length - eligible.length;
  console.log(`유니버스 ${universe.length}종목 중 mergerSpinoff 이력 ${excluded}종목 제외 → 대상 ${eligible.length}종목`);

  const a3ByCorp = loadAllByCorp('data/backfill/fundamentals/a3');
  const a3cByCorp = loadAllByCorp('data/backfill/fundamentals/a3c');
  const rebalanceDates = monthlyRebalanceDates(START, END);
  console.log(`리밸런싱일 ${rebalanceDates.length}개월 (${rebalanceDates[0]} ~ ${rebalanceDates[rebalanceDates.length - 1]})`);

  const datesByYear = new Map();
  for (const d of rebalanceDates) {
    const y = d.slice(0, 4);
    if (!datesByYear.has(y)) datesByYear.set(y, []);
    datesByYear.get(y).push(d);
  }

  const outDir = path.join(ROOT, 'research/strategy-lab/reports/2026-08-21-a5-valuation-precheck');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, 'valuation-panel.jsonl');
  const out = fs.createWriteStream(outPath);

  let totalRows = 0, pbrRows = 0;
  for (const [year, dates] of datesByYear.entries()) {
    const p = `data/backfill/price/a2a/${year}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    const priceIdx = new Map();
    for (const r of readJsonl(p)) priceIdx.set(`${r.ticker}|${r.date}`, r);

    for (const { ticker, corp } of eligible) {
      const a3 = a3ByCorp.get(corp) || [];
      if (a3.length === 0) continue;
      const a3c = a3cByCorp.get(corp) || [];
      const corporateActions = corpActionsByCorp.get(corp) || [];

      for (const asOf of dates) {
        const price = priceIdx.get(`${ticker}|${asOf}`);
        if (!price) continue;
        const resolved = resolve({ ticker, corp, asOf, fundamentals: a3, price, sharesOutstanding: a3c, corporateActions });
        const val = resolved.stockData.valuation || {};
        const fundamental = resolved.stockData.fundamental || {};
        totalRows += 1;
        if (val.pbr !== null && val.pbr !== undefined) pbrRows += 1;
        out.write(JSON.stringify({
          ticker, asOf, pbr: val.pbr ?? null, per: val.per ?? null,
          epsGrowthRate: val.epsGrowthRate ?? null, debtRatio: fundamental.debtRatio ?? null,
        }) + '\n');
      }
    }
    console.log(`${year} 완료 (누적 ${totalRows}행, pbr커버리지 ${(pbrRows / totalRows * 100).toFixed(1)}%)`);
  }
  out.end();
  console.log(`저장 → ${outPath} (${totalRows}행, pbr ${pbrRows}행=${(pbrRows / totalRows * 100).toFixed(1)}%)`);
}

main();
