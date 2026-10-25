/**
 * intraday-check.js 회귀.
 *
 * 왜 이제야 생겼나: detect() 주석이 "순수 함수 - 테스트 가능"이라 적혀 있었는데
 * 실제 테스트는 없었다. 그 사이에 조용한 고장이 자랐다(2026-09-11 실측):
 *
 *   cron '*./10' 이 하루 42회 기대인데 GitHub 이 흘려서 실측 하루 1회
 *   -> '직전 체크'가 10분 전이 아니라 약 24시간 전
 *   -> 24시간 변화에 3% 임계 = 353종목 중 269종목 발화
 *   -> 한 메시지 133줄 -> 텔레그램 HTTP 400 -> **한 번도 배달 안 됨**
 *   -> 그런데 lastAlertAt 은 전송 전에 찍혀서 쿨다운만 소모
 *   -> 실패를 '알림 채널 미설정'으로 오진 (채널은 등록돼 있었다)
 *
 * 아래 검사들은 그 사슬의 각 고리를 하나씩 붙잡는다.
 */
const assert = require('assert');
const { detect, stampAlerts, buildMessage, deliver, localYmd, RULES } = require('./intraday-check.js');

let n = 0;
const ok = (name, fn) => { fn(); n += 1; };

const MIN = 60 * 1000;
const NOW = 1_800_000_000_000;
const q = (price, prevClose) => ({ price, prevClose });

// ── suddenMove 는 간격을 알 때만 판정한다 ──────────────────────────────
ok('간격이 짧으면 suddenMove 가 뜬다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 10 * MIN, lastAlertAt: {} };
  const { alerts } = detect('005930', '삼성전자', 'KR', q(105, 104), st, NOW);
  const rules = alerts.map((a) => a.rule);
  assert(rules.includes('suddenMove'), '10분 전 대비 +5% 는 급변동이다');
  assert(/10분 전/.test(alerts.find((a) => a.rule === 'suddenMove').message),
    '메시지가 실제 경과시간을 밝혀야 한다 - 안 그러면 24시간을 급변동이라 부르게 된다');
});

ok('★ 간격이 길면 suddenMove 를 판정하지 않는다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 24 * 60 * MIN, lastAlertAt: {} };
  const { alerts, skippedSudden } = detect('005930', '삼성전자', 'KR', q(105, 104.9), st, NOW);
  assert.strictEqual(skippedSudden, true, '24시간 간격은 급변동을 잴 수 없다');
  assert(!alerts.some((a) => a.rule === 'suddenMove'),
    '이 한 줄이 269종목 동시 발화를 막는다(교훈57 - 모르면 판정하지 않는다)');
});

ok('lastCheckAt 이 없으면 간격을 모르는 것이지 0 이 아니다', () => {
  const st = { lastPrice: 100, lastAlertAt: {} };          // 옛 상태 파일 모양
  const { alerts, skippedSudden } = detect('005930', '삼성전자', 'KR', q(130, 129), st, NOW);
  assert.strictEqual(skippedSudden, true);
  assert(!alerts.some((a) => a.rule === 'suddenMove'));
});

ok('임계 = 간격 규칙과 무관하게 dailyMove 는 그대로 뜬다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 24 * 60 * MIN, lastAlertAt: {} };
  const { alerts } = detect('005930', '삼성전자', 'KR', q(110, 100), st, NOW);
  assert(alerts.some((a) => a.rule === 'dailyMove'), '전일 종가 대비는 간격과 무관한 규칙이다');
});

// ── 전일 대비는 단계가 새로 넘을 때만(09-28 HLB +27.9% 가 90분마다 반복됐다) ──
const qd = (price, prevClose, date = '20260928') => ({ price, prevClose, date });
const daily = (st, quote) => detect('028300', 'HLB', 'KR', quote, st, NOW).alerts.some((a) => a.rule === 'dailyMove');
ok('★ 같은 날 같은 단계면 다시 안 뜬다(쿨다운이 지나도)', () => {
  assert(!daily({ dailyStep: { day: '20260928', step: 5 } }, qd(127.9, 100)));
});
ok('다음 단계로 더 가면 뜬다 · 방향이 바뀌면 뜬다 · 다음 날이면 뜬다', () => {
  assert(daily({ dailyStep: { day: '20260928', step: 1 } }, qd(110, 100)), '5% → 10%');
  assert(daily({ dailyStep: { day: '20260928', step: 1 } }, qd(94, 100)), '+5% → -6%');
  assert(daily({ dailyStep: { day: '20260927', step: 5 } }, qd(127.9, 100)), '새 날');
  assert(!daily({ dailyStep: { day: '20260928', step: 2 } }, qd(107, 100)), '10% 찍고 7% 로 내려오면 조용');
});
ok('★ 같은 회차에 전일 대비가 뜨면 급변동 줄은 안 붙인다(두 줄 겹침)', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 10 * MIN, lastAlertAt: {} };
  const rules = detect('011070', 'LG이노텍', 'KR', qd(111, 100), st, NOW).alerts.map((a) => a.rule);
  assert.deepStrictEqual(rules, ['dailyMove']);
});
ok('급변동 기준은 5% — 10분에 3~4% 는 안 뜬다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 10 * MIN, lastAlertAt: {} };
  assert(!detect('005930', '삼성전자', 'KR', qd(104, 103), st, NOW).alerts.length);
});
ok('단계 도장은 전송 뒤에 찍힌다', () => {
  const state = { '028300': {} };
  stampAlerts(state, [{ ticker: '028300', rule: 'dailyMove', step: 5, day: '20260928' }], NOW);
  assert.deepStrictEqual(state['028300'].dailyStep, { day: '20260928', step: 5 });
  const { newState } = detect('028300', 'HLB', 'KR', qd(130, 100), {}, NOW);
  assert(!newState.dailyStep, 'detect() 는 단계를 찍지 않는다');
});

// ── 쿨다운 도장은 전송 뒤에 찍힌다 ───────────────────────────────────
ok('★ detect() 는 lastAlertAt 을 찍지 않는다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 5 * MIN, lastAlertAt: {} };
  const { alerts, newState } = detect('005930', '삼성전자', 'KR', q(110, 100), st, NOW);
  assert(alerts.length > 0);
  assert.deepStrictEqual(newState.lastAlertAt, {},
    '여기서 찍으면 배달 안 된 알림이 쿨다운을 먹는다 - 실제로 그랬다');
});

ok('stampAlerts 가 전송 성공 뒤에 찍는다', () => {
  const state = { '005930': { lastPrice: 110, lastCheckAt: NOW, lastAlertAt: {} } };
  stampAlerts(state, [{ ticker: '005930', rule: 'dailyMove' }], NOW);
  assert.strictEqual(state['005930'].lastAlertAt.dailyMove, NOW);
});

ok('모르는 종목에 도장을 찍어도 안 터진다', () => {
  const state = {};
  stampAlerts(state, [{ ticker: '없음', rule: 'dailyMove' }], NOW);
  assert.deepStrictEqual(state, {});
});

// ── 메시지 길이 ────────────────────────────────────────────────────
ok('★ 메시지가 텔레그램 한도 안에 들어온다', () => {
  const lines = Array.from({ length: 353 }, (_, i) => `[KR] 종목${i}(00${i}) 전일 대비 +7.7%`);
  const text = buildMessage(lines, RULES.maxAlertsPerMessage);
  assert(text.length < 4096, `4096자를 넘으면 HTTP 400 이다 (현재 ${text.length}자)`);
  assert(/생략\(총 353건\)/.test(text), '잘라낸 건수를 숨기지 않는다');
});

ok('한도 안이면 생략 문구가 없다', () => {
  const text = buildMessage(['a', 'b'], RULES.maxAlertsPerMessage);
  assert(!/생략/.test(text));
});

ok('★ 시세 날짜 대조는 시장 시간대의 오늘이다(휴장일 직전 봉 거르기)', () => {
  const t = Date.UTC(2026, 8, 25, 14, 30); // 09-25 23:30 KST = 09-25 10:30 ET
  assert.strictEqual(localYmd(t, 'Asia/Seoul'), '20260925');
  assert.strictEqual(localYmd(Date.UTC(2026, 8, 25, 16, 0), 'Asia/Seoul'), '20260926', 'KST 자정 넘김');
  assert.strictEqual(localYmd(Date.UTC(2026, 8, 26, 1, 0), 'America/New_York'), '20260925', '미국은 아직 전날');
});

// ── 전송(main 의 접착부) ──────────────────────────────────────────
const pending = [];
function okAsync(name, fn) { pending.push(fn().then(() => { n++; console.log(`  ok  ${name}`); })); }
okAsync('★ 보내는 문구는 사람이 읽는 줄이다([object Object] 금지)', async () => {
  let got = '';
  const state = { '005930': {} };
  await deliver(state, [{ ticker: '005930', rule: 'dailyMove', line: '[KR] 삼성전자(005930) 전일 대비 +7.7%' }],
    async (t) => { got = t; return true; }, NOW);
  assert(!got.includes('[object Object]') && got.includes('삼성전자(005930) 전일 대비 +7.7%'));
  assert.strictEqual(state['005930'].lastAlertAt.dailyMove, NOW, '보냈으면 쿨다운 도장');
});
okAsync('보내기 실패면 쿨다운 도장을 안 찍는다', async () => {
  const state = { '005930': {} };
  await deliver(state, [{ ticker: '005930', rule: 'dailyMove', line: 'x' }], async () => false, NOW);
  assert(!state['005930'].lastAlertAt);
});

// ── 맥락(유형·뉴스·공시, 2026-10-13) ──────────────────────────────────
const surge = require('../lib/surgeContext.js');
const { addContext } = require('./intraday-check.js');
ok('유형 경계: 갭 70% · 동료 5종목·30%', () => {
  const peers = (k, n) => [...Array(k).fill(3), ...Array(n - k).fill(0)];
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 7 }, [], false).kind, '시초 갭형');
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 6.9 }, [], false).kind, '단독');
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 0 }, peers(3, 10), false).kind, '장중 무리형');
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 0 }, peers(2, 10), false).kind, '단독', '20% 는 무리 아님');
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 0 }, peers(4, 4), false).kind, '단독', '동료 4종목은 판정 안 함');
  assert.strictEqual(surge.classifySurge({ dailyPct: 10, gapPct: 0 }, [], true).kind, '단독+공시');
  assert.strictEqual(surge.classifySurge({ dailyPct: -8, gapPct: -7 }, [], null).kind, '시초 갭형', '하락도 방향만 바꿔');
});
ok('시황 기사는 원인이 아니다', () => {
  assert(surge.isMarketRecap("미래에셋벤처투자·아주IB투자 주가 '휘청'…창업투자주 매물 압박"));
  assert(surge.isMarketRecap('[특징주] 가온전선, 상한가'));
  assert(surge.isMarketRecap('HLB 12% 급등'));
  assert(!surge.isMarketRecap('가온전선, 북미 전력망 1,200억 수주'));
  const r = surge.pickCauseArticle([{ title: '[특징주] 가온전선 급등', at: 2000 }, { title: '가온전선 북미 수주', at: 1500 },
    { title: '다른 회사 수주', at: 1800 }, { title: '가온전선 옛 기사', at: 500 }], 1000, '가온전선');
  assert.strictEqual(r.cause.title, '가온전선 북미 수주');
  assert.strictEqual(r.recap, 1);
  assert.strictEqual(r.total, 2);
});
ok('직전 마감 = 전 평일 15:30 KST', () => {
  const mon1000 = Date.UTC(2026, 9, 12, 1, 0);           // 10-12(월) 10:00 KST
  assert.strictEqual(surge.prevCloseMs(mon1000), Date.UTC(2026, 9, 9, 6, 30), '금요일 15:30');
  const tue0905 = Date.UTC(2026, 9, 13, 0, 5);
  assert.strictEqual(surge.prevCloseMs(tue0905), Date.UTC(2026, 9, 12, 6, 30));
});
ok('★ 맥락 줄이 붙어도 4096자 안(글자 수 상한)', () => {
  const lines = Array.from({ length: 40 }, (_, i) => `[KR] 종목${i}(00${i}) 전일 대비 +7.7%\n   └ 장중 무리형 · ${'가'.repeat(120)}`);
  const text = buildMessage(lines, RULES.maxAlertsPerMessage);
  assert(text.length < 4096, `현재 ${text.length}자`);
  assert(/생략\(총 40건\)/.test(text));
});
const quotes = { A00010: { price: 110, prevClose: 100, open: 101, name: '가온' }, B00020: { price: 95, prevClose: 100, open: 99, name: '나비' } };
const mkAlerts = () => [
  { ticker: 'A00010', market: 'KR', rule: 'dailyMove', pct: 10, line: '[KR] 가온(A00010) 전일 대비 +10%' },
  { ticker: 'B00020', market: 'KR', rule: 'dailyMove', pct: -5, line: '[KR] 나비(B00020) 전일 대비 -5%' },
  { ticker: 'AAPL', market: 'US', rule: 'dailyMove', pct: 6, line: '[US] AAPL' }];
const emptyIndex = { groupsOf: new Map(), members: new Map() };
okAsync('맥락: 뉴스·공시가 붙고 US 는 건드리지 않는다', async () => {
  const al = mkAlerts();
  const state = {};
  await addContext(al, quotes, state, NOW, { index: emptyIndex, news: { byTicker: {}, stale: false },
    search: async () => [{ title: '가온 북미 수주', at: NOW - 60000 }], dart: async (t) => (t === 'A00010' ? ['단일판매ㆍ공급계약체결'] : []) });
  assert(/북미 수주/.test(al[0].ctx) && /공급계약/.test(al[0].ctx), al[0].ctx);
  assert(/공시 없음/.test(al[1].ctx));
  assert(!al[2].ctx, 'US 는 맥락 없음');
  assert(state._ctx.dart.A00010.titles.length === 1, '공시 30분 캐시');
});
okAsync('★ 뉴스·공시 조회가 전부 던져도 알림은 나가고 도장이 찍힌다', async () => {
  const al = mkAlerts();
  const state = { A00010: {}, B00020: {}, AAPL: {} };
  await addContext(al, quotes, state, NOW, { index: emptyIndex, news: { byTicker: null, stale: true },
    search: async () => { throw new Error('naver down'); }, dart: async () => { throw new Error('dart down'); } });
  assert(/뉴스 확인 실패/.test(al[0].ctx) && /공시 확인 실패/.test(al[0].ctx), al[0].ctx);
  let got = '';
  await deliver(state, al, async (t) => { got = t; return true; }, NOW);
  assert(got.includes('가온(A00010)') && got.includes('└'));
  assert.strictEqual(state.A00010.lastAlertAt.dailyMove, NOW);
});
okAsync('DART 키 없음(null) → 공시 확인 안 함, 분류는 공시 모름으로', async () => {
  const al = mkAlerts();
  await addContext(al, quotes, {}, NOW, { index: emptyIndex, news: { byTicker: {}, stale: false }, search: async () => null, dart: async () => null });
  assert(/공시 확인 안 함/.test(al[0].ctx) && /^ {3}└ 뉴스 /.test(al[0].ctx), al[0].ctx);
});

Promise.all(pending).then(() => console.log(`test-intraday-check: ${n}건 통과`))
  .catch((e) => { console.error('FAIL', e.message); process.exit(1); });
