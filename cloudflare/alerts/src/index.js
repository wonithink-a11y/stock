// stock-alerts — Cloudflare Workers(무료). 주문 없음. 크론 4개(무료 한도 5개):
//   */5 * * * *    가격 목표 + 소수 종목 등락률(±MOVE_STEP% 단계) + 장중 VIX 20·25·30… 단계(참고용) — 장 밖이면 시세 조회 없이 끝  [텔레그램+카카오]
//   10 22 * * 1-5  SVIX 신호 알림(UTC 22:10 = KST 07:10 화~토, 미국 마감 뒤)                       [텔레그램+카카오]
//   40 6 * * 1-5   국내 마감 요약(KST 15:40) — 코스피200·코스닥150(ETF)                           [텔레그램만]
//   10 21 * * 1-5  미국 마감 요약(KST 06:10, 서머타임이어도 마감 뒤) — S&P500·나스닥100·감시 종목  [텔레그램만]
// 상태: KV ALERTS — targets · fired · vix_last · move_state · kakao_token. 시크릿: TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID · KAKAO_REST_API_KEY · (KAKAO_CLIENT_SECRET) · ADMIN_KEY
import { vixAlert, checkTargets, parseNaverQuote, checkMoves, checkVixLevel, digestMessage, marketOpen, etDate, tid, evalStops, stopLine, stopId, deadmanDue, MAX_STOPS } from './core.js';

const DASH = 'https://wonithink-a11y.github.io/stock/';
const UA = { 'User-Agent': 'Mozilla/5.0' };
const VIX_CRON = '10 22 * * 1-5', KR_DIGEST_CRON = '40 6 * * 1-5', US_DIGEST_CRON = '10 21 * * 1-5', MIN_CRON = '* * * * *';
const WATCH_US = ['SVIX', 'SOXL'];                                                   // 등락률 알림·미국 요약에 넣는 종목
const US_INDEX = [['^GSPC', 'S&P500'], ['^NDX', '나스닥100']];
const KR_INDEX = [['KPI200', '코스피200'], ['229200', '코스닥150(KODEX ETF)']];      // 코스닥150 지수는 무료 시세에 없어 ETF 로 대신한다
const S = (env, k) => (env[k] || '').trim();      // wrangler secret put 에 파이프로 넣으면 끝에 개행이 붙을 수 있다

// ---------- 전송 ----------
async function telegram(env, text, opts = {}) {
  const chat = (opts.chat === 'trade' && S(env, 'TELEGRAM_TRADE_CHAT_ID')) || S(env, 'TELEGRAM_CHAT_ID');   // 매매·보안방(없으면 기본 방으로 폴백)
  if (!S(env, 'TELEGRAM_BOT_TOKEN') || !chat) throw new Error('텔레그램 키 없음');
  const r = await fetch(`https://api.telegram.org/bot${S(env, 'TELEGRAM_BOT_TOKEN')}/sendMessage`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chat, text, disable_web_page_preview: true }),     // 미리보기가 확인 링크를 먼저 열지 않게
  });
  if (!r.ok) throw new Error(`telegram HTTP ${r.status}`);
}

async function kakaoAccessToken(env) {
  const raw = await env.ALERTS.get('kakao_token');
  if (!raw) throw new Error('kakao_token 없음');
  const tok = JSON.parse(raw), now = Date.now() / 1000;
  if (tok.access_expires_at - now > 600) return tok.access_token;
  const form = new URLSearchParams({ grant_type: 'refresh_token', client_id: S(env, 'KAKAO_REST_API_KEY'), refresh_token: tok.refresh_token });
  if (S(env, 'KAKAO_CLIENT_SECRET')) form.set('client_secret', S(env, 'KAKAO_CLIENT_SECRET'));
  const r = await (await fetch('https://kauth.kakao.com/oauth/token', { method: 'POST', body: form })).json();
  if (!r.access_token) throw new Error(`카카오 토큰 갱신 실패: ${JSON.stringify(r).slice(0, 120)}`);
  tok.access_token = r.access_token; tok.access_expires_at = now + r.expires_in;
  if (r.refresh_token) { tok.refresh_token = r.refresh_token; tok.refresh_expires_at = now + r.refresh_token_expires_in; }
  await env.ALERTS.put('kakao_token', JSON.stringify(tok));
  return tok.access_token;
}

async function kakao(env, text) {
  const token = await kakaoAccessToken(env);
  const tpl = { object_type: 'text', text, link: { web_url: DASH, mobile_web_url: DASH } };
  const r = await (await fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: new URLSearchParams({ template_object: JSON.stringify(tpl) }),
  })).json();
  if (r.result_code !== 0) throw new Error(`카카오 전송 실패: ${JSON.stringify(r).slice(0, 120)}`);
}

/** 채널을 따로 시도한다. 하나라도 성공하면 ok(그 알림은 '보냄'으로 친다). opts.kakao=false 면 텔레그램만(요약용). */
async function send(env, text, opts = {}) {
  const res = {};
  for (const [name, f] of [['telegram', telegram], ['kakao', kakao]].filter(([n]) => n !== 'kakao' || opts.kakao !== false)) {
    try { await f(env, text, opts); res[name] = 'OK'; } catch (e) { res[name] = String(e.message || e); console.log(name, '실패', res[name]); }
  }
  return { ok: Object.values(res).includes('OK'), res };
}

// ---------- 시세 ----------
async function vixCloses(now) {
  const r = await (await fetch('https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=3y&interval=1d', { headers: UA })).json();
  const res = r.chart.result[0], q = res.indicators.quote[0].close, today = etDate(now);
  return res.timestamp.map((t, i) => [etDate(new Date(t * 1000)), q[i]]).filter(([d, v]) => v != null && d < today);   // 오늘(미완성) 제외
}

/** 시세 {px, prev}(전일 종가). 실패·휴장·낡은 값이면 null. maxAgeSec: 미국은 마지막 체결이 이 초 안이어야(장중 1800, 요약은 같은 날 ET). */
async function quote(market, sym, now, maxAgeSec = 1800) {
  try {
    if (market === 'KR') {
      const x = await (await fetch(`https://fchart.stock.naver.com/sise.nhn?symbol=${sym}&timeframe=day&count=2&requestType=0`, { headers: UA })).text();
      return parseNaverQuote(x, now);
    }
    const m = (await (await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=1d&interval=1d`, { headers: UA })).json()).chart.result[0].meta;
    if (now.getTime() / 1000 - m.regularMarketTime > maxAgeSec) return null;
    return { px: Number(m.regularMarketPrice), prev: Number(m.chartPreviousClose), t: m.regularMarketTime };
  } catch (e) { console.log('시세 실패', market, sym, String(e)); return null; }
}
const fetchPx = async (market, sym, now) => (await quote(market, sym, now))?.px ?? null;

// ---------- 작업 ----------
async function vixJob(env, now) {
  const last = (await env.ALERTS.get('vix_last')) || '';
  const a = vixAlert(await vixCloses(now), last);
  if (!a) return console.log('VIX: 신호 없음/이미 보냄');
  if ((await send(env, a.msg)).ok) await env.ALERTS.put('vix_last', a.date);
}

async function priceJob(env, now) {
  const targets = JSON.parse((await env.ALERTS.get('targets')) || '[]');
  if (targets.length) {
    const fired = new Set(JSON.parse((await env.ALERTS.get('fired')) || '[]'));
    const hits = await checkTargets(targets, fired, now, (m, s) => fetchPx(m, s, now));
    for (const h of hits) if ((await send(env, h.msg)).ok) fired.add(h.id);
    if (hits.length) await env.ALERTS.put('fired', JSON.stringify([...fired]));
  }
  await moveJob(env, now);
}

/** 감시 종목(SVIX·SOXL)의 전일 대비 등락률 — 하루 한 번씩 10% 단계를 새로 넘거나 방향이 바뀔 때만(피로도 때문에 5% 가 아니다). */
async function moveJob(env, now) {
  if (!marketOpen('US', now)) return;
  await vixLevelJob(env, now);
  const quotes = [];
  for (const symbol of WATCH_US) { const q = await quote('US', symbol, now); if (q) quotes.push({ symbol, ...q }); }
  if (!quotes.length) return;
  const old = JSON.parse((await env.ALERTS.get('move_state')) || 'null');
  const { alerts, state } = checkMoves(quotes, old, etDate(now));
  if (!alerts.length) return;
  let sentAny = false;
  for (const a of alerts) sentAny = (await send(env, a)).ok || sentAny;
  if (sentAny) await env.ALERTS.put('move_state', JSON.stringify(state));     // 하나도 못 보냈으면 도장을 안 찍어 다음 회차에 다시 시도
}

/** 장중 VIX 가 20·25·30·35… 단계에 닿으면 참고 알림(하루 한 번씩, 전일 종가의 단계보다 높을 때만). 매매 신호가 아니다. */
async function vixLevelJob(env, now) {
  const q = await quote('US', '^VIX', now);
  if (!q) return;
  const old = JSON.parse((await env.ALERTS.get('vix_level')) || 'null');
  const { msg, state } = checkVixLevel(q.px, q.prev, old, etDate(now));
  if (msg && !(await send(env, msg)).ok) return;          // 못 보냈으면 도장을 안 찍어 다음 회차에 다시
  if (JSON.stringify(state) !== JSON.stringify(old)) await env.ALERTS.put('vix_level', JSON.stringify(state));
}

/** 마감 요약 한 통(텔레그램만). 오늘 봉이 하나도 없으면(휴장) 보내지 않는다. */
async function digestJob(env, now, market) {
  const dateLabel = market === 'US' ? etDate(now).slice(5) : new Date(now.getTime() + 9 * 3600e3).toISOString().slice(5, 10);   // MM-DD(미국 ET · 국내 KST)
  const list = market === 'KR' ? KR_INDEX : [...US_INDEX, ...WATCH_US.map((s) => [s, s])];
  const rows = [];
  for (const [sym, label] of list) {
    const q = await quote(market, sym, now, market === 'US' ? 6 * 3600 : 1800);   // 미국: 마감 뒤에도 같은 날 체결이면 인정
    if (q) rows.push({ label, ...q });
  }
  if (!rows.length) return console.log('요약: 시세 없음(휴장?)', market);
  await send(env, digestMessage(market === 'KR' ? '마감 요약 국내' : '마감 요약 미국', dateLabel, rows), { kakao: false });
}

// ---------- 손절선 이탈 감시 · 엔진 멈춤 (설계 docs/control/손절알림-설계-2026-11-15.md) — 알림만, 주문 없음 ----------
const BASE = 'https://stock-alerts.wonithink.workers.dev';
const kvJson = async (env, k, d) => JSON.parse((await env.ALERTS.get(k)) || JSON.stringify(d));
const kstClock = (now) => new Date(now.getTime() + 9 * 3600e3).toISOString().slice(11, 16) + ' KST';
async function hmacHex(env, msg) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(S(env, 'ADMIN_KEY')), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return [...new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(msg)))].map((b) => b.toString(16).padStart(2, '0')).join('');
}
const ackLink = async (env, id, breachAt) => `${BASE}/ack?id=${encodeURIComponent(id)}&b=${breachAt}&s=${await hmacHex(env, `${id}|${breachAt}`)}`;

/** 매분: 감시 중인 손절선의 시세를 보고 이탈이면 매매·보안방에 알린다(처음 10분 매분, 이후 5분마다, 확인하면 멈춤). 한 분의 알림은 한 통으로 묶는다(외부 요청 50건 한도 보호). */
async function stopsJob(env, now) {
  const stops = (await kvJson(env, 'stops', [])).slice(0, MAX_STOPS);
  if (!stops.length) return;
  const nowMs = now.getTime(), prices = {};
  await Promise.all(stops.filter((s) => marketOpen(s.market, now)).map(async (s) => {
    const q = await quote(s.market, s.symbol, now, 900);               // 미국은 마지막 체결이 15분 안이어야(낡은 값으로 오경보 방지)
    if (q) prices[stopId(s)] = { px: q.px, t: q.t };
  }));
  const r = evalStops(stops, prices, await kvJson(env, 'stops_breach', {}), await kvJson(env, 'stops_ack', {}), nowMs);
  if (r.alerts.length) {
    let text = `[손절 감시] ${kstClock(now)}\n` + r.alerts.map(stopLine).join('\n');
    const needAck = r.alerts.filter((a) => a.kind !== 'recover');
    if (needAck.length) { text += '\n확인(알림 멈춤):'; for (const a of needAck) text += `\n${a.s.symbol} ${await ackLink(env, a.id, a.breachAt)}`; }
    const first = r.alerts.some((a) => a.kind === 'break' || a.kind === 'recover');       // 카카오(보조)는 처음·회복만 — 매분 보내지 않는다
    if (!(await send(env, text, { chat: 'trade', kakao: first })).ok) return console.log('손절 알림 전송 실패 — 상태 저장 안 함(다음 분에 다시)');
  }
  if (r.changed) { await env.ALERTS.put('stops_breach', JSON.stringify(r.breach)); await env.ALERTS.put('stops_ack', JSON.stringify(r.ack)); }
}

/** 매분: 감시 목록이 있는데 엔진 하트비트가 20분 넘게 없으면 알린다(30분마다 반복, 복귀하면 한 번). 목록이 비면 조용. */
async function deadmanJob(env, now) {
  const stops = await kvJson(env, 'stops', []), hb = await kvJson(env, 'hb', null), dm = await kvJson(env, 'dm', null);
  if (!stops.length && !(dm && dm.active)) return;
  const r = deadmanDue(stops.length, hb && hb.t, now.getTime(), dm);
  if (r.send) {
    const text = r.kind === 'down'
      ? `[엔진 멈춤] 하트비트가 ${hb && hb.t ? Math.round((now.getTime() - hb.t) / 60000) + '분째' : '아직'} 없습니다.\n감시 중인 손절선 ${stops.length}개는 이 서비스가 계속 지켜보지만, 엔진이 멈춰 손절선·주문이 갱신되지 않습니다.`
      : '[엔진 복귀] 하트비트가 다시 옵니다.';
    if (!(await send(env, text, { chat: 'trade', kakao: r.kind === 'down' && !(dm && dm.active) })).ok) return;
  }
  if (JSON.stringify(r.dm) !== JSON.stringify(dm)) await env.ALERTS.put('dm', JSON.stringify(r.dm));
}

/** 크론 1개(매분)가 손절 감시·엔진 멈춤을 돌리고, 5분마다 기존 가격 목표·등락률 작업도 돌린다. */
async function minuteJob(env, now) {
  const jobs = [['손절', stopsJob], ['엔진멈춤', deadmanJob]];
  if (now.getUTCMinutes() % 5 === 0) jobs.push(['가격', priceJob]);
  const rs = await Promise.allSettled(jobs.map(([, f]) => f(env, now)));
  rs.forEach((x, i) => { if (x.status === 'rejected') console.log(jobs[i][0], '작업 실패', String(x.reason)); });
}

// ---------- 확인(ack) 페이지: GET 은 확인 버튼만 보여 주고 POST 가 실제로 멈춘다(텔레그램 링크 미리보기가 GET 으로 먼저 열어도 멈추지 않게) ----------
const esc = (x) => String(x).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const page = (body) => new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>손절 알림 확인</title><body style="font:18px system-ui;padding:24px;max-width:480px;margin:auto">${body}`, { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
const sameHex = (a, b) => a.length === b.length && [...a].reduce((d, c, i) => d | (c.charCodeAt(0) ^ b.charCodeAt(i)), 0) === 0;

async function ackHandler(request, env, url) {
  if (!S(env, 'ADMIN_KEY')) return new Response('Not Found', { status: 404 });
  const q = request.method === 'POST' ? new URLSearchParams(await request.text()) : url.searchParams;
  const id = q.get('id') || '', b = q.get('b') || '', s = q.get('s') || '';
  if (!id || !b || !sameHex(s, await hmacHex(env, `${id}|${b}`))) return page('<p>링크가 올바르지 않습니다.</p>');
  const breach = await kvJson(env, 'stops_breach', {});
  if (String(breach[id]) !== b) return page('<p>이미 끝난 알림입니다(회복했거나 새로 이탈했습니다).</p>');
  if (request.method === 'GET') return page(`<p><b>${esc(id)}</b><br>손절선 이탈 알림을 멈출까요?</p><form method="post" action="/ack"><input type="hidden" name="id" value="${esc(id)}"><input type="hidden" name="b" value="${esc(b)}"><input type="hidden" name="s" value="${esc(s)}"><button style="font-size:20px;padding:12px 24px">확인 — 알림 멈춤</button></form>`);
  const ack = await kvJson(env, 'stops_ack', {}); ack[id] = Date.now();
  await env.ALERTS.put('stops_ack', JSON.stringify(ack));
  return page('<p>확인했습니다. 이 이탈에 대한 알림을 멈춥니다. 가격이 회복되면 알려 드립니다.</p>');
}

// ---------- 관리용 HTTP(Bearer ADMIN_KEY) ----------
async function admin(request, env) {
  const url = new URL(request.url);
  if (url.pathname === '/ack' && ['GET', 'POST'].includes(request.method)) return ackHandler(request, env, url);   // 서명 링크로 인증(Bearer 아님)
  const auth = request.headers.get('Authorization') || '';
  if (!S(env, 'ADMIN_KEY') || auth !== `Bearer ${S(env, 'ADMIN_KEY')}`) return new Response('Not Found', { status: 404 });   // 존재를 숨긴다
  const { pathname } = url, json = (o) => Response.json(o);
  if (pathname === '/stops' && request.method === 'GET') {
    return json({ stops: await kvJson(env, 'stops', []), breach: await kvJson(env, 'stops_breach', {}), ack: await kvJson(env, 'stops_ack', {}), hb: await kvJson(env, 'hb', null), dm: await kvJson(env, 'dm', null) });
  }
  if (pathname === '/stops' && request.method === 'PUT') {          // ?src=engine|manual — 그 출처의 항목만 통째로 바꾼다
    const src = url.searchParams.get('src');
    if (!['engine', 'manual'].includes(src)) return new Response('src=engine|manual 필요', { status: 400 });
    const list = await request.json();
    for (const t of list) if (!['KR', 'US'].includes(t.market) || !t.symbol || !(t.stop > 0) || (t.dir && !['above', 'below'].includes(t.dir))) return new Response('형식 오류', { status: 400 });
    const merged = [...(await kvJson(env, 'stops', [])).filter((x) => x.src !== src), ...list.map((x) => ({ ...x, src }))];
    if (merged.length > MAX_STOPS) return new Response(`최대 ${MAX_STOPS}개`, { status: 400 });
    await env.ALERTS.put('stops', JSON.stringify(merged));
    return json({ ok: true, count: merged.length });
  }
  if (pathname === '/hb' && request.method === 'POST') { await env.ALERTS.put('hb', JSON.stringify({ t: Date.now() })); return json({ ok: true }); }
  if (pathname === '/targets' && request.method === 'GET') {
    const fired = new Set(JSON.parse((await env.ALERTS.get('fired')) || '[]'));
    return json(JSON.parse((await env.ALERTS.get('targets')) || '[]').map((t) => ({ ...t, fired: fired.has(tid(t)) })));
  }
  if (pathname === '/targets' && request.method === 'PUT') {
    const list = await request.json();
    for (const t of list) if (!['KR', 'US'].includes(t.market) || !['above', 'below'].includes(t.dir) || !(t.price > 0) || !t.symbol) return new Response('형식 오류', { status: 400 });
    await env.ALERTS.put('targets', JSON.stringify(list));
    return json({ ok: true, count: list.length });
  }
  if (pathname === '/rearm' && request.method === 'POST') { await env.ALERTS.put('fired', '[]'); return json({ ok: true }); }
  if (pathname === '/test' && request.method === 'POST') return json(await send(env, '[테스트] Cloudflare Workers 알림 연결 확인', url.searchParams.get('chat') === 'trade' ? { chat: 'trade', kakao: false } : {}));   // ?chat=trade 면 매매·보안방
  return new Response('Not Found', { status: 404 });
}

export default {
  async scheduled(event, env, ctx) {
    const now = new Date(event.scheduledTime);
    const job = { [VIX_CRON]: () => vixJob(env, now), [KR_DIGEST_CRON]: () => digestJob(env, now, 'KR'), [US_DIGEST_CRON]: () => digestJob(env, now, 'US'), [MIN_CRON]: () => minuteJob(env, now) }[event.cron];
    ctx.waitUntil(job ? job() : priceJob(env, now));
  },
  fetch: admin,
};
