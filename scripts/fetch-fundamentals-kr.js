#!/usr/bin/env node
/**
 * DART OpenAPI → config/fundamentals.json 자동 수집 (한국 종목 전용)
 *
 * 채우는 필드: roe, roeHistory5y, debtRatio, currentRatio,
 *              operatingMarginTrend, revenueGrowthYoY, epsGrowthRate,
 *              buybackOrDividendHistory
 * 채우지 않는 필드: perRelative (주가 필요 - DART 미제공, 기존 값 보존)
 * 미국 종목(market:'US')은 건드리지 않습니다.
 *
 * 키는 반드시 환경변수로만 주입합니다 (저장소가 공개이므로 하드코딩 금지):
 *   DART_API_KEY=xxxx node scripts/fetch-fundamentals-kr.js
 *
 * 외부 의존성 없음 (Node 18+ 내장 fetch/zlib 사용).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const KEY = process.env.DART_API_KEY;
if (!KEY) {
  console.error('❌ DART_API_KEY 환경변수가 없습니다. GitHub Secrets에 등록하세요.');
  process.exit(1);
}

const ROOT = path.resolve(__dirname, '..');
const WATCHLIST_PATH = path.join(ROOT, 'config', 'watchlist.json');
const FUND_PATH = path.join(ROOT, 'config', 'fundamentals.json');
const BASE = 'https://opendart.fss.or.kr/api';
const REPRT_ANNUAL = '11011'; // 사업보고서(연간)

const sleep = ms => new Promise(r => setTimeout(r, ms));
const round = (v, d = 1) => (v == null || !Number.isFinite(v)) ? null : Math.round(v * 10 ** d) / 10 ** d;

/** "1,234" | "-1,234" | "-" → number|null */
function num(s) {
  if (s == null) return null;
  const t = String(s).replace(/,/g, '').trim();
  if (!t || t === '-') return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

async function getJson(endpoint, params) {
  const url = `${BASE}/${endpoint}?` + new URLSearchParams({ crtfc_key: KEY, ...params });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${endpoint} HTTP ${res.status}`);
  const j = await res.json();
  if (j.status && j.status !== '000') {
    const e = new Error(`${endpoint} [${j.status}] ${j.message}`);
    e.dartStatus = j.status; // 013 = 조회된 데이터 없음
    throw e;
  }
  return j;
}

/** DART corpCode.xml 은 ZIP 이라 직접 해제 (의존성 없이) */
function unzipFirstEntry(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 70000; i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('ZIP EOCD를 찾지 못했습니다');
  const cdOff = buf.readUInt32LE(eocd + 16);
  if (buf.readUInt32LE(cdOff) !== 0x02014b50) throw new Error('ZIP 중앙 디렉터리 손상');
  const method = buf.readUInt16LE(cdOff + 10);
  const compSize = buf.readUInt32LE(cdOff + 20);
  const localOff = buf.readUInt32LE(cdOff + 42);
  const lNameLen = buf.readUInt16LE(localOff + 26);
  const lExtraLen = buf.readUInt16LE(localOff + 28);
  const start = localOff + 30 + lNameLen + lExtraLen;
  const data = buf.subarray(start, start + compSize);
  return (method === 0 ? data : zlib.inflateRawSync(data)).toString('utf8');
}

/** 종목코드 → 고유번호(corp_code) 매핑 */
async function loadCorpCodeMap() {
  const res = await fetch(`${BASE}/corpCode.xml?crtfc_key=${KEY}`);
  if (!res.ok) throw new Error(`corpCode HTTP ${res.status}`);
  const xml = unzipFirstEntry(Buffer.from(await res.arrayBuffer()));
  const map = {};
  const re = /<list>([\s\S]*?)<\/list>/g;
  let m;
  while ((m = re.exec(xml))) {
    const seg = m[1];
    const cc = (seg.match(/<corp_code>(.*?)<\/corp_code>/) || [])[1];
    const sc = (seg.match(/<stock_code>(.*?)<\/stock_code>/) || [])[1];
    if (cc && sc && sc.trim()) map[sc.trim()] = cc.trim();
  }
  return map;
}

/** 주요계정(fnlttSinglAcnt): 한 번 호출로 당기·전기·전전기 3개 연도 확보 */
async function fetchAccounts(corpCode, year) {
  const j = await getJson('fnlttSinglAcnt.json', {
    corp_code: corpCode, bsns_year: String(year), reprt_code: REPRT_ANNUAL,
  });
  const list = j.list || [];
  const build = fsDiv => {
    const rows = list.filter(r => r.fs_div === fsDiv);
    if (!rows.length) return null;
    const find = pred => rows.find(r => pred(String(r.account_nm || '').replace(/\s/g, ''))) || null;
    return {
      currentAssets: find(n => n === '유동자산'),
      currentLiab: find(n => n === '유동부채'),
      liabilities: find(n => n === '부채총계'),
      equity: find(n => n === '자본총계'),
      revenue: find(n => n.includes('매출')),         // '매출액' | '수익(매출액)'
      opProfit: find(n => n.includes('영업이익')),
      netIncome: find(n => n.includes('당기순이익')),
    };
  };
  return build('CFS') || build('OFS'); // 연결 우선, 없으면 별도
}

/** 계정 묶음 → {연도: {지표}} (당기/전기/전전기) */
function toYearly(acc, year) {
  if (!acc) return {};
  const cols = [['thstrm_amount', year], ['frmtrm_amount', year - 1], ['bfefrmtrm_amount', year - 2]];
  const out = {};
  for (const [field, y] of cols) {
    const g = k => (acc[k] ? num(acc[k][field]) : null);
    const row = {
      currentAssets: g('currentAssets'), currentLiab: g('currentLiab'),
      liabilities: g('liabilities'), equity: g('equity'),
      revenue: g('revenue'), opProfit: g('opProfit'), netIncome: g('netIncome'),
    };
    if (Object.values(row).some(v => v != null)) out[y] = row;
  }
  return out;
}

/** 배당에 관한 사항: 주당순이익(EPS) 3년치 + 현금배당 여부 */
async function fetchDividend(corpCode, year) {
  const j = await getJson('alotMatter.json', {
    corp_code: corpCode, bsns_year: String(year), reprt_code: REPRT_ANNUAL,
  });
  const list = j.list || [];
  const bySe = pred => list.find(r => pred(String(r.se || '').replace(/\s/g, ''))) || null;
  // EPS: 연결 우선, 없으면 별도
  const epsRow = bySe(n => n.includes('(연결)주당순이익')) || bySe(n => n.includes('주당순이익'));
  const divRow = list.find(r => String(r.se || '').replace(/\s/g, '').includes('주당현금배당금')
    && String(r.stock_knd || '').includes('보통주')) || bySe(n => n.includes('주당현금배당금'));
  return {
    eps: epsRow ? { [year]: num(epsRow.thstrm), [year - 1]: num(epsRow.frmtrm), [year - 2]: num(epsRow.lwfr) } : {},
    dividend: divRow ? [num(divRow.thstrm), num(divRow.frmtrm), num(divRow.lwfr)] : [],
  };
}

const roeOf = y => (y && y.netIncome != null && y.equity) ? (y.netIncome / y.equity) * 100 : null;
const opMarginOf = y => (y && y.opProfit != null && y.revenue) ? (y.opProfit / y.revenue) * 100 : null;

function computeMetrics(yearly, div, latestYear) {
  const cur = yearly[latestYear];
  const prev = yearly[latestYear - 1];
  if (!cur) return null;

  // 5년 ROE (오래된 → 최신 순, 마지막이 현재 roe)
  const span = [];
  for (let y = latestYear - 4; y <= latestYear; y++) span.push(roeOf(yearly[y]));
  let roeHistory5y = null;
  if (span.every(v => v != null)) {
    roeHistory5y = span.map(v => round(v, 1));
  } else {
    // 최신부터 연속으로 존재하는 구간만 사용 (3개 이상일 때)
    const tail = [];
    for (let y = latestYear; y >= latestYear - 4; y--) {
      const v = roeOf(yearly[y]);
      if (v == null) break;
      tail.unshift(round(v, 1));
    }
    if (tail.length >= 3) roeHistory5y = tail;
  }

  const mCur = opMarginOf(cur), mPrev = opMarginOf(prev);
  const epsCur = div.eps[latestYear], epsPrev = div.eps[latestYear - 1];

  return {
    roe: round(roeOf(cur), 1),
    roeHistory5y,
    debtRatio: (cur.liabilities != null && cur.equity) ? round(cur.liabilities / cur.equity * 100, 1) : null,
    currentRatio: (cur.currentAssets != null && cur.currentLiab) ? round(cur.currentAssets / cur.currentLiab * 100, 1) : null,
    operatingMarginTrend: (mCur != null && mPrev != null) ? round(mCur - mPrev, 2) : null,
    revenueGrowthYoY: (cur.revenue != null && prev && prev.revenue) ? round((cur.revenue / prev.revenue - 1) * 100, 1) : null,
    epsGrowthRate: (epsCur != null && epsPrev) ? round((epsCur / epsPrev - 1) * 100, 1)
      : ((cur.netIncome != null && prev && prev.netIncome > 0) ? round((cur.netIncome / prev.netIncome - 1) * 100, 1) : null),
    buybackOrDividendHistory: div.dividend.length ? div.dividend.some(v => v != null && v > 0) : null,
  };
}

/** 최신 사업보고서 연도 추정 (연간보고서는 이듬해 3월경 공시) */
function latestAnnualYear(now = new Date()) {
  return now.getMonth() >= 3 ? now.getFullYear() - 1 : now.getFullYear() - 2;
}

async function main() {
  const watchlist = JSON.parse(fs.readFileSync(WATCHLIST_PATH, 'utf8'));
  const fund = JSON.parse(fs.readFileSync(FUND_PATH, 'utf8'));
  const krTickers = (watchlist.tickers || []).filter(t => (t.market || 'KR') === 'KR');
  console.log(`대상 한국 종목 ${krTickers.length}개`);

  console.log('corpCode 매핑 다운로드 중...');
  const corpMap = await loadCorpCodeMap();
  console.log(`corpCode 매핑 ${Object.keys(corpMap).length}건 로드`);

  let baseYear = latestAnnualYear();
  const filled = [];
  const failed = [];

  for (const t of krTickers) {
    const corp = corpMap[t.code];
    if (!corp) { failed.push(`${t.code} ${t.name}: corp_code 없음`); continue; }
    try {
      // 최신 보고서(3년) + 3년 전 보고서(추가 3년) = 최대 6년
      let yearly = {};
      let usedYear = baseYear;
      try {
        yearly = toYearly(await fetchAccounts(corp, baseYear), baseYear);
      } catch (e) {
        if (e.dartStatus === '013') { // 아직 미공시 → 한 해 뒤로
          usedYear = baseYear - 1;
          yearly = toYearly(await fetchAccounts(corp, usedYear), usedYear);
        } else throw e;
      }
      await sleep(120);
      try {
        Object.assign(yearly, toYearly(await fetchAccounts(corp, usedYear - 3), usedYear - 3), yearly);
      } catch (e) { /* 과거분 없으면 무시 */ }
      await sleep(120);

      let div = { eps: {}, dividend: [] };
      try { div = await fetchDividend(corp, usedYear); } catch (e) { /* 배당 정보 없으면 무시 */ }
      await sleep(120);

      const m = computeMetrics(yearly, div, usedYear);
      if (!m) { failed.push(`${t.code} ${t.name}: 재무 데이터 없음`); continue; }

      const prevEntry = fund.byTicker[t.code] || {};
      // perRelative 등 수동 입력값은 보존, DART 산출값만 덮어쓰기
      fund.byTicker[t.code] = { ...prevEntry, ...m, _source: `DART ${usedYear} 사업보고서` };
      delete fund.byTicker[t.code]._note;

      const cov = Object.values(m).filter(v => v != null).length;
      filled.push(`${t.code} ${t.name}: ROE ${m.roe}% · 부채 ${m.debtRatio}% · 유동 ${m.currentRatio}% · 매출성장 ${m.revenueGrowthYoY}% (${cov}/8)`);
    } catch (e) {
      failed.push(`${t.code} ${t.name}: ${e.message}`);
    }
  }

  fund.updatedAt = new Date().toISOString().slice(0, 10);
  fund.description = (fund.description || '').replace(/\s*\[자동\].*$/, '') +
    ` [자동] 한국 종목은 scripts/fetch-fundamentals-kr.js 가 DART 사업보고서에서 분기 1회 자동 수집합니다(ROE=당기순이익÷자본총계, 기말 자본 기준). perRelative와 미국 종목은 수동 입력 유지.`;

  fs.writeFileSync(FUND_PATH, JSON.stringify(fund, null, 2) + '\n', 'utf8');

  console.log(`\n✅ 성공 ${filled.length}건`);
  filled.forEach(s => console.log('  ' + s));
  if (failed.length) {
    console.log(`\n⚠ 실패/건너뜀 ${failed.length}건`);
    failed.forEach(s => console.log('  ' + s));
  }
  console.log(`\n${FUND_PATH} 갱신 완료`);
}

main().catch(e => { console.error('❌', e); process.exit(1); });
