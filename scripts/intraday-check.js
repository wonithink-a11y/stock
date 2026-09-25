/**
 * intraday-check.js
 *
 * 장중 급등락 감시. 2026-09-25 부터 **VM systemd 타이머**(deploy/intraday-alert.*)가 10분마다 돌린다.
 *
 * ★ 실측(2026-09-11·09-25): GitHub Actions cron 은 공개 저장소의 고빈도 schedule 을 흘려서
 *   하루 5회 안팎만 돌았다 - 그래서 VM 으로 옮겼다. 규칙은 여전히 실제 간격을 확인한다
 *   (아래 suddenMaxGapMinutes) - VM 이 멈췄다 살아나도 긴 간격을 '급변동'으로 읽지 않는다.
 *
 * 동작:
 *  1. 현재 UTC 시각으로 열려 있는 시장(KR 09:00~15:30 KST / US 09:30~16:00 ET) 판별
 *  2. 열린 시장의 관심종목 현재가 조회 (KR: 네이버 fchart / US: Yahoo spark 20종목 일괄)
 *     ★ 시세 날짜가 그 시장의 '오늘'이 아니면 건너뛴다 - 휴장일엔 직전 거래일 봉이 그대로
 *       와서(교훈81) 지난 등락을 90분마다 다시 알린다
 *  3. 감지 규칙 통과 시 텔레그램/슬랙 알림
 *     - dailyMove: 전일 종가 대비 ±5% 이상
 *     - suddenMove: 직전 체크 대비 ±3% 이상. ★ 직전 체크가 suddenMaxGapMinutes
 *       보다 오래됐으면 **판정하지 않는다** - 그 간격은 '급변동'이 아니다(교훈57)
 *  4. 같은 종목·같은 규칙 재알림은 쿨다운(기본 90분)으로 제한
 *     ★ 쿨다운 도장은 **전송 성공 뒤에만** 찍는다. 안 그러면 배달 안 된 알림이
 *       쿨다운을 먹고, 다음 기회까지 조용해진다
 *
 * 상태 파일: INTRADAY_STATE_PATH (VM: ~/collector-venv/intraday/state.json).
 *   없으면 docs/data/intraday-state.json (옛 Actions 경로, 수동 실행용)
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const STATE_PATH = process.env.INTRADAY_STATE_PATH || path.join(ROOT, 'docs', 'data', 'intraday-state.json');

const RULES = {
  dailyMovePct: 5.0, // 전일 종가 대비
  suddenMovePct: 3.0, // 직전 체크 대비
  cooldownMinutes: 90,

  // ★ 이 둘은 2026-09-11 실측으로 들어왔다. cron '*/10' 은 한국장 창에서 하루 42회
  //   기대인데 GitHub 이 고빈도 schedule 을 흘려서 **실측 하루 1회**다
  //   (docs/operations/shares-snapshot-timeout-2026-09.md 와 같은 날 감사).
  //   그래서 '직전 체크'가 10분 전이 아니라 **약 24시간 전**이었고:
  //     - 24시간 변화에 3% 임계를 걸면 353종목 중 269종목이 걸린다(실측)
  //     - 한 메시지에 133줄이 실려 텔레그램이 HTTP 400 으로 거부했다(실측)
  //     - 즉 이 알림은 **한 번도 배달되지 않은 채** 워크플로는 초록이었다
  //   cron 으로는 못 고친다. 그러니 **잴 수 있는 것만 판정한다**(교훈57).
  suddenMaxGapMinutes: 30, // 직전 체크가 이보다 오래됐으면 suddenMove 를 건너뛴다
  maxAlertsPerMessage: 40, // 텔레그램 4096자 제한. 넘으면 잘라내고 몇 건 생략했는지 밝힌다
};

const UA = { 'User-Agent': 'Mozilla/5.0 (compatible; stock-scoring-app)' };

async function fetchText(url) {
  const res = await fetch(url, { headers: UA });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return res.text();
}

// ---------- 장 시간 판별 (UTC 기준) ----------

function marketsOpenNow(now = new Date()) {
  const day = now.getUTCDay(); // 0=일, 6=토
  if (day === 0 || day === 6) return [];
  const mins = now.getUTCHours() * 60 + now.getUTCMinutes();
  const open = [];
  // KR: 09:00~15:30 KST = 00:00~06:30 UTC (여유 10분 포함)
  if (mins >= 0 && mins <= 6 * 60 + 40) open.push('KR');
  // US: 09:30~16:00 ET = 13:30~20:00 UTC(서머타임) / 14:30~21:00 UTC(표준시) - 둘 다 커버
  if (mins >= 13 * 60 + 20 && mins <= 21 * 60 + 10) open.push('US');
  return open;
}

// ---------- 현재가 조회 ----------

/** 그 시장 시간대의 오늘 날짜 'YYYYMMDD'. 시세 날짜와 대조해 휴장일의 직전 봉을 거른다. */
function localYmd(now, timeZone) {
  return new Date(now).toLocaleDateString('en-CA', { timeZone }).replace(/-/g, '');
}
const MARKET_TZ = { KR: 'Asia/Seoul', US: 'America/New_York' };

async function fetchQuoteKR(code) {
  // fchart 일봉 최근 3개: 마지막 캔들은 장중 현재가로 갱신됨. data="YYYYMMDD|시|고|저|종|량"
  const url = `https://fchart.stock.naver.com/sise.nhn?symbol=${code}&timeframe=day&count=3&requestType=0`;
  const xml = await fetchText(url);
  const rows = [...xml.matchAll(/<item data="([^"]+)"\s*\/>/g)].map((m) => m[1].split('|'));
  if (rows.length < 2) throw new Error(`시세 파싱 실패: ${code}`);
  const last = rows[rows.length - 1];
  const prev = rows[rows.length - 2];
  return { price: Number(last[4]), prevClose: Number(prev[4]), date: last[0] };
}

/**
 * Yahoo spark 로 US 종목을 20개씩 묶어 조회한다(한도 20, 실측). range=1d 의 chartPreviousClose 가 전일 종가다.
 * stooq 는 2026-09 에 전 종목 fetch failed/404 였다 - 미국장 알림이 그동안 한 번도 판정되지 않았다.
 * 반환: Map(code → {price, prevClose, date}). 빠진 종목은 조회 실패로 센다.
 */
async function fetchQuotesUS(codes) {
  const out = new Map();
  for (let i = 0; i < codes.length; i += 20) {
    const batch = codes.slice(i, i + 20);
    try {
      const url = `https://query1.finance.yahoo.com/v7/finance/spark?symbols=${batch.join(',')}&range=1d&interval=1d`;
      const j = JSON.parse(await fetchText(url));
      for (const r of (j.spark && j.spark.result) || []) {
        const m = r.response && r.response[0] && r.response[0].meta;
        if (!m || typeof m.regularMarketPrice !== 'number' || typeof m.chartPreviousClose !== 'number') continue;
        out.set(r.symbol, {
          price: m.regularMarketPrice,
          prevClose: m.chartPreviousClose,
          date: localYmd(m.regularMarketTime * 1000, MARKET_TZ.US),
        });
      }
    } catch (e) {
      console.warn(`  [경고] US 일괄조회 실패(${batch[0]}~): ${e.message}`);
    }
  }
  return out;
}

// ---------- 감지 로직 (순수 함수 - 테스트 가능) ----------

function pct(from, to) {
  return from ? Math.round(((to - from) / from) * 1000) / 10 : null;
}

function detect(ticker, name, market, quote, tickerState, now = Date.now(), rules = RULES) {
  const alerts = [];
  const cooldownMs = rules.cooldownMinutes * 60 * 1000;
  const lastAlertAt = (tickerState && tickerState.lastAlertAt) || {};
  const canAlert = (rule) => !lastAlertAt[rule] || now - lastAlertAt[rule] >= cooldownMs;

  const dailyPct = pct(quote.prevClose, quote.price);
  if (dailyPct !== null && Math.abs(dailyPct) >= rules.dailyMovePct && canAlert('dailyMove')) {
    alerts.push({ rule: 'dailyMove', message: `${name}(${ticker}) 전일 대비 ${dailyPct > 0 ? '+' : ''}${dailyPct}%` });
  }

  // suddenMove 는 **간격을 알 때만** 판정한다. lastCheckAt 이 없으면 간격을 모르는
  // 것이지 0 이 아니다(교훈57) - 모르면 판정하지 않는다.
  const lastCheckAt = tickerState && tickerState.lastCheckAt;
  const gapMin = typeof lastCheckAt === 'number' ? Math.round((now - lastCheckAt) / 60000) : null;
  const gapOk = gapMin !== null && gapMin >= 0 && gapMin <= rules.suddenMaxGapMinutes;
  if (gapOk && tickerState && typeof tickerState.lastPrice === 'number') {
    const suddenPct = pct(tickerState.lastPrice, quote.price);
    if (suddenPct !== null && Math.abs(suddenPct) >= rules.suddenMovePct && canAlert('suddenMove')) {
      alerts.push({ rule: 'suddenMove', message: `${name}(${ticker}) 직전 체크(${gapMin}분 전) 대비 ${suddenPct > 0 ? '+' : ''}${suddenPct}% 급변동` });
    }
  }

  // ★ lastAlertAt 은 여기서 안 찍는다 - 전송 성공 뒤에 stampAlerts() 가 찍는다.
  const newState = { lastPrice: quote.price, lastCheckAt: now, lastAlertAt: { ...lastAlertAt } };
  return { alerts, newState, skippedSudden: !gapOk, gapMin };
}

/** 전송에 성공한 알림에만 쿨다운 도장을 찍는다. 실패하면 상태를 안 건드려 다음 기회에 다시 뜬다. */
function stampAlerts(state, fired, now = Date.now()) {
  for (const { ticker, rule } of fired) {
    const st = state[ticker];
    if (!st) continue;
    st.lastAlertAt = { ...(st.lastAlertAt || {}), [rule]: now };
  }
  return state;
}

/** 메시지를 길이 제한 안으로 자른다. 잘라낸 건수를 숨기지 않는다. */
function buildMessage(lines, max) {
  const shown = lines.slice(0, max);
  const omitted = lines.length - shown.length;
  const tail = omitted > 0 ? `\n… 외 ${omitted}건 생략(총 ${lines.length}건)` : '';
  return `🚨 [장중 급등락 알림]\n${shown.join('\n')}${tail}\n\n※ 자동 감시 결과이며 투자 자문이 아닙니다.`;
}

// ---------- 알림 전송 ----------

async function sendTelegram(text) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return false;
  const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text }),
  });
  if (!res.ok) console.error(`텔레그램 전송 실패: HTTP ${res.status}`);
  return res.ok;
}

async function sendSlack(text) {
  const url = process.env.SLACK_WEBHOOK_URL;
  if (!url) return false;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) console.error(`슬랙 전송 실패: HTTP ${res.status}`);
  return res.ok;
}

/**
 * 알림을 보내고, **보낸 뒤에만** 쿨다운 도장을 찍는다. send(text) -> Promise<boolean>.
 * main 이 한때 객체 배열을 그대로 join 해 '[object Object]' 만 보냈고 도장도 안 찍어 체크마다 같은 알림이 반복됐다(2026-09-22).
 */
async function deliver(state, allAlerts, send, now = Date.now()) {
  const text = buildMessage(allAlerts.map((a) => a.line), RULES.maxAlertsPerMessage);
  console.log(text);
  const sent = await send(text);
  if (sent) stampAlerts(state, allAlerts, now);
  return sent;
}

// ---------- 메인 ----------

async function main() {
  const open = marketsOpenNow();
  if (open.length === 0) {
    console.log('열려 있는 시장이 없습니다 (장외 시간). 종료.');
    return;
  }

  const watchlist = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'watchlist.json'), 'utf-8'));
  const targets = watchlist.tickers.filter((t) => open.includes(t.market || 'KR'));
  console.log(`감시 대상: ${open.join('+')} 시장 ${targets.length}종목`);

  const state = fs.existsSync(STATE_PATH) ? JSON.parse(fs.readFileSync(STATE_PATH, 'utf-8')) : {};
  const allAlerts = [];
  const now = Date.now();
  const usQuotes = open.includes('US')
    ? await fetchQuotesUS(targets.filter((t) => t.market === 'US').map((t) => t.code)) : new Map();
  let failed = 0;
  let stale = 0;

  for (const t of targets) {
    const market = t.market || 'KR';
    try {
      const quote = market === 'US' ? usQuotes.get(t.code) : await fetchQuoteKR(t.code);
      if (!quote) { failed++; continue; }
      if (quote.date !== localYmd(now, MARKET_TZ[market])) { stale++; continue; } // 휴장일·개장 전
      const { alerts, newState } = detect(t.code, t.name, market, quote, state[t.code], now);
      state[t.code] = newState;
      for (const a of alerts) allAlerts.push({ ticker: t.code, rule: a.rule, line: `[${market}] ${a.message}` });
    } catch (e) {
      failed++;
      console.warn(`  [경고] ${t.code} 시세 조회 실패: ${e.message}`);
    }
  }
  console.log(`조회 실패 ${failed} · 오늘 시세 아님(휴장·개장 전) ${stale} / ${targets.length}`);
  // 전부 실패는 소스가 죽은 것이다 - 초록으로 끝내면 stooq 처럼 몇 주를 모른다
  if (targets.length && failed === targets.length) throw new Error(`시세 소스 전멸: ${failed}종목 전부 실패`);

  if (allAlerts.length === 0) {
    console.log('감지된 급등락 없음.');
  } else {
    const sent = await deliver(state, allAlerts, async (text) => {
      const tg = await sendTelegram(text);
      const slack = await sendSlack(text);
      return tg || slack;
    });
    if (!sent) console.log('(전송 실패 또는 알림 채널 미설정 - 쿨다운을 찍지 않았다, 다음 체크에 다시 뜬다)');
  }

  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2), 'utf-8'); // 도장까지 반영한 뒤 저장
}

if (require.main === module) {
  main().catch((e) => {
    console.error('장중 감시 실패:', e);
    process.exit(1);
  });
}

module.exports = { detect, marketsOpenNow, stampAlerts, buildMessage, deliver, localYmd, RULES };
