#!/usr/bin/env node
/**
 * DART OpenAPI → 관심종목 공시 자동 수집 + 텔레그램 알림 (한국 종목 전용)
 *
 * watchlist.json 의 한국 종목 corp_code 로 최근 N일 공시(list.json)를 조회하고,
 * 투자에 영향이 큰 유형(유상증자·최대주주변경·자기주식·지분5%·실적잠정 등)만 걸러
 *   - docs/data/disclosures.json  (대시보드 표시용)
 *   - 텔레그램 알림               (신규 건만)
 * 로 내보냅니다. 이전 실행분과 rcept_no 로 비교해 새 공시만 알립니다.
 *
 * 키는 환경변수로만 주입 (저장소 공개 → 하드코딩 금지):
 *   DART_API_KEY=xxxx TELEGRAM_BOT_TOKEN=xxxx TELEGRAM_CHAT_ID=xxxx \
 *     node scripts/fetch-disclosures-kr.js
 *
 * 외부 의존성 없음 (Node 18+ 내장 fetch/zlib).
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
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TG_CHAT = process.env.TELEGRAM_CHAT_ID || '';

const ROOT = path.resolve(__dirname, '..');
const WATCHLIST_PATH = path.join(ROOT, 'config', 'watchlist.json');
const OUT_PATH = path.join(ROOT, 'docs', 'data', 'disclosures.json');
const BASE = 'https://opendart.fss.or.kr/api';

const LOOKBACK_DAYS = Number(process.env.DISCLOSURE_LOOKBACK_DAYS || 3); // 주말·휴일 공백 흡수
const KEEP_DAYS = Number(process.env.DISCLOSURE_KEEP_DAYS || 30);        // 파일에 보관할 기간

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// KST 기준 YYYYMMDD (서버가 UTC여도 한국 날짜로 조회)
function kstYmd(offsetDays = 0) {
  const d = new Date(Date.now() + 9 * 3600 * 1000 - offsetDays * 86400 * 1000);
  return d.toISOString().slice(0, 10).replace(/-/g, '');
}

// 투자 영향이 큰 공시 유형만 통과 (report_nm 키워드 → 한글 라벨·중요도)
// level: 'high'(빨강) | 'info'(파랑, 대체로 호재/중립)
const CATEGORIES = [
  { re: /유상증자/, label: '유상증자', level: 'high' },
  { re: /무상증자/, label: '무상증자', level: 'info' },
  { re: /전환사채|신주인수권부사채|교환사채/, label: '메자닌(CB/BW)', level: 'high' },
  { re: /자기주식.*취득|자사주.*취득|자기주식취득/, label: '자사주 취득', level: 'info' },
  { re: /자기주식.*처분|자기주식처분/, label: '자사주 처분', level: 'high' },
  { re: /최대주주.*변경|경영권/, label: '최대주주 변경', level: 'high' },
  { re: /주식등의대량보유|대량보유상황보고/, label: '지분 5% 변동', level: 'info' },
  { re: /임원.*주요주주.*소유|특정증권등소유상황/, label: '임원·주요주주 지분', level: 'info' },
  { re: /영업\s*\(?잠정\)?|잠정실적|매출액또는손익구조/, label: '실적(잠정)', level: 'info' },
  { re: /현금.?현물배당|배당/, label: '배당', level: 'info' },
  { re: /감자/, label: '감자', level: 'high' },
  { re: /횡령|배임/, label: '횡령·배임', level: 'high' },
  { re: /상장폐지|관리종목|거래정지|투자주의환기/, label: '상장폐지·관리', level: 'high' },
  { re: /불성실공시/, label: '불성실공시', level: 'high' },
];
function classify(reportNm) {
  const nm = String(reportNm || '').replace(/\s/g, '');
  for (const c of CATEGORIES) if (c.re.test(nm)) return c;
  return null; // 관심 유형 아님 → 제외
}

/** DART corpCode.xml(ZIP) 직접 해제 (의존성 없이) */
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

/** 한 종목의 최근 공시 목록 (list.json, 필요시 페이지네이션) */
async function fetchDisclosures(corp, bgnDe, endDe) {
  const items = [];
  for (let page = 1; page <= 5; page++) {
    const url = `${BASE}/list.json?` + new URLSearchParams({
      crtfc_key: KEY, corp_code: corp, bgn_de: bgnDe, end_de: endDe,
      page_no: String(page), page_count: '100',
    });
    const res = await fetch(url);
    if (!res.ok) throw new Error(`list HTTP ${res.status}`);
    const j = await res.json();
    if (j.status === '013') break;          // 조회된 데이터 없음
    if (j.status && j.status !== '000') throw new Error(`list [${j.status}] ${j.message}`);
    for (const r of j.list || []) items.push(r);
    if (page >= Number(j.total_page || 1)) break;
    await sleep(120);
  }
  return items;
}

function loadPrev() {
  try { return JSON.parse(fs.readFileSync(OUT_PATH, 'utf8')); }
  catch { return { items: [] }; }
}

async function tgNotify(text) {
  if (!TG_TOKEN || !TG_CHAT) return;
  try {
    await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TG_CHAT, text, disable_web_page_preview: true }),
    });
  } catch (e) { console.warn('텔레그램 알림 실패:', e.message); }
}

async function main() {
  const watchlist = JSON.parse(fs.readFileSync(WATCHLIST_PATH, 'utf8'));
  const krTickers = (watchlist.tickers || []).filter((t) => (t.market || 'KR') === 'KR');
  console.log(`대상 한국 종목 ${krTickers.length}개, 최근 ${LOOKBACK_DAYS}일 공시 조회`);

  const corpMap = await loadCorpCodeMap();
  const bgnDe = kstYmd(LOOKBACK_DAYS);
  const endDe = kstYmd(0);

  const prev = loadPrev();
  const prevSeen = new Set((prev.items || []).map((x) => x.rceptNo));

  const collected = [];
  const failed = [];
  for (const t of krTickers) {
    const corp = corpMap[t.code];
    if (!corp) { failed.push(`${t.code} ${t.name}: corp_code 없음`); continue; }
    try {
      const rows = await fetchDisclosures(corp, bgnDe, endDe);
      for (const r of rows) {
        const cat = classify(r.report_nm);
        if (!cat) continue;
        collected.push({
          ticker: t.code, name: t.name,
          rceptNo: r.rcept_no,
          reportNm: String(r.report_nm || '').trim(),
          flr: String(r.flr_nm || '').trim(),
          rceptDt: r.rcept_dt, // YYYYMMDD
          category: cat.label,
          level: cat.level,
          url: `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${r.rcept_no}`,
        });
      }
      await sleep(120);
    } catch (e) {
      failed.push(`${t.code} ${t.name}: ${e.message}`);
    }
  }

  // 신규(이전 파일에 없던 rcept_no) 추출 → 알림
  const fresh = collected.filter((x) => !prevSeen.has(x.rceptNo));

  // 기존 + 이번 수집 병합, KEEP_DAYS 이내만 보관, 최신순 정렬, rceptNo 중복 제거
  const cutoff = kstYmd(KEEP_DAYS);
  const byNo = new Map();
  for (const x of [...(prev.items || []), ...collected]) {
    if (String(x.rceptDt || '') >= cutoff) byNo.set(x.rceptNo, x);
  }
  const merged = [...byNo.values()].sort((a, b) =>
    (b.rceptDt + b.rceptNo).localeCompare(a.rceptDt + a.rceptNo));

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify({
    updatedAt: new Date().toISOString(),
    range: { bgnDe, endDe },
    count: merged.length,
    items: merged,
  }, null, 2) + '\n', 'utf8');

  console.log(`\n✅ 관심유형 공시 ${collected.length}건(신규 ${fresh.length}건) → ${OUT_PATH}`);
  fresh.forEach((x) => console.log(`  [신규] ${x.name} · ${x.category} · ${x.reportNm} (${x.rceptDt})`));
  if (failed.length) { console.log(`\n⚠ 실패/건너뜀 ${failed.length}건`); failed.forEach((s) => console.log('  ' + s)); }

  // 텔레그램 알림 (신규 건, 최대 20건 묶음)
  if (fresh.length) {
    const lines = fresh.slice(0, 20).map((x) =>
      `${x.level === 'high' ? '🔴' : '🔵'} ${x.name} [${x.category}] ${x.reportNm}\n${x.url}`);
    await tgNotify(`📢 관심종목 신규 공시 ${fresh.length}건\n\n` + lines.join('\n\n'));
  }
}

main().catch((e) => { console.error('❌', e); process.exit(1); });
