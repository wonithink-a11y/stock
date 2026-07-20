#!/usr/bin/env node
/**
 * 네이버 검색 API(뉴스) → 관심종목 뉴스 피드 + 시장 주요뉴스 + 악재/호재 키워드 알림
 *
 *   - docs/data/news.json  (대시보드 뉴스 탭·시장 헤드라인용)
 *   - 텔레그램 알림          (키워드에 걸린 신규 기사만)
 *
 * 네이버 검색 API는 '실시간 스트림'이 아니라 최신순 검색 폴링입니다.
 * 하루 25,000 호출 한도 — 종목 20개 + 시장쿼리 몇 개면 1회 실행에 ~25콜, 부담 없음.
 *
 * 키는 환경변수로만 주입 (저장소 공개 → 하드코딩 금지):
 *   NAVER_CLIENT_ID=xxxx NAVER_CLIENT_SECRET=xxxx \
 *   [TELEGRAM_BOT_TOKEN=xxxx TELEGRAM_CHAT_ID=xxxx] node scripts/fetch-news-kr.js
 *
 * 외부 의존성 없음 (Node 18+ 내장 fetch).
 */
'use strict';

const fs = require('fs');
const path = require('path');

const CID = process.env.NAVER_CLIENT_ID;
const CSECRET = process.env.NAVER_CLIENT_SECRET;
if (!CID || !CSECRET) {
  console.error('❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 없습니다. GitHub Secrets에 등록하세요.');
  process.exit(1);
}
const TG_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TG_CHAT = process.env.TELEGRAM_CHAT_ID || '';

const ROOT = path.resolve(__dirname, '..');
const WATCHLIST_PATH = path.join(ROOT, 'config', 'watchlist.json');
const OUT_PATH = path.join(ROOT, 'docs', 'data', 'news.json');

const PER_STOCK = Number(process.env.NEWS_PER_STOCK || 5);   // 종목당 저장 기사 수
const MARKET_QUERIES = (process.env.NEWS_MARKET_QUERIES ||
  '코스피,원달러 환율,미국 연준 금리,반도체 업황').split(',').map((s) => s.trim()).filter(Boolean);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 투자 영향 큰 키워드 (제목·요약에서 탐지) → 알림·태그
const BAD = ['유상증자', '무상감자', '감자', '횡령', '배임', '소송', '고소', '피소', '압수수색',
  '리콜', '결함', '어닝쇼크', '적자전환', '영업손실', '하한가', '상장폐지', '관리종목',
  '불성실공시', '실권주', '과징금', '분식', '영업정지', '해킹', '유출'];
const GOOD = ['자사주', '자기주식취득', '수주', '공급계약', '계약체결', '흑자전환', '어닝서프라이즈',
  '최대실적', '사상최대', '신약', '임상', '품목허가', '승인', '특허', '상한가', '배당확대', '인수'];

function classifyNews(text) {
  const t = String(text || '');
  const bad = BAD.filter((k) => t.includes(k));
  const good = GOOD.filter((k) => t.includes(k));
  if (bad.length) return { level: 'bad', flags: bad.slice(0, 3) };
  if (good.length) return { level: 'good', flags: good.slice(0, 3) };
  return { level: 'neutral', flags: [] };
}

function stripTags(s) {
  return String(s || '')
    .replace(/<\/?b>/g, '')
    .replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&#39;/g, "'").replace(/&apos;/g, "'")
    .trim();
}

// pubDate("Mon, 20 Jul 2026 14:03:00 +0900") → ISO / 표시용
function parsePub(s) {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? { iso: null, disp: String(s || '') }
    : { iso: d.toISOString(), disp: d.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) };
}

async function searchNews(query, display = 10, sort = 'date') {
  const url = 'https://openapi.naver.com/v1/search/news.json?' + new URLSearchParams({
    query, display: String(display), start: '1', sort,
  });
  const res = await fetch(url, { headers: { 'X-Naver-Client-Id': CID, 'X-Naver-Client-Secret': CSECRET } });
  if (!res.ok) throw new Error(`news HTTP ${res.status}`);
  const j = await res.json();
  return (j.items || []).map((it) => {
    const title = stripTags(it.title);
    const desc = stripTags(it.description);
    const c = classifyNews(title + ' ' + desc);
    const pub = parsePub(it.pubDate);
    return {
      title, desc,
      link: it.link, originallink: it.originallink,
      source: (() => { try { return new URL(it.originallink || it.link).hostname.replace(/^www\./, ''); } catch { return ''; } })(),
      pubDate: pub.iso, pubDisp: pub.disp,
      level: c.level, flags: c.flags,
    };
  });
}

function loadPrev() {
  try { return JSON.parse(fs.readFileSync(OUT_PATH, 'utf8')); } catch { return {}; }
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
  const tickers = watchlist.tickers || [];
  console.log(`대상 종목 ${tickers.length}개 + 시장쿼리 ${MARKET_QUERIES.length}개`);

  // 이전 파일에서 이미 알린 기사 링크 집합 (중복 알림 방지)
  const prev = loadPrev();
  const prevLinks = new Set();
  for (const v of Object.values(prev.byTicker || {})) for (const it of v.items || []) prevLinks.add(it.originallink || it.link);

  const byTicker = {};
  const freshAlerts = [];
  let calls = 0;

  for (const t of tickers) {
    try {
      const items = await searchNews(t.name, 10, 'date');
      calls++;
      // 같은 기사 중복 제거(originallink) 후 상위 PER_STOCK
      const seen = new Set();
      const uniq = [];
      for (const it of items) {
        const key = it.originallink || it.link;
        if (seen.has(key)) continue;
        seen.add(key);
        uniq.push(it);
        if (uniq.length >= PER_STOCK) break;
      }
      byTicker[t.code] = { name: t.name, market: t.market || 'KR', items: uniq };
      // 키워드에 걸린 신규 기사 알림 대상 수집
      for (const it of uniq) {
        if (it.level !== 'neutral' && !prevLinks.has(it.originallink || it.link)) {
          freshAlerts.push({ code: t.code, name: t.name, ...it });
        }
      }
    } catch (e) {
      console.warn(`  [경고] ${t.code} ${t.name} 뉴스 실패: ${e.message}`);
      if (prev.byTicker && prev.byTicker[t.code]) byTicker[t.code] = prev.byTicker[t.code]; // 실패 시 직전분 유지
    }
    await sleep(120);
  }

  const market = [];
  for (const q of MARKET_QUERIES) {
    try {
      const items = await searchNews(q, 5, 'date');
      calls++;
      market.push({ query: q, items: items.slice(0, 4) });
    } catch (e) { console.warn(`  [경고] 시장쿼리 "${q}" 실패: ${e.message}`); }
    await sleep(120);
  }

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify({
    updatedAt: new Date().toISOString(),
    perStock: PER_STOCK,
    byTicker, market,
  }, null, 2) + '\n', 'utf8');

  console.log(`\n✅ 뉴스 갱신: 종목 ${Object.keys(byTicker).length} · 시장 ${market.length}쿼리 · API ${calls}콜 · 신규 키워드기사 ${freshAlerts.length}건 → ${OUT_PATH}`);
  freshAlerts.forEach((a) => console.log(`  [${a.level === 'bad' ? '악재' : '호재'}] ${a.name}: ${a.title}`));

  if (freshAlerts.length) {
    const lines = freshAlerts.slice(0, 15).map((a) =>
      `${a.level === 'bad' ? '🔴' : '🟢'} ${a.name} [${a.flags.join(',')}]\n${a.title}\n${a.originallink || a.link}`);
    await tgNotify(`📰 관심종목 뉴스 키워드 감지 ${freshAlerts.length}건\n\n` + lines.join('\n\n'));
  }
}

main().catch((e) => { console.error('❌', e); process.exit(1); });
