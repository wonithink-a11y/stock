#!/usr/bin/env node
'use strict';
/**
 * A6 v1 — exitReasonCoverage + GATE-EP-1/2 진단 (docs/BF-1.1-백필계약.md §6.4).
 *
 * A6의 Primary 결론(IC·분위 스프레드 확정 해석)은 두 가지로 막혀 있다:
 *   1. GATE-EP-1/2가 UNKNOWN 비율을 검사해 통과 전까지 Primary를 금지한다
 *   2. EP-1.0의 liquidation/tender 모드가 요구하는 exitPrice를 어느 단계도
 *      아직 수집하지 않는다(A5는 exitPrice:null을 그대로 저장한다)
 * §6.4가 명시적으로 허용하는 것 — exitReasonCoverage 리포트, GATE 판정,
 * 진단 산출물 — 만 계산한다. 이 스크립트는 Primary IC를 만들지 않는다.
 *
 * exitReason 소스는 두 층이다:
 *   A1b baked값     data/backfill/universe/a1b/delisted.jsonl (전건 UNKNOWN, 의도된 미완)
 *   EO overlay(있으면 우선) data/backfill/exitOverlay/v1.jsonl (Tier A+B 승격 분류)
 * A6은 overlay가 있으면 그 값을, 없으면 A1b baked 값을 쓴다(문서 §1이 남긴
 * "A5 baked값 대신 overlay 우선?" 결정 — 이 스크립트가 그 결정을 실제로 구현한다).
 * A5 산출물 자체(data/backfill/scores/)는 exitReason을 다시 계산하지 않는다 — 계약대로
 * baked-in 사실만 저장하고, overlay 반영은 전적으로 A6(이 스크립트) 몫이다.
 *
 * GATE-EP-1  분모: A1b 전체 DELISTED corp 수. UNKNOWN 비율 > 5% → HOLD.
 * GATE-EP-2  분모: A5에 DELISTED 행이 있는 corp 중, 폐지 직전 마지막 스냅샷의
 *            finalScore로 5분위(Q1=최저~Q5=최고) 나눠 분위별 UNKNOWN 비율의
 *            Q5/Q1 비. A5 커버리지가 없는 corp(가격 흔적 자체가 없는 corp,
 *            2026-08-24 후속2·3이 이미 실측한 591종목류)은 원리적으로 점수가
 *            없어 이 분위 계산에서 제외한다 — 지어내지 않는다(교훈57).
 *
 * 사용: node scripts/build-a6-coverage-report.js
 *       node scripts/build-a6-coverage-report.js --selftest
 */
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.join(__dirname, '..');
const A1B_PATH = path.join(ROOT, 'data/backfill/universe/a1b/delisted.jsonl');
const OVERLAY_PATH = path.join(ROOT, 'data/backfill/exitOverlay/v1.jsonl');
const SCORES_DIR = path.join(ROOT, 'data/backfill/scores');
const OUT_DIR = path.join(ROOT, 'docs/verification');

const GATE_EP1_UNKNOWN_RATE_MAX = 0.05;  // §6.4, 결과를 보기 전에 고정된 임계
const GATE_EP2_Q5Q1_RATIO_MAX = 3.0;     // §6.4

function readJsonl(p) {
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

/** A1b baked exitReason(전건 UNKNOWN 가능) 위에 EO overlay(있으면)를 덮어씌운다. */
function effectiveExitReasons(a1bRows, overlayRows) {
  const byCorp = new Map();
  for (const r of a1bRows) byCorp.set(r.corp, { corp: r.corp, ticker: r.ticker, exitReason: r.exitReason, source: 'a1b-baked' });
  for (const r of overlayRows) {
    if (byCorp.has(r.corp)) byCorp.set(r.corp, { corp: r.corp, ticker: r.ticker, exitReason: r.exitReason, source: r.source });
  }
  return byCorp;
}

function computeCoverage(effByCorp) {
  const dist = {};
  for (const { exitReason } of effByCorp.values()) dist[exitReason] = (dist[exitReason] || 0) + 1;
  const total = effByCorp.size;
  const unknown = dist.UNKNOWN || 0;
  return { total, dist, unknown, unknownRate: total ? unknown / total : null };
}

/** A5 scores/*.jsonl.gz를 스트리밍해 DELISTED 행 중 corp별 최신(asOf 최대) 행만 남긴다. */
function latestDelistedScoreByCorp() {
  const files = fs.readdirSync(SCORES_DIR).filter((f) => f.endsWith('.jsonl.gz')).sort();
  const byCorp = new Map();
  for (const f of files) {
    const buf = zlib.gunzipSync(fs.readFileSync(path.join(SCORES_DIR, f)));
    for (const line of buf.toString('utf8').split('\n')) {
      if (!line) continue;
      const r = JSON.parse(line);
      if (r.listingStatus !== 'DELISTED') continue;
      const prev = byCorp.get(r.corp);
      if (!prev || r.d > prev.d) byCorp.set(r.corp, { corp: r.corp, d: r.d, fin: r.fin });
    }
  }
  return byCorp;
}

/** finalScore 기준 5분위(Q1=최저 ~ Q5=최고)로 나누고 분위별 UNKNOWN 비율 계산. */
function computeGateEp2(latestScoreByCorp, effByCorp) {
  const rows = [...latestScoreByCorp.values()]
    .filter((r) => typeof r.fin === 'number' && effByCorp.has(r.corp))
    .map((r) => ({ ...r, exitReason: effByCorp.get(r.corp).exitReason }))
    .sort((a, b) => a.fin - b.fin);

  const n = rows.length;
  if (n < 5) return { eligibleCorps: n, quintiles: null, q5q1Ratio: null, note: '분위 계산에 충분한 corp이 없다(<5)' };

  const quintiles = [];
  for (let q = 0; q < 5; q++) {
    const lo = Math.floor((n * q) / 5);
    const hi = Math.floor((n * (q + 1)) / 5);
    const bucket = rows.slice(lo, hi);
    const unknown = bucket.filter((r) => r.exitReason === 'UNKNOWN').length;
    quintiles.push({
      quintile: `Q${q + 1}`, count: bucket.length, unknown,
      unknownRate: bucket.length ? unknown / bucket.length : null,
      scoreRange: bucket.length ? [bucket[0].fin, bucket[bucket.length - 1].fin] : null,
    });
  }
  const q1 = quintiles[0].unknownRate, q5 = quintiles[4].unknownRate;
  const q5q1Ratio = (q1 && q1 > 0) ? q5 / q1 : null;
  return { eligibleCorps: n, quintiles, q5q1Ratio, note: (q1 === 0 || q1 == null) ? 'Q1 UNKNOWN율이 0이라 비율 계산 불가(N/A) — Q5도 0이 아니면 그 자체가 편중 신호' : null };
}

function renderReport({ coverage, ep1Pass, gateEp2, ep2Pass, overlayPresent, generatedAt }) {
  const distLines = Object.entries(coverage.dist)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `| ${k} | ${v} | ${(100 * v / coverage.total).toFixed(1)}% |`)
    .join('\n');

  const q2Lines = gateEp2.quintiles
    ? gateEp2.quintiles.map((q) => `| ${q.quintile} | ${q.count} | ${q.unknown} | ${q.unknownRate == null ? '-' : (100 * q.unknownRate).toFixed(1) + '%'} | ${q.scoreRange ? q.scoreRange.map((x) => x.toFixed(1)).join(' ~ ') : '-'} |`).join('\n')
    : '(분위 계산 불가 — ' + gateEp2.note + ')';

  return `# A6 v1 — exitReasonCoverage + GATE-EP-1/2 진단 (${generatedAt})

이 리포트는 \`scripts/build-a6-coverage-report.js\`가 계산한다. **Primary 결론
(IC·분위 스프레드 확정 해석)은 포함하지 않는다** — GATE 통과 여부와 무관하게
아직 계산하지 않는다(exitPrice 미수집이 별도로 막고 있다, 아래 참고).

overlay 상태: ${overlayPresent ? 'EO 승격됨 — overlay 분류를 A1b baked 값 위에 덮어썼다' : '**EO 미승격** — A1b baked 값(전건 UNKNOWN)만 사용했다. exit-overlay.yml을 먼저 트리거하라.'}

## exitReasonCoverage (A1b DELISTED corp 전체 ${coverage.total}건 기준)

| exitReason | count | share |
|---|---|---|
${distLines}

## GATE-EP-1

\`\`\`
UNKNOWN ${coverage.unknown} / ${coverage.total} = ${(100 * coverage.unknownRate).toFixed(1)}%   (임계 ${(100 * GATE_EP1_UNKNOWN_RATE_MAX).toFixed(0)}%)
판정: ${ep1Pass ? 'PASS' : 'FAIL → A6 Primary 결론 금지 (HOLD)'}
\`\`\`

## GATE-EP-2 (A5에 DELISTED 행이 있는 ${gateEp2.eligibleCorps}종목 대상, 폐지 직전 최종 finalScore 5분위)

| 분위 | corp 수 | UNKNOWN | UNKNOWN율 | finalScore 범위 |
|---|---|---|---|---|
${q2Lines}

\`\`\`
Q5/Q1 비 = ${gateEp2.q5q1Ratio == null ? 'N/A (' + (gateEp2.note || '') + ')' : gateEp2.q5q1Ratio.toFixed(2)}   (임계 ${GATE_EP2_Q5Q1_RATIO_MAX.toFixed(1)})
판정: ${ep2Pass === null ? 'N/A' : (ep2Pass ? 'PASS' : 'FAIL → HOLD')}
\`\`\`

## 종합 판정

\`\`\`
${(ep1Pass && ep2Pass !== false) ? 'GATE-EP-1/2 통과 — A6 Primary 결론 착수 가능(단 exitPrice 수집은 별도 선결 조건)' : 'HOLD — A6 Primary 결론 금지. 진단 산출물(이 리포트)만 유효하다.'}
\`\`\`

exitPrice(정리매매 최종가·공개매수가) 수집 파이프라인은 이 프로젝트 어디에도
없다 — GATE를 통과해도 liquidation/tender 모드의 EP-1.0 실현수익률 계산은
그 데이터 없이는 불가능하다(별도 🔴 결정, 이번 범위 밖).
`;
}

function selftest() {
  const checks = [];
  const check = (name, cond) => checks.push([name, !!cond]);

  const a1b = [
    { corp: 'A', ticker: '000001', exitReason: 'UNKNOWN' },
    { corp: 'B', ticker: '000002', exitReason: 'UNKNOWN' },
    { corp: 'C', ticker: '000003', exitReason: 'UNKNOWN' },
  ];
  const overlay = [{ corp: 'A', ticker: '000001', exitReason: 'MERGED', source: 'tierA-mergerSpinoff' }];
  const eff = effectiveExitReasons(a1b, overlay);
  check('overlay가 있는 A는 MERGED로 덮어써짐', eff.get('A').exitReason === 'MERGED');
  check('overlay가 없는 B·C는 baked UNKNOWN 유지', eff.get('B').exitReason === 'UNKNOWN' && eff.get('C').exitReason === 'UNKNOWN');

  const cov = computeCoverage(eff);
  check('coverage.total === 3', cov.total === 3);
  check('coverage.unknown === 2', cov.unknown === 2);
  check('coverage.unknownRate === 2/3', Math.abs(cov.unknownRate - 2 / 3) < 1e-9);

  const a1b5 = [
    { corp: 'A', ticker: '000001', exitReason: 'UNKNOWN' },
    { corp: 'B', ticker: '000002', exitReason: 'UNKNOWN' },
    { corp: 'C', ticker: '000003', exitReason: 'UNKNOWN' },
    { corp: 'D', ticker: '000004', exitReason: 'UNKNOWN' },
    { corp: 'E', ticker: '000005', exitReason: 'UNKNOWN' },
  ];
  const overlay5 = [
    { corp: 'A', ticker: '000001', exitReason: 'MERGED', source: 'tierA-mergerSpinoff' },
    { corp: 'B', ticker: '000002', exitReason: 'BANKRUPTCY', source: 'tierB-dart-list-i' },
  ];
  const eff5 = effectiveExitReasons(a1b5, overlay5);
  const latest = new Map([
    ['A', { corp: 'A', d: '2020-01-01', fin: 90 }],
    ['B', { corp: 'B', d: '2020-01-01', fin: 70 }],
    ['C', { corp: 'C', d: '2020-01-01', fin: 50 }],
    ['D', { corp: 'D', d: '2020-01-01', fin: 30 }],
    ['E', { corp: 'E', d: '2020-01-01', fin: 10 }],
  ]);
  const gate2 = computeGateEp2(latest, eff5);
  check('eligibleCorps === 5', gate2.eligibleCorps === 5);
  check('5분위 배열 길이 5', gate2.quintiles.length === 5);
  check('최저 점수(E, Q1)는 UNKNOWN', gate2.quintiles[0].unknown === 1 && gate2.quintiles[0].unknownRate === 1);
  check('최고 점수(A, Q5)는 MERGED라 UNKNOWN 아님', gate2.quintiles[4].unknown === 0);
  check('n<5는 quintiles:null로 안전 처리(경계조건)', computeGateEp2(new Map([['X', { corp: 'X', d: '2020', fin: 1 }]]), eff5).quintiles === null);

  const rendered = renderReport({
    coverage: cov, ep1Pass: cov.unknownRate <= GATE_EP1_UNKNOWN_RATE_MAX,
    gateEp2: gate2, ep2Pass: gate2.q5q1Ratio == null ? null : gate2.q5q1Ratio <= GATE_EP2_Q5Q1_RATIO_MAX,
    overlayPresent: true, generatedAt: '2026-08-24',
  });
  check('리포트 렌더링이 exitReasonCoverage 표를 포함', rendered.includes('exitReasonCoverage'));
  check('리포트가 Primary 결론을 만들지 않는다고 명시', rendered.includes('Primary 결론'));

  const ok = checks.every(([, c]) => c);
  for (const [name, c] of checks) console.log((c ? '  PASS  ' : '  FAIL  ') + name);
  console.log(`\n통과 ${checks.filter(([, c]) => c).length} · 실패 ${checks.filter(([, c]) => !c).length}`);
  return ok ? 0 : 1;
}

function main() {
  if (process.argv.includes('--selftest')) process.exit(selftest());

  if (!fs.existsSync(A1B_PATH)) { console.error(`${A1B_PATH} 없음 — A1b를 먼저 실행하라`); process.exit(1); }
  if (!fs.existsSync(SCORES_DIR)) { console.error(`${SCORES_DIR} 없음 — A5를 먼저 실행하라`); process.exit(1); }

  const a1b = readJsonl(A1B_PATH);
  const overlayPresent = fs.existsSync(OVERLAY_PATH);
  const overlay = overlayPresent ? readJsonl(OVERLAY_PATH) : [];
  const eff = effectiveExitReasons(a1b, overlay);
  const coverage = computeCoverage(eff);
  const ep1Pass = coverage.unknownRate != null && coverage.unknownRate <= GATE_EP1_UNKNOWN_RATE_MAX;

  console.log(`A1b DELISTED corp: ${coverage.total} · overlay: ${overlayPresent ? overlay.length + '건 승격' : '미승격'}`);
  console.log(`GATE-EP-1: UNKNOWN ${coverage.unknown}/${coverage.total} = ${(100 * coverage.unknownRate).toFixed(1)}% → ${ep1Pass ? 'PASS' : 'FAIL'}`);

  console.log('A5 scores/*.jsonl.gz 스트리밍 중...');
  const latest = latestDelistedScoreByCorp();
  const gateEp2 = computeGateEp2(latest, eff);
  const ep2Pass = gateEp2.q5q1Ratio == null ? null : gateEp2.q5q1Ratio <= GATE_EP2_Q5Q1_RATIO_MAX;
  console.log(`GATE-EP-2: eligibleCorps ${gateEp2.eligibleCorps} · Q5/Q1 ${gateEp2.q5q1Ratio == null ? 'N/A' : gateEp2.q5q1Ratio.toFixed(2)} → ${ep2Pass === null ? 'N/A' : (ep2Pass ? 'PASS' : 'FAIL')}`);

  const generatedAt = new Date().toISOString().slice(0, 10);
  const report = renderReport({ coverage, ep1Pass, gateEp2, ep2Pass, overlayPresent, generatedAt });
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const outPath = path.join(OUT_DIR, `BF-1.1-A6-coverage-gate-${generatedAt}.md`);
  fs.writeFileSync(outPath, report, 'utf8');
  console.log(`\nwrote ${path.relative(ROOT, outPath)}`);
}

main();
