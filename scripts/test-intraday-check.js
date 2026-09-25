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

ok('쿨다운 안이면 안 뜬다', () => {
  const st = { lastPrice: 100, lastCheckAt: NOW - 5 * MIN, lastAlertAt: { dailyMove: NOW - 10 * MIN } };
  const { alerts } = detect('005930', '삼성전자', 'KR', q(110, 100), st, NOW);
  assert(!alerts.some((a) => a.rule === 'dailyMove'));
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

Promise.all(pending).then(() => console.log(`test-intraday-check: ${n}건 통과`))
  .catch((e) => { console.error('FAIL', e.message); process.exit(1); });
