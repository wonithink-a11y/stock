/**
 * analyze.js
 *
 * data/inputs.json(collect.js 산출물)을 받아:
 *  1. 시장 국면 판단 (환율은 자동 수집값으로 덮어씀) - 한국 시장 대상
 *  2. 관심종목 스코어링 (KR: criteria.json / US: criteria-us.json)
 *  3. 보유종목 포트폴리오 신호
 *  4. B등급 이상 추천 이력 기록 + 성과 갱신
 *  5. 대시보드용 JSON(docs/data/*)과 백테스트용 일별 스냅샷(docs/data/history/) 저장
 *
 * [v2.1] 일별 스냅샷에 그 시점의 시장 국면(regimeGrade/regimeScore)을 함께 기록합니다.
 *        backtester 의 국면 조건부 분석("우호 국면에서만 진입했다면 승률은?")에 사용됩니다.
 *        ⚠️ 반드시 '그날 판단된 국면'이어야 합니다(사후 국면을 넣으면 look-ahead bias).
 */

const fs = require('fs');
const path = require('path');
const { scoreStock } = require('../lib/scoringEngine');
const { evaluateRegime } = require('../lib/marketRegimeEngine');
const { evaluateHolding } = require('../lib/portfolioAdvisor');
const { recordRecommendation, getPerformance } = require('../lib/recommendationTracker');

const ROOT = path.join(__dirname, '..');
const OUT_DIR = path.join(ROOT, 'docs', 'data');
const HISTORY_DIR = path.join(OUT_DIR, 'history');
const RECO_PATH = path.join(OUT_DIR, 'recommendations-log.json');

function loadJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}
function saveJson(p, data) {
  fs.writeFileSync(p, JSON.stringify(data, null, 2), 'utf-8');
}

function main() {
  const inputs = loadJson(path.join(ROOT, 'data', 'inputs.json'), null);
  if (!inputs) {
    console.error('data/inputs.json이 없습니다. 먼저 scripts/collect.js를 실행하세요.');
    process.exit(1);
  }

  const criteriaKR = loadJson(path.join(ROOT, 'config', 'criteria.json'));
  const criteriaUS = loadJson(path.join(ROOT, 'config', 'criteria-us.json'), criteriaKR);
  const criteriaFor = (market) => (market === 'US' ? criteriaUS : criteriaKR);
  const macro = loadJson(path.join(ROOT, 'config', 'macroInput.json'));
  const holdingsConfig = loadJson(path.join(ROOT, 'config', 'holdings.json'), { holdings: [] });

  fs.mkdirSync(HISTORY_DIR, { recursive: true });

  // 1. 국면 판단 (환율 자동값 반영) - 한국 시장 기준. 미국 종목 신호에도 참고로 함께 표시됩니다.
  if (inputs.fx && inputs.fx.usdKrwLevel) {
    macro.fx.usdKrwLevel = inputs.fx.usdKrwLevel;
    if (inputs.fx.usdKrw20dChangePct !== null) macro.fx.usdKrw20dChangePct = inputs.fx.usdKrw20dChangePct;
  }
  const regime = evaluateRegime(macro);
  saveJson(path.join(OUT_DIR, 'regime.json'), {
    updatedAt: inputs.collectedAt,
    grade: regime.grade,
    score: regime.regimeScore,
    action: regime.action,
    specialFlags: regime.specialFlags,
    macroUsed: macro,
  });

  // 2. 관심종목 스코어링 (시장별 기준 적용)
  const watchlist = loadJson(path.join(ROOT, 'config', 'watchlist.json'), { groupLabels: {} });
  const results = inputs.stocks.map((s) => {
    const market = s.market || s.meta.market || 'KR';
    const r = scoreStock(s, criteriaFor(market));
    return { ...r, market, currentPrice: s.meta.currentPrice, lastDate: s.meta.lastDate, groups: s.meta.groups || [] };
  });
  results.sort((a, b) => (b.totalScore ?? -1) - (a.totalScore ?? -1));
  saveJson(path.join(OUT_DIR, 'latest.json'), {
    updatedAt: inputs.collectedAt,
    regime: { grade: regime.grade, score: regime.regimeScore },
    groupLabels: watchlist.groupLabels || {},
    results,
  });

  // 3. 포트폴리오 신호
  const inputByTicker = Object.fromEntries(inputs.stocks.map((s) => [s.ticker, s]));
  const holdings = holdingsConfig.holdings
    .map((h) => {
      const stockInput = inputByTicker[h.code];
      if (!stockInput) {
        console.warn(`[경고] 보유종목 ${h.code}가 watchlist에 없어 신호를 계산할 수 없습니다. watchlist.json에 추가하세요.`);
        return null;
      }
      const market = stockInput.market || 'KR';
      const currentPrice = stockInput.meta.currentPrice ?? h.avgPrice;
      const result = evaluateHolding(
        { ticker: h.code, name: h.name, quantity: h.quantity, avgPrice: h.avgPrice, currentPrice },
        stockInput,
        regime,
        criteriaFor(market)
      );
      return { ...result, market };
    })
    .filter(Boolean);
  saveJson(path.join(OUT_DIR, 'portfolio.json'), { updatedAt: inputs.collectedAt, marketRegime: regime.grade, holdings });

  // 4. 추천 이력: B등급(65점) 이상 신규 기록 + 전체 성과 갱신
  for (const r of results) {
    if (r.totalScore !== null && r.totalScore >= 65 && r.dataCoverage.sufficient && r.currentPrice) {
      recordRecommendation(
        { ticker: r.ticker, name: r.name, priceAtRecommendation: r.currentPrice, score: r.totalScore, grade: r.grade, note: r.market },
        RECO_PATH
      );
    }
  }
  const currentPrices = Object.fromEntries(results.filter((r) => r.currentPrice).map((r) => [r.ticker, r.currentPrice]));
  const marketByTicker = Object.fromEntries(results.map((r) => [r.ticker, r.market]));
  const performance = getPerformance(currentPrices, { onlyOpen: true, logPath: RECO_PATH }).map((p) => ({
    ...p,
    market: marketByTicker[p.ticker] || 'KR',
  }));
  saveJson(path.join(OUT_DIR, 'recommendations.json'), { updatedAt: inputs.collectedAt, performance });

  // 5. 백테스트용 일별 스냅샷 (입력 데이터 원본 + 종가 + 벤치마크 종가 + 그날의 시장 국면)
  const today = new Date().toISOString().slice(0, 10);
  saveJson(path.join(HISTORY_DIR, `${today}.json`), {
    date: today,
    regimeGrade: regime.grade, // [v2.1] 국면 조건부 백테스트용
    regimeScore: regime.regimeScore, // [v2.1] 국면 점수(연속값) - 추후 구간 분석용
    kospiClose: inputs.kospiClose,
    spxClose: inputs.spxClose ?? null,
    stocks: inputs.stocks.map((s) => ({
      ticker: s.ticker,
      name: s.name,
      market: s.market || 'KR',
      close: s.meta.currentPrice,
      stockData: { ticker: s.ticker, name: s.name, fundamental: s.fundamental, valuation: s.valuation, technical: s.technical, supplyDemand: s.supplyDemand },
    })),
  });

  // 알림용: 직전 결과 보관 후 이번 결과로 교체
  const prevPath = path.join(OUT_DIR, 'previous.json');
  const latestForDiff = { results: results.map((r) => ({ ticker: r.ticker, name: r.name, totalScore: r.totalScore, grade: r.grade, warnings: r.warnings })) };
  const lastSaved = loadJson(path.join(OUT_DIR, 'current-summary.json'), null);
  if (lastSaved) saveJson(prevPath, lastSaved);
  saveJson(path.join(OUT_DIR, 'current-summary.json'), latestForDiff);

  console.log(`분석 완료: 종목 ${results.length}건, 국면 ${regime.grade}(${regime.regimeScore}점), 보유신호 ${holdings.length}건`);
}

main();
