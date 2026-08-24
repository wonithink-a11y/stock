#!/usr/bin/env node
/**
 * A5 본백필 — 3,801종목 × 553주(2016-01~2026-08) 전량 PIT 채점.
 *
 * A5 파일럿(build-a5-pilot.js, 20종목×52주)이 이미 검증한 파이프라인을 전체
 * 유니버스·전체 구간으로 확장한다 — resolve()+score()(운영과 같은 엔진)·
 * priceSource.js(A2a 우선·A2b 폴백)·fwd/fwdStatus(FUTURE>EXIT>MISSING>HALTED>OK)
 * 전부 파일럿과 동일 로직. 다른 것은 셋뿐이다.
 *
 *   1. 격자 — 고정 20종목이 아니라 A1a(활성)+A1b(폐지) 전체(3,801),
 *      52주 창이 아니라 calendar.snapshotDays 전체(553주, 2016-01-08~)
 *   2. 샤드 단위 — (corp) 하나다(A3/A3c/A3d와 동일 패턴). 샤드마다 담당
 *      corp의 정적 데이터(A3/A3b/A3c/A3d)를 정확히 한 번만 읽는다
 *   3. 산출물 — BF-1.1 §5 스키마(data/backfill/scores/{YYYY}.jsonl.gz,
 *      _meta 헤더 포함)로 쓴다. 파일럿의 flat pilot.jsonl과 다르다
 *
 * 재개(resume) 상태 파일은 없다 — 표본 실측(60종목 전체 553주 기준
 * 944ms/corp)으로 전체 예상 소요가 순차 약 1시간, 8샤드면 샤드당 약
 * 7~8분이라 실패 시 그 샤드만 처음부터 재시도해도 충분하다(GH Actions
 * "재실행"으로 충분, 파일럿의 SIGKILL급 장시간 실행 전제가 여기엔 없다).
 *
 * 사용:
 *   node scripts/build-a5-backfill.js --plan
 *   node scripts/build-a5-backfill.js --shard N --shards M [--limit N]
 *   node scripts/build-a5-backfill.js --finalize
 *
 * 로컬 실행은 진단 전용이다(규칙 4) — 실행 후 반드시 `git checkout -- data/`.
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const STAGE_VERSION = 'A5.0';
const HORIZONS = [20, 60, 120];
const SHARD_DIR = path.join(ROOT, 'data/backfill/scores/_shards');
const OUT_DIR = path.join(ROOT, 'data/backfill/scores');

// ── 공용 로더 (build-a5-pilot.js와 동일 패턴) ──────────────────────
function readJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

const A3D_CATEGORIES = [
  'split', 'reverseOrConsolidation', 'bonusIssue', 'capitalReductionFree',
  'capitalReductionPaid', 'capitalReductionUnknown', 'rightsOfferingThirdParty',
  'rightsOfferingShareholders', 'mergerSpinoff',
];

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
    const p = `data/backfill/fundamentals/a3d/${cat}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    events = events.concat(readJsonl(p).filter((r) => r.corp === corp).map((r) => ({ ...r, category: cat })));
  }
  return events;
}

function loadStaticBundle(corp) {
  return {
    a3records: findByCorpAcrossYears('data/backfill/fundamentals/a3', corp),
    a3bRecordsAll: findByCorpAcrossYears('data/backfill/fundamentals/a3b', corp),
    a3cRecordsAll: findByCorpAcrossYears('data/backfill/fundamentals/a3c', corp),
    corporateActions: findCorporateActions(corp),
  };
}

function loadA1bByCorp() {
  const rows = readJsonl('data/backfill/universe/a1b/delisted.jsonl');
  const byCorp = new Map();
  for (const r of rows) byCorp.set(r.corp, { exitReason: r.exitReason, exitAt: r.exitAt || null });
  return byCorp;
}

function loadExitAtConfirmedByCorp() {
  const rows = readJsonl('data/backfill/price/a2b/delisted-exit.jsonl.gz');
  const byCorp = new Map();
  for (const r of rows) byCorp.set(r.corp, r.exitAtConfirmed);
  return byCorp;
}

/** 전체 유니버스(A1a+A1b) — corp 기준 정렬. A3/A3c/A3d와 같은 정렬 원칙(결정론). */
function loadUniverse() {
  const a1a = readJsonl('data/backfill/universe/a1a/current.jsonl')
    .map((r) => ({ ticker: r.ticker, corp: r.corp, name: r.name, group: 'active' }));
  const a1b = readJsonl('data/backfill/universe/a1b/delisted.jsonl')
    .map((r) => ({ ticker: r.ticker, corp: r.corp, name: r.corpName, group: 'delisted' }));
  const all = [...a1a, ...a1b];
  all.sort((a, b) => (a.corp < b.corp ? -1 : a.corp > b.corp ? 1 : 0));
  return all;
}

function loadCalendar() {
  const cal = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/calendar.json'), 'utf8'));
  const dateIndex = new Map(cal.tradingDays.map((d, i) => [d, i]));
  return { tradingDays: cal.tradingDays, snapshotDays: cal.snapshotDays, dateIndex, warmupDays: cal.warmupDays };
}

function round(n, d) {
  if (n === null || n === undefined || Number.isNaN(n)) return null;
  const p = Math.pow(10, d);
  return Math.round(n * p) / p;
}

// ── fwd/fwdStatus — build-a5-pilot.js의 computeForward()와 동일 로직 ────
// (OpenCode가 독립 재구현으로 2,379/2,379 일치 확인, 2026-08-24)
function computeForward({ ticker, asOf, exitAtConfirmed, tradingDays, dateIndex, findPrice, snapshotPrice }) {
  const startIdx = dateIndex.get(asOf);
  const fwd = {}, fwdStatus = {};
  for (const h of HORIZONS) {
    const key = `d${h}`;
    const targetIdx = startIdx + h;
    if (targetIdx >= tradingDays.length) {
      fwdStatus[key] = 'FUTURE'; fwd[key] = null; continue;
    }
    const targetDate = tradingDays[targetIdx];
    if (exitAtConfirmed && targetDate > exitAtConfirmed) {
      fwdStatus[key] = 'EXIT'; fwd[key] = null; continue;
    }
    const targetPrice = findPrice(ticker, targetDate);
    if (!targetPrice) {
      fwdStatus[key] = 'MISSING'; fwd[key] = null; continue;
    }
    if (!(snapshotPrice.volume > 0) || !(targetPrice.volume > 0)) {
      fwdStatus[key] = 'HALTED'; fwd[key] = null; continue;
    }
    fwd[key] = round((targetPrice.close - snapshotPrice.close) / snapshotPrice.close, 4);
    fwdStatus[key] = 'OK';
  }
  return { fwd, fwdStatus };
}

// ── plan ────────────────────────────────────────────────────────
function runPlan() {
  const universe = loadUniverse();
  const { snapshotDays } = loadCalendar();
  console.log(JSON.stringify({
    corpCount: universe.length,
    activeCount: universe.filter((u) => u.group === 'active').length,
    delistedCount: universe.filter((u) => u.group === 'delisted').length,
    snapshotCount: snapshotDays.length,
    gridSize: universe.length * snapshotDays.length,
    snapshotFrom: snapshotDays[0], snapshotTo: snapshotDays[snapshotDays.length - 1],
  }, null, 2));
}

// ── 샤드 실행 ───────────────────────────────────────────────────
function runShard(shard, shards, limit, universeLimit) {
  const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
  const { score } = require(path.join(ROOT, 'lib/scoringEngine'));
  const { validate } = require(path.join(ROOT, 'lib/validator'));
  const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
  const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));
  const { findPrice, findCandles } = require(path.join(ROOT, 'lib/a5/priceSource'));

  fs.mkdirSync(SHARD_DIR, { recursive: true });

  // universeLimit(전체 유니버스를 자른다, 샤딩 전) — --limit(샤드 담당분만 자른다,
  // 샤딩 후)과 다르다. universeLimit은 모든 샤드가 같은 축소 유니버스에 합의하므로
  // corpsDone이 정확히 그 축소값으로 수렴한다 — finalize의 인수 조건(gate) 자체를
  // 로컬에서 실제로 통과시켜 검증할 수 있는 유일한 방법이다(전체 3,801종목을 로컬
  // 에서 다 돌리지 않고). smokeTest 플래그가 있으면 verify-diagnostics.js가
  // A2a/A3d와 같은 이유로 정상 산출 승격을 막는다(forbidden).
  const universe = universeLimit ? loadUniverse().slice(0, universeLimit) : loadUniverse();
  const { tradingDays, snapshotDays, dateIndex } = loadCalendar();
  let mine = universe.filter((_, i) => i % shards === shard);
  if (limit) mine = mine.slice(0, limit);

  console.log(`A5 본백필 샤드 ${shard}/${shards} — 담당 ${mine.length}종목 · 스냅샷 ${snapshotDays.length}주`);

  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');
  const a1b = loadA1bByCorp();
  const exitAtConfirmedByCorp = loadExitAtConfirmedByCorp();

  // 연도별 fragment 파일 핸들은 열어두지 않는다 — 매 레코드 appendFileSync로
  // 연다/닫는다(느리지만 프로세스 중단에도 안전, 파일럿에서 검증된 패턴).
  const diag = {
    corpsAssigned: mine.length, corpsDone: 0,
    universeLimit: universeLimit || null, smokeTest: !!(limit || universeLimit),
    noPriceAtAsOf: 0, assembleFailed: 0, validateViolations: 0,
    exitReasonUnknown: 0, written: 0,
    byYear: {},
  };
  const t0 = Date.now();

  for (const { ticker, corp, name, group } of mine) {
    const bundle = loadStaticBundle(corp);
    const isActive = group === 'active';
    const exitInfo = isActive ? null : a1b.get(corp);
    const exitAtConfirmed = exitAtConfirmedByCorp.get(corp) || null;

    for (const asOf of snapshotDays) {
      const price = findPrice(ticker, asOf);
      if (!price) { diag.noPriceAtAsOf += 1; continue; }

      const { candles } = findCandles(ticker, asOf, 260);
      let record = null;
      try {
        const resolved = resolve({
          ticker, corp, asOf,
          fundamentals: bundle.a3records, price, dividendEps: bundle.a3bRecordsAll,
          candles, sharesOutstanding: bundle.a3cRecordsAll, corporateActions: bundle.corporateActions,
        });
        const stockData = { ticker, name, dataCutoff: asOf, state: null, ...resolved.stockData };
        const scoreResult = score(stockData, criteria, policies);
        const result = scoreResult.result;

        let violations = [];
        try {
          violations = validate(scoreResult, policies, { mode: 'lenient' });
        } catch (err) {
          diag.assembleFailed += 1;
          continue; // critical 위반 — 이 레코드는 쓰지 않는다
        }
        if (violations.length) diag.validateViolations += violations.length;

        const { fwd, fwdStatus } = computeForward({
          ticker, asOf, exitAtConfirmed, tradingDays, dateIndex, findPrice, snapshotPrice: price,
        });

        const exitReason = exitInfo ? exitInfo.exitReason : null;
        if (exitReason === 'UNKNOWN') diag.exitReasonUnknown += 1;

        record = {
          d: asOf, t: ticker, corp,
          raw: result.rawScore, pen: result.riskPenalty, fin: result.finalScore,
          c: result.components, cov: result.confidence.coverage, conf: result.confidence.value,
          flags: result.flags,
          listingStatus: isActive ? 'ACTIVE' : 'DELISTED',
          tradingState: result.tradingState,
          exitReason, exitAt: exitInfo ? exitInfo.exitAt : null,
          exitPrice: null, exitPriceType: null, // A6 몫(EP tender/liquidation) — A5는 사실만 저장
          fwd, fwdStatus,
          bm: null, // 벤치마크 동기간 수익률 — 이번 백필 범위 밖
        };
      } catch (err) {
        diag.assembleFailed += 1;
        continue;
      }

      const year = asOf.slice(0, 4);
      const fpath = path.join(SHARD_DIR, `shard-${shard}-${year}.jsonl`);
      fs.appendFileSync(fpath, JSON.stringify(record) + '\n');
      diag.written += 1;
      diag.byYear[year] = (diag.byYear[year] || 0) + 1;
    }
    diag.corpsDone += 1;
    if (diag.corpsDone % 100 === 0) {
      console.log(`  ${diag.corpsDone}/${mine.length}종목 · 기록 ${diag.written} · ${((Date.now() - t0) / 1000).toFixed(0)}s`);
    }
  }

  diag.elapsedSeconds = Math.round((Date.now() - t0) / 1000);
  fs.writeFileSync(path.join(SHARD_DIR, `_diagnostics-shard-${shard}.json`), JSON.stringify(diag, null, 2));

  console.log(`\n샤드 ${shard} 완료 — 기록 ${diag.written} · 가격없음스킵 ${diag.noPriceAtAsOf} · ` +
    `조립실패 ${diag.assembleFailed} · 검증위반 ${diag.validateViolations} · ${diag.elapsedSeconds}초`);
  return 0;
}

// ── finalize ────────────────────────────────────────────────────
// 인수 조건 실패 시 산출물을 쓰지 않는다(manifest 계약, 교훈43) — 그래서
// 먼저 전부 메모리에서 판정한 뒤에만 gz를 쓴다. 두 단계로 나눈 이유는
// 210만 레코드 전체를 한 번에 들고 있지 않기 위해서다: 1단계는 연도별
// 레코드 수만 세고(라인 카운트, JSON.parse 없음), 판정을 통과해야만
// 2단계에서 연도 하나씩 실제로 읽어 정렬·gzip한다(교훈73 — 잴 수 있는
// 만큼만 먼저 재고, 쓰기는 그 뒤에 한다).
function runFinalize() {
  const { hashFile, hashPolicyFiles, verifyUpstream, SCHEMA_VERSION } = require(path.join(ROOT, 'lib/backfillManifest'));
  const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));
  const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
  const { score } = require(path.join(ROOT, 'lib/scoringEngine'));

  const dpath = path.join(OUT_DIR, '_diagnostics.json');
  const abort = (reason, extra) => {
    const diag = { stage: 'A5', aborted: true, abortReason: reason,
      acceptancePassed: false, acceptanceFails: [reason], acceptanceWarns: [], ...extra };
    fs.mkdirSync(OUT_DIR, { recursive: true });
    fs.writeFileSync(dpath, JSON.stringify(diag, null, 2));
    console.error(`\n중단: ${reason}`);
    return 2;
  };

  if (!fs.existsSync(SHARD_DIR)) return abort(`${SHARD_DIR}에 샤드 산출물이 없다 — --shard로 먼저 돌려라`);
  const shardFiles = fs.readdirSync(SHARD_DIR).filter((f) => /^shard-\d+-\d{4}\.jsonl$/.test(f));
  const diagFiles = fs.readdirSync(SHARD_DIR).filter((f) => /^_diagnostics-shard-\d+\.json$/.test(f));
  if (shardFiles.length === 0) return abort('샤드 산출물(shard-N-YYYY.jsonl)이 없다');

  const agg = { corpsAssigned: 0, corpsDone: 0, noPriceAtAsOf: 0, assembleFailed: 0,
    validateViolations: 0, exitReasonUnknown: 0, written: 0 };
  let smokeTest = false, universeLimits = new Set();
  for (const f of diagFiles) {
    const d = JSON.parse(fs.readFileSync(path.join(SHARD_DIR, f), 'utf8'));
    for (const k of Object.keys(agg)) agg[k] += d[k] || 0;
    if (d.smokeTest) smokeTest = true;
    universeLimits.add(d.universeLimit || null);
  }
  if (universeLimits.size > 1) {
    return abort(`샤드마다 --universeLimit 값이 다르다(${[...universeLimits].join(',')}) — 같은 유니버스에 합의하지 못했다`);
  }
  const universeLimit = [...universeLimits][0] || null;
  console.log(`[1/4] 샤드 진단 ${diagFiles.length}개 병합 — 담당 ${agg.corpsAssigned} · 완료 ${agg.corpsDone} · 기록 ${agg.written}` +
    (smokeTest ? ' · smokeTest=true' : ''));

  const universeCount = universeLimit ? Math.min(universeLimit, loadUniverse().length) : loadUniverse().length;
  const corpsIncomplete = universeCount - agg.corpsDone;

  const years = [...new Set(shardFiles.map((f) => f.match(/-(\d{4})\.jsonl$/)[1]))].sort();
  const perYearCounts = {};
  for (const year of years) {
    let n = 0;
    for (const f of shardFiles.filter((sf) => sf.endsWith(`-${year}.jsonl`))) {
      n += fs.readFileSync(path.join(SHARD_DIR, f), 'utf8').split('\n').filter((l) => l.trim()).length;
    }
    perYearCounts[year] = n;
  }

  console.log('[2/4] 인수 조건 판정');
  const scoresPolicy = JSON.parse(fs.readFileSync(path.join(ROOT, 'config/policies/scores.v1.json'), 'utf8'));
  const acc = scoresPolicy.acceptance;
  const attempted = agg.written + agg.assembleFailed;
  const assembleFailedRate = attempted > 0 ? agg.assembleFailed / attempted : 0;

  const fails = [], warns = [];
  const inject = (process.env.SCORES_FAIL_INJECTION || '').trim();
  if (inject) fails.push(`[FAIL INJECTION] ${inject} — 게이트 검증용 강제 실패`);

  if (corpsIncomplete > acc.corpsIncompleteMax) {
    fails.push(`corpsIncomplete=${corpsIncomplete} > ${acc.corpsIncompleteMax} (대상 ${universeCount} · 완료 ${agg.corpsDone})`);
  }
  for (const year of years) {
    if (perYearCounts[year] < acc.minRecordCountPerYear) {
      fails.push(`${year}년 레코드 ${perYearCounts[year]}건 < 최소 ${acc.minRecordCountPerYear}`);
    }
  }
  if (assembleFailedRate > acc.assembleFailedRateWarn) {
    warns.push(`assembleFailedRate ${(assembleFailedRate * 100).toFixed(2)}% > ${acc.assembleFailedRateWarn * 100}% (조립실패 ${agg.assembleFailed}/${attempted})`);
  }
  console.log(`  corpsIncomplete=${corpsIncomplete} · assembleFailedRate=${(assembleFailedRate * 100).toFixed(3)}% · 연도 ${years.length}개`);
  if (warns.length) for (const w of warns) console.log(`  WARN ${w}`);

  if (fails.length) {
    for (const f of fails) console.error(`  FAIL ${f}`);
    return abort(fails[0], { acceptanceFails: fails, acceptanceWarns: warns,
      corpsIncomplete, assembleFailedRate, perYearCounts, ...agg });
  }

  console.log('[3/4] 상류 검증 + 정책 해시');
  const upstream = verifyUpstream(['A0.5', 'A1a', 'A1b', 'A2a', 'A2b', 'A3', 'A3b', 'A3c', 'A3d']);
  const policyHashes = hashPolicyFiles(['confidence', 'validation', 'missingAxis', 'riskPenalty', 'trading', 'stateMap', 'flagCodes', 'universe', 'price', 'fundamentals', 'scores']);
  policyHashes.criteria = hashFile('config/criteria/KR-2.2.json');

  const policies = loadPolicies('KR');
  // engineVersion은 score()의 meta에서 얻는다(하드코딩 금지 — 엔진 자신이 유일한 출처).
  const probe = score({ ticker: '_PROBE_', name: null, dataCutoff: null, state: null,
    fundamental: {} }, loadCriteria('KR').criteria, policies);
  const engineVersion = probe.meta.engineVersion;
  const { warmupDays } = loadCalendar();

  console.log(`[4/4] 연도별 병합·gzip — ${years.length}개 연도(${years[0]}~${years[years.length - 1]})`);
  fs.mkdirSync(OUT_DIR, { recursive: true });
  for (const old of fs.readdirSync(OUT_DIR)) {
    if (/^\d{4}\.jsonl\.gz$/.test(old)) fs.unlinkSync(path.join(OUT_DIR, old));
  }

  let totalRecordCount = 0;
  for (const year of years) {
    const yearFiles = shardFiles.filter((f) => f.endsWith(`-${year}.jsonl`));
    const rows = [];
    for (const f of yearFiles) {
      for (const line of fs.readFileSync(path.join(SHARD_DIR, f), 'utf8').split('\n')) {
        if (line.trim()) rows.push(JSON.parse(line));
      }
    }
    rows.sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : (a.t < b.t ? -1 : 1)));

    const meta = {
      _meta: {
        schemaVersion: SCHEMA_VERSION, stage: 'A5', stageVersion: STAGE_VERSION,
        market: 'KR', year: Number(year), engineVersion,
        policies: policies.versions, policyHashes, upstream,
        warmupDays, recordCount: rows.length,
        _diagnostics: {
          assembleFailed: agg.assembleFailed, validateViolations: agg.validateViolations,
          exitReasonUnknown: agg.exitReasonUnknown,
        },
      },
    };
    const lines = [JSON.stringify(meta), ...rows.map((r) => JSON.stringify(r))];
    const raw = Buffer.from(lines.join('\n') + '\n', 'utf8');
    const gz = zlib.gzipSync(raw, { level: 9 });
    fs.writeFileSync(path.join(OUT_DIR, `${year}.jsonl.gz`), gz);
    totalRecordCount += rows.length;
    console.log(`  ${year}.jsonl.gz — ${rows.length}행`);
  }

  const finalDiag = {
    stage: 'A5', aborted: false, smokeTest,
    acceptancePassed: true, acceptanceFails: [], acceptanceWarns: warns,
    ...agg, recordCount: totalRecordCount, corpsIncomplete, assembleFailedRate, perYearCounts, years,
  };
  fs.writeFileSync(dpath, JSON.stringify(finalDiag, null, 2));

  console.log(`\n${OUT_DIR} — 전체 ${totalRecordCount}행 · ${years.length}개 연도`);
  console.log(JSON.stringify(finalDiag, null, 2));
  return 0;
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--plan')) { runPlan(); return 0; }
  if (args.includes('--finalize')) return runFinalize();

  const shardIdx = args.indexOf('--shard');
  const shardsIdx = args.indexOf('--shards');
  const limitIdx = args.indexOf('--limit');
  const universeLimitIdx = args.indexOf('--universeLimit');
  if (shardIdx === -1 || shardsIdx === -1) {
    console.error('--shard N --shards M [--limit N] [--universeLimit N] · --finalize · --plan 중 하나가 필요하다');
    return 1;
  }
  const shard = Number(args[shardIdx + 1]);
  const shards = Number(args[shardsIdx + 1]);
  const limit = limitIdx === -1 ? 0 : Number(args[limitIdx + 1]);
  const universeLimit = universeLimitIdx === -1 ? 0 : Number(args[universeLimitIdx + 1]);
  if (!(shard >= 0 && shard < shards)) {
    console.error('--shard는 0 이상 --shards 미만이어야 한다');
    return 1;
  }
  return runShard(shard, shards, limit, universeLimit);
}

if (require.main === module) process.exit(main());

module.exports = { computeForward, loadUniverse, loadCalendar };
