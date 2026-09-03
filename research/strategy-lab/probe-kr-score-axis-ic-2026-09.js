/**
 * probe-kr-score-axis-ic-2026-09.js
 *
 * backtest-report.js가 KR IC=-0.211(41일·1404건, KR-2.3 적용 후에도 여전히
 * 역방향)을 보인 원인을 축 단위로 쪼갠다. scoreStock()의 breakdown이 이미
 * 축별 점수를 주므로, 최종가중합 대신 축 각각을 forwardReturns.d20과
 * 상관시킨다 - MA크로스 반전(KR-2.3)이 오늘 이미 반영된 뒤에도 전체가
 * 왜 여전히 역방향인지 보는 진단 전용 스크립트. data/backfill/·manifest에
 * 아무것도 안 쓴다(교훈43과 같은 원칙).
 *
 *   node research/strategy-lab/probe-kr-score-axis-ic-2026-09.js
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { scoreStock } = require('../../lib/scoringEngine');
const { loadCriteria } = require('../../lib/loadCriteria');
const { spearmanIC } = require('../../lib/backtester');

const ROOT = path.join(__dirname, '..', '..');
const HISTORY_DIR = path.join(ROOT, 'docs', 'data', 'history');
const HORIZON_CAL_DAYS = 28; // backtest-report.js와 동일 근사(20거래일≈28달력일)

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

function main() {
  const days = loadHistory();
  const criteria = loadCriteria('KR').criteria;
  const axisPairs = { fundamental: [], valuation: [], technical: [], supplyDemand: [], total: [] };

  for (const day of days) {
    for (const stock of day.stocks) {
      if ((stock.market || 'KR') !== 'KR') continue;
      if (typeof stock.close !== 'number') continue;
      const future = findSnapshotOnOrAfter(days, addDays(day.date, HORIZON_CAL_DAYS));
      if (!future) continue;
      const futureStock = future.stocks.find((s) => s.ticker === stock.ticker);
      const fr = futureStock ? pctChange(stock.close, futureStock.close) : undefined;
      if (fr === undefined) continue;

      const result = scoreStock(stock.stockData, criteria);
      for (const axis of ['fundamental', 'valuation', 'technical', 'supplyDemand']) {
        const s = result.breakdown[axis] && result.breakdown[axis].score;
        if (typeof s === 'number') axisPairs[axis].push({ x: s, y: fr });
      }
      if (typeof result.totalScore === 'number') axisPairs.total.push({ x: result.totalScore, y: fr });
    }
  }

  console.log(`KR criteria: ${loadCriteria('KR').version || '(버전 필드 없음)'}  일수: ${days.length}`);
  console.log('축별 IC (d20, 축 점수 vs 실제 20거래일 수익률):');
  for (const axis of ['fundamental', 'valuation', 'technical', 'supplyDemand', 'total']) {
    const pairs = axisPairs[axis];
    const n = pairs.filter((p) => typeof p.x === 'number' && typeof p.y === 'number').length;
    const ic = spearmanIC(pairs);
    const flag = ic !== null && ic < 0 ? '  << 역방향' : '';
    console.log(`  ${axis.padEnd(14)} n=${n}  IC=${ic === null ? 'null(n<3)' : ic.toFixed(3)}${flag}`);
  }
}

main();
