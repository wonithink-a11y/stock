/**
 * backtest-report.js
 *
 * docs/data/history/에 매일 쌓인 스냅샷으로 실데이터 백테스트를 돌립니다.
 * 시장별로 분리 실행: KR은 criteria.json + KOSPI 벤치마크,
 * US는 criteria-us.json + S&P500 벤치마크.
 *
 * 이력이 쌓이기 전(최소 ~1개월)에는 표본이 없어 리포트가 비어 있습니다 - 정상입니다.
 * 데모용 가상 데이터가 아니라 실제 수집 데이터만 사용하므로,
 * 여기서 나오는 IC·등급 성과가 곧 모델의 실제 성적표입니다.
 *
 * [v2.1] 각 스냅샷에 그날의 시장 국면(regimeGrade)을 실어 보내
 *        backtester 가 국면 조건부 분석(regimeAnalysis)을 산출합니다.
 *        analyze.js 가 history 파일에 regimeGrade 를 기록해야 동작하며,
 *        없으면 regimeAnalysis.available=false 로 나오고 나머지는 기존과 동일합니다.
 *
 * [P10] backtest.json(V1)은 그대로 두고 backtest-v2.json을 병행 출력한다(STEP6과 동일한
 *       병행 원칙). V2 riskPenalty는 과거 스냅샷에 state가 없어 항상 0이다 — look-ahead
 *       bias를 피하려고 현재 state를 과거에 소급 적용하지 않는다(lib/backtester.js 주석 참조).
 *       즉 지금 backtest-v2.json은 "축 스코어링(rawScore)의 예측력"만 검증하고,
 *       리스크 감점의 효과는 analyze.js가 history에 state를 함께 기록하기 시작한 뒤부터 검증된다.
 */

const fs = require('fs');
const path = require('path');
const { runBacktest } = require('../lib/backtester');
const { loadCriteria } = require('../lib/loadCriteria');
const { loadPolicies } = require('../lib/loadPolicies');

const ROOT = path.join(__dirname, '..');
const OUT_DIR = path.join(ROOT, 'docs', 'data');
const HISTORY_DIR = path.join(OUT_DIR, 'history');

const HORIZON_DAYS = { d20: 28, d60: 84, d120: 168 }; // 거래일 → 달력일 근사 (7/5배)

function loadJson(p, fallback) {
  if (!fs.existsSync(p)) return fallback;
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

function loadHistory() {
  if (!fs.existsSync(HISTORY_DIR)) return [];
  return fs
    .readdirSync(HISTORY_DIR)
    .filter((f) => f.endsWith('.json'))
    .sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(HISTORY_DIR, f), 'utf-8')));
}

// 목표일 이후 가장 가까운 스냅샷을 찾음 (주말/휴장 보정)
function findSnapshotOnOrAfter(days, targetDate) {
  for (const day of days) {
    if (day.date >= targetDate) return day;
  }
  return null;
}

function addDays(dateStr, n) {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function pctChange(from, to) {
  if (typeof from !== 'number' || typeof to !== 'number' || from === 0) return undefined;
  return ((to - from) / from) * 100;
}

function buildSnapshots(days, market) {
  const benchKey = market === 'US' ? 'spxClose' : 'kospiClose';
  const snapshots = [];

  for (const day of days) {
    for (const stock of day.stocks) {
      if ((stock.market || 'KR') !== market) continue;
      if (typeof stock.close !== 'number') continue;

      const forwardReturns = {};
      const benchmarkReturns = {};
      let hasAnyHorizon = false;

      for (const [h, calDays] of Object.entries(HORIZON_DAYS)) {
        const future = findSnapshotOnOrAfter(days, addDays(day.date, calDays));
        if (!future) continue;
        const futureStock = future.stocks.find((s) => s.ticker === stock.ticker);
        const fr = futureStock ? pctChange(stock.close, futureStock.close) : undefined;
        const br = pctChange(day[benchKey], future[benchKey]);
        if (fr !== undefined) {
          forwardReturns[h] = Math.round(fr * 100) / 100;
          hasAnyHorizon = true;
        }
        if (br !== undefined) benchmarkReturns[h] = Math.round(br * 100) / 100;
      }

      if (hasAnyHorizon) {
        snapshots.push({
          date: day.date,
          regimeGrade: day.regimeGrade, // [v2.1] 그날의 시장 국면 (없으면 undefined)
          stockData: stock.stockData,
          forwardReturns,
          benchmarkReturns,
        });
      }
    }
  }
  return snapshots;
}

function main() {
  const days = loadHistory();
  const criteriaKR = loadCriteria('KR').criteria;
  const criteriaUS = loadCriteria('US').criteria;
  const policiesKR = loadPolicies('KR');
  const policiesUS = loadPolicies('US');

  const markets = {};
  const marketsV2 = {};
  let totalSamples = 0;
  let totalSamplesV2 = 0;

  for (const [market, criteria, policies] of [['KR', criteriaKR, policiesKR], ['US', criteriaUS, policiesUS]]) {
    const snapshots = buildSnapshots(days, market);
    if (snapshots.length === 0) continue;
    const cost = market === 'US' ? 0.1 : 0.3;
    markets[market] = runBacktest(snapshots, criteria, { transactionCostPct: cost });
    totalSamples += markets[market].sampleCount;

    // [P10] V2 병행 실행 — 같은 스냅샷을 policies와 함께 넘기면 backtester가 V2 score()로 분기한다.
    marketsV2[market] = runBacktest(snapshots, criteria, { transactionCostPct: cost, policies });
    totalSamplesV2 += marketsV2[market].sampleCount;
  }

  fs.mkdirSync(OUT_DIR, { recursive: true });

  if (totalSamples === 0) {
    const insufficient = {
      updatedAt: new Date().toISOString(),
      status: 'insufficient_history',
      message: `이력 ${days.length}일 누적됨. 최소 horizon(약 28일) 이상 쌓여야 첫 결과가 나옵니다.`,
    };
    fs.writeFileSync(path.join(OUT_DIR, 'backtest.json'), JSON.stringify(insufficient, null, 2), 'utf-8');
    fs.writeFileSync(path.join(OUT_DIR, 'backtest-v2.json'), JSON.stringify(insufficient, null, 2), 'utf-8');
    console.log('아직 백테스트 가능한 이력이 부족합니다 (정상).');
    return;
  }

  fs.writeFileSync(
    path.join(OUT_DIR, 'backtest.json'),
    JSON.stringify({ updatedAt: new Date().toISOString(), status: 'ok', historyDays: days.length, markets }, null, 2),
    'utf-8'
  );

  fs.writeFileSync(
    path.join(OUT_DIR, 'backtest-v2.json'),
    JSON.stringify({
      updatedAt: new Date().toISOString(),
      status: 'ok',
      historyDays: days.length,
      note: 'riskPenalty는 과거 스냅샷에 state가 없어 현재 항상 0이다 — look-ahead bias 방지(§ lib/backtester.js 주석). rawScore(축 스코어링)의 예측력만 검증된 결과다.',
      markets: marketsV2,
    }, null, 2),
    'utf-8'
  );

  for (const [market, result] of Object.entries(markets)) {
    console.log(`[${market}] 표본 ${result.sampleCount}건`);
    result.verdicts.forEach((v) => console.log(`  - ${v}`));
    const ra = result.regimeAnalysis;
    if (ra && ra.available) {
      const fc = ra.filterComparison;
      const h0 = Object.keys(fc.allRegimes.horizons)[0];
      console.log(
        `  [국면] 전 구간 승률 ${fc.allRegimes.horizons[h0].winRatePct}% → ` +
          `우호 국면만 ${fc.favorableOnly.horizons[h0].winRatePct}% (${h0})`
      );
    }
  }

  console.log(`\n[V2] 총 표본 ${totalSamplesV2}건 (V1과 표본 수 동일해야 정상 — 다르면 축 결측 처리 차이를 의심)`);
  for (const [market, result] of Object.entries(marketsV2)) {
    console.log(`[V2:${market}] 표본 ${result.sampleCount}건`);
    result.verdicts.forEach((v) => console.log(`  - ${v}`));
  }
}

main();
