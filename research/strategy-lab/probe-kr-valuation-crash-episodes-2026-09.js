/**
 * probe-kr-valuation-crash-episodes-2026-09.js
 *
 * kr-production-valuation-fundamental-inversion-2026-09.md §4 정정 이후
 * 가설: "2026-07 급락(-31%, 07-06~07-31)처럼 실제 급락기에는 valuation
 * 축이 뒤집히는가." A5 10년 백필 안에 있는 실제 역사적 급락(2020년
 * 코로나, krkospi_raw.parquet 실측 2020-02-17 고점 2242 -> 2020-03-19
 * 저점 1458, -35.7%)을 대조군으로 쓴다 - 같은 8주 규모 창.
 *
 * A5 레코드의 c.valuation·fwd.d20을 그대로 읽는다(재채점 없음).
 *
 *   node research/strategy-lab/probe-kr-valuation-crash-episodes-2026-09.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const readline = require('readline');
const { spearmanIC } = require('../../lib/backtester');

const ROOT = path.join(__dirname, '..', '..');
const SCORES_DIR = path.join(ROOT, 'data', 'backfill', 'scores');

const EPISODES = [
  { label: '2020 코로나 급락(02-17~04-14, -35.7%)', year: '2020', start: '2020-02-17', end: '2020-04-14' },
  { label: '2020 전체', year: '2020', start: '2020-01-01', end: '2020-12-31' },
  { label: '2026-07 급락(07-06~08-31, -31%~반등)', year: '2026', start: '2026-07-06', end: '2026-08-31' },
];

async function readYearFile(year) {
  const filePath = path.join(SCORES_DIR, `${year}.jsonl.gz`);
  if (!fs.existsSync(filePath)) return [];
  const stream = fs.createReadStream(filePath).pipe(zlib.createGunzip());
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  const rows = [];
  let first = true;
  for await (const line of rl) {
    if (!line) continue;
    if (first) { first = false; continue; }
    rows.push(JSON.parse(line));
  }
  return rows;
}

function ic(pairs) {
  const n = pairs.filter((p) => typeof p.x === 'number' && typeof p.y === 'number').length;
  return { ic: spearmanIC(pairs), n };
}

async function main() {
  const yearsNeeded = [...new Set(EPISODES.map((e) => e.year))];
  const rowsByYear = {};
  for (const y of yearsNeeded) rowsByYear[y] = await readYearFile(y);

  for (const ep of EPISODES) {
    const rows = rowsByYear[ep.year].filter((r) => r.d >= ep.start && r.d <= ep.end);
    const pairs = [];
    for (const r of rows) {
      if (!r.fwdStatus || r.fwdStatus.d20 !== 'OK') continue;
      const fr = r.fwd && r.fwd.d20;
      const s = r.c && r.c.valuation;
      if (typeof fr === 'number' && typeof s === 'number') pairs.push({ x: s, y: fr * 100 });
    }
    const { ic: v, n } = ic(pairs);
    console.log(`${ep.label.padEnd(38)} n=${String(n).padStart(6)}  valuation IC=${v === null ? 'null(n<3)' : v.toFixed(4)}`);
  }
}

main();
