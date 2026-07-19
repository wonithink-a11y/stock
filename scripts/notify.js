/**
 * notify.js (v2 - 종목 수와 무관하게 길이가 수렴하는 알림)
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
 *
 * ── v1 → v2 변경점 ──────────────────────────────────────────────
 * 배경: 관심종목이 20 → 108로 늘면서 텔레그램 4096자 제한을 넘길 수 있게 됐습니다.
 *      v1도 '전체 목록'이 아니라 '변동분'만 보냈지만, 아래 세 상황에서 터집니다.
 *        (a) 유니버스 확대 직후 — 신규 88종목이 전부 '신규 진입'으로 잡힘
 *        (b) 급락장 — 108종목 중 30~40개가 동시에 과매도에 걸림
 *        (c) 업종 기준 도입 — sectorAdjusted 등이 51종목에 한꺼번에 발생
 *
 * 해결 방향: 글자수로 잘라내는 게 아니라 '보낼 것'을 줄입니다.
 *      글자수 상한만 두면 무엇이 잘릴지 통제되지 않습니다. 그래서
 *        1) 상시 속성 플래그는 알림에서 제외 (매일 뜨는 상태값이지 사건이 아님)
 *        2) 개수에 비례해 길어지는 부분은 상한 + '외 N건'으로 접음
 *        3) 유니버스가 바뀐 날은 개별 알림 대신 요약 한 줄로 대체
 *        4) 하드 리밋은 마지막 안전장치로만 사용 (우선순위 낮은 것부터 잘림)
 *      결과적으로 종목이 몇 개든 400~900자로 수렴합니다.
 */

const fs = require('fs');
const path = require('path');

const OUT_DIR = path.join(__dirname, '..', 'docs', 'data');

// 텔레그램 메시지 상한은 4096자입니다. JS의 String.length가 텔레그램이 세는 단위와
// 같으므로(둘 다 UTF-16 코드 유닛) 한글도 1자로 계산됩니다. 여유를 두고 3900.
const HARD_LIMIT = Number(process.env.NOTIFY_MAX_CHARS || 3900);

// 종목명을 나열할 최대 개수 (초과분은 '외 N건')
const MAX_GRADE_CHANGES = Number(process.env.NOTIFY_MAX_GRADE || 15);
const MAX_NEW_ENTRIES = Number(process.env.NOTIFY_MAX_NEW || 10);
const MAX_EVENT_WARN = Number(process.env.NOTIFY_MAX_EVENT || 10);
const MAX_TECH_WARN = Number(process.env.NOTIFY_MAX_TECH || 5);

const DASHBOARD_URL = process.env.DASHBOARD_URL || 'https://wonithink-a11y.github.io/stock/';

/**
 * 경고 분류
 *  event  : 그날 실제로 일어난 사건. 항상 종목명을 보여준다.
 *  tech   : RSI 구간 진입. 사건이라기보단 상태에 가깝고 급락장에 무더기로 발생하므로 상한을 둔다.
 *  config : 설정을 고쳐야 해소되는 것. 매일 반복되므로 개수만 보고한다.
 *  static : 종목의 고정 속성(업종 기준으로 채점됨 등). 알림 대상이 아니다.
 */
const WARNING_CLASS = {
  deadCatBounce: 'event',
  debtRatioAbove200: 'event',
  consecutiveOperatingLoss: 'event',
  auditOpinionNonStandard: 'event',
  majorShareholderSelloff: 'event',
  oversold: 'tech',
  extremeOverbought: 'tech',
  unmappedSector: 'config',
  sectorAdjusted: 'static',
  lowSectorConfidence: 'static',
};

const WARNING_LABEL = {
  deadCatBounce: '데드캣바운스',
  debtRatioAbove200: '부채비율 초과',
  consecutiveOperatingLoss: '연속 영업적자',
  auditOpinionNonStandard: '감사의견 비적정',
  majorShareholderSelloff: '대주주 매각',
  oversold: '과매도',
  extremeOverbought: '극단 과매수',
  unmappedSector: '업종 미분류',
};

function loadJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (e) {
    console.warn(`[경고] ${path.basename(p)} 파싱 실패: ${e.message}`);
    return fallback;
  }
}

const gradeChar = (g) => (g || '?').charAt(0);

/** 종목 뒤에 붙는 업종 꼬리표. general이면 아무것도 붙이지 않는다. */
function sectorTag(r) {
  if (!r.sectorLabel) return '';
  const low = r.sectorConfidence === 'low' ? '·저신뢰' : '';
  // 라벨의 괄호 설명은 길어서 제거 ('금융업 (은행·보험·증권)' → '금융업')
  const short = String(r.sectorLabel).replace(/\s*\(.*$/, '');
  return ` [${short}${low}]`;
}

/** n건 중 앞 max개만 이름을 쓰고 나머지는 '외 N건' */
function joinCapped(names, max) {
  if (names.length <= max) return names.join(', ');
  return `${names.slice(0, max).join(', ')} 외 ${names.length - max}건`;
}

function buildSections() {
  const current = loadJson(path.join(OUT_DIR, 'current-summary.json'), { results: [] });
  const previous = loadJson(path.join(OUT_DIR, 'previous.json'), { results: [] });
  const regime = loadJson(path.join(OUT_DIR, 'regime.json'), null);

  const prevByTicker = Object.fromEntries((previous.results || []).map((r) => [r.ticker, r]));
  const hasPrev = (previous.results || []).length > 0;

  // 유니버스가 바뀐 날인지 판정.
  // 바뀐 날은 '신규 진입'이 수십 건 쏟아지는데 그건 시장 신호가 아니라 설정 변경의 결과다.
  const universeChanged =
    hasPrev &&
    previous.universeVersion !== undefined &&
    current.universeVersion !== undefined &&
    previous.universeVersion !== current.universeVersion;

  const head = [];
  const gradeChanges = [];
  const newEntries = [];
  const eventWarnings = []; // { label, name }
  const techWarnings = {}; // label → [name]
  let configCount = 0;

  // 1) 시장 국면 (가장 위, 절대 잘리지 않음)
  if (regime && (regime.grade === 'caution' || regime.grade === 'risk')) {
    head.push(`⚠ 시장 국면 ${regime.grade} (${regime.score}점) — ${regime.action}`);
  }

  for (const r of current.results) {
    const prev = prevByTicker[r.ticker];

    if (prev && gradeChar(prev.grade) !== gradeChar(r.grade)) {
      const from = gradeChar(prev.grade);
      const to = gradeChar(r.grade);
      // 등급이 좋아졌는지 나빠졌는지를 화살표로 (A가 가장 좋으므로 문자 비교는 반대)
      const arrow = to < from ? '↑' : '↓';
      gradeChanges.push(`${arrow} ${r.name} ${from}→${to} ${r.totalScore}${sectorTag(r)}`);
    } else if (!prev && r.totalScore !== null && r.totalScore >= 65) {
      newEntries.push(`${r.name} ${gradeChar(r.grade)} ${r.totalScore}${sectorTag(r)}`);
    }

    const prevWarnings = new Set(prev ? prev.warnings || [] : []);
    for (const w of r.warnings || []) {
      if (prevWarnings.has(w)) continue; // 신규 발생만
      const cls = WARNING_CLASS[w] || 'event';
      if (cls === 'static') continue; // 상시 속성은 알림 대상 아님
      if (cls === 'config') { configCount++; continue; }
      if (cls === 'tech') {
        const label = WARNING_LABEL[w] || w;
        (techWarnings[label] = techWarnings[label] || []).push(r.name);
      } else {
        eventWarnings.push({ label: WARNING_LABEL[w] || w, name: r.name });
      }
    }
  }

  // 유니버스 변경일: 개별 신규 진입 알림을 요약 한 줄로 대체
  if (universeChanged) {
    const before = previous.universeSize ?? (previous.results || []).length;
    const after = current.universeSize ?? current.results.length;
    head.push(
      `📋 유니버스 변경: ${previous.universeVersion} → ${current.universeVersion} ` +
      `(${before} → ${after}종목, 신규 ${newEntries.length}건)`
    );
    head.push('   신규 종목 개별 알림은 생략합니다. 다음 실행부터 정상 비교됩니다.');
    newEntries.length = 0;
    // 업종 기준이 처음 적용되는 날이라 경고도 무더기로 뜬다 → 집계만
    if (eventWarnings.length + Object.keys(techWarnings).length > 0) {
      head.push(`   (경고 ${eventWarnings.length + Object.values(techWarnings).reduce((a, b) => a + b.length, 0)}건도 첫 산출이라 생략)`);
      eventWarnings.length = 0;
      for (const k of Object.keys(techWarnings)) delete techWarnings[k];
    }
  }

  // 섹션 조립 (우선순위 순 — 뒤쪽일수록 먼저 잘림)
  const sections = [];

  if (gradeChanges.length) {
    const shown = gradeChanges.slice(0, MAX_GRADE_CHANGES);
    const rest = gradeChanges.length - shown.length;
    sections.push({
      priority: 1,
      text: `■ 등급 변동 ${gradeChanges.length}\n` + shown.map((s) => ' ' + s).join('\n') +
        (rest > 0 ? `\n 외 ${rest}건` : ''),
    });
  }

  if (newEntries.length) {
    const shown = newEntries.slice(0, MAX_NEW_ENTRIES);
    const rest = newEntries.length - shown.length;
    sections.push({
      priority: 2,
      text: `■ 신규 B↑ ${newEntries.length}\n` + shown.map((s) => ' ' + s).join('\n') +
        (rest > 0 ? `\n 외 ${rest}건` : ''),
    });
  }

  if (eventWarnings.length) {
    const byLabel = {};
    for (const e of eventWarnings) (byLabel[e.label] = byLabel[e.label] || []).push(e.name);
    const body = Object.entries(byLabel)
      .map(([label, names]) => ` ${label} ${names.length}: ${joinCapped(names, MAX_EVENT_WARN)}`)
      .join('\n');
    sections.push({ priority: 3, text: `■ 경고 ${eventWarnings.length}\n${body}` });
  }

  const techTotal = Object.values(techWarnings).reduce((a, b) => a + b.length, 0);
  if (techTotal) {
    const body = Object.entries(techWarnings)
      .map(([label, names]) => ` ${label} ${names.length}: ${joinCapped(names, MAX_TECH_WARN)}`)
      .join('\n');
    sections.push({ priority: 4, text: `■ 기술적 신호 ${techTotal}\n${body}` });
  }

  if (configCount > 0) {
    sections.push({
      priority: 5,
      text: `■ 설정 확인: 업종 미분류 ${configCount}종목 — config/sector-map.json`,
    });
  }

  return { head, sections, universeChanged };
}

/** 우선순위가 낮은 섹션부터 버리면서 상한에 맞춘다 */
function assemble(head, sections, dateStr) {
  const title = `[주식 스코어링] ${dateStr}`;
  const footer = `\n▸ 상세: ${DASHBOARD_URL}\n※ 참고 신호이며 투자 자문이 아닙니다.`;
  const headText = head.length ? head.join('\n') + '\n' : '';

  const ordered = [...sections].sort((a, b) => a.priority - b.priority);
  const kept = [];

  // 우선순위 순으로 담다가 '처음 안 들어가는 것'에서 멈춘다.
  // 건너뛰고 다음 섹션을 담으면, 큰 고우선순위 섹션(등급 변동)이 빠지고
  // 작은 저우선순위 섹션(설정 확인)만 남는 역전이 생긴다.
  let dropped = 0;
  for (let i = 0; i < ordered.length; i++) {
    const note = ordered.length - kept.length - 1 > 0 ? `\n\n(길이 제한으로 ${ordered.length - kept.length - 1}개 항목 생략)` : '';
    const candidate = `${title}\n${headText}${kept.concat(ordered[i].text).join('\n\n')}${note}${footer}`;
    if (candidate.length <= HARD_LIMIT) {
      kept.push(ordered[i].text);
    } else {
      dropped = ordered.length - kept.length;
      break;
    }
  }

  // 한 섹션도 못 담을 만큼 상한이 빡빡하면 빈 알림이 되어버린다.
  // 그럴 때는 각 섹션의 머리글(예: '■ 등급 변동 25')만 모아 요약으로 대체한다.
  // 기본 상한(3900)에서는 도달하지 않는 경로이며, 상한을 낮게 조정했을 때의 안전망이다.
  if (kept.length === 0 && ordered.length > 0) {
    const digest = ordered.map((s) => s.text.split('\n')[0].replace(/^■\s*/, '')).join(' · ');
    return `${title}\n${headText}${digest}\n(항목이 많아 요약만 표시)${footer}`.slice(0, HARD_LIMIT);
  }

  const body = headText + kept.join('\n\n');
  let text = `${title}\n${body}` + (dropped > 0 ? `\n\n(길이 제한으로 ${dropped}개 항목 생략)` : '') + footer;

  // 최후의 안전장치: 그래도 넘치면 문자 단위로 자른다.
  // (서로게이트 페어를 반으로 자르지 않도록 마지막 문자를 확인)
  if (text.length > HARD_LIMIT) {
    let cut = HARD_LIMIT - footer.length - 20;
    const code = text.charCodeAt(cut - 1);
    if (code >= 0xd800 && code <= 0xdbff) cut -= 1; // 상위 서로게이트로 끝나면 한 칸 당김
    text = text.slice(0, cut) + '\n…(생략)' + footer;
  }
  return text;
}

async function sendTelegram(text) {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  const chatId = process.env.TELEGRAM_CHAT_ID;
  if (!token || !chatId) return false;
  const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
  });
  if (!res.ok) {
    let detail = '';
    try { detail = JSON.stringify(await res.json()); } catch (e) { /* 본문 없으면 무시 */ }
    console.error(`텔레그램 전송 실패: HTTP ${res.status} ${detail}`);
  }
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
  const { head, sections, universeChanged } = buildSections();
  if (head.length === 0 && sections.length === 0) {
    console.log('알림 조건에 해당하는 변동이 없습니다.');
    return;
  }

  const dateStr = new Date().toISOString().slice(0, 10);
  const text = assemble(head, sections, dateStr);
  console.log(text);
  console.log(`\n(메시지 길이 ${text.length}자 / 상한 ${HARD_LIMIT}자${universeChanged ? ', 유니버스 변경일' : ''})`);

  const sentTg = await sendTelegram(text);
  const sentSlack = await sendSlack(text);
  if (!sentTg && !sentSlack) {
    console.log('(알림 채널 미설정 - Secrets에 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 또는 SLACK_WEBHOOK_URL을 등록하세요)');
  }
}

// 직접 실행할 때만 전송한다 (테스트에서 require 하면 main이 돌지 않도록)
if (require.main === module) {
  main().catch((e) => {
    console.error('알림 실패:', e);
    process.exit(1);
  });
}

module.exports = { buildSections, assemble, HARD_LIMIT }; // 테스트용
