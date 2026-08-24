#!/usr/bin/env node
/**
 * A5 파일럿 — 20종목×52주 오케스트레이션 검증 (docs/A5-파일럿-exit-overlay-설계안.md).
 *
 * 목적은 "A5가 좋은 점수를 내는가"가 아니라 "①점 계산 ②가격 조회 ③샤드/재개
 * ④fwd/fwdStatus 넷이 실제로 이어 붙는가"다. 새로 짠 로직은 fwd/fwdStatus뿐
 * (설계안 §2) — 나머지는 이미 검증된 조각을 그대로 잇는다:
 *   1점 계산   scripts/probe-v7-vertical-slice.js와 같은 resolve()+score() 호출
 *   가격 조회   lib/a5/priceSource.js 그대로(A2a 우선·A2b 폴백)
 *   샤드/재개   scripts/build-fundamentals-a3d.py 패턴(state 파일, corp→corp×asOf)
 *
 * exitReason/exitAt는 "그 시점(빌드 시점) A1b 값을 그대로 baked-in"(설계안 §1) —
 * corp별 상수이며 레코드의 asOf와 무관하다. fwdStatus의 EXIT 판정은 이것과
 * 별개로 A2b delisted-exit.jsonl.gz의 exitAtConfirmed(실측 마지막 거래일)를
 * 직접 쓴다 — 설계안 §2가 명시한 대로 "exitAtConfirmed 존재"가 판정 기준이다.
 *
 * 진단 전용(규칙 4) — data/backfill/에 아무것도 쓰지 않는다. 출력은
 * research/strategy-lab/a5-pilot/ 안에만.
 *
 * 사용:
 *   node scripts/test-a5-pilot.js       (선행 회귀 — computeForward() selftest)
 *   node scripts/build-a5-pilot.js --plan
 *   node scripts/build-a5-pilot.js --shard 0 --shards 2
 *   node scripts/build-a5-pilot.js --shard 1 --shards 2
 *   node scripts/build-a5-pilot.js --finalize
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

// ── 파일럿 20종목 (docs/A5-파일럿-exit-overlay-설계안.md §3.1, 실측 확정) ──
const PILOT_SYMBOLS = [
  { ticker: '005930', corp: '00126380', corpName: '삼성전자', group: 'active' },
  { ticker: '000660', corp: '00164779', corpName: 'SK하이닉스', group: 'active' },
  { ticker: '005380', corp: '00164742', corpName: '현대자동차', group: 'active' },
  { ticker: '035420', corp: '00266961', corpName: 'NAVER', group: 'active' },
  { ticker: '051910', corp: '00356361', corpName: 'LG화학', group: 'active' },
  { ticker: '000270', corp: '00106641', corpName: '기아', group: 'active' },
  { ticker: '105560', corp: '00688996', corpName: 'KB금융', group: 'active' },
  { ticker: '017670', corp: '00159023', corpName: 'SK텔레콤', group: 'active' },
  { ticker: '230980', corp: '01110076', corpName: '비유테크놀러지', group: 'tierB' },
  { ticker: '140910', corp: '00860730', corpName: '에이자기관리부동산투자회사', group: 'tierB' },
  { ticker: '044060', corp: '00291860', corpName: '조광아이엘아이', group: 'tierB' },
  { ticker: '495900', corp: '01872893', corpName: '에이엠시지', group: 'tierB' },
  { ticker: '451700', corp: '01712616', corpName: '엔에이치기업인수목적29호', group: 'tierA' },
  { ticker: '257990', corp: '00425254', corpName: '나우코스', group: 'tierA' },
  { ticker: '439410', corp: '01675254', corpName: '엔에이치기업인수목적26호', group: 'unknown' },
  { ticker: '449020', corp: '01701753', corpName: '유안타제13호기업인수목적', group: 'unknown' },
  { ticker: '208340', corp: '00972293', corpName: '파멥신', group: 'unknown' },
  { ticker: '008110', corp: '00157104', corpName: '대동전자', group: 'unknown' },
  { ticker: '096040', corp: '00480756', corpName: '이트론', group: 'unknown' },
  { ticker: '003560', corp: '00154426', corpName: '아이에이치큐', group: 'unknown' },
];

const SNAPSHOT_FROM = '2025-06-20';
const SNAPSHOT_TO = '2026-06-12';
const HORIZONS = [20, 60, 120];

const OUT_DIR = path.join(ROOT, 'research/strategy-lab/a5-pilot');
const SHARD_DIR = path.join(OUT_DIR, '_shards');
const FINAL_DIR = path.join(OUT_DIR, 'output');

// ── 공용 로더 (probe-v7-vertical-slice.js와 같은 패턴) ──────────────
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

/** corp별 정적 데이터(asOf 무관) — 종목당 1회만 읽는다. */
function loadStaticBundle(corp) {
  return {
    a3records: findByCorpAcrossYears('data/backfill/fundamentals/a3', corp),
    a3bRecordsAll: findByCorpAcrossYears('data/backfill/fundamentals/a3b', corp),
    a3cRecordsAll: findByCorpAcrossYears('data/backfill/fundamentals/a3c', corp),
    corporateActions: findCorporateActions(corp),
  };
}

/** A1b의 baked-in exitReason/exitAt — corp별 상수(빌드 시점 값, asOf와 무관). */
function loadA1bByCorp() {
  const rows = readJsonl('data/backfill/universe/a1b/delisted.jsonl');
  const byCorp = new Map();
  for (const r of rows) byCorp.set(r.corp, { exitReason: r.exitReason, exitAt: r.exitAt || null });
  return byCorp;
}

/** A2b 실측 마지막 거래일 — fwdStatus EXIT 판정 전용(레코드 필드로 baked하지 않는다). */
function loadExitAtConfirmedByCorp() {
  const rows = readJsonl('data/backfill/price/a2b/delisted-exit.jsonl.gz');
  const byCorp = new Map();
  for (const r of rows) byCorp.set(r.corp, r.exitAtConfirmed);
  return byCorp;
}

function loadCalendar() {
  const cal = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/calendar.json'), 'utf8'));
  const snapshotDays = cal.snapshotDays.filter((d) => d >= SNAPSHOT_FROM && d <= SNAPSHOT_TO);
  const dateIndex = new Map(cal.tradingDays.map((d, i) => [d, i]));
  return { tradingDays: cal.tradingDays, snapshotDays, dateIndex };
}

function round(n, d) {
  if (n === null || n === undefined || Number.isNaN(n)) return null;
  const p = Math.pow(10, d);
  return Math.round(n * p) / p;
}

// ── fwd/fwdStatus — 이 파일럿에서 새로 짠 유일한 로직 (설계안 §2) ──────
// 우선순위: FUTURE > EXIT > MISSING > HALTED > OK. 지어내지 않는다(교훈57) —
// 못 찾으면 null이지 값을 채우지 않는다.
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
    // returnTransition(price.v1.json) — volume>0인 날 사이에서만 수익률을 잰다.
    if (!(snapshotPrice.volume > 0) || !(targetPrice.volume > 0)) {
      fwdStatus[key] = 'HALTED'; fwd[key] = null; continue;
    }
    fwd[key] = round((targetPrice.close - snapshotPrice.close) / snapshotPrice.close, 4);
    fwdStatus[key] = 'OK';
  }
  return { fwd, fwdStatus };
}

// selftest는 scripts/test-a5-pilot.js에 있다(회귀 발견 관례: scripts/test-*.js).

// ── 격자 ────────────────────────────────────────────────────────
function buildGrid(snapshotDays) {
  const grid = [];
  for (const sym of PILOT_SYMBOLS) {
    for (const d of snapshotDays) grid.push({ ticker: sym.ticker, corp: sym.corp, asOf: d });
  }
  grid.sort((a, b) => (a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : (a.asOf < b.asOf ? -1 : 1)));
  return grid;
}

function cellKey(c) { return `${c.ticker}|${c.asOf}`; }

// ── 샤드 실행 ───────────────────────────────────────────────────
function runShard(shard, shards) {
  const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
  const { score } = require(path.join(ROOT, 'lib/scoringEngine'));
  const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
  const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));
  const { findPrice, findCandles } = require(path.join(ROOT, 'lib/a5/priceSource'));

  fs.mkdirSync(SHARD_DIR, { recursive: true });
  const rpath = path.join(SHARD_DIR, `shard-${shard}.jsonl`);
  const spath = path.join(SHARD_DIR, `_state-${shard}.json`);

  const { tradingDays, snapshotDays, dateIndex } = loadCalendar();
  const grid = buildGrid(snapshotDays);
  const mine = grid.filter((_, i) => i % shards === shard);

  const state = fs.existsSync(spath) ? JSON.parse(fs.readFileSync(spath, 'utf8')) : { shard, shards, doneKeys: [] };
  const done = new Set(state.doneKeys);
  const todo = mine.filter((c) => !done.has(cellKey(c)));

  console.log(`A5 파일럿 샤드 ${shard}/${shards} — 담당 ${mine.length}격자 · 완료 ${mine.length - todo.length} · 남음 ${todo.length}`);

  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');
  const a1b = loadA1bByCorp();
  const exitAtConfirmedByCorp = loadExitAtConfirmedByCorp();
  const staticCache = new Map(); // ticker -> bundle

  const diag = { noPriceAtAsOf: 0, scoreError: 0, written: 0 };

  for (const cell of todo) {
    const { ticker, corp, asOf } = cell;
    const sym = PILOT_SYMBOLS.find((s) => s.ticker === ticker);
    const price = findPrice(ticker, asOf);

    // record는 성공/스킵/오류 셋 중 정확히 하나만 채워진다. 어느 분기든
    // done.add+상태쓰기는 아래 한 곳에서만 한다 — 분기마다 따로 두면
    // 특정 분기의 쓰기 누락이 재개 완결성을 깬다(이 스크립트 첫 실행 때
    // noPriceAtAsOf 분기가 그랬다: 마지막 종목의 후행 스킵 10건이 상태
    // 파일에 안 남아 재개 시 "미완료"로 다시 보였다 — 스킵 자체는 멱등이라
    // 데이터 유실은 아니었지만 재개 완결성 검증에는 실패였다).
    let record = null;
    if (!price) {
      diag.noPriceAtAsOf += 1;
    } else {
      if (!staticCache.has(ticker)) staticCache.set(ticker, loadStaticBundle(corp));
      const bundle = staticCache.get(ticker);
      const { candles } = findCandles(ticker, asOf, 260);

      try {
        const resolved = resolve({
          ticker, corp, asOf,
          fundamentals: bundle.a3records, price, dividendEps: bundle.a3bRecordsAll,
          candles, sharesOutstanding: bundle.a3cRecordsAll, corporateActions: bundle.corporateActions,
        });
        const stockData = { ticker, name: sym.corpName, dataCutoff: asOf, state: null, ...resolved.stockData };
        const result = score(stockData, criteria, policies).result;

        const isActive = sym.group === 'active';
        const exitInfo = isActive ? null : a1b.get(corp);
        const exitAtConfirmed = exitAtConfirmedByCorp.get(corp) || null;
        const { fwd, fwdStatus } = computeForward({
          ticker, asOf, exitAtConfirmed, tradingDays, dateIndex, findPrice, snapshotPrice: price,
        });

        record = {
          d: asOf, t: ticker, corp,
          raw: result.rawScore, pen: result.riskPenalty, fin: result.finalScore,
          c: result.components, cov: result.confidence.coverage, conf: result.confidence.value,
          flags: result.flags,
          listingStatus: isActive ? 'ACTIVE' : 'DELISTED',
          tradingState: result.tradingState,
          exitReason: exitInfo ? exitInfo.exitReason : null,
          exitAt: exitInfo ? exitInfo.exitAt : null,
          exitPrice: null, exitPriceType: null, // 파일럿 범위 밖(설계안 §2·§6) — EP tender/liquidation은 A6 몫
          fwd, fwdStatus,
          bm: null, // 벤치마크 동기간 수익률 — 파일럿 범위 밖(설계안 §2에 없음)
        };
      } catch (err) {
        diag.scoreError += 1;
        console.error(`  SCORE_ERROR ${ticker} ${asOf}: ${err.message}`);
      }
    }

    if (record) {
      // appendFileSync — 동기 쓰기. createWriteStream은 process.exit()가
      // 버퍼를 비우기 전에 종료시켜 셀은 "완료"로 기록되고도 실제 행이
      // 유실되는 사고를 낸다(이 스크립트 첫 실행에서 실제로 그랬다).
      fs.appendFileSync(rpath, JSON.stringify(record) + '\n');
      diag.written += 1;
    }
    done.add(cellKey(cell));

    // 매 셀마다 상태를 즉시 반영한다 — SIGKILL 재개 검증(설계안 §4)이 요구하는 지점.
    state.doneKeys = Array.from(done);
    fs.writeFileSync(spath, JSON.stringify(state));
  }

  console.log(`샤드 ${shard} 완료 — 기록 ${diag.written} · 가격없음스킵 ${diag.noPriceAtAsOf} · 스코어오류 ${diag.scoreError}`);
  return 0;
}

// ── finalize ────────────────────────────────────────────────────
function runFinalize() {
  const shardFiles = fs.existsSync(SHARD_DIR)
    ? fs.readdirSync(SHARD_DIR).filter((f) => /^shard-\d+\.jsonl$/.test(f)) : [];
  if (shardFiles.length === 0) {
    console.error(`${SHARD_DIR}에 샤드 산출물이 없다 — --shard로 먼저 돌려라`);
    return 1;
  }

  const byKey = new Map();
  for (const f of shardFiles) {
    const lines = fs.readFileSync(path.join(SHARD_DIR, f), 'utf8').split('\n').filter(Boolean);
    for (const l of lines) {
      const r = JSON.parse(l);
      byKey.set(`${r.t}|${r.d}`, r); // 같은 키가 여럿이면 마지막(재실행 시 최신)만
    }
  }
  const rows = Array.from(byKey.values());
  rows.sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : (a.t < b.t ? -1 : 1)));

  const { snapshotDays } = loadCalendar();
  const expectedGridSize = PILOT_SYMBOLS.length * snapshotDays.length;

  const fwdStatusDist = { d20: {}, d60: {}, d120: {} };
  const bump = (o, k) => { o[k] = (o[k] || 0) + 1; };
  for (const r of rows) for (const h of HORIZONS) bump(fwdStatusDist[`d${h}`], r.fwdStatus[`d${h}`]);

  const exitByCorp = {};
  for (const r of rows) {
    if (r.fwdStatus.d120 === 'EXIT') {
      exitByCorp[r.t] = (exitByCorp[r.t] || 0) + 1;
    }
  }

  const diag = {
    generatedAt: new Date().toISOString(),
    shardCount: shardFiles.length,
    expectedGridSize,
    rowCount: rows.length,
    duplicateKeysCollapsed: shardFiles.reduce((sum, f) =>
      sum + fs.readFileSync(path.join(SHARD_DIR, f), 'utf8').split('\n').filter(Boolean).length, 0) - rows.length,
    fwdStatusDistribution: fwdStatusDist,
    d120ExitCountByTicker: exitByCorp,
  };

  fs.mkdirSync(FINAL_DIR, { recursive: true });
  const outPath = path.join(FINAL_DIR, 'pilot.jsonl');
  fs.writeFileSync(outPath, rows.map((r) => JSON.stringify(r)).join('\n') + '\n');
  const diagPath = path.join(FINAL_DIR, '_diagnostics.json');
  fs.writeFileSync(diagPath, JSON.stringify(diag, null, 2));

  console.log(`${outPath} — ${rows.length}행`);
  console.log(JSON.stringify(diag, null, 2));
  return 0;
}

function runPlan() {
  const { snapshotDays } = loadCalendar();
  console.log(JSON.stringify({
    symbolCount: PILOT_SYMBOLS.length,
    snapshotCount: snapshotDays.length,
    gridSize: PILOT_SYMBOLS.length * snapshotDays.length,
    snapshotFrom: snapshotDays[0], snapshotTo: snapshotDays[snapshotDays.length - 1],
  }, null, 2));
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--plan')) { runPlan(); return 0; }
  if (args.includes('--finalize')) return runFinalize();

  const shardIdx = args.indexOf('--shard');
  const shardsIdx = args.indexOf('--shards');
  if (shardIdx === -1 || shardsIdx === -1) {
    console.error('--shard N --shards M · --finalize · --plan · --selftest 중 하나가 필요하다');
    return 1;
  }
  const shard = Number(args[shardIdx + 1]);
  const shards = Number(args[shardsIdx + 1]);
  if (!(shard >= 0 && shard < shards)) {
    console.error('--shard는 0 이상 --shards 미만이어야 한다');
    return 1;
  }
  return runShard(shard, shards);
}

if (require.main === module) process.exit(main());

module.exports = { computeForward, buildGrid, PILOT_SYMBOLS };
