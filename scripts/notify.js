/**
 * notify.js
 *
 * 분석 결과에서 알림 조건을 골라 텔레그램/슬랙으로 전송합니다.
 * 환경변수(GitHub Secrets)가 설정된 채널로만 전송됩니다:
 *  - TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
 *  - SLACK_WEBHOOK_URL
 *
 * 알림 조건:
 *  1. 등급 변동 (직전 실행 대비, 예: C → B)
 *  2. 신규 B등급 이상 진입
 *  3. 경고 플래그 신규 발생
 *  4. 시장 국면이 caution/risk
 */

const fs = require('fs');
const path = require('path');

const OUT_DIR = path.join(__dirname, '..', 'docs', 'data');

function loadJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

function buildMessages() {
  const current = loadJson(path.join(OUT_DIR, 'current-summary.json'), { results: [] });
  const previous = loadJson(path.join(OUT_DIR, 'previous.json'), { results: [] });
  const regime = loadJson(path.join(OUT_DIR, 'regime.json'), null);

  const prevByTicker = Object.fromEntries(previous.results.map((r) => [r.ticker, r]));
  const lines = [];

  for (const r of current.results) {
    const prev = prevByTicker[r.ticker];
    const gradeChar = (g) => (g || '?').charAt(0);

    if (prev && gradeChar(prev.grade) !== gradeChar(r.grade)) {
      lines.push(`등급 변동: ${r.name}(${r.ticker}) ${gradeChar(prev.grade)} → ${gradeChar(r.grade)} (${r.totalScore}점)`);
    } else if (!prev && r.totalScore !== null && r.totalScore >= 65) {
      lines.push(`신규 B등급 이상: ${r.name}(${r.ticker}) ${gradeChar(r.grade)}등급 ${r.totalScore}점`);
    }

    const prevWarnings = new Set(prev ? prev.warnings : []);
    const newWarnings = (r.warnings || []).filter((w) => !prevWarnings.has(w));
    if (newWarnings.length > 0) {
      lines.push(`경고 발생: ${r.name}(${r.ticker}) - ${newWarnings.join(', ')}`);
    }
  }

  if (regime && (regime.grade === 'caution' || regime.grade === 'risk')) {
    lines.unshift(`시장 국면 주의: ${regime.grade} (${regime.score}점) - ${regime.action}`);
  }

  return lines;
}

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

async function main() {
  const lines = buildMessages();
  if (lines.length === 0) {
    console.log('알림 조건에 해당하는 변동이 없습니다.');
    return;
  }
  const text = `[주식 스코어링 알림]\n${lines.join('\n')}\n\n※ 참고 신호이며 투자 자문이 아닙니다.`;
  console.log(text);

  const sentTg = await sendTelegram(text);
  const sentSlack = await sendSlack(text);
  if (!sentTg && !sentSlack) {
    console.log('(알림 채널 미설정 - Secrets에 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 또는 SLACK_WEBHOOK_URL을 등록하세요)');
  }
}

main().catch((e) => {
  console.error('알림 실패:', e);
  process.exit(1);
});
