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
const { buildEvents } = require('../lib/eventBuilders/dart');
const { reduce } = require('../lib/stateReducer');
const { getState, putState, appendHistory } = require('../lib/stateStore');
const stateMapPolicy = require('../config/policies/stateMap.v1.json');

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

const CORPMAP_CACHE = path.join(ROOT, 'data', 'cache', 'corpCodeMap.json');
const CORPMAP_TTL_DAYS = Number(process.env.CORPMAP_TTL_DAYS || 7);
const NET_RETRY = Number(process.env.DART_NET_RETRY || 4);

/** DART 접속은 간헐적으로 끊긴다(UND_ERR_CONNECT_TIMEOUT). 지수 백오프로 재시도한다. */
async function fetchRetry(url) {
  let lastErr;
  for (let i = 0; i < NET_RETRY; i++) {
    try { return await fetch(url); }
    catch (e) {
      lastErr = e;
      console.warn(`  네트워크 재시도 ${i + 1}/${NET_RETRY}: ${e.cause?.code || e.message}`);
      if (i < NET_RETRY - 1) await sleep(2000 * 2 ** i);   // 2s → 4s → 8s
    }
  }
  throw lastErr;
}

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

function readCorpMapCache() {
  const j = JSON.parse(fs.readFileSync(CORPMAP_CACHE, 'utf8'));
  if (!j.map || Object.keys(j.map).length === 0) throw new Error('corpCode 캐시가 비어있음');
  return j;
}

/** corp_code 매핑은 거의 변하지 않는데 매 실행 20MB ZIP을 받는 것은 낭비이자 단일 실패점이다.
 *  캐시가 신선하면 재사용하고, 갱신에 실패하면 오래된 캐시로라도 계속 진행한다. */
async function loadCorpCodeMap() {
  try {
    const c = readCorpMapCache();
    const ageDays = (Date.now() - new Date(c.fetchedAt).getTime()) / 86400000;
    if (ageDays < CORPMAP_TTL_DAYS) {
      console.log(`corpCode 캐시 사용 (${Object.keys(c.map).length}건, ${ageDays.toFixed(1)}일 경과)`);
      return c.map;
    }
  } catch { /* 캐시 없음·손상 → 새로 받는다 */ }

  try {
    const res = await fetchRetry(`${BASE}/corpCode.xml?crtfc_key=${KEY}`);
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
    if (Object.keys(map).length === 0) throw new Error('corpCode 파싱 결과 0건');
    fs.mkdirSync(path.dirname(CORPMAP_CACHE), { recursive: true });
    fs.writeFileSync(CORPMAP_CACHE, JSON.stringify({ fetchedAt: new Date().toISOString(), map }, null, 0));
    console.log(`corpCode 갱신 (${Object.keys(map).length}건)`);
    return map;
  } catch (e) {
    let c;
    // 캐시도 없으면 중단한다. 이때 표면에 나올 원인은 캐시 부재가 아니라 네트워크 실패여야 한다.
    try { c = readCorpMapCache(); }
    catch { throw new Error(`corpCode 갱신 실패(${e.cause?.code || e.message}) + 사용할 캐시 없음`); }
    console.warn(`⚠ corpCode 갱신 실패(${e.cause?.code || e.message}) → 캐시(${c.fetchedAt})로 계속 진행`);
    return c.map;
  }
}

/** 한 종목의 최근 공시 목록 (list.json, 필요시 페이지네이션) */
async function fetchDisclosures(corp, bgnDe, endDe) {
  const items = [];
  for (let page = 1; page <= 5; page++) {
    const url = `${BASE}/list.json?` + new URLSearchParams({
      crtfc_key: KEY, corp_code: corp, bgn_de: bgnDe, end_de: endDe,
      page_no: String(page), page_count: '100',
    });
    const res = await fetchRetry(url);
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
  const rawRows = [];   // 원시 DART 응답. 이벤트는 알림 필터(CATEGORIES)와 무관하게 전량에서 만든다.
  const failed = [];
  for (const t of krTickers) {
    const corp = corpMap[t.code];
    if (!corp) { failed.push(`${t.code} ${t.name}: corp_code 없음`); continue; }
    try {
      const rows = await fetchDisclosures(corp, bgnDe, endDe);
      // stock_code가 비는 응답이 있어 watchlist 코드로 보정 (buildEvents의 필수 필드)
      for (const r of rows) rawRows.push({ ...r, stock_code: r.stock_code || t.code });
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

  // ── STEP2: Event → State 반영 ────────────────────────────────
  // 알림·JSON 생성과 완전히 분리한다. 여기서 예외가 나도 위 산출물은 정상 생성되어야 한다.
  const stateSync = { processed: 0, applied: 0, failed: [] };
  const events = [];
  for (const item of rawRows) {
    try { events.push(...buildEvents(item)); }
    catch (err) { stateSync.failed.push({ rceptNo: item.rcept_no ?? null, reason: err.message }); }
  }
  events.sort((a, b) => a.sortKey.localeCompare(b.sortKey));   // REDUCE-006 전제: sortKey 오름차순
  for (const ev of events) {
    stateSync.processed++;
    try {
      const prevState = getState(ev.ticker);
      const nextState = reduce(prevState, ev, stateMapPolicy);
      // reduce는 이미 반영된 이벤트에 대해 prevState를 그대로 반환한다.
      // 동일 참조면 건너뛰어야 재실행 시 state-history에 중복 append가 쌓이지 않는다.
      if (nextState === prevState) continue;
      putState(nextState);
      appendHistory(ev);
      stateSync.applied++;
    } catch (err) {
      stateSync.failed.push({ ticker: ev.ticker, eventId: ev.eventId, reason: err.message });
    }
  }

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
    stateSync,
    items: merged,
  }, null, 2) + '\n', 'utf8');

  console.log(`\n✅ 관심유형 공시 ${collected.length}건(신규 ${fresh.length}건) → ${OUT_PATH}`);
  fresh.forEach((x) => console.log(`  [신규] ${x.name} · ${x.category} · ${x.reportNm} (${x.rceptDt})`));
  if (failed.length) { console.log(`\n⚠ 실패/건너뜀 ${failed.length}건`); failed.forEach((s) => console.log('  ' + s)); }
  console.log(`\n🧩 state: 이벤트 ${stateSync.processed}건 중 ${stateSync.applied}건 반영, 실패 ${stateSync.failed.length}건`);
  stateSync.failed.slice(0, 10).forEach((f) => console.log('  ' + JSON.stringify(f)));

  // 텔레그램 알림 (신규 건, 최대 20건 묶음)
  if (fresh.length) {
    const lines = fresh.slice(0, 20).map((x) =>
      `${x.level === 'high' ? '🔴' : '🔵'} ${x.name} [${x.category}] ${x.reportNm}\n${x.url}`);
    await tgNotify(`📢 관심종목 신규 공시 ${fresh.length}건\n\n` + lines.join('\n\n'));
  }
}

main().catch((e) => { console.error('❌', e); process.exit(1); });
