// 손절 감시·엔진 멈춤·확인 링크·관리 HTTP 통합 시험(시세·텔레그램은 가짜 fetch, KV 는 Map).   node cloudflare/alerts/test/worker.mjs
import assert from 'node:assert/strict';
import worker from '../src/index.js';

let n = 0; const t = async (name, f) => { await f(); n++; };
const kv = new Map();
const env = { ALERTS: { get: async (k) => kv.get(k) ?? null, put: async (k, v) => { kv.set(k, v); } }, TELEGRAM_BOT_TOKEN: 'tok', TELEGRAM_CHAT_ID: '111', TELEGRAM_TRADE_CHAT_ID: '222', ADMIN_KEY: 'adminkey' };
let price = 69900, calls = [];
globalThis.fetch = async (url, init) => {
  url = String(url); calls.push({ url, body: init && init.body });
  if (url.includes('api.telegram.org')) return Response.json({ ok: true });
  if (url.includes('fchart.stock.naver.com')) return new Response(`<item data="20261113|1|1|1|70500|100" /><item data="20261116|1|1|1|${price}|100" />`);
  return new Response('', { status: 500 });          // 카카오 등은 실패(보조 채널 — 시험에서는 무시)
};
const sent = () => calls.filter((c) => c.url.includes('api.telegram.org')).map((c) => JSON.parse(c.body));
const MON = (m) => Date.parse('2026-11-16T01:00:00Z') + m * 60000;           // 월요일 10:00 KST + m 분
async function tick(m) { const ps = []; await worker.scheduled({ cron: '* * * * *', scheduledTime: MON(m) }, env, { waitUntil: (p) => ps.push(p) }); await Promise.all(ps); }
const adm = (path, method = 'GET', body) => worker.fetch(new Request('https://x' + path, { method, headers: { Authorization: 'Bearer adminkey' }, body: body && JSON.stringify(body) }), env);

await t('관리 HTTP: 인증 없으면 404, 형식 오류는 400, 정상 저장', async () => {
  assert.equal((await worker.fetch(new Request('https://x/stops'), env)).status, 404);
  assert.equal((await adm('/stops?src=manual', 'PUT', [{ market: 'XX', symbol: 'A', stop: 1 }])).status, 400);
  assert.equal((await adm('/stops', 'PUT', [])).status, 400);                                            // src 필수
  const r = await adm('/stops?src=manual', 'PUT', [{ market: 'KR', symbol: '005930', stop: 70000, name: '삼성전자' }]);
  assert.equal((await r.json()).count, 1);
  await adm('/stops?src=engine', 'PUT', []);                                                            // 다른 출처를 비워도 manual 은 남는다
  assert.equal((await (await adm('/stops')).json()).stops.length, 1);
});

await t('하트비트가 없고 감시 목록이 있으면 엔진 멈춤을 매매방(222)으로 알린다', async () => {
  price = 71000; calls = [];
  await tick(0); const s = sent();
  assert.equal(s.length, 1); assert.equal(s[0].chat_id, '222'); assert.match(s[0].text, /엔진 멈춤/); assert.equal(s[0].disable_web_page_preview, true);
  await adm('/hb', 'POST'); kv.set('hb', JSON.stringify({ t: MON(0.4) }));                            // 이후 하트비트가 온다고 가정(시험은 가짜 시각)
  calls = []; await tick(0.5); const up = sent();                                                       // 하트비트 복귀 → 복귀 알림 한 번
  assert.equal(up.length, 1); assert.match(up[0].text, /엔진 복귀/);
});

await t('손절선 이탈: 처음 알림 + 확인 링크, 다음 분 반복, 같은 분 재실행 없음', async () => {
  calls = []; price = 69900; kv.set('hb', JSON.stringify({ t: MON(1) }));
  await tick(1); let s = sent();
  assert.equal(s.length, 1); assert.equal(s[0].chat_id, '222'); assert.match(s[0].text, /삼성전자\(005930\)/); assert.match(s[0].text, /1번째/); assert.match(s[0].text, /\/ack\?id=KR%3A005930%3A70000&b=/);
  calls = []; kv.set('hb', JSON.stringify({ t: MON(2) })); await tick(2); s = sent();
  assert.equal(s.length, 1); assert.match(s[0].text, /2번째/);
});

await t('확인 링크: GET 은 버튼만(멈추지 않음), POST 가 멈춘다, 잘못된 서명은 거부', async () => {
  const link = [...sent()[0].text.matchAll(/https:\/\/\S+/g)][0][0], u = new URL(link);
  const bad = await worker.fetch(new Request(link.replace(/s=[0-9a-f]+/, 's=00')), env); assert.match(await bad.text(), /올바르지 않습니다/);
  const g = await worker.fetch(new Request(link), env), html = await g.text(); assert.match(html, /<button/); assert.equal(JSON.parse(kv.get('stops_ack') || '{}')['KR:005930:70000'], undefined);
  const form = new URLSearchParams({ id: u.searchParams.get('id'), b: u.searchParams.get('b'), s: u.searchParams.get('s') }).toString();
  const realNow = Date.now; Date.now = () => MON(2.5);                                                  // 시험의 가짜 시각(실제로는 이탈 시각보다 항상 늦다)
  const p = await worker.fetch(new Request('https://x/ack', { method: 'POST', body: form, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }), env);
  Date.now = realNow;
  assert.match(await p.text(), /확인했습니다/); assert.ok(JSON.parse(kv.get('stops_ack'))['KR:005930:70000'] > 0);
  calls = []; kv.set('hb', JSON.stringify({ t: MON(3) })); await tick(3); assert.equal(sent().length, 0);   // 확인 뒤엔 조용
});

await t('회복하면 한 번 알리고 상태를 지운다', async () => {
  calls = []; price = 70500; kv.set('hb', JSON.stringify({ t: MON(4) })); await tick(4); const s = sent();
  assert.equal(s.length, 1); assert.match(s[0].text, /회복/); assert.equal(kv.get('stops_breach'), '{}');
});

await t('하트비트가 20분 넘게 끊기면 다시 알리고, 목록을 비우면 조용해진다', async () => {
  calls = []; await tick(30); let s = sent(); assert.equal(s.length, 1); assert.match(s[0].text, /엔진 멈춤/);
  await adm('/stops?src=manual', 'PUT', []); calls = []; await tick(31); s = sent();
  assert.ok(s.every((x) => /엔진 복귀/.test(x.text) === false || true));                                 // 목록이 비면 복귀 알림도 없다
  assert.equal(s.length, 0);
});

await t('매매방 번호가 없으면 기본 방으로 폴백', async () => {
  delete env.TELEGRAM_TRADE_CHAT_ID; calls = [];
  await worker.fetch(new Request('https://x/test?chat=trade', { method: 'POST', headers: { Authorization: 'Bearer adminkey' } }), env);
  assert.equal(sent()[0].chat_id, '111');
});

console.log(`OK ${n}/${n}`);
