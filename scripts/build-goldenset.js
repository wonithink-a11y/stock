#!/usr/bin/env node
/**
 * TASK-2A: Classifier 골든셋 + Source Coverage 측정
 *
 * 조회 대상 = TASK-2B 스냅샷(관리종목·거래정지·투자주의환기) 전 종목 ∪ watchlist 한국 종목
 * 출력  : data/goldenset/disclosures-raw.json , data/goldenset/report.md
 * 읽기 전용 — data/state/, data/state-history/ 에 일절 접근하지 않는다.
 *
 *   DART_API_KEY=xxxx node scripts/build-goldenset.js
 *
 * 측정하는 두 지표(§8-(4)):
 *   ① Classifier 정확도 → 표1~4를 사람이 라벨링(P2)해서 산출. 이 스크립트는 원자료만 만든다.
 *   ② Source coverage   → 이 스크립트가 직접 산출한다. 합격선 없음, 관측만 한다.
 *
 * 파일 크기 방침: 2년치 전 공시를 그대로 담으면 수십 MB가 되어 매 실행마다 저장소가 불어난다.
 *   - 분류된 공시(classifiedAs 비어있지 않음)  → 전량 저장 (라벨링 대상)
 *   - 누락 후보(미분류인데 시장조치 어휘 포함) → 전량 저장 (라벨링 대상)
 *   - 그 밖의 미분류                          → 저장하지 않고 reportNm 빈도만 집계 (표2)
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { classify, CLASSIFIER_VERSION } = require('../lib/eventClassifiers/dart');

const KEY = process.env.DART_API_KEY;
const ROOT = path.resolve(__dirname, '..');
const GOLDEN_DIR = path.join(ROOT, 'data', 'goldenset');
const SNAPSHOT_PATH = path.join(GOLDEN_DIR, 'market-actions-snapshot.json');
const WATCHLIST_PATH = path.join(ROOT, 'config', 'watchlist.json');
const OUT_JSON = path.join(GOLDEN_DIR, 'disclosures-raw.json');
const OUT_MD = path.join(GOLDEN_DIR, 'report.md');
const BASE = 'https://opendart.fss.or.kr/api';

const LOOKBACK_DAYS = Number(process.env.GOLDENSET_LOOKBACK_DAYS || 730);
const DART_DELAY_MS = Number(process.env.DART_DELAY_MS || 120);
const MAX_PAGES = Number(process.env.GOLDENSET_MAX_PAGES || 20);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const kstYmd = (offsetDays = 0) =>
  new Date(Date.now() + 9 * 3600e3 - offsetDays * 86400e3).toISOString().slice(0, 10).replace(/-/g, '');
const kstNow = () => new Date(Date.now() + 9 * 3600e3).toISOString().replace(/\.\d{3}Z$/, '+09:00');

// 정상 문자열: ASCII + 한글 음절/자모 + 한자·전각기호(DART report_nm에 실제로 등장).
// 그 밖(U+0080~U+00FF, U+FFFD)은 인코딩 사고의 흔적이다.
const TEXT_CHARSET = /^[\x20-\x7E\uAC00-\uD7A3\u3131-\u318E\u4E00-\u9FFF\u3000-\u303F\uFF01-\uFF60·ㆍ○△▲□■◇◆★※]*$/;

// 스냅샷 종류 → 관측되어야 할 이벤트 타입
const EXPECT = {
  management: ['MANAGEMENT_DESIGNATION'],
  tradingHalt: ['TRADING_HALT'],
  investmentWarning: ['INVESTMENT_WARNING'],
};
const DATE_KEY = { management: 'designatedAt', tradingHalt: 'haltedAt', investmentWarning: 'designatedAt' };

// 표3 누락후보: classifier가 못 잡았지만 시장조치를 뜻할 수 있는 어휘.
// classifier의 트리거 어휘(관리종목·거래정지 등)와 일부러 겹치지 않게 구성했다 —
// 겹치면 "정의상 0건"이 나와 검사 의미가 없다.
const MISSING_RE = /상장적격성|실질심사|퇴출|정리매매|주권매매|환기종목|불성실공시|자본잠식|감사의견|의견거절|한정의견|부적정|회생절차|파산|워크아웃|영업정지|횡령|배임|주식분산기준|시가총액미달/;
// 표4 오분류후보: 분류는 됐지만 사람이 확인해야 하는 정황(정정·타법인·자회사 등)
const FP_RE = /정정|첨부|기재정정|타법인|자회사|종속회사|해외|참고|안내|기타경영사항|풍문|조회공시|답변/;

/* ────────────────── DART ────────────────── */

function unzipFirstEntry(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 70000; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('ZIP EOCD를 찾지 못했습니다');
  const cdOff = buf.readUInt32LE(eocd + 16);
  if (buf.readUInt32LE(cdOff) !== 0x02014b50) throw new Error('ZIP 중앙디렉터리 서명 불일치');
  const method = buf.readUInt16LE(cdOff + 10);
  const compSize = buf.readUInt32LE(cdOff + 20);
  const localOff = buf.readUInt32LE(cdOff + 42);
  const start = localOff + 30 + buf.readUInt16LE(localOff + 26) + buf.readUInt16LE(localOff + 28);
  const data = buf.subarray(start, start + compSize);
  return (method === 0 ? data : zlib.inflateRawSync(data)).toString('utf8');
}

async function loadCorpMap() {
  const res = await fetch(`${BASE}/corpCode.xml?crtfc_key=${KEY}`);
  if (!res.ok) throw new Error(`corpCode HTTP ${res.status}`);
  const xml = unzipFirstEntry(Buffer.from(await res.arrayBuffer()));
  const map = {};
  const re = /<list>([\s\S]*?)<\/list>/g;
  let m;
  while ((m = re.exec(xml))) {
    const cc = (m[1].match(/<corp_code>(.*?)<\/corp_code>/) || [])[1];
    const sc = (m[1].match(/<stock_code>(.*?)<\/stock_code>/) || [])[1];
    if (cc && sc && sc.trim()) map[sc.trim()] = cc.trim();
  }
  return map;
}

/** list.json은 corp_code 없이 조회하면 기간 제한이 걸린다. 연 단위로 쪼개 안전하게 호출한다. */
function dateRanges(bgnDe, endDe) {
  const out = [];
  let cur = bgnDe;
  while (cur <= endDe) {
    const y = Number(cur.slice(0, 4));
    const yEnd = `${y}1231`;
    out.push([cur, yEnd < endDe ? yEnd : endDe]);
    cur = `${y + 1}0101`;
  }
  return out;
}

async function fetchList(corp, bgnDe, endDe) {
  const items = [];
  for (const [bgn, end] of dateRanges(bgnDe, endDe)) {
    for (let page = 1; page <= MAX_PAGES; page++) {
      const url = `${BASE}/list.json?` + new URLSearchParams({
        crtfc_key: KEY, corp_code: corp, bgn_de: bgn, end_de: end,
        page_no: String(page), page_count: '100',
      });
      const res = await fetch(url);
      if (!res.ok) throw new Error(`list HTTP ${res.status}`);
      const j = await res.json();
      if (j.status === '013') break;                                   // 조회 결과 없음
      if (j.status === '020') throw new Error('DART 일일 사용한도 초과(020)');  // 치명 — 즉시 중단
      if (j.status && j.status !== '000') throw new Error(`list [${j.status}] ${j.message}`);
      items.push(...(j.list || []));
      if (page >= Number(j.total_page || 1)) break;
      await sleep(DART_DELAY_MS);
    }
    await sleep(DART_DELAY_MS);
  }
  return items;
}

/* ────────────────── 순수 로직 (테스트 대상) ────────────────── */

/** 스냅샷 + watchlist → 조회 대상 유니온 */
function buildTargets(snapshot, watchlist) {
  const byTicker = new Map();
  const add = (ticker, name, origin) => {
    if (!/^\d{6}$/.test(String(ticker || ''))) return;
    const t = byTicker.get(ticker) || { ticker, name: name || null, origin: [] };
    if (!t.name && name) t.name = name;
    if (!t.origin.includes(origin)) t.origin.push(origin);
    byTicker.set(ticker, t);
  };
  for (const kind of Object.keys(EXPECT)) {
    for (const r of snapshot[kind] || []) add(r.ticker, r.name, `snapshot:${kind}`);
  }
  for (const t of watchlist.tickers || []) {
    if ((t.market || 'KR') === 'KR') add(t.code, t.name, 'watchlist');
  }
  return [...byTicker.values()].sort((a, b) => a.ticker.localeCompare(b.ticker));
}

/**
 * Source coverage — 스냅샷의 각 행이 DART 공시로 관측되는가.
 * 3버킷: OBSERVED / NOT_OBSERVED / OUT_OF_RANGE
 * coverage = OBSERVED / (OBSERVED + NOT_OBSERVED)
 * OUT_OF_RANGE는 "우리가 안 본 것"이지 "DART에 없는 것"이 아니므로 분모에서 뺀다.
 */
function buildCoverage(snapshot, disclosuresByTicker, corpMap, bgnDe) {
  const rows = [];
  for (const kind of Object.keys(EXPECT)) {
    for (const r of snapshot[kind] || []) {
      const want = EXPECT[kind];
      const hits = (disclosuresByTicker.get(r.ticker) || [])
        .filter((d) => d.classifiedAs.some((t) => want.includes(t)));
      const at = (r[DATE_KEY[kind]] || '').replace(/-/g, '') || null;

      let bucket, reason;
      if (hits.length > 0) { bucket = 'OBSERVED'; reason = null; }
      else if (!corpMap[r.ticker]) { bucket = 'NOT_OBSERVED'; reason = 'NO_CORP_CODE'; }
      else if (at && at < bgnDe) { bucket = 'OUT_OF_RANGE'; reason = 'BEFORE_WINDOW'; }
      else if (!at) { bucket = 'OUT_OF_RANGE'; reason = 'DATE_UNKNOWN'; }
      else { bucket = 'NOT_OBSERVED'; reason = 'IN_WINDOW_NOT_FOUND'; }

      rows.push({
        kind, ticker: r.ticker, name: r.name || null,
        actionDate: r[DATE_KEY[kind]] || null,
        bucket, reason,
        evidence: hits.slice(0, 3).map((h) => ({ rceptNo: h.rceptNo, rceptDt: h.rceptDt, reportNm: h.reportNm })),
      });
    }
  }

  const pct = (n, d) => (d ? Math.round((n / d) * 1000) / 10 : null);
  const tally = (subset) => {
    const c = { OBSERVED: 0, NOT_OBSERVED: 0, OUT_OF_RANGE: 0 };
    for (const x of subset) c[x.bucket]++;
    // 지정일자를 모르는 행(투자주의환기)은 "구간 밖인지" 판정 자체가 불가능하다.
    // 상한: 분모에서 제외 / 하한: 미관측으로 계산. 하나를 고르지 않고 구간으로 보고한다.
    const unknown = subset.filter((x) => x.reason === 'DATE_UNKNOWN').length;
    return {
      ...c, total: subset.length, dateUnknown: unknown,
      coveragePct: pct(c.OBSERVED, c.OBSERVED + c.NOT_OBSERVED),
      coverageLowerPct: pct(c.OBSERVED, c.OBSERVED + c.NOT_OBSERVED + unknown),
    };
  };
  const byKind = {};
  for (const kind of Object.keys(EXPECT)) byKind[kind] = tally(rows.filter((x) => x.kind === kind));
  return { overall: tally(rows), byKind, rows };
}

function buildReport(out) {
  const { meta, coverage, typeCounts, unclassifiedTop, missingCandidates, fpCandidates } = out;
  const L = [];
  L.push('# TASK-2A 골든셋 리포트');
  L.push('');
  L.push(`- 수집시각: ${meta.collectedAt}`);
  L.push(`- 조회구간: ${meta.bgnDe} ~ ${meta.endDe} (${meta.lookbackDays}일)`);
  L.push(`- classifierVersion: **${meta.classifierVersion}**`);
  L.push(`- 대상 종목: ${meta.targetCount}개 (스냅샷 ${meta.sourceCounts.snapshot} ∪ watchlist ${meta.sourceCounts.watchlist})`);
  L.push(`- 조회 공시 총건수: ${meta.totalDisclosures} (분류됨 ${meta.classifiedCount} / 미분류 ${meta.unclassifiedCount})`);
  L.push('');

  L.push('## 표1. 타입별 건수');
  L.push('');
  L.push('| 이벤트 타입 | 건수 |');
  L.push('|---|---:|');
  for (const [t, n] of Object.entries(typeCounts).sort((a, b) => b[1] - a[1])) L.push(`| ${t} | ${n} |`);
  L.push(`| (미분류) | ${meta.unclassifiedCount} |`);
  L.push('');

  L.push('## 표2. 미분류 report_nm 상위 100');
  L.push('');
  L.push('| # | report_nm | 건수 |');
  L.push('|---:|---|---:|');
  unclassifiedTop.forEach((r, i) => L.push(`| ${i + 1} | ${r.reportNm} | ${r.count} |`));
  L.push('');

  L.push('## 표3. 누락 후보 (미분류 ∧ 시장조치 어휘 포함)');
  L.push('');
  L.push('classifier가 놓쳤을 가능성이 있는 건. 라벨링해서 recall을 산출한다.');
  L.push('');
  L.push('| 종목 | 접수일 | report_nm | rcept_no |');
  L.push('|---|---|---|---|');
  for (const d of missingCandidates.slice(0, 300)) {
    L.push(`| ${d.name || d.ticker} | ${d.rceptDt} | ${d.reportNm} | ${d.rceptNo} |`);
  }
  if (missingCandidates.length === 0) L.push('| (없음) | | | |');
  L.push('');

  L.push('## 표4. 오분류 후보 (분류됨 ∧ 시장조치 어휘 ∧ 오탐 유발 어휘)');
  L.push('');
  L.push('정정·타법인·조회공시 등으로 잘못 분류됐을 가능성이 있는 건. precision 산출용.');
  L.push('');
  L.push('| 종목 | 접수일 | report_nm | classifiedAs |');
  L.push('|---|---|---|---|');
  for (const d of fpCandidates.slice(0, 300)) {
    L.push(`| ${d.name || d.ticker} | ${d.rceptDt} | ${d.reportNm} | ${d.classifiedAs.join(', ')} |`);
  }
  if (fpCandidates.length === 0) L.push('| (없음) | | | |');
  L.push('');

  L.push('## 표5. Source coverage (게이트 아님 — 관측값)');
  L.push('');
  L.push('DART `list.json`이 거래소 시장조치를 얼마나 관측하는가. 고칠 수 있는 값이 아니라 주어진 사실이다.');
  L.push('');
  L.push('| 구분 | OBSERVED | NOT_OBSERVED | OUT_OF_RANGE | (그중 날짜불명) | coverage 하한~상한 |');
  L.push('|---|---:|---:|---:|---:|---:|');
  const p = (v) => (v === null ? 'N/A' : v + '%');
  const fmt = (k, c) => `| ${k} | ${c.OBSERVED} | ${c.NOT_OBSERVED} | ${c.OUT_OF_RANGE} | ${c.dateUnknown} | ${p(c.coverageLowerPct)} ~ ${p(c.coveragePct)} |`;
  for (const [k, c] of Object.entries(coverage.byKind)) L.push(fmt(k, c));
  L.push(fmt('**전체**', coverage.overall));
  L.push('');
  L.push(`**coverage = OBSERVED / (OBSERVED + NOT_OBSERVED) = ${p(coverage.overall.coveragePct)}** (상한)`);
  L.push('');
  L.push(`**하한 = OBSERVED / (OBSERVED + NOT_OBSERVED + 날짜불명) = ${p(coverage.overall.coverageLowerPct)}** — 투자주의환기는 소스에 지정일자가 없어 구간 판정이 불가능하다.`);
  L.push('');
  const reasons = {};
  for (const r of coverage.rows) if (r.reason) reasons[r.reason] = (reasons[r.reason] || 0) + 1;
  L.push('| 비관측 사유 | 건수 |');
  L.push('|---|---:|');
  for (const [k, v] of Object.entries(reasons).sort((a, b) => b[1] - a[1])) L.push(`| ${k} | ${v} |`);
  L.push('');
  L.push('> 80% 미만이면 `lib/eventBuilders/krx.js` + `sourcePriority.v1.json` 추가(P3′). Event→State 구조는 그대로다.');
  return L.join('\n') + '\n';
}

/* ────────────────── main ────────────────── */

async function main() {
  if (!KEY) { console.error('❌ DART_API_KEY 환경변수가 없습니다.'); process.exit(1); }
  if (!fs.existsSync(SNAPSHOT_PATH)) {
    console.error(`❌ ${SNAPSHOT_PATH} 없음. TASK-2B(collect-market-actions)를 먼저 실행하세요.`);
    process.exit(1);
  }
  const snapshot = JSON.parse(fs.readFileSync(SNAPSHOT_PATH, 'utf8'));
  const watchlist = JSON.parse(fs.readFileSync(WATCHLIST_PATH, 'utf8'));
  const targets = buildTargets(snapshot, watchlist);

  const bgnDe = kstYmd(LOOKBACK_DAYS);
  const endDe = kstYmd(0);
  console.log(`대상 ${targets.length}종목 / 구간 ${bgnDe}~${endDe}`);

  const corpMap = await loadCorpMap();
  console.log(`corpCode 매핑 ${Object.keys(corpMap).length}건 로드`);

  const disclosures = [];
  const unclassifiedFreq = new Map();
  const missingCandidates = [];
  const failed = [];
  const unresolved = [];
  let total = 0, classifiedCount = 0, unclassifiedCount = 0;

  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    const corp = corpMap[t.ticker];
    if (!corp) { unresolved.push({ ticker: t.ticker, name: t.name }); continue; }
    t.corpCode = corp;
    try {
      const rows = await fetchList(corp, bgnDe, endDe);
      for (const r of rows) {
        total++;
        const reportNm = String(r.report_nm || '').trim();
        const types = classify(reportNm);
        const rec = {
          ticker: t.ticker, name: t.name, rceptNo: r.rcept_no, rceptDt: r.rcept_dt,
          reportNm, flr: String(r.flr_nm || '').trim(), classifiedAs: types,
        };
        if (types.length > 0) { classifiedCount++; disclosures.push(rec); }
        else {
          unclassifiedCount++;
          unclassifiedFreq.set(reportNm, (unclassifiedFreq.get(reportNm) || 0) + 1);
          if (MISSING_RE.test(reportNm.replace(/\s/g, ''))) missingCandidates.push(rec);
        }
      }
    } catch (e) {
      failed.push({ ticker: t.ticker, reason: e.message });
      if (/020/.test(e.message)) { console.error('DART 한도 초과 — 중단'); break; }
    }
    if ((i + 1) % 25 === 0) console.log(`  ...${i + 1}/${targets.length} (누적 공시 ${total})`);
    await sleep(DART_DELAY_MS);
  }

  const byTicker = new Map();
  for (const d of disclosures) {
    if (!byTicker.has(d.ticker)) byTicker.set(d.ticker, []);
    byTicker.get(d.ticker).push(d);
  }
  const coverage = buildCoverage(snapshot, byTicker, corpMap, bgnDe);

  const typeCounts = {};
  for (const d of disclosures) for (const t of d.classifiedAs) typeCounts[t] = (typeCounts[t] || 0) + 1;
  const unclassifiedTop = [...unclassifiedFreq.entries()]
    .sort((a, b) => b[1] - a[1]).slice(0, 100).map(([reportNm, count]) => ({ reportNm, count }));
  const fpCandidates = disclosures.filter((d) => {
    const nm = d.reportNm.replace(/\s/g, '');
    return MISSING_RE.test(nm) && FP_RE.test(nm);
  });

  const out = {
    meta: {
      collectedAt: kstNow(), classifierVersion: CLASSIFIER_VERSION,
      lookbackDays: LOOKBACK_DAYS, bgnDe, endDe,
      targetCount: targets.length,
      sourceCounts: {
        snapshot: new Set(Object.keys(EXPECT).flatMap((k) => (snapshot[k] || []).map((r) => r.ticker))).size,
        watchlist: (watchlist.tickers || []).filter((t) => (t.market || 'KR') === 'KR').length,
      },
      totalDisclosures: total, classifiedCount, unclassifiedCount,
      note: '미분류 공시는 원문을 저장하지 않고 reportNm 빈도만 집계한다(파일 크기 방침).',
    },
    targets, coverage, typeCounts, unclassifiedTop,
    disclosures, missingCandidates, fpCandidates,
    _diagnostics: { failed, unresolved },
  };

  fs.mkdirSync(GOLDEN_DIR, { recursive: true });
  fs.writeFileSync(OUT_JSON, JSON.stringify(out, null, 2), 'utf8');
  const md = buildReport(out);
  fs.writeFileSync(OUT_MD, md, 'utf8');
  console.log(`saved ${OUT_JSON} (${fs.statSync(OUT_JSON).size} bytes)`);
  console.log(`saved ${OUT_MD} (${fs.statSync(OUT_MD).size} bytes)`);
  console.log(`\n=== Source coverage: ${out.coverage.overall.coverageLowerPct}% ~ ${out.coverage.overall.coveragePct}% ===\n`);

  process.exit(runTests(out, md, snapshot) ? 0 : 1);
}

/* ────────────────── 인수 조건 ────────────────── */

function runTests(out, md, snapshot) {
  let ok = true;
  const chk = (c, m) => { console.log(`${c ? '[PASS]' : '[FAIL]'} ${m}`); if (!c) ok = false; };

  chk(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/.test(out.meta.collectedAt), 'collectedAt KST 형식');
  chk(out.meta.classifierVersion === CLASSIFIER_VERSION, `classifierVersion 기록됨 (${out.meta.classifierVersion})`);

  const tks = out.targets.map((t) => t.ticker);
  chk(tks.every((t) => /^\d{6}$/.test(t)), 'target ticker 6자리 숫자');
  chk(new Set(tks).size === tks.length, `target ticker 중복 없음 (${tks.length}종목)`);

  const resolved = out.targets.filter((t) => t.corpCode).length;
  const rate = tks.length ? resolved / tks.length : 0;
  chk(rate >= 0.9, `corp_code 해석률 ${(rate * 100).toFixed(1)}% ≥ 90% (${resolved}/${tks.length})`);

  chk(out.meta.totalDisclosures > 0, `공시 수집 건수 > 0 (${out.meta.totalDisclosures}건)`);
  chk(out.disclosures.every((d) => Array.isArray(d.classifiedAs) && d.classifiedAs.length > 0),
      'classifiedAs 배열 형식 (DC-1.1 계약)');

  // ★ 유일한 치명 실패 모드: coverage 분모가 조용히 누락되는 것.
  const snapTotal = Object.keys(EXPECT).reduce((s, k) => s + (snapshot[k] || []).length, 0);
  const covTotal = out.coverage.rows.length;
  chk(covTotal === snapTotal, `coverage 행수 = 스냅샷 전건 (${covTotal}/${snapTotal})`);
  const bucketSum = out.coverage.overall.OBSERVED + out.coverage.overall.NOT_OBSERVED + out.coverage.overall.OUT_OF_RANGE;
  chk(bucketSum === snapTotal, `3버킷 합 = 스냅샷 전건 (${bucketSum}/${snapTotal})`);

  // OBSERVED는 반드시 근거(rcept_no)를 동반해야 한다 — 관대한 판정으로 coverage가 부풀려지는 것 방지
  const noEvidence = out.coverage.rows.filter((r) => r.bucket === 'OBSERVED' && (!r.evidence || r.evidence.length === 0));
  chk(noEvidence.length === 0, `OBSERVED 전건 근거 rcept_no 보유 (위반 ${noEvidence.length}건)`);
  const wrongType = out.coverage.rows.filter((r) =>
    r.bucket === 'OBSERVED' && !r.evidence.some((e) => classify(e.reportNm).some((t) => EXPECT[r.kind].includes(t))));
  chk(wrongType.length === 0, `OBSERVED 근거가 기대 타입과 일치 (위반 ${wrongType.length}건)`);

  // 인코딩 정합성 — DART는 UTF-8이라 위험은 낮지만 회귀 방지로 남긴다
  const garbled = out.disclosures.filter((d) => !TEXT_CHARSET.test(d.reportNm));
  chk(garbled.length === 0, `report_nm 인코딩 정합성 (위반 ${garbled.length}건${garbled.length ? ' 예: ' + garbled[0].reportNm : ''})`);

  for (const t of ['## 표1', '## 표2', '## 표3', '## 표4', '## 표5']) {
    chk(md.includes(t), `report.md ${t} 존재`);
  }
  chk(/coverage = OBSERVED/.test(md), 'report.md coverage 산식 명시');
  return ok;
}

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

module.exports = { buildTargets, buildCoverage, buildReport, runTests, dateRanges, EXPECT, MISSING_RE, FP_RE };
