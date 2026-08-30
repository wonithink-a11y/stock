#!/usr/bin/env node
/**
 * 19개 scoring slot의 marginal contribution — 독립 분석 (production 정책 + 연구 데이터만 사용)
 *
 * node research/strategy-lab/slot_marginal_analysis.js
 *
 * 접근 (production 무수정):
 *   - lib/a5/resolver.js·lib/a5/technicalFrom.js·lib/scoringEngine.js·lib/loadCriteria.js를
 *     그대로 require한다 — 채점 공식·임계값·가중치는 모두 production과 동일.
 *   - config/criteria/policies는 읽기만, 수정하지 않는다.
 *   - 동일한 PIT snapshot(같은 ticker×asOf)에서 슬롯 조합만 바꾼 stockData로
 *     scoreStock()을 여러 번 부른다. 슬롯 off = stockData에서 해당 입력 필드 제거.
 *   - 최소 비교 4개(사용자 요구): base / base+foreign / base+inst / base+both.
 *     + full(17개 측정 슬롯)과 LOO(각 슬롯 제거)로 19개 슬롯의 marginal을 잰다.
 *
 * 미검증 슬롯: largeShareholderChange·buybackOrRetirement — 원자료 없음(A4 외 소스 없음).
 *   이 둘은 이 스크립트에서 제외하고 "미검증"으로 보고한다(효과없음 판정 금지).
 *
 * valuation 한계: A2a(수정주가)와 A3b(원본 EPS)·A3c(발행주식수)의 조정 기준 불일치
 *   (resolver.js valuationFrom 주석, 005930/2016 실측 per=0.197). A3c istcTotqy가
 *   연속 레코드 사이 ≥2배 점프한 corp는 액면분할 등 조정 불일치로 보고 valuation 슬롯을
 *   전체 null 처리(caExcluded). 그 외 corp는 잠정 측정 — perRelative·pbr·peg·marginOfSafety
 *   를 직접 계산해 넣고 한계를 결과에 기록한다.
 *
 * 출력: research/strategy-lab/findings/slot-marginal-contribution/snapshots.json
 */
'use strict';
const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..', '..');

const { resolve, fundamentalsFrom } = require(path.join(ROOT, 'lib/a5/resolver'));
const { scoreStock } = require(path.join(ROOT, 'lib/scoringEngine'));
const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));

const SAMPLE_SIZE = 120;
const SEED = 20260820;
const PRICE_YEARS = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026'];
const FUND_YEARS = ['2015', '2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025'];
const A4_YEARS = ['2016', '2017', '2018', '2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026'];
const HORIZONS = { d20: 20, d60: 60, d120: 120 };
const SD5D_WINDOW = 5;
const INSTITUTION_CATEGORIES = ['금융투자', '보험', '투신', '사모', '은행', '기타금융', '연기금', '기타법인'];

const criteria = loadCriteria('KR').criteria;

function readGzJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean);
}

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
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
  if (window.length === 0) return undefined;
  let daysBuy = 0;
  for (const r of window) if (netOf(r, categories) > 0) daysBuy++;
  const total = window.length;
  if (daysBuy === total) return 'consistentBuy';
  if (daysBuy === 0) return 'consistentSell';
  if (daysBuy > total / 2) return 'netBuy';
  if (daysBuy < total / 2) return 'netSell';
  return 'neutral';
}

/** corp의 A3c istcTotqy가 연속 레코드 사이 ≥2배 변한 적이 있는가 (액면분할 등) */
function detectCorpActions(a3cRecords) {
  const sorted = [...a3cRecords].sort((a, b) => (a.availableFrom < b.availableFrom ? -1 : a.availableFrom > b.availableFrom ? 1 : 0));
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1].istcTotqy, cur = sorted[i].istcTotqy;
    if (typeof prev === 'number' && typeof cur === 'number' && prev > 0) {
      const ratio = cur / prev;
      if (ratio >= 2 || ratio <= 0.5) return true;
    }
  }
  return false;
}

function main() {
  const t0 = Date.now();
  const cal = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/calendar.json'), 'utf8'));
  const tradingDays = cal.tradingDays;
  const tradingDayIdx = new Map(tradingDays.map((d, i) => [d, i]));
  const SNAPSHOT_DATES = Object.values(cal.monthFirst).filter((d) => d >= '2016-01-01' && d <= '2026-08-31');

  const universe = readGzJsonl('data/backfill/universe/a1a/current.jsonl').map((l) => JSON.parse(l));
  console.error(`유니버스 ${universe.length}종목. 데이터 보유 종목으로 샘플링...`);

  // 데이터 보유 판별: A4(ticker) / A3·A3b·A3c(corp) — 있는 종목만 샘플 풀
  const a4Tickers = new Set();
  for (const y of A4_YEARS) {
    const rel = `data/backfill/supplyDemand/a4/${y}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, rel))) continue;
    for (const line of readGzJsonl(rel)) {
      const m = line.match(/"ticker":\s*"(\d{6})"/);
      if (m) a4Tickers.add(m[1]);
    }
  }
  const fundCorps = new Set();
  for (const y of FUND_YEARS) {
    for (const p of [`a3`, `a3b`, `a3c`]) {
      const rel = `data/backfill/fundamentals/${p}/${y}.jsonl.gz`;
      if (!fs.existsSync(path.join(ROOT, rel))) continue;
      for (const line of readGzJsonl(rel)) {
        const m = line.match(/"corp":\s*"(\d{8})"/);
        if (m) fundCorps.add(m[1]);
      }
    }
  }
  console.error(`A4 ticker ${a4Tickers.size}개, fundamental corp ${fundCorps.size}개`);

  const eligible = universe.filter((u) => a4Tickers.has(u.ticker) && fundCorps.has(u.corp));
  console.error(`전체 데이터 보유 종목 ${eligible.length}개`);

  const rnd = mulberry32(SEED);
  const shuffled = [...eligible].sort(() => rnd() - 0.5);
  const sample = shuffled.slice(0, SAMPLE_SIZE);
  const tickers = new Set(sample.map((s) => s.ticker));
  const corps = new Set(sample.map((s) => s.corp));
  console.error(`샘플 ${sample.length}종목 (seed=${SEED})`);

  console.error('색인 구축 중...');
  const priceIdx = buildTickerIndex('data/backfill/price/a2a/{year}.jsonl.gz', PRICE_YEARS, tickers, 'ticker');
  const a3Idx = buildTickerIndex('data/backfill/fundamentals/a3/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a3bIdx = buildTickerIndex('data/backfill/fundamentals/a3b/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a3cIdx = buildTickerIndex('data/backfill/fundamentals/a3c/{year}.jsonl.gz', FUND_YEARS, corps, 'corp');
  const a4Idx = buildTickerIndex('data/backfill/supplyDemand/a4/{year}.jsonl.gz', A4_YEARS, tickers, 'ticker');

  const priceByDate = new Map();
  for (const [ticker, arr] of priceIdx) {
    const m = new Map();
    for (const r of arr) m.set(r.date, r.close);
    priceByDate.set(ticker, m);
  }

  // corp action 판별
  const caSet = new Set();
  for (const { corp } of sample) if (detectCorpActions(a3cIdx.get(corp) || [])) caSet.add(corp);
  console.error(`corp action(발행주식수 ≥2배 점프) 종목 ${caSet.size}/${sample.length} — valuation 슬롯 제외`);

  // ── snapshot 생성 ──
  const rows = [];
  let snap = 0;
  for (const { ticker, corp, name } of sample) {
    const priceArr = priceIdx.get(ticker) || [];
    const a3records = a3Idx.get(corp) || [];
    const a3bRecords = a3bIdx.get(corp) || [];
    const a3cRecords = a3cIdx.get(corp) || [];
    const a4arr = a4Idx.get(ticker) || [];
    const closeMap = priceByDate.get(ticker) || new Map();
    const isCA = caSet.has(corp);

    for (const asOf of SNAPSHOT_DATES) {
      const price = priceArr.find((r) => r.date === asOf) || null;
      const candles = priceArr.filter((r) => r.date <= asOf).slice(-260).map((r) => ({ date: r.date, close: r.close, volume: r.volume }));

      const resolved = resolve({ ticker, corp, asOf, fundamentals: a3records, price, dividendEps: a3bRecords, candles });
      const f = fundamentalsFrom(a3records, asOf);
      const sicCode = (f.history[0] && f.history[0].sicCode) || null;

      // valuation (잠정 측정) — A3b PIT eps·A3 PIT equity·A3c PIT istcTotqy
      let per = null, epsGrowthRate = null, pbr = null, peg = null, marginOfSafety = null;
      if (!isCA && price && typeof price.close === 'number' && price.close > 0) {
        const cur3b = latestBefore(a3bRecords, asOf);
        const prev3b = latestBefore(a3bRecords.filter((r) => r.fiscalYear < (cur3b ? cur3b.fiscalYear : 9999)), asOf);
        if (cur3b && typeof cur3b.eps === 'number' && cur3b.eps > 0) {
          per = price.close / cur3b.eps;
          if (prev3b && typeof prev3b.eps === 'number' && prev3b.eps !== 0) {
            epsGrowthRate = (cur3b.eps / prev3b.eps - 1) * 100;
          }
        }
        const cur3 = latestBefore(a3records, asOf);
        const cur3c = latestBefore(a3cRecords, asOf);
        if (cur3 && typeof cur3.equity === 'number' && cur3.equity > 0
            && cur3c && typeof cur3c.istcTotqy === 'number' && cur3c.istcTotqy > 0) {
          const bps = cur3.equity / cur3c.istcTotqy;
          if (bps > 0) pbr = price.close / bps;
        }
        if (per !== null && epsGrowthRate !== null && epsGrowthRate > 0) peg = per / epsGrowthRate;
        if (per !== null && per > 0 && pbr !== null && pbr > 0) marginOfSafety = 1 - Math.sqrt((per * pbr) / 22.5);
      }

      const sdWindow = a4arr.filter((r) => r.date <= asOf).slice(-SD5D_WINDOW);
      const foreignTrend = trendFromWindow(sdWindow, ['외국인']);
      const institutionTrend = trendFromWindow(sdWindow, INSTITUTION_CATEGORIES);

      const asOfIdx = tradingDayIdx.get(asOf);
      const asOfClose = closeMap.get(asOf);
      const forwardReturns = {};
      if (asOfIdx !== undefined && typeof asOfClose === 'number' && asOfClose > 0) {
        for (const [h, n] of Object.entries(HORIZONS)) {
          const futureDate = tradingDays[asOfIdx + n];
          if (!futureDate) continue;
          const futureClose = closeMap.get(futureDate);
          if (typeof futureClose === 'number') forwardReturns[h] = (futureClose - asOfClose) / asOfClose;
        }
      }

      rows.push({
        ticker, corp, name, date: asOf, sicCode, caExcluded: isCA,
        per, epsGrowthRate, pbr, peg, marginOfSafety,
        foreignTrend, institutionTrend,
        forwardReturns,
        fundamentals: resolved.stockData.fundamental || {},
        technical: resolved.stockData.technical || {},
        scoreBase: null, scoreForeign: null, scoreInst: null, scoreBoth: null,
      });
      snap++;
    }
  }
  console.error(`snapshot ${snap}건 생성 (${((Date.now() - t0) / 1000).toFixed(1)}s)`);

  // perRelative — 같은 날짜·같은 sic2 업종평균 대비
  const perRelativeMap = new Map();
  {
    const byDateSic = new Map();
    for (const r of rows) {
      if (r.per === null || r.per === undefined || !r.sicCode) continue;
      const key = `${r.date}|${String(r.sicCode).slice(0, 2)}`;
      const e = byDateSic.get(key) || { sum: 0, n: 0 };
      e.sum += r.per; e.n += 1;
      byDateSic.set(key, e);
    }
    for (const r of rows) {
      if (r.per === null || r.per === undefined || !r.sicCode) { perRelativeMap.set(`${r.ticker}|${r.date}`, null); continue; }
      const key = `${r.date}|${String(r.sicCode).slice(0, 2)}`;
      const e = byDateSic.get(key);
      if (!e || e.n < 5) { perRelativeMap.set(`${r.ticker}|${r.date}`, null); continue; }
      perRelativeMap.set(`${r.ticker}|${r.date}`, r.per / (e.sum / e.n));
    }
  }

  // ── config별 점수 ──
  // base stockData = resolver가 만든 것 그대로(fundamental+technical). 여기에 슬롯을 더/빼며 채점.
  const configNames = ['base', 'base_foreign', 'base_inst', 'base_both', 'full'];
  const looSlots = [
    'roe', 'roeConsistency', 'debtRatio', 'currentRatio', 'operatingMarginTrend', 'revenueGrowthYoY', 'shareholderReturn',
    'perRelative', 'pbr', 'peg', 'marginOfSafety',
    'movingAverageCross', 'rsi', 'macd', 'volumeConfirmation',
    'foreignNetBuy5d', 'institutionNetBuy5d',
  ];
  const configs = {};
  for (const c of configNames) configs[c] = [];
  for (const s of looSlots) configs[`loo_${s}`] = [];

  function scoreFor(stockData) {
    return scoreStock(stockData, criteria);
  }

  for (const r of rows) {
    const base = { ticker: r.ticker, name: r.name, dataCutoff: r.date, state: null, fundamental: r.fundamentals, technical: r.technical };
    const perRel = perRelativeMap.get(`${r.ticker}|${r.date}`);

    const valuationFull = {};
    if (perRel !== null) valuationFull.perRelative = perRel;
    if (r.pbr !== null) valuationFull.pbr = r.pbr;
    if (r.peg !== null) valuationFull.peg = r.peg;
    if (r.marginOfSafety !== null) valuationFull.marginOfSafety = r.marginOfSafety;

    const withSD = (s) => ({ ...base, fundamental: { ...base.fundamental }, technical: { ...base.technical }, supplyDemand: { ...s } });
    const withFull = (s) => ({ ...base, fundamental: { ...base.fundamental }, technical: { ...base.technical }, supplyDemand: { ...s }, valuation: { ...valuationFull } });

    const sdForeign = { foreignTrend5d: r.foreignTrend };
    const sdInst = { institutionTrend5d: r.institutionTrend };
    const sdBoth = { foreignTrend5d: r.foreignTrend, institutionTrend5d: r.institutionTrend };

    const collect = (result) => ({
      score: result.totalScore,
      grade: result.grade,
      coverage: result.dataCoverage ? result.dataCoverage.overall : null,
    });

    configs.base.push(collect(scoreFor(base)));
    configs.base_foreign.push(collect(scoreFor(withSD(sdForeign))));
    configs.base_inst.push(collect(scoreFor(withSD(sdInst))));
    configs.base_both.push(collect(scoreFor(withSD(sdBoth))));
    configs.full.push(collect(scoreFor(withFull(sdBoth))));

    // LOO — full에서 각 슬롯의 입력 필드 제거
    const fundamentalKeys = {
      roe: 'roe', roeConsistency: 'roeHistory5y', debtRatio: 'debtRatio', currentRatio: 'currentRatio',
      operatingMarginTrend: 'operatingMarginTrend', revenueGrowthYoY: 'revenueGrowthYoY', shareholderReturn: 'buybackOrDividendHistory',
    };
    const technicalKeys = { movingAverageCross: 'maSignal', rsi: 'rsi', macd: 'macdSignal', volumeConfirmation: 'volumeConfirmed' };
    const valuationKeys = { perRelative: 'perRelative', pbr: 'pbr', peg: 'peg', marginOfSafety: 'marginOfSafety' };
    const sdKeys = { foreignNetBuy5d: 'foreignTrend5d', institutionNetBuy5d: 'institutionTrend5d' };

    for (const slot of looSlots) {
      const stockData = withFull(sdBoth);
      if (fundamentalKeys[slot]) delete stockData.fundamental[fundamentalKeys[slot]];
      else if (technicalKeys[slot]) delete stockData.technical[technicalKeys[slot]];
      else if (valuationKeys[slot]) delete stockData.valuation[valuationKeys[slot]];
      else if (sdKeys[slot]) delete stockData.supplyDemand[sdKeys[slot]];
      configs[`loo_${slot}`].push(collect(scoreFor(stockData)));
    }
  }

  const outDir = path.join(ROOT, 'research', 'strategy-lab', 'findings', 'slot-marginal-contribution');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, 'snapshots-seed2.json');
  fs.writeFileSync(outPath, JSON.stringify({
    generatedAt: new Date().toISOString(),
    seed: SEED, sampleSize: sample.length, snapshotCount: rows.length,
    caExcludedCount: caSet.size,
    configs, rows,
  }, null, 0));
  console.log('결과 →', outPath, `(${((Date.now() - t0) / 1000).toFixed(1)}s)`);
}

/** availableFrom(asOf 기준 미래 아님)의 최신 레코드 — availableFrom은 YYYYMMDD 또는 YYYY-MM-DD */
function latestBefore(records, asOf) {
  const norm = (d) => String(d).replace(/-/g, '');
  let best = null;
  for (const r of records) {
    if (!r.availableFrom) continue;
    if (norm(r.availableFrom) <= norm(asOf)) best = r;
  }
  return best;
}

main();