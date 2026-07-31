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
const HOLDINGS_PATH = path.join(ROOT, 'config', 'holdings.json');
const OUT_PATH = path.join(ROOT, 'docs', 'data', 'news.json');

const PER_STOCK = Number(process.env.NEWS_PER_STOCK || 5);   // 종목당 저장 기사 수
const USE_GOOGLE = process.env.NEWS_GOOGLE !== '0';           // 구글뉴스 RSS 병행(무키). 0이면 끔
const RETENTION_DAYS = Number(process.env.NEWS_RETENTION_DAYS || 3);  // 이보다 오래된 기사는 버림
const BRIEF_MAX = Number(process.env.NEWS_BRIEF_MAX || 15);   // '꼭 볼 뉴스' 최대 건수
const SEEN_TTL_DAYS = 7;                                      // 알림 중복방지 원장 보존일

const CUTOFF = Date.now() - RETENTION_DAYS * 86400e3;

// 네이버는 최신 기사가 없으면 몇 주 전 기사를 그대로 돌려준다. 그대로 두면 낡은 뉴스가
// 계속 화면에 남고 파일만 커지므로, 수집 시점에 컷오프로 잘라낸다.
// pubDate 파싱이 안 되는 기사는 판단 불가 → 남긴다(정보 손실보다 낫다).
function isFresh(it) {
  if (!it || !it.pubDate) return true;
  const t = Date.parse(it.pubDate);
  return Number.isNaN(t) ? true : t >= CUTOFF;
}

// ─────────────────────────────────────────────────────────────
// 시장 뉴스 그룹 — 대시보드 뉴스탭 세부탭과 1:1 대응.
// intl:true 인 그룹만 구글뉴스 RSS(영문)를 추가로 훑는다(원문 헤드라인이 몇 시간 빠름).
// 쿼리를 바꾸고 싶으면 이 블록만 고치면 된다.
// ─────────────────────────────────────────────────────────────
const MARKET_GROUPS = [
  {
    key: 'kr', label: '🇰🇷 한국시장',
    queries: ['코스피', '코스닥', '외국인 순매수', '원달러 환율', '한국은행 기준금리', '밸류업 프로그램'],
  },
  {
    key: 'us', label: '🇺🇸 미국·글로벌', intl: true,
    queries: ['미국 연준 금리', 'FOMC', '나스닥 지수', '미국 국채 금리', '미국 소비자물가', '미국 고용지표'],
    enQueries: ['Federal Reserve rate decision', 'US inflation CPI', 'Treasury yields'],
  },
  {
    key: 'sector', label: '🏭 업종·테마',
    queries: ['반도체 업황', 'HBM', '2차전지', '조선 수주', '방산 수출', '원전 수주', '전력기기', '바이오 신약'],
  },
  {
    key: 'risk', label: '⚠️ 리스크·지정학', intl: true,
    queries: ['국제유가', '호르무즈 해협', '이란', '관세', '반도체 수출규제', '미중 갈등', '공매도 과열'],
    enQueries: ['oil prices Strait of Hormuz', 'geopolitical risk markets', 'tariffs trade'],
  },
];

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

// ─────────────────────────────────────────────────────────────
// 매크로·지정학 충격 (기업 단위 BAD/GOOD 과 별개 계층)
//
// 위의 BAD/GOOD 은 전부 기업 이벤트(유상증자·횡령·리콜)라서 "호르무즈 봉쇄"나
// "국제유가 급등" 같은 시장 전체 충격은 전부 neutral 로 흘러 알림도 안 갔다.
// 그래서 별도 계층을 둔다.
//
// benefit/harm 은 관심종목 중 '일반적인 전달경로'상 방향이 다른 종목이다.
// ⚠ 개별 기업의 헤지·장기계약·판가전가 능력에 따라 실제 방향은 달라질 수 있고,
//    점수(criteria)에는 절대 반영하지 않는다 — 맥락 표시 전용이다.
// ─────────────────────────────────────────────────────────────
const MACRO_SHOCKS = [
  {
    key: 'oil', label: '유가·에너지',
    re: /국제유가|유가\s*급[등락]|브렌트유?|두바이유|WTI|OPEC|감산|호르무즈|\boil prices?\b|\bcrude\b|\bbrent\b|\bHormuz\b/i,
    benefit: ['010950', '096770', '047050', 'XOM', 'CVX'],           // 정유·가스전·에너지
    harm: ['003490', '051910', '161390', '015760'],                   // 항공유·납사·원재료·연료수입
    note: '유가 상승은 정유·에너지 마진에 유리하고 항공·화학·전력에는 원가 부담입니다.',
  },
  {
    key: 'war', label: '지정학·분쟁',
    // ⚠ 한국어 '이란'은 "밸류업이란 무엇인가" 처럼 조사로도 쓰여 오탐이 난다 → 검색 쿼리에만 두고
    //    분류 정규식에서는 뺀다. 이스라엘·호르무즈·무력충돌 등 모호하지 않은 말로 잡는다.
    re: /전쟁|공습|미사일|무력충돌|휴전|정전협정|중동\s*정세|이스라엘|이란(?:산|군|핵|\s*(?:정부|제재|공격|혁명수비대))|대만\s*해협|지정학|\bgeopolitic|\bairstrikes?\b|\bmissiles?\b|\bceasefire\b|\bIran\b|\bIsrael\b|\bmilitary conflict\b/i,
    benefit: ['012450', '079550', '047810', '064350', '272210', 'RTX', 'GE'],  // 방산
    harm: ['003490', '352820', '090430'],                             // 여행·항공·소비재 심리
    note: '분쟁 국면은 방산 수주 기대에 유리하나, 지수 전반에는 위험회피로 작용합니다.',
  },
  {
    key: 'logistics', label: '물류·해상운임',
    re: /해상운임|운임\s*급[등락]|SCFI|BDI|수에즈|파나마\s*운하|항만\s*적체|선복|\bfreight rates?\b|\bSuez\b|\bPanama Canal\b|\bport congestion\b/i,
    benefit: ['011200', '009540', '042660', '010140'],                // 해운·조선
    harm: ['003490', '086280'],
    note: '운임 급등은 해운사 실적에 직결되고, 화주·물류비 부담 기업에는 역방향입니다.',
  },
  {
    key: 'fx', label: '환율',
    re: /원달러|원\/달러|환율\s*급[등락]|달러\s*[강약]세|외환당국|구두개입|\bdollar (?:strength|weakness)\b|\bFX intervention\b/i,
    benefit: ['005930', '005380', '000270', '000660'],                // 수출 대형주
    harm: ['003490', '015760', '032640'],                             // 외화부채·수입연료
    note: '원화 약세는 수출주 환산이익에 유리하고, 외화부채·수입원가 기업에는 부담입니다.',
  },
  {
    key: 'tariff', label: '관세·수출규제',
    re: /관세|무역장벽|수출\s*[규통]제|반덤핑|세이프가드|엔티티\s*리스트|\btariffs?\b|\bexport controls?\b|\bentity list\b|\banti-dumping\b/i,
    benefit: [],
    harm: ['005930', '000660', '005380', '000270', '005490', '051910'],
    note: '관세·수출규제는 수출 비중이 큰 대형 제조업에 직접적인 하방 요인입니다.',
  },
];

function detectShock(text) {
  const t = String(text || '');
  return MACRO_SHOCKS.filter((s) => s.re.test(t));
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

// ── 구글뉴스 RSS (무키·의존성 없음) ────────────────────────────
// 야후 파이낸스 종목별 RSS(feeds.finance.yahoo.com/rss/2.0/headline?s=)는 폐지되어
// 빈 응답만 돌아온다. 영문 원문 헤드라인은 구글뉴스 RSS 로 대체한다.
// 실패해도 전체 수집을 막지 않는다(fail-soft) — 성공/실패는 _diagnostics 에 남긴다.
const gnDiag = { ok: 0, fail: 0, errors: [] };

function stripHtml(s) {
  return stripTags(String(s || '').replace(/<[^>]+>/g, ' ')).replace(/\s{2,}/g, ' ').trim();
}

function parseRss(xml) {
  const out = [];
  const uncdata = (s) => String(s || '').replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, '$1');
  const re = /<item\b[^>]*>([\s\S]*?)<\/item>/g;
  let m;
  while ((m = re.exec(xml))) {
    const body = m[1];
    const pick = (tag) => {
      const r = new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)</${tag}>`);
      const x = r.exec(body);
      return x ? uncdata(x[1]).trim() : '';
    };
    const title = stripHtml(pick('title'));
    const link = pick('link');
    if (!title || !link) continue;
    out.push({ title, link, pubDate: pick('pubDate'), source: stripHtml(pick('source')), desc: stripHtml(pick('description')) });
  }
  return out;
}

async function searchGoogleNews(query, display = 5, lang = 'en') {
  const p = lang === 'ko'
    ? { hl: 'ko', gl: 'KR', ceid: 'KR:ko' }
    : { hl: 'en-US', gl: 'US', ceid: 'US:en' };
  const url = 'https://news.google.com/rss/search?' + new URLSearchParams({
    q: `${query} when:2d`, ...p,
  });
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; stock-news-bot/1.0)' } });
  if (!res.ok) throw new Error(`google HTTP ${res.status}`);
  const xml = await res.text();
  const items = parseRss(xml).slice(0, display);
  if (!items.length) throw new Error('구글뉴스 파싱 결과 0건 (RSS 형식 변경 가능성)');
  return items.map((it) => {
    const c = classifyNews(it.title + ' ' + it.desc);
    const pub = parsePub(it.pubDate);
    return {
      title: it.title, desc: it.desc,
      link: it.link, originallink: it.link,
      source: it.source || 'Google News',
      pubDate: pub.iso, pubDisp: pub.disp,
      level: c.level, flags: c.flags,
      lang: lang === 'ko' ? 'ko' : 'en',
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
  const nameByCode = Object.fromEntries(tickers.map((t) => [t.code, t.name]));
  const qCount = MARKET_GROUPS.reduce((a, g) => a + g.queries.length, 0);
  console.log(`대상 종목 ${tickers.length}개 + 시장쿼리 ${qCount}개(${MARKET_GROUPS.length}그룹)`
    + (USE_GOOGLE ? ' + 구글뉴스 RSS' : ''));

  // 보유종목 — '꼭 볼 뉴스' 최우선 판단 근거. 파일이 없거나 비어도 정상 동작한다.
  let heldCodes = new Set();
  try {
    const h = JSON.parse(fs.readFileSync(HOLDINGS_PATH, 'utf8'));
    heldCodes = new Set((h.holdings || []).map((x) => x.code));
  } catch { console.warn('  [안내] holdings.json 을 읽지 못했습니다 — 보유종목 가중치 없이 진행합니다.'); }
  console.log(`보유종목 ${heldCodes.size}개 · 보존기간 ${RETENTION_DAYS}일`);

  const prev = loadPrev();

  // 알림 중복방지 원장. 예전에는 직전 byTicker 에서 링크를 모았는데, 이제 오래된 기사를
  // 잘라내므로 그 방식이면 '잘렸다가 다시 검색된' 기사가 재알림된다 → 링크별 시각을 따로 보관.
  const seenLedger = { ...(prev._seen || {}) };
  const seenCut = Date.now() - SEEN_TTL_DAYS * 86400e3;
  for (const k of Object.keys(seenLedger)) {
    if (Date.parse(seenLedger[k]) < seenCut) delete seenLedger[k];
  }
  // 구버전 파일에서 올라온 경우(원장 없음) 직전 기사들을 이미 본 것으로 간주 — 최초 1회 폭탄 알림 방지
  if (!prev._seen) {
    for (const v of Object.values(prev.byTicker || {})) {
      for (const it of v.items || []) seenLedger[it.originallink || it.link] = new Date().toISOString();
    }
  }

  const byTicker = {};
  const freshAlerts = [];
  let calls = 0;
  let droppedOld = 0;

  for (const t of tickers) {
    try {
      // 2글자 이하 사명(LG·SK·GS·한화…)은 그대로 검색하면 무관 기사가 쏟아진다 → '주가' 를 덧붙여 좁힌다
      const q = String(t.name).length <= 2 ? `${t.name} 주가` : t.name;
      const items = await searchNews(q, 10, 'date');
      calls++;
      // 같은 기사 중복 제거(originallink) + 보존기간 컷오프 후 상위 PER_STOCK
      const seen = new Set();
      const uniq = [];
      for (const it of items) {
        const key = it.originallink || it.link;
        if (seen.has(key)) continue;
        seen.add(key);
        if (!isFresh(it)) { droppedOld++; continue; }
        uniq.push(it);
        if (uniq.length >= PER_STOCK) break;
      }
      // 기사가 하나도 없는 종목은 아예 싣지 않는다 (news.json 크기·화면 노이즈 감소)
      if (uniq.length) byTicker[t.code] = { name: t.name, market: t.market || 'KR', held: heldCodes.has(t.code), items: uniq };
      // 키워드에 걸린 신규 기사 알림 대상 수집
      for (const it of uniq) {
        const key = it.originallink || it.link;
        if (it.level !== 'neutral' && !seenLedger[key]) {
          freshAlerts.push({ code: t.code, name: t.name, held: heldCodes.has(t.code), ...it });
        }
        seenLedger[key] = new Date().toISOString();
      }
    } catch (e) {
      console.warn(`  [경고] ${t.code} ${t.name} 뉴스 실패: ${e.message}`);
      // 실패 시 직전분 유지 — 단 보존기간은 그대로 적용
      const keep = ((prev.byTicker || {})[t.code] || {}).items || [];
      const fresh = keep.filter(isFresh);
      if (fresh.length) byTicker[t.code] = { ...prev.byTicker[t.code], held: heldCodes.has(t.code), items: fresh };
    }
    await sleep(120);
  }

  // ── 시장 뉴스: 그룹별 수집 (네이버 + intl 그룹은 구글뉴스 영문 병행) ──
  // 같은 사건을 여러 매체가 쓰므로 그룹 전체에서 링크·제목 기준으로 중복을 제거한다.
  const market = [];
  const seenMarket = new Set();
  const normTitle = (s) => String(s).replace(/[^가-힣a-zA-Z0-9]/g, '').slice(0, 22).toLowerCase();
  const shockHits = new Map();   // shock.key → { ...shock, items:[] }

  const collect = (group, query, source, items) => {
    const uniq = [];
    for (const it of items) {
      const lk = it.originallink || it.link;
      const tk = normTitle(it.title);
      if (seenMarket.has(lk) || seenMarket.has(tk)) continue;
      seenMarket.add(lk); seenMarket.add(tk);
      if (!isFresh(it)) { droppedOld++; continue; }
      uniq.push(it);
      // 매크로·지정학 충격 감지 (기업 BAD/GOOD 과 별개 계층)
      for (const s of detectShock(it.title + ' ' + it.desc)) {
        if (!shockHits.has(s.key)) shockHits.set(s.key, { key: s.key, label: s.label, note: s.note, items: [] });
        const bucket = shockHits.get(s.key);
        if (bucket.items.length < 5) bucket.items.push({ ...it, group: group.key });
      }
    }
    if (uniq.length) market.push({ group: group.key, label: group.label, query, source, items: uniq });
  };

  for (const g of MARKET_GROUPS) {
    for (const q of g.queries) {
      try {
        collect(g, q, 'naver', (await searchNews(q, 8, 'date')).slice(0, 5));
        calls++;
      } catch (e) { console.warn(`  [경고] 시장쿼리 "${q}" 실패: ${e.message}`); }
      await sleep(120);
    }
    if (USE_GOOGLE && g.intl) {
      for (const q of (g.enQueries || [])) {
        try {
          collect(g, q, 'google', await searchGoogleNews(q, 5, 'en'));
          gnDiag.ok++;
        } catch (e) {
          gnDiag.fail++; gnDiag.errors.push(`${q}: ${e.message}`);
          console.warn(`  [경고] 구글뉴스 "${q}" 실패: ${e.message}`);
        }
        await sleep(250);
      }
    }
  }

  // 충격별 수혜·피해 종목을 관심종목 안에서만 매핑 (점수 반영 없음, 표시 전용)
  const shocks = [...shockHits.values()].map((s) => {
    const def = MACRO_SHOCKS.find((x) => x.key === s.key) || {};
    const pick = (codes) => (codes || []).filter((c) => nameByCode[c]).map((c) => ({ code: c, name: nameByCode[c] }));
    return { ...s, benefit: pick(def.benefit), harm: pick(def.harm) };
  });

  // ── '꼭 볼 뉴스' 선별 ────────────────────────────────────────
  // 수집한 기사는 수백 건이라 그대로 보면 못 본다. 아래 우선순위로 점수를 매겨
  // 상위 BRIEF_MAX 건만 남긴다. 같은 기사는 가장 높은 사유 하나로만 싣는다.
  //
  //   보유종목 악재 > 보유종목 호재 > 시장 충격 > 관심종목 악재 > 보유종목 일반 > 관심종목 호재
  //
  // 보유종목 '일반' 기사는 종목당 2건까지만 — 조용한 날에 브리핑이 잡담으로 채워지는 걸 막는다.
  const briefPool = new Map();   // link → 후보
  const addBrief = (it, priority, why, extra = {}) => {
    const key = it.originallink || it.link;
    const cur = briefPool.get(key);
    if (cur && cur.priority >= priority) return;
    briefPool.set(key, { ...it, ...extra, priority, why });
  };

  for (const [code, v] of Object.entries(byTicker)) {
    let neutralQuota = 2;
    for (const it of v.items) {
      const ref = { code, name: v.name, held: !!v.held };
      if (v.held && it.level === 'bad') addBrief(it, 100, '보유종목 악재', ref);
      else if (v.held && it.level === 'good') addBrief(it, 85, '보유종목 호재', ref);
      else if (it.level === 'bad') addBrief(it, 60, '관심종목 악재', ref);
      else if (v.held && neutralQuota > 0) { addBrief(it, 50, '보유종목 소식', ref); neutralQuota--; }
      else if (it.level === 'good') addBrief(it, 40, '관심종목 호재', ref);
    }
  }
  // 충격이 여러 종 동시에 뜨면(유가+분쟁+환율+관세…) 브리핑을 전부 차지해
  // 정작 관심종목 악재가 밀려난다 → 기사 수가 많은 충격부터 최대 4건까지만.
  let shockQuota = 4;
  for (const s of [...shocks].sort((a, b) => b.items.length - a.items.length)) {
    for (const it of s.items.slice(0, 2)) {
      if (shockQuota <= 0) break;
      addBrief(it, 75, `시장 충격 · ${s.label}`, { shock: s.key });
      shockQuota--;
    }
  }

  const briefing = [...briefPool.values()]
    .sort((a, b) => b.priority - a.priority
      || String(b.pubDate || '').localeCompare(String(a.pubDate || '')))
    .slice(0, BRIEF_MAX);

  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify({
    updatedAt: new Date().toISOString(),
    perStock: PER_STOCK,
    retentionDays: RETENTION_DAYS,
    groups: MARKET_GROUPS.map((g) => ({ key: g.key, label: g.label })),
    briefing, byTicker, market, shocks,
    _seen: seenLedger,
    _diagnostics: {
      naverCalls: calls,
      droppedOld,
      heldCount: heldCodes.size,
      google: USE_GOOGLE ? { ok: gnDiag.ok, fail: gnDiag.fail, errors: gnDiag.errors.slice(0, 5) } : 'disabled',
    },
  }, null, 2) + '\n', 'utf8');

  const marketCount = market.reduce((a, m) => a + m.items.length, 0);
  console.log(`\n✅ 뉴스 갱신: 꼭볼뉴스 ${briefing.length}건 · 종목 ${Object.keys(byTicker).length}`
    + ` · 시장 ${marketCount}건/${market.length}쿼리`
    + ` · 네이버 ${calls}콜 · 구글 ok${gnDiag.ok}/fail${gnDiag.fail}`
    + ` · 충격 ${shocks.length}종 · ${RETENTION_DAYS}일 초과 폐기 ${droppedOld}건 → ${OUT_PATH}`);
  console.log('\n── 꼭 볼 뉴스 ──');
  briefing.forEach((b) => console.log(`  [${b.why}] ${b.name ? b.name + ' · ' : ''}${b.title}`));
  freshAlerts.forEach((a) => console.log(`  [알림:${a.level === 'bad' ? '악재' : '호재'}] ${a.name}: ${a.title}`));
  shocks.forEach((s) => console.log(`  [충격] ${s.label} ${s.items.length}건 · 수혜 ${s.benefit.length} / 피해 ${s.harm.length}`));
  if (USE_GOOGLE && gnDiag.ok === 0) {
    console.warn('  ⚠ 구글뉴스 RSS 가 한 건도 성공하지 못했습니다. 형식 변경이거나 차단일 수 있습니다'
      + ' (네이버 수집은 정상). NEWS_GOOGLE=0 으로 끌 수 있습니다.');
  }

  if (freshAlerts.length) {
    // 보유종목을 먼저, 그 다음 악재 순으로 — 알림이 잘려도 중요한 것이 남게
    freshAlerts.sort((a, b) => (b.held - a.held) || ((a.level === 'bad' ? -1 : 1) - (b.level === 'bad' ? -1 : 1)));
    const lines = freshAlerts.slice(0, 15).map((a) =>
      `${a.held ? '📌' : ''}${a.level === 'bad' ? '🔴' : '🟢'} ${a.name} [${a.flags.join(',')}]\n${a.title}\n${a.originallink || a.link}`);
    await tgNotify(`📰 관심종목 뉴스 키워드 감지 ${freshAlerts.length}건 (📌=보유)\n\n` + lines.join('\n\n'));
  }
}

main().catch((e) => { console.error('❌', e); process.exit(1); });
