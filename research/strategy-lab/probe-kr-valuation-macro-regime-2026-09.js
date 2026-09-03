/**
 * probe-kr-valuation-macro-regime-2026-09.js
 *
 * probe-kr-score-axis-ic-2026-09.js가 찾은 "valuation 축 IC=-0.191(41일,
 * 역방향)"이 구조적 결함인지 국면(미국 10년물 상승기 vs 하락기) 탓인지
 * 가른다. 이 프로젝트의 PBR 매크로 연구(pbr_macro_rate_regime_check.py)가
 * 이미 고정해 둔 정의(TRAIL_DAYS=126거래일, 재최적화 없음)를 그대로 재사용 -
 * 새 임계값을 만들지 않는다. ui/data/macro.json의 usTreasury10y 이력을
 * 국면 분류에만 쓰고, 점수·수익률 계산 로직은 무변경.
 *
 *   node research/strategy-lab/probe-kr-valuation-macro-regime-2026-09.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { scoreStock } = require('../../lib/scoringEngine');
const { loadCriteria } = require('../../lib/loadCriteria');
const { spearmanIC } = require('../../lib/backtester');

const ROOT = path.join(__dirname, '..', '..');
const HISTORY_DIR = path.join(ROOT, 'docs', 'data', 'history');
const MACRO_PATH = path.join(ROOT, 'ui', 'data', 'macro.json');
const HORIZON_CAL_DAYS = 28;
const TRAIL_DAYS = 126; // pbr_macro_rate_regime_check.py와 동일, 사전 고정

function loadHistory() {
  return fs.readdirSync(HISTORY_DIR).filter((f) => f.endsWith('.json')).sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(HISTORY_DIR, f), 'utf-8')));
}
function addDays(dateStr, n) {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}
function findSnapshotOnOrAfter(days, targetDate) {
  for (const day of days) if (day.date >= targetDate) return day;
  return null;
}
function pctChange(from, to) {
  if (typeof from !== 'number' || typeof to !== 'number' || from === 0) return undefined;
  return ((to - from) / from) * 100;
}
function buildRegimeClassifier() {
  const macro = JSON.parse(fs.readFileSync(MACRO_PATH, 'utf-8'));
  const hist = macro.series.usTreasury10y.history
    .filter((p) => typeof p.value === 'number')
    .sort((a, b) => (a.date < b.date ? -1 : 1));
  const dates = hist.map((p) => p.date);

  return function regimeAt(dateStr) {
    // dateStr 이하 가장 가까운 US10Y 관측일 찾기
    let idx = -1;
    for (let i = dates.length - 1; i >= 0; i--) {
      if (dates[i] <= dateStr) { idx = i; break; }
    }
    if (idx < TRAIL_DAYS) return null; // 이력 부족
    const now = hist[idx].value;
    const then = hist[idx - TRAIL_DAYS].value;
    return { change: now - then, regime: now - then > 0 ? 'rising' : 'falling' };
  };
}

function main() {
  const days = loadHistory();
  const criteria = loadCriteria('KR').criteria;
  const regimeAt = buildRegimeClassifier();

  const buckets = { rising: [], falling: [] };
  const dayRegimeCount = { rising: new Set(), falling: new Set() };
  let sampleRegime = null;

  for (const day of days) {
    const r = regimeAt(day.date);
    if (!r) continue;
    if (!sampleRegime) sampleRegime = { date: day.date, ...r };
    for (const stock of day.stocks) {
      if ((stock.market || 'KR') !== 'KR') continue;
      if (typeof stock.close !== 'number') continue;
      const future = findSnapshotOnOrAfter(days, addDays(day.date, HORIZON_CAL_DAYS));
      if (!future) continue;
      const futureStock = future.stocks.find((s) => s.ticker === stock.ticker);
      const fr = futureStock ? pctChange(stock.close, futureStock.close) : undefined;
      if (fr === undefined) continue;

      const result = scoreStock(stock.stockData, criteria);
      const vScore = result.breakdown.valuation && result.breakdown.valuation.score;
      if (typeof vScore === 'number') {
        buckets[r.regime].push({ x: vScore, y: fr });
        dayRegimeCount[r.regime].add(day.date);
      }
    }
  }

  console.log('예시 국면 판정(첫 유효일):', sampleRegime);
  console.log(`거래일 수 - rising: ${dayRegimeCount.rising.size}일 · falling: ${dayRegimeCount.falling.size}일`);
  console.log('국면별 valuation 축 IC (d20):');
  for (const regime of ['rising', 'falling']) {
    const pairs = buckets[regime];
    const n = pairs.filter((p) => typeof p.x === 'number' && typeof p.y === 'number').length;
    const ic = spearmanIC(pairs);
    console.log(`  US10Y ${regime.padEnd(8)} n=${n}  IC=${ic === null ? 'null(n<3)' : ic.toFixed(3)}`);
  }
}

main();
