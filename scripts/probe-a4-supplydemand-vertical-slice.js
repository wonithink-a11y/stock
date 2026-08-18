#!/usr/bin/env node
/**
 * A4(수급) 소비 — baseline vs +supplyDemand 정찰. 1단계(5종목×6주)를 통과한 뒤
 * 그 방향으로 확대한 2단계 — 종목 35개 × 2016~2026 전체 주간 snapshot(553개):
 *
 *   node scripts/probe-a4-supplydemand-vertical-slice.js
 *
 * probe-bf11-vertical-slice.js(2026-08-12, 820f097)와 같은 원칙 — data/backfill/scores/나
 * manifest에 아무것도 안 쓴다(교훈43). resolver.js·scoringEngine.js·config/policies/*는
 * 전혀 안 건드린다 — production 코드 그대로 두 번 호출해서(수급 축 있음/없음) 비교만 한다.
 *
 * ★ valuation은 여전히 안 붙는다(resolver.js:170-196, A5-3 별건 블로커) — 그래서
 *   "KR_3AXIS"/"KR_4AXIS"가 아니라 "baseline"/"+supplyDemand"라고 부른다. 1단계와 동일.
 *
 * ★ 성능 설계(1단계에서 5종목×6일=30칸으로도 2분 넘게 걸려 중단한 교훈, 그리고 A4
 *   finalize의 OOM 교훈 둘 다 반영): 종목×날짜마다 연도 파일 전체를 다시 훑지 않는다.
 *   각 연도 파일을 정확히 한 번만 읽어 대상 종목만 뽑아 담고(buildTickerIndex),
 *   전량(전체 시장) 배열은 즉시 버린다 — 붙잡고 있으면 그것도 OOM 후보다.
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
const { score } = require(path.join(ROOT, 'lib/scoringEngine'));
const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));
const axisBasis = require(path.join(ROOT, 'lib/a5/axisBasis'));

// 1단계 대형주 5개 + KOSPI·2015-01-01 이전 상장 652종목에서 균등추출 30개 = 35종목.
// 대형주로만 편향되지 않게(소형·다양 업종 포함) 하기 위한 표본이다.
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

const SD5D_WINDOW = 5;
const INSTITUTION_CATEGORIES = ['금융투자', '보험', '투신', '사모', '은행', '기타금융', '연기금', '기타법인'];

function readGzJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean);
}

/**
 * 연도 파일을 정확히 한 번씩만 읽어 대상 종목(keyField)만 뽑는다. 전량 배열은 안 붙잡는다.
 *
 * 대상은 전체 종목의 1~2%뿐이라(35/2578) 매 줄을 JSON.parse부터 하면 느리다
 * (실측: 45개 연도 파일 인덱싱이 3분 넘게 안 끝나 중단) — 정규식으로 먼저 걸러
 * 후보 줄만 JSON.parse한다. JSON.parse는 파싱 비용이지 필터 비용이 아니다.
 */
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

/** 잠정 분류(production 규칙 아님) — daysBuy > total/2 = netBuy, 전부 = consistentBuy, 동률 = neutral. */
function trendFromWindow(window, categories) {
  if (window.length === 0) return { trend: undefined, netSum: null, daysTotal: 0 };
  let daysBuy = 0, netSum = 0;
  for (const r of window) {
    const n = netOf(r, categories);
    netSum += n;
    if (n > 0) daysBuy++;
  }
  const total = window.length;
  let trend;
  if (daysBuy === total) trend = 'consistentBuy';
  else if (daysBuy === 0) trend = 'consistentSell';
  else if (daysBuy > total / 2) trend = 'netBuy';
  else if (daysBuy < total / 2) trend = 'netSell';
  else trend = 'neutral';
  return { trend, netSum, daysTotal: total };
}

function main() {
  const t0 = Date.now();
  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');

  const tickers = new Set(SAMPLE.map((s) => s.ticker));
  const corps = new Set(SAMPLE.map((s) => s.corp));

  const cal = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/calendar.json'), 'utf8'));
  const SNAPSHOT_DATES = cal.snapshotDays.filter((d) => d >= '2016-01-04');

  console.error(`색인 구축 중 — ${SAMPLE.length}종목 × 가격${PRICE_YEARS.length}년/재무${FUND_YEARS.length}년/수급${A4_YEARS.length}년...`);
  const priceIdx = buildTickerIndex('data/backfill/price/a2a/{year}.jsonl.gz', PRICE_YEARS, tickers, 'ticker');
  const a3Idx = buildTickerIndex('data/backfill/fundamentals/a3/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a3bIdx = buildTickerIndex('data/backfill/fundamentals/a3b/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a4Idx = buildTickerIndex('data/backfill/supplyDemand/a4/{year}.jsonl.gz', A4_YEARS, tickers, 'ticker');
  const a1a = readGzJsonl('data/backfill/universe/a1a/current.jsonl').map((l) => JSON.parse(l));
  console.error(`색인 완료 (${((Date.now() - t0) / 1000).toFixed(1)}s). ${SAMPLE.length}종목 × ${SNAPSHOT_DATES.length}snapshot = ${SAMPLE.length * SNAPSHOT_DATES.length}칸 채점 시작...`);

  const samples = [];

  for (const { ticker, corp, name } of SAMPLE) {
    const uni = a1a.find((r) => r.ticker === ticker) || null;
    const priceArr = priceIdx.get(ticker) || [];
    const a3records = a3Idx.get(corp) || [];
    const a3bRecordsAll = a3bIdx.get(corp) || [];
    const a4arr = a4Idx.get(ticker) || [];

    for (const asOf of SNAPSHOT_DATES) {
      const price = priceArr.find((r) => r.date === asOf) || null;
      const candles = priceArr.filter((r) => r.date <= asOf).slice(-260).map((r) => ({ date: r.date, close: r.close, volume: r.volume }));

      const resolved = resolve({
        ticker, corp, asOf, fundamentals: a3records, price, dividendEps: a3bRecordsAll, candles,
      });

      const sdWindow = a4arr.filter((r) => r.date <= asOf).slice(-SD5D_WINDOW);
      const pitOk = sdWindow.every((r) => r.date <= asOf);
      const foreign = trendFromWindow(sdWindow, ['외국인']);
      const institution = trendFromWindow(sdWindow, INSTITUTION_CATEGORIES);

      const stockDataBase = { ticker, name, dataCutoff: asOf, state: null, ...resolved.stockData };
      const stockDataSD = { ...stockDataBase, supplyDemand: { foreignTrend5d: foreign.trend, institutionTrend5d: institution.trend } };

      let resultBase, resultSD, err = null;
      try {
        resultBase = score(stockDataBase, criteria, policies);
        resultSD = score(stockDataSD, criteria, policies);
      } catch (e) { err = e.message; }

      const entry = {
        ticker, asOf,
        listedBeforeAsOf: uni ? uni.listedAt <= asOf : null,
        sdJoinFound: sdWindow.length,
        pitOk,
        foreignTrend5d: foreign.trend,
        institutionTrend5d: institution.trend,
      };

      if (err) {
        entry.error = err;
      } else {
        const basisBase = axisBasis.basisOf(resultBase.result.components, criteria.categoryWeights);
        const basisSD = axisBasis.basisOf(resultSD.result.components, criteria.categoryWeights);
        entry.baselineScore = resultBase.result.finalScore;
        entry.withSDScore = resultSD.result.finalScore;
        entry.scoreDelta = (entry.baselineScore !== null && entry.withSDScore !== null)
          ? Math.round((entry.withSDScore - entry.baselineScore) * 10) / 10 : null;
        entry.basisBase = axisBasis.basisKey(basisBase);
        entry.basisSD = axisBasis.basisKey(basisSD);
        entry.supplyDemandAddedToBasis = !basisBase.includes('supplyDemand') && basisSD.includes('supplyDemand');
      }

      samples.push(entry);
    }
  }

  // ── 집계 ──────────────────────────────────────────────────────
  const errors = samples.filter((s) => s.error);
  const withDelta = samples.filter((s) => s.scoreDelta !== undefined && s.scoreDelta !== null);
  const pitViolations = samples.filter((s) => !s.pitOk);
  const joinFull = samples.filter((s) => s.sdJoinFound === SD5D_WINDOW);
  const basisAdded = samples.filter((s) => s.supplyDemandAddedToBasis);
  const nonZeroDelta = withDelta.filter((s) => s.scoreDelta !== 0);
  const deltas = withDelta.map((s) => s.scoreDelta);

  const byTicker = {};
  for (const s of withDelta) {
    (byTicker[s.ticker] = byTicker[s.ticker] || []).push(s.scoreDelta);
  }
  const perTickerAvg = Object.fromEntries(
    Object.entries(byTicker).map(([t, arr]) => [t, Math.round((arr.reduce((a, b) => a + b, 0) / arr.length) * 100) / 100])
  );

  const byYear = {};
  for (const s of withDelta) {
    const y = s.asOf.slice(0, 4);
    (byYear[y] = byYear[y] || []).push(s.scoreDelta);
  }
  const perYearAvg = Object.fromEntries(
    Object.entries(byYear).map(([y, arr]) => [y, Math.round((arr.reduce((a, b) => a + b, 0) / arr.length) * 100) / 100])
  );

  const summary = {
    generatedAt: new Date().toISOString(),
    elapsedSec: Math.round((Date.now() - t0) / 100) / 10,
    universeSize: SAMPLE.length,
    snapshotDateCount: SNAPSHOT_DATES.length,
    dateRange: [SNAPSHOT_DATES[0], SNAPSHOT_DATES[SNAPSHOT_DATES.length - 1]],
    totalCells: samples.length,
    scoreErrors: errors.length,
    pitViolations: pitViolations.length,
    a4JoinFullWindowRate: Math.round((joinFull.length / samples.length) * 1000) / 1000,
    supplyDemandEnteredBasisRate: Math.round((basisAdded.length / withDelta.length) * 1000) / 1000,
    nonZeroScoreDeltaRate: Math.round((nonZeroDelta.length / withDelta.length) * 1000) / 1000,
    scoreDeltaMin: Math.min(...deltas),
    scoreDeltaMax: Math.max(...deltas),
    scoreDeltaMean: Math.round((deltas.reduce((a, b) => a + b, 0) / deltas.length) * 1000) / 1000,
    scoreDeltaStdDev: Math.round(Math.sqrt(deltas.reduce((s, d) => s + (d - deltas.reduce((a, b) => a + b, 0) / deltas.length) ** 2, 0) / deltas.length) * 1000) / 1000,
    perTickerAvgDelta: perTickerAvg,
    perYearAvgDelta: perYearAvg,
  };

  const outPath = path.join(ROOT, 'scratch-a4-supplydemand-vertical-slice.json');
  fs.writeFileSync(outPath, JSON.stringify({ summary, samples }, null, 0));
  console.log('결과 →', outPath, `(${samples.length}칸, ${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  console.log(JSON.stringify(summary, null, 2));
}

main();
