/**
 * intraday-check.js
 *
 * 장중 급등락 감시 (준실시간, GitHub Actions 10분 간격 실행용).
 * PC 없이 동작하지만 "10분 간격 + Actions 실행 지연 1~3분"의 한계가 있습니다 -
 * 초 단위 실시간이 필요하면 증권사 MTS 앱의 조건 알림을 병행하세요.
 *
 * 동작:
 *  1. 현재 UTC 시각으로 열려 있는 시장(KR 09:00~15:30 KST / US 09:30~16:00 ET) 판별
 *  2. 열린 시장의 관심종목 현재가 조회 (KR: 네이버 fchart / US: stooq 실시간 quote)
 *  3. 감지 규칙 통과 시 텔레그램/슬랙 알림
 *     - dailyMove: 전일 종가 대비 ±5% 이상
 *     - suddenMove: 직전 체크(약 10분 전) 대비 ±3% 이상
 *  4. 같은 종목·같은 규칙 재알림은 쿨다운(기본 90분)으로 제한
 *
 * 상태 파일: docs/data/intraday-state.json (Actions가 커밋해서 실행 간 유지)
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const STATE_PATH = path.join(ROOT, 'docs', 'data', 'intraday-state.json');

const RULES = {
  dailyMovePct: 5.0, // 전일 종가 대비
  suddenMovePct: 3.0, // 직전 체크 대비
  cooldownMinutes: 90,
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

async function fetchQuoteKR(code) {
  // fchart 일봉 최근 3개: 마지막 캔들은 장중 현재가로 갱신됨
  const url = `https://fchart.stock.naver.com/sise.nhn?symbol=${code}&timeframe=day&count=3&requestType=0`;
  const xml = await fetchText(url);
  const rows = [...xml.matchAll(/<item data="([^"]+)"\s*\/>/g)].map((m) => m[1].split('|'));
  if (rows.length < 2) throw new Error(`시세 파싱 실패: ${code}`);
  const last = rows[rows.length - 1];
  const prev = rows[rows.length - 2];
  return { price: Number(last[4]), prevClose: Number(prev[4]) };
}

async function fetchQuoteUS(ticker) {
  // stooq 실시간(지연 가능) quote CSV: Symbol,Date,Time,Open,High,Low,Close,Volume
  const quoteCsv = await fetchText(`https://stooq.com/q/l/?s=${ticker.toLowerCase()}.us&f=sd2t2ohlcv&h&e=csv`);
  const qLine = quoteCsv.trim().split('\n')[1];
  if (!qLine) throw new Error(`quote 파싱 실패: ${ticker}`);
  const qParts = qLine.split(',');
  const price = Number(qParts[6]);
  const quoteDate = qParts[1]; // YYYY-MM-DD

  // 전일 종가: 일봉 CSV의 마지막 행이 오늘이면 그 전 행 사용
  const dailyCsv = await fetchText(`https://stooq.com/q/d/l/?s=${ticker.toLowerCase()}.us&i=d`);
  const dLines = dailyCsv.trim().split('\n');
  const lastRow = dLines[dLines.length - 1].split(',');
  const prevRow = dLines.length >= 3 ? dLines[dLines.length - 2].split(',') : null;
  const prevClose = lastRow[0] === quoteDate && prevRow ? Number(prevRow[4]) : Number(lastRow[4]);

  if (Number.isNaN(price) || Number.isNaN(prevClose)) throw new Error(`시세 값 오류: ${ticker}`);
  return { price, prevClose };
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

  if (tickerState && typeof tickerState.lastPrice === 'number') {
    const suddenPct = pct(tickerState.lastPrice, quote.price);
    if (suddenPct !== null && Math.abs(suddenPct) >= rules.suddenMovePct && canAlert('suddenMove')) {
      alerts.push({ rule: 'suddenMove', message: `${name}(${ticker}) 직전 체크 대비 ${suddenPct > 0 ? '+' : ''}${suddenPct}% 급변동` });
    }
  }

  const newState = { lastPrice: quote.price, lastCheckAt: now, lastAlertAt: { ...lastAlertAt } };
  for (const a of alerts) newState.lastAlertAt[a.rule] = now;
  return { alerts, newState };
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

  for (const t of targets) {
    const market = t.market || 'KR';
    try {
      const quote = market === 'US' ? await fetchQuoteUS(t.code) : await fetchQuoteKR(t.code);
      const { alerts, newState } = detect(t.code, t.name, market, quote, state[t.code]);
      state[t.code] = newState;
      allAlerts.push(...alerts.map((a) => `[${market}] ${a.message}`));
    } catch (e) {
      console.warn(`  [경고] ${t.code} 시세 조회 실패: ${e.message}`);
    }
  }

  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2), 'utf-8');

  if (allAlerts.length === 0) {
    console.log('감지된 급등락 없음.');
    return;
  }

  const text = `🚨 [장중 급등락 알림]\n${allAlerts.join('\n')}\n\n※ 약 10분 간격 체크 기준이며 투자 자문이 아닙니다.`;
  console.log(text);
  const tg = await sendTelegram(text);
  const slack = await sendSlack(text);
  if (!tg && !slack) console.log('(알림 채널 미설정 - Secrets 등록 필요)');
}

if (require.main === module) {
  main().catch((e) => {
    console.error('장중 감시 실패:', e);
    process.exit(1);
  });
}

module.exports = { detect, marketsOpenNow };
