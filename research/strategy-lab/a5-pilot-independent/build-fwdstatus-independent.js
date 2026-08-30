'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..', '..');
const PRICE_SOURCE = require(path.join(ROOT, 'lib', 'a5', 'priceSource.js'));

const TICKERS = [
  { ticker: '005930', corp: '00126380' },
  { ticker: '000660', corp: '00164779' },
  { ticker: '005380', corp: '00164742' },
  { ticker: '035420', corp: '00266961' },
  { ticker: '051910', corp: '00356361' },
  { ticker: '000270', corp: '00106641' },
  { ticker: '105560', corp: '00688996' },
  { ticker: '017670', corp: '00159023' },
  { ticker: '230980', corp: '01110076' },
  { ticker: '140910', corp: '00860730' },
  { ticker: '044060', corp: '00291860' },
  { ticker: '495900', corp: '01872893' },
  { ticker: '451700', corp: '01712616' },
  { ticker: '257990', corp: '00425254' },
  { ticker: '439410', corp: '01675254' },
  { ticker: '449020', corp: '01701753' },
  { ticker: '208340', corp: '00972293' },
  { ticker: '008110', corp: '00157104' },
  { ticker: '096040', corp: '00480756' },
  { ticker: '003560', corp: '00154426' },
];

const HORIZONS = {
  d20: 20,
  d60: 60,
  d120: 120,
};

function loadCalendar() {
  const calPath = path.join(ROOT, 'data', 'backfill', 'calendar.json');
  return JSON.parse(fs.readFileSync(calPath, 'utf8'));
}

function loadExitConfirmed() {
  const exitPath = path.join(ROOT, 'data', 'backfill', 'price', 'a2b', 'delisted-exit.jsonl.gz');
  const buf = fs.readFileSync(exitPath);
  const text = zlib.gunzipSync(buf).toString('utf8');
  const map = new Map();
  for (const line of text.split('\n').filter(Boolean)) {
    const r = JSON.parse(line);
    map.set(r.corp, r.exitAtConfirmed);
  }
  return map;
}

function getSnapshotDays(calendar) {
  return calendar.snapshotDays.filter(d => d >= '2025-06-20' && d <= '2026-06-12');
}

function findTradingDayIndex(tradingDays, date) {
  const idx = tradingDays.indexOf(date);
  return idx >= 0 ? idx : -1;
}

function computeForward(ticker, corp, asOf, snapshotPrice, tradingDays, exitConfirmedMap) {
  const asOfIdx = findTradingDayIndex(tradingDays, asOf);
  if (asOfIdx < 0) return null;

  const exitAtConfirmed = exitConfirmedMap.get(corp) || null;

  const results = {};

  for (const [horizonKey, h] of Object.entries(HORIZONS)) {
    const targetIdx = asOfIdx + h;

    if (targetIdx >= tradingDays.length) {
      results[horizonKey] = { fwdStatus: 'FUTURE', fwd: null };
      continue;
    }

    const targetDate = tradingDays[targetIdx];

    if (exitAtConfirmed && targetDate > exitAtConfirmed) {
      results[horizonKey] = { fwdStatus: 'EXIT', fwd: null };
      continue;
    }

    const targetPrice = PRICE_SOURCE.findPrice(ticker, targetDate);
    if (!targetPrice) {
      results[horizonKey] = { fwdStatus: 'MISSING', fwd: null };
      continue;
    }

    if (snapshotPrice.volume <= 0 || targetPrice.volume <= 0) {
      results[horizonKey] = { fwdStatus: 'HALTED', fwd: null };
      continue;
    }

    const fwd = (targetPrice.close - snapshotPrice.close) / snapshotPrice.close;
    results[horizonKey] = { fwdStatus: 'OK', fwd };
  }

  return results;
}

function main() {
  console.log('Loading calendar...');
  const calendar = loadCalendar();
  const tradingDays = calendar.tradingDays;
  const snapshotDays = getSnapshotDays(calendar);
  console.log(`Trading days: ${tradingDays.length}`);
  console.log(`Snapshot days in range: ${snapshotDays.length}`);

  console.log('Loading exit confirmed...');
  const exitConfirmedMap = loadExitConfirmed();
  console.log(`Exit confirmed entries: ${exitConfirmedMap.size}`);

  const results = [];

  for (const { ticker, corp } of TICKERS) {
    console.log(`Processing ${ticker} (${corp})...`);
    let processed = 0;
    let skipped = 0;

    for (const asOf of snapshotDays) {
      const snapshotPrice = PRICE_SOURCE.findPrice(ticker, asOf);
      if (!snapshotPrice) {
        skipped++;
        continue;
      }

      const fwdResults = computeForward(ticker, corp, asOf, snapshotPrice, tradingDays, exitConfirmedMap);
      if (fwdResults) {
        results.push({
          ticker,
          corp,
          asOf,
          fwd: {
            d20: fwdResults.d20.fwd,
            d60: fwdResults.d60.fwd,
            d120: fwdResults.d120.fwd,
          },
          fwdStatus: {
            d20: fwdResults.d20.fwdStatus,
            d60: fwdResults.d60.fwdStatus,
            d120: fwdResults.d120.fwdStatus,
          },
        });
        processed++;
      }
    }
    console.log(`  ${ticker}: processed=${processed}, skipped=${skipped}`);
  }

  const outPath = path.join(__dirname, 'independent-results.jsonl');
  const lines = results.map(r => JSON.stringify(r)).join('\n') + '\n';
  fs.writeFileSync(outPath, lines);
  console.log(`\nWritten ${results.length} records to ${outPath}`);
}

main();