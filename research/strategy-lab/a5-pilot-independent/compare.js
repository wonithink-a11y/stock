'use strict';

const fs = require('fs');
const path = require('path');

const INDEPENDENT_PATH = path.join(__dirname, 'independent-results.jsonl');
const CLAUDE_PATH = path.join(__dirname, '..', 'a5-pilot', 'output', 'pilot.jsonl');

function loadResults(filePath, isClaude = false) {
  const text = fs.readFileSync(filePath, 'utf8');
  const map = new Map();
  for (const line of text.split('\n').filter(Boolean)) {
    const r = JSON.parse(line);
    const ticker = isClaude ? r.t : r.ticker;
    const asOf = isClaude ? r.d : r.asOf;
    const key = `${ticker}|${asOf}`;
    map.set(key, {
      ticker,
      asOf,
      fwd: r.fwd,
      fwdStatus: r.fwdStatus,
    });
  }
  return map;
}

function fwdStatusMatch(a, b) {
  return a === b;
}

function fwdMatch(a, b, tolerance = 0.0001) {
  if (a === null && b === null) return true;
  if (a === null || b === null) return false;
  return Math.abs(a - b) <= tolerance;
}

function main() {
  console.log('Loading independent results...');
  const independent = loadResults(INDEPENDENT_PATH, false);
  console.log(`Independent records: ${independent.size}`);

  console.log('Loading Claude results...');
  const claude = loadResults(CLAUDE_PATH, true);
  console.log(`Claude records: ${claude.size}`);

  const allKeys = new Set([...independent.keys(), ...claude.keys()]);
  console.log(`Total unique (ticker, asOf) keys: ${allKeys.size}`);

  let comparable = 0;
  const horizonStats = {
    d20: { match: 0, mismatch: 0, fwdMismatch: 0 },
    d60: { match: 0, mismatch: 0, fwdMismatch: 0 },
    d120: { match: 0, mismatch: 0, fwdMismatch: 0 },
  };

  const mismatches = [];

  for (const key of allKeys) {
    const ind = independent.get(key);
    const cla = claude.get(key);

    if (!ind || !cla) {
      continue;
    }

    comparable++;

    for (const horizon of ['d20', 'd60', 'd120']) {
      const indStatus = ind.fwdStatus[horizon];
      const claStatus = cla.fwdStatus[horizon];
      const indFwd = ind.fwd[horizon];
      const claFwd = cla.fwd[horizon];

      const statusMatch = fwdStatusMatch(indStatus, claStatus);

      if (statusMatch) {
        horizonStats[horizon].match++;
      } else {
        horizonStats[horizon].mismatch++;
      }

      if (statusMatch && !fwdMatch(indFwd, claFwd)) {
        horizonStats[horizon].fwdMismatch++;
      }

      if (!statusMatch || (statusMatch && !fwdMatch(indFwd, claFwd))) {
        if (mismatches.length < 20) {
          mismatches.push({
            ticker: ind.ticker,
            asOf: ind.asOf,
            horizon,
            claude: { fwdStatus: claStatus, fwd: claFwd },
            yours: { fwdStatus: indStatus, fwd: indFwd },
          });
        }
      }
    }
  }

  console.log(`\n=== Comparison Summary ===`);
  console.log(`Comparable cells (both have records): ${comparable}`);
  console.log(`Total horizon comparisons: ${comparable * 3}`);

  for (const horizon of ['d20', 'd60', 'd120']) {
    const s = horizonStats[horizon];
    console.log(`\n${horizon}:`);
    console.log(`  fwdStatus match: ${s.match}`);
    console.log(`  fwdStatus mismatch: ${s.mismatch}`);
    console.log(`  fwdStatus match but fwd value differs (>0.0001): ${s.fwdMismatch}`);
  }

  const totalMatch = horizonStats.d20.match + horizonStats.d60.match + horizonStats.d120.match;
  const totalMismatch = horizonStats.d20.mismatch + horizonStats.d60.mismatch + horizonStats.d120.mismatch;
  const totalFwdMismatch = horizonStats.d20.fwdMismatch + horizonStats.d60.fwdMismatch + horizonStats.d120.fwdMismatch;
  console.log(`\nOverall fwdStatus match rate: ${(totalMatch / (totalMatch + totalMismatch) * 100).toFixed(2)}%`);

  console.log('\n=== Mismatch Samples (max 20) ===');
  for (const m of mismatches) {
    console.log(JSON.stringify(m, null, 2));
  }

  const comparison = {
    comparableCells: comparable,
    totalHorizonComparisons: comparable * 3,
    byHorizon: horizonStats,
    overall: {
      fwdStatusMatch: totalMatch,
      fwdStatusMismatch: totalMismatch,
      fwdValueMismatchWhenStatusMatch: totalFwdMismatch,
      fwdStatusMatchRate: totalMatch / (totalMatch + totalMismatch),
    },
    mismatches,
  };

  const outPath = path.join(__dirname, 'comparison.json');
  fs.writeFileSync(outPath, JSON.stringify(comparison, null, 2));
  console.log(`\nWritten comparison.json to ${outPath}`);
}

main();