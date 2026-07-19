#!/usr/bin/env node
/**
 * DART OpenAPI → config/fundamentals.json 자동 수집 (한국 종목 전용)
 *
 * 채우는 필드: roe, roeHistory5y, debtRatio, currentRatio,
 *              operatingMarginTrend, revenueGrowthYoY, epsGrowthRate,
 *              buybackOrDividendHistory, sicCode, sectorType, sectorResolved
 * 채우지 않는 필드: perRelative (주가 필요 - DART 미제공, 기존 값 보존)
 * 미국 종목(market:'US')은 건드리지 않습니다.
 *
 * 키는 반드시 환경변수로만 주입합니다 (저장소가 공개이므로 하드코딩 금지):
 *   DART_API_KEY=xxxx node scripts/fetch-fundamentals-kr.js
 *
 * 외부 의존성 없음 (Node 18+ 내장 fetch/zlib 사용).
 *
 * ── v1 → v2 변경점 ──────────────────────────────────────────────
 * (1) 업종 표준분류 수집
 *     기업개황 API(company.json)에서 induty_code(한국표준산업분류)를 받아
 *     lib/sectorResolver 로 sectorType(financial/holding/utility/construction/
 *     shipping/airline/bio/telecom/reit/general)을 확정합니다.
 *     종목당 요청 1회 추가 — 분기 1회 실행이라 DART 한도(일 20,000건)에 여유가 큽니다.
 *
 * (2) v1의 업종 판별 한계
 *     v1은 "유동자산·유동부채가 둘 다 없으면 금융업"이라는 재무제표 형태 휴리스틱만
 *     썼습니다. 금융업은 이걸로 잡히지만 건설·해운·항공·바이오·유틸리티는 전혀
 *     구분되지 않아 전부 'general'(제조업 기준)로 채점됐습니다.
 *     v2는 표준산업분류를 1차 근거로 쓰고, 이 휴리스틱은 교차검증용으로 남깁니다.
 *     둘이 어긋나면 경고를 찍되 '금융 재무제표 형태'를 우선합니다
 *     (부채비율 오채점이 가장 큰 사고이므로 안전한 쪽으로).
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { resolveSector } = require('../lib/sectorResolver');

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

/** 부채비율 원값을 debtRatioRaw에만 두고 debtRatio는 null로 비우는 업종.
 *  criteria.json 의 sectorOverrides[*].fundamental.metrics.debtRatio.useRawDebtRatio 와 짝을 이룹니다.
 *  여기 없는 업종은 debtRatio를 그대로 채워 일반 경로로 채점됩니다. */
const RAW_DEBT_SECTORS = new Set(['financial']);

/** DART 호출 간 간격. 종목당 4회 호출(주요계정×2, 배당, 기업개황).
 *  DART는 공식 API라 네이버보다 관대하지만, 100종목×4회 = 400회를 몰아치지 않도록 여유를 둡니다.
 *  100종목 기준 약 4~5분. 분기 1회 실행이라 속도는 전혀 중요하지 않습니다. */
const DART_DELAY_MS = Number(process.env.DART_DELAY_MS || 250);

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

/** [v2] 기업개황: 표준산업분류코드(induty_code) 확보 */
async function fetchCompanyInfo(corpCode) {
  const j = await getJson('company.json', { corp_code: corpCode });
  return {
    sicCode: (j.induty_code || '').trim() || null,
    corpName: (j.corp_name || '').trim() || null,
  };
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
      // 일반기업 '매출액' / 금융업 '영업수익' / 일부 '수익(매출액)'
      revenue: find(n => n === '매출액') || find(n => n.includes('영업수익'))
            || find(n => n.includes('매출')) || find(n => n.startsWith('수익')),
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

/**
 * @param sector {{sectorType, sectorResolved, sicCode}} [v2] 업종 해석 결과
 */
function computeMetrics(yearly, div, latestYear, sector) {
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

  const debtRaw = (cur.liabilities != null && cur.equity)
    ? round(cur.liabilities / cur.equity * 100, 1) : null;

  // criteria.json 의 operatingMarginTrend 단위는 '방향성(-1~1)'
  // → 영업이익률 변화(%p)를 ±5%p = ±1 로 정규화
  let omTrend = null;
  if (mCur != null && mPrev != null) {
    const pp = mCur - mPrev;
    omTrend = round(Math.max(-1, Math.min(1, pp / 5)), 2);
  }

  // 전기 EPS가 0 이하(적자)면 성장률이 무의미 → 결측 처리
  const epsGrowth = (epsCur != null && epsPrev != null && epsPrev > 0)
    ? round((epsCur / epsPrev - 1) * 100, 1)
    : ((cur.netIncome != null && prev && prev.netIncome > 0)
      ? round((cur.netIncome / prev.netIncome - 1) * 100, 1) : null);

  // 금융업은 예금·보험부채가 부채로 잡혀 부채비율이 구조적으로 1000%대 →
  // 일반 기준(poor 200%)으로 채점하면 최하점·오경고가 나므로 debtRatio는 비우고
  // 원값은 debtRatioRaw에 보존한다. 엔진이 업종 임계값으로 원값을 채점한다.
  const useRaw = RAW_DEBT_SECTORS.has(sector.sectorType);

  return {
    roe: round(roeOf(cur), 1),
    roeHistory5y,
    debtRatio: useRaw ? null : debtRaw,
    debtRatioRaw: debtRaw,
    currentRatio: (cur.currentAssets != null && cur.currentLiab)
      ? round(cur.currentAssets / cur.currentLiab * 100, 1) : null,
    operatingMarginTrend: omTrend,
    operatingMarginTrendPP: (mCur != null && mPrev != null) ? round(mCur - mPrev, 2) : null,
    revenueGrowthYoY: (cur.revenue != null && prev && prev.revenue) ? round((cur.revenue / prev.revenue - 1) * 100, 1) : null,
    epsGrowthRate: epsGrowth,
    buybackOrDividendHistory: div.dividend.length ? div.dividend.some(v => v != null && v > 0) : null,
    // [v2] 업종 정보 — collect.js가 그대로 종목 데이터에 실어 보낸다
    sicCode: sector.sicCode,
    sectorType: sector.sectorType,
    sectorResolved: sector.sectorResolved,
  };
}

/**
 * [v2] 표준산업분류 + 재무제표 형태를 교차검증해 업종을 확정.
 * 재무제표에 유동자산·유동부채가 둘 다 없으면 금융업 양식이다(v1의 휴리스틱).
 */
function decideSector(ticker, name, sicCode, cur, logs) {
  const looksFinancial = cur && cur.currentAssets == null && cur.currentLiab == null;

  let r;
  try {
    r = resolveSector({ ticker, name, sicCode });
  } catch (e) {
    logs.push(`${ticker} 업종 해석 실패(${e.message}) → 휴리스틱 사용`);
    r = { sectorType: looksFinancial ? 'financial' : 'general', resolved: false, warnings: [] };
    return { sectorType: r.sectorType, sectorResolved: r.resolved, sicCode };
  }
  for (const w of r.warnings) logs.push(`${ticker} ${w.message}`);

  let sectorType = r.sectorType;
  let sectorResolved = r.resolved;

  // 교차검증: 재무제표는 금융 양식인데 분류가 다르면 금융을 우선한다.
  // 부채비율 오채점(정상 금융사가 최하점 + 오경고)이 가장 큰 사고이기 때문.
  if (looksFinancial && sectorType !== 'financial') {
    logs.push(
      `${ticker} ${name}: 표준산업분류는 '${sectorType}'(SIC ${sicCode || '없음'})인데 ` +
      `재무제표가 금융업 양식(유동자산·유동부채 없음)입니다. 안전하게 financial로 채점합니다. ` +
      `실제로 금융사가 아니라면 config/sector-map.json 의 byTicker에 고정하세요.`
    );
    sectorType = 'financial';
    sectorResolved = true;
  }
  // 반대 방향은 경고만 (지주회사가 금융업으로 분류되는 경우 등)
  if (!looksFinancial && sectorType === 'financial') {
    logs.push(
      `${ticker} ${name}: 'financial'로 분류됐지만 재무제표에 유동자산·유동부채가 있습니다. ` +
      `일반 기업일 수 있으니 sector-map.json 확인을 권합니다.`
    );
  }

  return { sectorType, sectorResolved, sicCode };
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
  const sectorLogs = [];
  const sectorCount = {};

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
      await sleep(DART_DELAY_MS);
      try {
        Object.assign(yearly, toYearly(await fetchAccounts(corp, usedYear - 3), usedYear - 3), yearly);
      } catch (e) { /* 과거분 없으면 무시 */ }
      await sleep(DART_DELAY_MS);

      let div = { eps: {}, dividend: [] };
      try { div = await fetchDividend(corp, usedYear); } catch (e) { /* 배당 정보 없으면 무시 */ }
      await sleep(DART_DELAY_MS);

      // [v2] 표준산업분류 조회 (실패해도 휴리스틱으로 진행)
      let sicCode = null;
      try {
        const info = await fetchCompanyInfo(corp);
        sicCode = info.sicCode;
      } catch (e) {
        sectorLogs.push(`${t.code} ${t.name}: 기업개황 조회 실패(${e.message}) → 업종코드 없이 진행`);
      }
      await sleep(DART_DELAY_MS);

      const sector = decideSector(t.code, t.name, sicCode, yearly[usedYear], sectorLogs);

      const m = computeMetrics(yearly, div, usedYear, sector);
      if (!m) { failed.push(`${t.code} ${t.name}: 재무 데이터 없음`); continue; }

      sectorCount[m.sectorType] = (sectorCount[m.sectorType] || 0) + 1;

      const prevEntry = fund.byTicker[t.code] || {};
      // perRelative 등 수동 입력값은 보존, DART 산출값만 덮어쓰기
      fund.byTicker[t.code] = { ...prevEntry, ...m, _source: `DART ${usedYear} 사업보고서` };
      delete fund.byTicker[t.code]._note;

      const scored = ['roe', 'roeHistory5y', 'debtRatio', 'currentRatio',
        'operatingMarginTrend', 'revenueGrowthYoY', 'epsGrowthRate', 'buybackOrDividendHistory'];
      const cov = scored.filter(k => m[k] != null).length;
      const tag = m.sectorType === 'general' ? '' : ` [${m.sectorType}]`;
      filled.push(`${t.code} ${t.name}${tag}: ROE ${m.roe}% · 부채 ${m.debtRatioRaw}% · 매출성장 ${m.revenueGrowthYoY}% · 이익률추세 ${m.operatingMarginTrend} (${cov}/8) · SIC ${m.sicCode || '없음'}`);
    } catch (e) {
      failed.push(`${t.code} ${t.name}: ${e.message}`);
    }
    await sleep(DART_DELAY_MS); // 종목 사이 간격
  }

  fund.updatedAt = new Date().toISOString().slice(0, 10);
  fund.description = (fund.description || '').replace(/\s*\[자동\].*$/, '') +
    ` [자동] 한국 종목은 scripts/fetch-fundamentals-kr.js 가 DART 사업보고서에서 분기 1회 자동 수집합니다(ROE=당기순이익÷자본총계, 기말 자본 기준). 업종(sectorType)은 기업개황 API의 표준산업분류코드를 config/sector-map.json 으로 변환한 값입니다. perRelative와 미국 종목은 수동 입력 유지.`;

  fs.writeFileSync(FUND_PATH, JSON.stringify(fund, null, 2) + '\n', 'utf8');

  console.log(`\n✅ 성공 ${filled.length}건`);
  filled.forEach(s => console.log('  ' + s));

  console.log(`\n📊 업종 분포: ${JSON.stringify(sectorCount)}`);
  if (sectorLogs.length) {
    console.log(`\n🔎 업종 관련 확인사항 ${sectorLogs.length}건`);
    sectorLogs.forEach(s => console.log('  ' + s));
  }

  if (failed.length) {
    console.log(`\n⚠ 실패/건너뜀 ${failed.length}건`);
    failed.forEach(s => console.log('  ' + s));
  }
  console.log(`\n${FUND_PATH} 갱신 완료`);
}

main().catch(e => { console.error('❌', e); process.exit(1); });
