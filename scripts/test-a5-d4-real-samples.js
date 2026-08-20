#!/usr/bin/env node
/**
 * A5-3 D4 — 실제 수집 데이터(N=20+ 표본) 통합 회귀.
 *   node scripts/test-a5-d4-real-samples.js
 *
 * docs/control/세션인수인계-2026-08-20-c.md §3 "다음 순서 1"·
 * docs/A5-3-peg-조정기준-결정브리프.md §14 4번이 요구한 작업 — 기존
 * scripts/test-a5-d4.js는 손으로 만든 단일 이벤트 픽스처로 순수 함수만
 * 검증한다. 이 파일은 다르다: **실제 data/backfill/fundamentals/{a3,a3c,a3d}**
 * 에서 진짜 corp을 뽑아, 그 corp의 실제 이벤트 전부(복합·중복 포함, 손으로
 * 안 고름)를 그대로 resolver.js의 sharesOutstandingFrom·valuationD4From에
 * 태운다 — 메시지가 지저분한 실데이터에서 파이프라인이 죽지 않고 구조적으로
 * 정직하게(값 아니면 알려진 withheldBy) 동작하는지가 검증 대상이다.
 *
 * split·reverseOrConsolidation의 multiplier는 2026-08-21 PIT 버그 수정
 * (scripts/build-fundamentals-a3d.py) 이후 값으로 로컬 재계산해서 쓴다 —
 * 실제 data/backfill/fundamentals/a3d/ 산출물은 아직 재수집 전이라 옛
 * (버그 있는) multiplier를 담고 있고, 그걸 그대로 쓰면 이 회귀가 옛 버그를
 * "정답"으로 착각한다(교훈72와 같은 함정 — 유도된 값으로 그 값을 검사하지
 * 않는다). research/strategy-lab/probe_a3d_pit_fix_impact.py가 이미 만든
 * findings/a3d-bracket-candidates/pit-fix-impact.json(corp·category·
 * disclosureDate·newMultiplier)을 재사용한다.
 *
 * 네트워크 없음. 표본은 seed 고정 셔플로 재현 가능하다.
 */
'use strict';
const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { sharesOutstandingFrom, valuationD4From } = require(path.join(ROOT, 'lib/a5/resolver'));

let passed = 0, failed = 0;
function ok(name, cond, detail) {
  if (cond) { passed++; }
  else { failed++; console.log(`  FAIL  ${name}${detail ? '  — ' + detail : ''}`); }
}

function readGzJsonl(rel) {
  const buf = fs.readFileSync(path.join(ROOT, rel));
  return zlib.gunzipSync(buf).toString('utf8').split('\n').filter(Boolean).map(JSON.parse);
}

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const A3D_CATEGORIES = [
  'split', 'reverseOrConsolidation', 'bonusIssue', 'capitalReductionFree',
  'capitalReductionPaid', 'capitalReductionUnknown', 'rightsOfferingThirdParty',
  'rightsOfferingShareholders', 'mergerSpinoff',
];
const VALID_WITHHOLD_CODES = new Set([
  'SHARES_MISSING', 'SHARES_EXCEED_AUTHORIZED', 'SHARES_IMPLAUSIBLE', 'DART_MATCH_FAIL',
  'COMPOUND_EVENT', 'RIGHTS_FORMULA_UNVERIFIED', 'CAPITAL_REDUCTION_TYPE_UNKNOWN', 'MERGER_UNHANDLED',
]);

function main() {
  // ── 원자료 로드 ──
  const pitFix = JSON.parse(fs.readFileSync(
    path.join(ROOT, 'research/strategy-lab/findings/a3d-bracket-candidates/pit-fix-impact.json'), 'utf8'));
  const fixedMultiplier = new Map(); // `${corp}|${category}|${disclosureDate}` -> newMultiplier
  for (const r of pitFix.records) {
    fixedMultiplier.set(`${r.corp}|${r.category}|${r.disclosureDate}`, r.newMultiplier);
  }

  let a3dAll = [];
  for (const cat of A3D_CATEGORIES) {
    a3dAll = a3dAll.concat(readGzJsonl(`data/backfill/fundamentals/a3d/${cat}.jsonl.gz`).map((r) => ({ ...r, category: cat })));
  }
  const a3dByCorp = new Map();
  for (const r of a3dAll) {
    if (!a3dByCorp.has(r.corp)) a3dByCorp.set(r.corp, []);
    a3dByCorp.get(r.corp).push(r);
  }

  const a3cYears = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025'];
  const a3cByCorp = new Map();
  for (const y of a3cYears) {
    const p = `data/backfill/fundamentals/a3c/${y}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    for (const r of readGzJsonl(p)) {
      if (!a3cByCorp.has(r.corp)) a3cByCorp.set(r.corp, []);
      a3cByCorp.get(r.corp).push(r);
    }
  }

  const a3Years = a3cYears;
  const a3ByCorp = new Map();
  for (const y of a3Years) {
    const p = `data/backfill/fundamentals/a3/${y}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    for (const r of readGzJsonl(p)) {
      if (!a3ByCorp.has(r.corp)) a3ByCorp.set(r.corp, []);
      a3ByCorp.get(r.corp).push(r);
    }
  }

  // ── corporateActions 빌드 (split·reverseOrConsolidation은 수정된 배수로 치환) ──
  function buildCorporateActions(corp) {
    const events = a3dByCorp.get(corp) || [];
    const out = [];
    for (const e of events) {
      let multiplier = e.multiplier;
      if (e.category === 'split' || e.category === 'reverseOrConsolidation') {
        const key = `${corp}|${e.category}|${e.disclosureDate}`;
        multiplier = fixedMultiplier.has(key) ? fixedMultiplier.get(key) : null;
        if (multiplier === null) continue; // 수정 후 None(BRACKET_MISSING)이 될 레코드 — 재수집됐다면 애초에 안 실렸을 것
      }
      out.push({ category: e.category, disclosureDate: e.disclosureDate, multiplier, rceptNo: e.rceptNo });
    }
    return out;
  }

  // ── 표본 선정: a3d 이벤트가 있고 a3c·a3 데이터도 있는 corp 중 seed 고정 셔플 ──
  const eligible = [...a3dByCorp.keys()].filter((corp) => a3cByCorp.has(corp) && a3ByCorp.has(corp));
  const rnd = mulberry32(20260821);
  const randomSample = [...eligible].sort(() => rnd() - 0.5).slice(0, 20);

  // 무작위 표본은 대부분 이벤트가 여러 건(복합)이라 exact-value 재검증(단일
  // splitLike)이 잘 안 걸린다 — "정확값 재검증"이 실제로 몇 건은 돌게, 단일
  // splitLike 이벤트만 가진 corp을 별도로 5개 더 얹는다(결정적, corp 오름차순).
  const singleSplitLike = eligible.filter((corp) => {
    const acts = buildCorporateActions(corp);
    return acts.length === 1 && (acts[0].category === 'split' || acts[0].category === 'reverseOrConsolidation');
  }).sort().slice(0, 5);

  const sample = [...new Set([...randomSample, ...singleSplitLike])];
  console.log(`[표본] 이벤트+A3c+A3 전부 있는 corp ${eligible.length}개 중 무작위 20개(seed=20260821) `
    + `+ 단일splitLike 5개 = ${sample.length}개`);

  let cleanExactChecks = 0;
  for (const corp of sample) {
    const a3cRecords = a3cByCorp.get(corp);
    const a3Records = a3ByCorp.get(corp);
    const corporateActions = buildCorporateActions(corp);
    const ticker = (a3cRecords[0] || {}).ticker || (a3Records[0] || {}).ticker;

    // asOf = 이 corp이 가진 가장 늦은 A3c availableFrom(=지금까지 알려진 최신 시점)
    const asOf = a3cRecords.reduce((m, r) => (r.availableFrom > m ? r.availableFrom : m), '0');
    const latestFY = a3Records.reduce((m, r) => Math.max(m, r.fiscalYear), 0);
    // 가장 이른 회계연도 — "사건보다 먼저 접수된 레코드"에 해당할 확률이 높아
    // splitLike의 실제 forward 보정(factor 곱하기) 경로를 더 자주 실행시킨다.
    const earliestFY = a3Records.reduce((m, r) => Math.min(m, r.fiscalYear), Infinity);

    let threw = null;
    let shares = null;
    try {
      shares = sharesOutstandingFrom(a3cRecords, latestFY, asOf, corporateActions);
    } catch (e) {
      threw = e;
    }
    ok(`[${corp}/${ticker}] sharesOutstandingFrom이 예외 없이 끝난다`, threw === null, threw && threw.stack);
    if (threw) continue;

    const structurallyValid = shares.withheldBy
      ? (shares.value === null && VALID_WITHHOLD_CODES.has(shares.withheldBy))
      : (typeof shares.value === 'number' && shares.value > 0);
    ok(`[${corp}/${ticker}] 값 아니면 알려진 withheldBy 코드 — 결과: ${shares.withheldBy || shares.value}`,
       structurallyValid, JSON.stringify(shares));

    let val = null, threwVal = null;
    try {
      val = valuationD4From(a3Records, a3cRecords, corporateActions, asOf, null);
    } catch (e) {
      threwVal = e;
    }
    ok(`[${corp}/${ticker}] valuationD4From이 예외 없이 끝난다`, threwVal === null, threwVal && threwVal.stack);
    if (threwVal) continue;
    if (val.provenance) {
      const cur = val.provenance.sharesOutstanding.cur;
      const curValid = cur.withheldBy
        ? (cur.value === null && VALID_WITHHOLD_CODES.has(cur.withheldBy))
        : (typeof cur.value === 'number' && cur.value > 0);
      ok(`[${corp}/${ticker}] valuationD4From의 cur sharesOutstanding도 구조적으로 정직하다`,
         curValid, JSON.stringify(cur));
    }

    // 이벤트가 정확히 하나(단일 splitLike, 복합 아님)면 factor를 직접 재검증할 수 있다.
    // latest·earliest 회계연도 둘 다 시도 — earliest가 "사건보다 먼저 접수된
    // 레코드"에 해당해 실제 forward 보정(factor 곱하기) 경로를 탈 확률이 높다.
    const splitLikeEvents = corporateActions.filter((e) => e.category === 'split' || e.category === 'reverseOrConsolidation');
    if (corporateActions.length === 1 && splitLikeEvents.length === 1) {
      for (const [label, fy] of [['latest', latestFY], ['earliest', earliestFY]]) {
        if (fy === latestFY && label === 'earliest' && earliestFY === latestFY) continue; // 같은 연도 중복 방지
        let s2;
        try { s2 = sharesOutstandingFrom(a3cRecords, fy, asOf, corporateActions); } catch (e) { continue; }
        if (s2.withheldBy || !s2.record) continue;
        const applied = s2.factor !== 1; // 사건이 레코드보다 미래일 때만 곱해진다
        if (!applied) continue;
        const raw = s2.record.istcTotqy;
        const expected = raw * splitLikeEvents[0].multiplier;
        ok(`[${corp}/${ticker}/${label}FY=${fy}] 단일 splitLike 이벤트 — factor 재계산 일치`,
           Math.abs(s2.value - expected) < 1, `raw=${raw} mult=${splitLikeEvents[0].multiplier} got=${s2.value} want=${expected}`);
        cleanExactChecks++;
      }
    }
  }

  console.log(`[정확값 재검증] 단일 splitLike 이벤트로 factor를 직접 대조한 표본 ${cleanExactChecks}건`);
  console.log(`${'='.repeat(54)}`);
  console.log(`통과 ${passed} · 실패 ${failed}`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
