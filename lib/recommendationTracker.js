/**
 * recommendationTracker.js
 *
 * 종목을 추천한 시점의 가격/점수를 config/recommendations.json에 기록하고,
 * 이후 현재가를 입력받아 추천가 대비 변동률을 계산합니다.
 *
 * 사용 예:
 *   const { recordRecommendation, getPerformance } = require('./recommendationTracker');
 *
 *   recordRecommendation({
 *     ticker: '005930', name: '삼성전자', priceAtRecommendation: 72000,
 *     score: 88, grade: 'A (강력 매수 후보)'
 *   });
 *
 *   const performance = getPerformance({ '005930': 76500 });
 *   // -> [{ ticker, name, recommendedDate, priceAtRecommendation, currentPrice, changePct, holdingDays, ... }]
 */

const fs = require('fs');
const path = require('path');

const DEFAULT_LOG_PATH = path.join(__dirname, '..', 'config', 'recommendations.json');

function loadLog(logPath = DEFAULT_LOG_PATH) {
  if (!fs.existsSync(logPath)) return [];
  const raw = fs.readFileSync(logPath, 'utf-8').trim();
  if (!raw) return [];
  return JSON.parse(raw);
}

function saveLog(entries, logPath = DEFAULT_LOG_PATH) {
  fs.writeFileSync(logPath, JSON.stringify(entries, null, 2), 'utf-8');
}

/**
 * 새 추천을 기록합니다. 같은 종목을 같은 날짜에 중복 기록하지 않습니다.
 *
 * @param {object} rec - { ticker, name, priceAtRecommendation, score, grade, note? }
 * @param {string} logPath - 로그 파일 경로 (선택)
 */
function recordRecommendation(rec, logPath = DEFAULT_LOG_PATH) {
  if (!rec.ticker || rec.priceAtRecommendation === undefined) {
    throw new Error('ticker와 priceAtRecommendation은 필수입니다.');
  }

  const entries = loadLog(logPath);
  const today = new Date().toISOString().slice(0, 10);

  const alreadyRecordedToday = entries.some((e) => e.ticker === rec.ticker && e.recommendedDate === today);
  if (alreadyRecordedToday) {
    return { added: false, reason: '오늘 이미 같은 종목이 기록되어 있습니다.' };
  }

  const entry = {
    id: `${rec.ticker}_${today}_${Date.now()}`,
    ticker: rec.ticker,
    name: rec.name || null,
    recommendedDate: today,
    priceAtRecommendation: rec.priceAtRecommendation,
    score: rec.score ?? null,
    grade: rec.grade ?? null,
    note: rec.note ?? null,
    status: 'open', // 'open' | 'closed' (직접 매도 처리 시 closed로 변경 가능)
  };

  entries.push(entry);
  saveLog(entries, logPath);
  return { added: true, entry };
}

/**
 * 추천 이력에 현재가를 반영해 변동률을 계산합니다.
 *
 * @param {object} currentPrices - { [ticker]: currentPrice } 형태
 * @param {object} options - { onlyOpen: boolean, logPath: string }
 */
function getPerformance(currentPrices = {}, options = {}) {
  const { onlyOpen = true, logPath = DEFAULT_LOG_PATH } = options;
  const entries = loadLog(logPath);
  const today = new Date();

  return entries
    .filter((e) => !onlyOpen || e.status === 'open')
    .map((e) => {
      const currentPrice = currentPrices[e.ticker];
      const holdingDays = Math.floor((today - new Date(e.recommendedDate)) / (1000 * 60 * 60 * 24));

      let changePct = null;
      if (currentPrice !== undefined && e.priceAtRecommendation) {
        changePct = ((currentPrice - e.priceAtRecommendation) / e.priceAtRecommendation) * 100;
      }

      return {
        id: e.id,
        ticker: e.ticker,
        name: e.name,
        recommendedDate: e.recommendedDate,
        priceAtRecommendation: e.priceAtRecommendation,
        currentPrice: currentPrice ?? null,
        changePct: changePct !== null ? Math.round(changePct * 100) / 100 : null,
        holdingDays,
        scoreAtRecommendation: e.score,
        gradeAtRecommendation: e.grade,
        status: e.status,
      };
    });
}

/**
 * 추천 건을 종료 처리(매도 등)합니다.
 */
function closeRecommendation(id, logPath = DEFAULT_LOG_PATH) {
  const entries = loadLog(logPath);
  const idx = entries.findIndex((e) => e.id === id);
  if (idx === -1) return { closed: false, reason: '해당 id를 찾을 수 없습니다.' };
  entries[idx].status = 'closed';
  saveLog(entries, logPath);
  return { closed: true, entry: entries[idx] };
}

module.exports = { recordRecommendation, getPerformance, closeRecommendation, loadLog };
