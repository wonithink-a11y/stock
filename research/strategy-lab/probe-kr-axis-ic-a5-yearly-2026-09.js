/**
 * probe-kr-axis-ic-a5-yearly-2026-09.js
 *
 * kr-production-valuation-fundamental-inversion-2026-09.md §6이 제안한
 * 다음 단계 - 41일 production 이력 대신 이미 완성된 A5 10년 백필
 * (data/backfill/scores/, KR-2.3 적용, 1,254,759행)로 valuation·
 * fundamental 축 IC를 연도별로 쪼갠다.
 *
 * 사용자 제기 가설: "2025·2026년 장이 너무 좋아서 그 두 해가 다른 해의
 * 신호를 희석시키는 게 아닌가" - PBR 2022년 집중 검증
 * (pbr-macro-rate-regime-check-2026-08.md §3, "ex-2022 재검산")과 같은
 * 방식으로 연도별 IC를 내고 "전체 10년" vs "2025·2026 제외"를 직접 대조한다.
 *
 * A5 레코드는 이미 c.{fundamental,valuation,technical,supplyDemand}
 * (축 점수)와 fwd.d20(20거래일 실제 수익률)을 갖고 있다 - 재채점 없이
 * 그대로 읽는다. fwdStatus.d20 !== "OK"인 행은 제외(교훈57 - 모르는 건 0이
 * 아니다).
 *
 *   node research/strategy-lab/probe-kr-axis-ic-a5-yearly-2026-09.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const readline = require('readline');
const { spearmanIC } = require('../../lib/backtester');

const ROOT = path.join(__dirname, '..', '..');
const SCORES_DIR = path.join(ROOT, 'data', 'backfill', 'scores');
const AXES = ['fundamental', 'valuation', 'technical', 'supplyDemand'];
const DILUTE_YEARS = new Set(['2025', '2026']); // 사용자 가설 - 검증 대상, 사전에 정한다

async function readYearFile(year) {
  const filePath = path.join(SCORES_DIR, `${year}.jsonl.gz`);
  const stream = fs.createReadStream(filePath).pipe(zlib.createGunzip());
  const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
  const rows = [];
  let first = true;
  for await (const line of rl) {
    if (!line) continue;
    if (first) { first = false; continue; } // 첫 줄은 _meta 헤더
    rows.push(JSON.parse(line));
  }
  return rows;
}

function ic(pairs) {
  const n = pairs.filter((p) => typeof p.x === 'number' && typeof p.y === 'number').length;
  return { ic: spearmanIC(pairs), n };
}

async function main() {
  const years = fs.readdirSync(SCORES_DIR)
    .filter((f) => /^\d{4}\.jsonl\.gz$/.test(f))
    .map((f) => f.slice(0, 4))
    .sort();

  // axis -> year -> pairs[], axis -> 'all'/'exDilute' -> pairs[]
  const byYear = {};
  for (const axis of AXES) byYear[axis] = {};

  for (const year of years) {
    const rows = await readYearFile(year);
    for (const axis of AXES) byYear[axis][year] = [];
    for (const row of rows) {
      if (!row.fwdStatus || row.fwdStatus.d20 !== 'OK') continue;
      const fr = row.fwd && row.fwd.d20;
      if (typeof fr !== 'number') continue;
      for (const axis of AXES) {
        const s = row.c && row.c[axis];
        if (typeof s === 'number') byYear[axis][year].push({ x: s, y: fr * 100 }); // % 단위로 통일
      }
    }
    console.log(`  ${year} 로드 완료 (${rows.length}행)`);
  }

  console.log('\n=== 연도별 IC (d20) ===');
  for (const axis of AXES) {
    console.log(`\n[${axis}]`);
    for (const year of years) {
      const { ic: v, n } = ic(byYear[axis][year]);
      const flag = v !== null && v < 0 ? '  << 역방향' : '';
      const dilute = DILUTE_YEARS.has(year) ? '  (가설상 희석 후보)' : '';
      console.log(`  ${year}  n=${String(n).padStart(6)}  IC=${v === null ? 'null' : v.toFixed(4)}${flag}${dilute}`);
    }
  }

  console.log('\n=== 전체 10년 vs 2025·2026 제외 (희석 가설 직접 대조) ===');
  for (const axis of AXES) {
    const allPairs = years.flatMap((y) => byYear[axis][y]);
    const exDilutePairs = years.filter((y) => !DILUTE_YEARS.has(y)).flatMap((y) => byYear[axis][y]);
    const full = ic(allPairs);
    const ex = ic(exDilutePairs);
    console.log(`  ${axis.padEnd(14)} 전체10년 n=${full.n} IC=${full.ic === null ? 'null' : full.ic.toFixed(4)}   |   2025·26 제외 n=${ex.n} IC=${ex.ic === null ? 'null' : ex.ic.toFixed(4)}`);
  }
}

main();
