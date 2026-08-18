#!/usr/bin/env node
/**
 * A4(수급) 소비 3단계 — baseline vs +supplyDemand를 lib/backtester.js의
 * runBacktest()에 태워 forward return·IC·등급 단조성까지 비교한다.
 *
 *   node scripts/probe-a4-runbacktest-comparison.js
 *
 * 2단계(probe-a4-supplydemand-vertical-slice.js)와 같은 원칙 — resolver.js·
 * scoringEngine.js·backtester.js·config/policies/*는 전혀 안 건드린다.
 * runBacktest()를 production 계약 그대로 두 번 부른다(스냅샷 집합만 다름).
 * data/backfill/scores/나 manifest에 아무것도 안 쓴다(교훈43).
 *
 * ★ axisModel을 선언하지 않는다. 이유: SB-1.0(scoreBasis.v1.json)에 등록된
 *   KR_3AXIS/KR_4AXIS는 둘 다 valuation을 basis에 요구하는데, resolver.js가
 *   valuation을 아직 안 붙인다(A5-3 별건 블로커, 2단계에서 발견) — 그래서 실제
 *   관측 basis([fundamental,technical] / [fundamental,technical,supplyDemand])가
 *   어떤 등록 모델과도 안 맞는다. axisModel을 억지로 선언하면 resolveModel()이
 *   던지거나, BASIS_MISMATCH로 전량 걸러진다. 대신 두 snapshot 집합을 처음부터
 *   basis가 동질(homogeneous)하게 따로 만들어서, "undeclared 모델 둘의 A/B 비교"로
 *   한다 — runBacktest는 이걸 막지 않는다(verdicts에 "다른 실행과 비교 말라"는
 *   경고가 붙는데, 그건 축소된 값을 KR_4AXIS 운영 성능으로 오독하지 말라는
 *   뜻이지 이 스크립트가 하는 A/B 비교 자체를 막는 게 아니다).
 *
 * ★ benchmarkReturns는 안 만든다. 이 프로젝트에 KOSPI 지수 백필이 없다
 *   (docs/BF-1.1-백필계약.md §10: "KRX 지수 — 차단"). 대체 프록시를 임의로
 *   지어내지 않는다(정직한 결측) — avgExcessVsBenchmarkPct·국면 필터 효과 비교는
 *   이 스크립트에서 항상 null/불가로 나온다. forward return·승률·IC·등급
 *   단조성은 benchmark 없이도 유효하다.
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
const { runBacktest } = require(path.join(ROOT, 'lib/backtester'));
const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));

// 2단계와 동일한 35종목·2016~2026 전체 주간 snapshot — 같은 종목/같은 기간이라야
// baseline과 +supplyDemand가 비교 가능하다.
const SAMPLE = [
  { ticker: '005930', corp: '00126380', name: '삼성전자' },
  { ticker: '000660', corp: '00164779', name: 'SK하이닉스' },
  { ticker: '005380', corp: '00164742', name: '현대자동차' },
  { ticker: '051910', corp: '00356361', name: 'LG화학' },
  { ticker: '035420', corp: '00266961', name: 'NAVER' },
  { ticker: '000020', corp: '00119195', name: '동화약품' },
  { ticker: '000480', corp: '00148984', name: '시알홀딩스' },
  { ticker: '000990', corp: '00160843', name: 'DB하이텍' },
  { ticker: '001450', corp: '00164973', name: '현대해상' },
  { ticker: '001940', corp: '00159740', name: 'KISCO홀딩스' },
  { ticker: '002600', corp: '00149345', name: '조흥' },
  { ticker: '003070', corp: '00152880', name: '코오롱글로벌' },
  { ticker: '003610', corp: '00122348', name: '방림' },
  { ticker: '004270', corp: '00172185', name: '남성' },
  { ticker: '004920', corp: '00127158', name: '씨아이테크' },
  { ticker: '005680', corp: '00127200', name: '삼영전자공업' },
  { ticker: '006220', corp: '00148832', name: '제주은행' },
  { ticker: '007160', corp: '00124799', name: '사조산업' },
  { ticker: '008490', corp: '00131692', name: '서흥' },
  { ticker: '009440', corp: '00159971', name: 'KC그린홀딩스' },
  { ticker: '010780', corp: '00115977', name: '아이에스동서' },
  { ticker: '011780', corp: '00106368', name: '금호석유화학' },
  { ticker: '013700', corp: '00129420', name: '까뮤이앤씨' },
  { ticker: '015890', corp: '00153339', name: '태경산업' },
  { ticker: '017960', corp: '00159795', name: '한국카본' },
  { ticker: '023530', corp: '00120526', name: '롯데쇼핑' },
  { ticker: '027410', corp: '00219097', name: 'BGF' },
  { ticker: '033240', corp: '00146861', name: '자화전자' },
  { ticker: '037270', corp: '00249247', name: 'YG PLUS' },
  { ticker: '053690', corp: '00413523', name: '한미글로벌' },
  { ticker: '071320', corp: '00159698', name: '지역난방공사' },
  { ticker: '084010', corp: '00113225', name: '대한제강' },
  { ticker: '093240', corp: '00441243', name: '형지엘리트' },
  { ticker: '108670', corp: '00759513', name: 'LX하우시스' },
  { ticker: '138040', corp: '00860332', name: '메리츠금융지주' },
];

const PRICE_YEARS = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026'];
const FUND_YEARS = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025'];
const A4_YEARS = ['2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026'];
const HORIZONS = { d20: 20, d60: 60, d120: 120 }; // 거래일(달력일 근사 아님 — calendar.tradingDays로 정확히 센다)

const SD5D_WINDOW = 5;
const INSTITUTION_CATEGORIES = ['금융투자', '보험', '투신', '사모', '은행', '기타금융', '연기금', '기타법인'];

function readGzJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean);
}

function buildTickerIndex(pathTemplate, years, keySet, keyField) {
  const idx = new Map();
  for (const k of keySet) idx.set(k, []);
  const needle = new RegExp(`"${keyField}"\\s*:\\s*"(?:${[...keySet].join('|')})"`);
  for (const year of years) {
    const rel = pathTemplate.replace('{year}', year);
    if (!fs.existsSync(path.join(ROOT, rel))) continue;
    for (const line of readGzJsonl(rel)) {
      if (!needle.test(line)) continue;
      const r = JSON.parse(line);
      const k = r[keyField];
      if (idx.has(k)) idx.get(k).push(r);
    }
  }
  for (const arr of idx.values()) arr.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return idx;
}

function netOf(rec, categories) {
  let net = 0;
  for (const c of categories) net += (rec.buyAmount[c] || 0) - (rec.sellAmount[c] || 0);
  return net;
}

function trendFromWindow(window, categories) {
  if (window.length === 0) return { trend: undefined };
  let daysBuy = 0;
  for (const r of window) if (netOf(r, categories) > 0) daysBuy++;
  const total = window.length;
  if (daysBuy === total) return { trend: 'consistentBuy' };
  if (daysBuy === 0) return { trend: 'consistentSell' };
  if (daysBuy > total / 2) return { trend: 'netBuy' };
  if (daysBuy < total / 2) return { trend: 'netSell' };
  return { trend: 'neutral' };
}

function main() {
  const t0 = Date.now();
  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');

  const tickers = new Set(SAMPLE.map((s) => s.ticker));
  const corps = new Set(SAMPLE.map((s) => s.corp));

  const cal = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/calendar.json'), 'utf8'));
  const SNAPSHOT_DATES = cal.snapshotDays.filter((d) => d >= '2016-01-04');
  const tradingDays = cal.tradingDays;
  const tradingDayIdx = new Map(tradingDays.map((d, i) => [d, i]));

  console.error('색인 구축 중...');
  const priceIdx = buildTickerIndex('data/backfill/price/a2a/{year}.jsonl.gz', PRICE_YEARS, tickers, 'ticker');
  const a3Idx = buildTickerIndex('data/backfill/fundamentals/a3/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a3bIdx = buildTickerIndex('data/backfill/fundamentals/a3b/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a4Idx = buildTickerIndex('data/backfill/supplyDemand/a4/{year}.jsonl.gz', A4_YEARS, tickers, 'ticker');

  // ticker별 date→close Map — forward return 조회용 O(1).
  const priceByDate = new Map();
  for (const [ticker, arr] of priceIdx) {
    const m = new Map();
    for (const r of arr) m.set(r.date, r.close);
    priceByDate.set(ticker, m);
  }

  console.error(`색인 완료 (${((Date.now() - t0) / 1000).toFixed(1)}s). 스냅샷 생성 시작...`);

  const snapshotsBase = [];
  const snapshotsSD = [];
  let sdJoinFull = 0, sdJoinTotal = 0;

  for (const { ticker, corp, name } of SAMPLE) {
    const priceArr = priceIdx.get(ticker) || [];
    const a3records = a3Idx.get(corp) || [];
    const a3bRecordsAll = a3bIdx.get(corp) || [];
    const a4arr = a4Idx.get(ticker) || [];
    const closeMap = priceByDate.get(ticker) || new Map();

    for (const asOf of SNAPSHOT_DATES) {
      const price = priceArr.find((r) => r.date === asOf) || null;
      const candles = priceArr.filter((r) => r.date <= asOf).slice(-260).map((r) => ({ date: r.date, close: r.close, volume: r.volume }));

      const resolved = resolve({ ticker, corp, asOf, fundamentals: a3records, price, dividendEps: a3bRecordsAll, candles });

      const sdWindow = a4arr.filter((r) => r.date <= asOf).slice(-SD5D_WINDOW);
      sdJoinTotal += 1;
      if (sdWindow.length === SD5D_WINDOW) sdJoinFull += 1;
      const foreign = trendFromWindow(sdWindow, ['외국인']);
      const institution = trendFromWindow(sdWindow, INSTITUTION_CATEGORIES);

      // forward return — 거래일 정확히 셈(calendar.tradingDays 기반, 달력일 근사 아님)
      const asOfIdx = tradingDayIdx.get(asOf);
      const asOfClose = closeMap.get(asOf);
      const forwardReturns = {};
      if (asOfIdx !== undefined && typeof asOfClose === 'number' && asOfClose > 0) {
        for (const [h, n] of Object.entries(HORIZONS)) {
          const futureDate = tradingDays[asOfIdx + n];
          if (!futureDate) continue;
          const futureClose = closeMap.get(futureDate);
          if (typeof futureClose === 'number') {
            forwardReturns[h] = Math.round(((futureClose - asOfClose) / asOfClose) * 10000) / 100;
          }
        }
      }

      const stockDataBase = { ticker, name, dataCutoff: asOf, state: null, ...resolved.stockData };
      const stockDataSD = { ...stockDataBase, supplyDemand: { foreignTrend5d: foreign.trend, institutionTrend5d: institution.trend } };

      snapshotsBase.push({ date: asOf, stockData: stockDataBase, forwardReturns });
      snapshotsSD.push({ date: asOf, stockData: stockDataSD, forwardReturns });
    }
  }

  console.error(`snapshot ${snapshotsBase.length}개 생성 완료 (${((Date.now() - t0) / 1000).toFixed(1)}s). runBacktest() 실행...`);

  const opts = { policies, horizons: Object.keys(HORIZONS), transactionCostPct: 0.3 };
  const resultBase = runBacktest(snapshotsBase, criteria, opts);
  const resultSD = runBacktest(snapshotsSD, criteria, opts);

  const out = {
    generatedAt: new Date().toISOString(),
    elapsedSec: Math.round((Date.now() - t0) / 100) / 10,
    universeSize: SAMPLE.length,
    snapshotDateCount: SNAPSHOT_DATES.length,
    dateRange: [SNAPSHOT_DATES[0], SNAPSHOT_DATES[SNAPSHOT_DATES.length - 1]],
    a4JoinFullWindowRate: Math.round((sdJoinFull / sdJoinTotal) * 1000) / 1000,
    note: 'benchmarkReturns 없음 — KOSPI 지수 백필 없음(BF-1.1 §10). avgExcessVsBenchmarkPct·국면 필터 비교는 이 결과에서 항상 null.',
    baseline: resultBase,
    withSupplyDemand: resultSD,
  };

  const outPath = path.join(ROOT, 'scratch-a4-runbacktest-comparison.json');
  fs.writeFileSync(outPath, JSON.stringify(out, null, 0));
  console.log('결과 →', outPath, `(${((Date.now() - t0) / 1000).toFixed(1)}s)`);

  console.log('\n=== baseline ===');
  console.log('sampleCount:', resultBase.sampleCount, 'model:', resultBase.population.model.axisModel);
  console.log('ic:', JSON.stringify(resultBase.ic), 'icSampleCount:', JSON.stringify(resultBase.icSampleCount));
  console.log('gradeMonotonic:', resultBase.gradeMonotonic);
  resultBase.verdicts.forEach((v) => console.log('  -', v));

  console.log('\n=== +supplyDemand ===');
  console.log('sampleCount:', resultSD.sampleCount, 'model:', resultSD.population.model.axisModel);
  console.log('ic:', JSON.stringify(resultSD.ic), 'icSampleCount:', JSON.stringify(resultSD.icSampleCount));
  console.log('gradeMonotonic:', resultSD.gradeMonotonic);
  resultSD.verdicts.forEach((v) => console.log('  -', v));
}

main();
