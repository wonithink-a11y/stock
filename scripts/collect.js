/**
 * collect.js (v3 - 일봉 시계열 저장 추가)
 *
 * 관심종목(한국+미국)의 시세·밸류에이션·기술지표·수급 데이터를 수집해
 * data/inputs.json 으로 저장합니다 (analyze.js의 입력).
 *
 * ── v2 → v3 변경점 ──────────────────────────────────────────────
 * (1) 일봉 시계열(OHLCV) 저장 [기능]  ★ 이번 수정의 핵심
 *     v2까지는 fchart/stooq에서 받은 일봉에서 종가·거래량만 뽑아 기술지표를
 *     계산하고 나머지(시가·고가·저가·시계열 전체)를 버렸습니다. 그 결과 대시보드는
 *     "현재가 1개"만 알 수 있어 주가 변화·차트를 그릴 수 없었습니다.
 *     이제 종목마다 최근 CANDLE_KEEP(기본 120)일의 OHLCV를 compact 형태
 *     (d/o/h/l/c/v)로 stocks[].candles 에 실어 보냅니다.
 *     - 추가 네트워크 호출 0 (이미 받던 데이터를 저장만 함)
 *     - 수집 실패 시 직전 inputs.json의 candles로 폴백
 *     - analyze.js가 이 candles로 docs/data/prices.json 을 만듭니다.
 *
 * 데이터 소스:
 *  [한국 KR] 일봉/현재가: fchart.stock.naver.com | PER/PBR·수급: m.stock.naver.com
 *  [미국 US] 일봉/현재가: stooq.com CSV | PER/PBR: config/fundamentals.json 수동
 *  [공통]    재무: config/fundamentals.json (fetch-fundamentals-kr.js 분기 갱신)
 *
 * 설계 원칙: 수집 실패는 에러로 죽지 않고 해당 필드를 결측(null)으로 남깁니다.
 */

const fs = require('fs');
const path = require('path');
const { resolveSector } = require('../lib/sectorResolver');

const ROOT = path.join(__dirname, '..');
const DATA_DIR = path.join(ROOT, 'data');
const INPUTS_PATH = path.join(DATA_DIR, 'inputs.json');

const UA = { 'User-Agent': 'Mozilla/5.0 (compatible; stock-scoring-app)' };

// ---------- 수집 파라미터 ----------
const REQUEST_DELAY_MS = Number(process.env.COLLECT_DELAY_MS || 1500); // 종목 사이 간격
const INTRA_DELAY_MS = Number(process.env.COLLECT_INTRA_DELAY_MS || 600); // 한 종목 내 요청 사이 간격
const MAX_RETRIES = Number(process.env.COLLECT_MAX_RETRIES || 4);
const TIMEOUT_MS = Number(process.env.COLLECT_TIMEOUT_MS || 15000);
const RETRY_BASE_MS = 1500; // 지수 백오프 기준값 (1.5s → 3s → 6s, 429는 ×3)
// [v3.1] inputs.json / prices.json 에 저장할 일봉 개수.
//  - CANDLE_FETCH: fchart/stooq에서 받아올 개수(260 ≈ 1년 거래일). 기술지표+1년 수익률용.
//  - CANDLE_KEEP:  저장 개수(250). 1D/1W/1M/3M/6M/1Y/YTD 등락률과 차트 기간 토글(전체=1년)에 사용.
//  파일 크기: 100종목×250일이면 prices.json ≈ 2MB 안팎(CDN 배포에 무리 없음).
const CANDLE_FETCH = Number(process.env.COLLECT_CANDLE_FETCH || 260);
const CANDLE_KEEP = Number(process.env.COLLECT_CANDLE_KEEP || 250);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 수집 실패 집계 (마지막에 요약 출력)
const failures = [];
function noteFailure(scope, target, message) {
  failures.push({ scope, target, message });
}

// ---------- 재시도·타임아웃이 붙은 fetch ----------

function isRetriable(status) {
  if (status === undefined) return true; // 네트워크 오류
  if (status === 429) return true; // 요청 과다 - 백오프 대상
  return status >= 500;
}

async function fetchWithRetry(url, parse) {
  let lastErr;
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(url, { headers: UA, signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) {
        const err = new Error(`HTTP ${res.status}`);
        err.status = res.status;
        throw err;
      }
      return await parse(res);
    } catch (e) {
      clearTimeout(timer);
      lastErr = e;
      const status = e.status;
      if (!isRetriable(status) || attempt === MAX_RETRIES) break;
      const wait = RETRY_BASE_MS * Math.pow(2, attempt - 1) * (status === 429 ? 3 : 1);
      await sleep(wait);
    }
  }
  throw lastErr;
}

const fetchText = (url) => fetchWithRetry(url, (res) => res.text());
const fetchJson = (url) => fetchWithRetry(url, (res) => res.json());

// ---------- 일봉 수집: 한국 (fchart: XML 형태) ----------
// [v3] open/high/low 도 함께 보존 (v2는 close/volume만 남겼음)

async function fetchDailyCandlesKR(symbol, count = 140) {
  const url = `https://fchart.stock.naver.com/sise.nhn?symbol=${symbol}&timeframe=day&count=${count}&requestType=0`;
  const xml = await fetchText(url);
  const candles = [];
  const re = /<item data="([^"]+)"\s*\/>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const [date, open, high, low, close, volume] = m[1].split('|');
    candles.push({
      date,
      open: Number(open),
      high: Number(high),
      low: Number(low),
      close: Number(close),
      volume: Number(volume),
    });
  }
  if (candles.length === 0) throw new Error(`일봉 파싱 실패: ${symbol}`);
  return candles; // 과거 → 최신 순
}

// ---------- 일봉 수집: 미국 (stooq CSV) ----------

async function fetchDailyCandlesUS(ticker, count = 140) {
  const symbol = ticker.startsWith('^') ? ticker : `${ticker.toLowerCase()}.us`;
  const url = `https://stooq.com/q/d/l/?s=${encodeURIComponent(symbol)}&i=d`;
  const csv = await fetchText(url);
  const lines = csv.trim().split('\n');
  if (lines.length < 2 || !lines[0].startsWith('Date')) throw new Error(`CSV 파싱 실패: ${ticker}`);
  const candles = lines
    .slice(1)
    .map((line) => {
      const [date, open, high, low, close, volume] = line.split(',');
      return {
        date: date.replace(/-/g, ''),
        open: Number(open),
        high: Number(high),
        low: Number(low),
        close: Number(close),
        volume: Number(volume) || 0,
      };
    })
    .filter((c) => !Number.isNaN(c.close));
  if (candles.length === 0) throw new Error(`일봉 데이터 없음: ${ticker}`);
  return candles.slice(-count); // 과거 → 최신 순
}

// [v3] 저장용 compact 변환 (키를 1글자로 줄여 파일 크기 절약)
function toCompactCandles(candles, keep = CANDLE_KEEP) {
  return candles.slice(-keep).map((c) => ({
    d: c.date,
    o: c.open,
    h: c.high,
    l: c.low,
    c: c.close,
    v: c.volume,
  }));
}

// ---------- 기술지표 계산 (시장 공통) ----------

function sma(values, period, offset = 0) {
  const end = values.length - offset;
  const slice = values.slice(end - period, end);
  if (slice.length < period) return null;
  return slice.reduce((a, b) => a + b, 0) / period;
}

function computeMaSignal(closes) {
  const ma20 = sma(closes, 20);
  const ma60 = sma(closes, 60);
  const ma20Prev = sma(closes, 20, 1);
  const ma60Prev = sma(closes, 60, 1);
  if (ma20 === null || ma60 === null) return null;
  if (ma20Prev !== null && ma60Prev !== null) {
    if (ma20Prev <= ma60Prev && ma20 > ma60) return 'goldenCross';
    if (ma20Prev >= ma60Prev && ma20 < ma60) return 'deadCross';
  }
  const last = closes[closes.length - 1];
  if (last > ma20 && last > ma60) return 'aboveBothMA';
  if (last < ma20 && last < ma60) return 'belowBothMA';
  return ma20 > ma60 ? 'aboveBothMA' : 'belowBothMA';
}

function computeRsi(closes, period = 14) {
  if (closes.length < period + 1) return null;
  let gain = 0;
  let loss = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    if (diff > 0) gain += diff;
    else loss -= diff;
  }
  if (gain + loss === 0) return 50;
  const rs = loss === 0 ? Infinity : gain / loss;
  return Math.round((100 - 100 / (1 + rs)) * 10) / 10;
}

function ema(values, period) {
  const k = 2 / (period + 1);
  let e = values[0];
  const out = [e];
  for (let i = 1; i < values.length; i++) {
    e = values[i] * k + e * (1 - k);
    out.push(e);
  }
  return out;
}

function computeMacdSignal(closes) {
  if (closes.length < 35) return null;
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdLine = ema12.map((v, i) => v - ema26[i]);
  const signalLine = ema(macdLine, 9);
  const n = macdLine.length;
  const diffNow = macdLine[n - 1] - signalLine[n - 1];
  const diffPrev = macdLine[n - 2] - signalLine[n - 2];
  if (diffPrev <= 0 && diffNow > 0) return 'bullishCross';
  if (diffPrev >= 0 && diffNow < 0) return 'bearishCross';
  return 'neutral';
}

function computeTechnical(candles) {
  const closes = candles.map((c) => c.close);
  const volumes = candles.map((c) => c.volume);
  const last = candles[candles.length - 1];

  const avgVol20 = sma(volumes, 20, 1); // 당일 제외 20일 평균
  const volumeConfirmed = avgVol20 !== null && avgVol20 > 0 ? last.volume >= avgVol20 * 1.5 : undefined;

  const close5Ago = closes.length >= 6 ? closes[closes.length - 6] : null;
  const priceDropPct = close5Ago ? Math.round(((last.close - close5Ago) / close5Ago) * 1000) / 10 : undefined;
  const reboundVolumeConfirmed = volumeConfirmed === undefined ? undefined : volumeConfirmed;

  return {
    maSignal: computeMaSignal(closes),
    rsi: computeRsi(closes),
    macdSignal: computeMacdSignal(closes),
    volumeConfirmed,
    priceDropPct,
    reboundVolumeConfirmed,
    currentPrice: last.close,
    lastDate: last.date,
  };
}

// ---------- 밸류에이션: 한국 (네이버 모바일 API) ----------

async function fetchValuationInfoKR(code) {
  const out = { per: null, pbr: null, industryPer: null, ok: false };
  const toNum = (v) => parseFloat(String(v).replace(/[,배%\s]/g, ''));
  try {
    const data = await fetchJson(`https://m.stock.naver.com/api/stock/${code}/integration`);
    const infos = data.totalInfos || [];
    for (const info of infos) {
      const value = toNum(info.value);
      if (Number.isNaN(value)) continue;
      if (info.code === 'per') out.per = value;
      else if (info.code === 'pbr') out.pbr = value;
      // 동일업종 PER: 네이버 필드명이 버전마다 달라 코드/라벨을 방어적으로 탐색
      else if (/industry.*per|sameindustry.*per|upjong.*per/i.test(info.code || '') ||
               /동일\s*업종\s*per/i.test(`${info.key || ''}${info.name || ''}${info.title || ''}`)) {
        out.industryPer = value;
      }
    }
    out.ok = true;
  } catch (e) {
    console.warn(`  [경고] ${code} 밸류에이션 수집 실패: ${e.message}`);
    noteFailure('valuation', code, e.message);
  }
  // 통합 API에 동일업종 PER이 없으면 데스크톱 종목 페이지 HTML에서 폴백 추출.
  // (네이버 데스크톱은 EUC-KR 인코딩이라 UTF-8로 읽으면 한글이 깨져 매칭 실패 → 바이트를 EUC-KR로 디코드)
  if (out.industryPer === null) {
    try {
      const html = await fetchWithRetry(
        `https://finance.naver.com/item/main.naver?code=${code}`,
        async (res) => new TextDecoder('euc-kr').decode(Buffer.from(await res.arrayBuffer()))
      );
      const m = html.match(/동일업종\s*PER[\s\S]{0,240}?(-?[\d,]+\.\d+)\s*배/);
      if (m) { const v = toNum(m[1]); if (!Number.isNaN(v) && v > 0) out.industryPer = v; }
    } catch (e) {
      noteFailure('industryPer', code, e.message);
    }
  }
  return out;
}

// ---------- 수급: 한국 (외국인/기관 5일 추세) ----------

function netBuysToTrend(netBuys) {
  if (!netBuys || netBuys.length === 0) return null;
  const buyDays = netBuys.filter((v) => v > 0).length;
  const total = netBuys.reduce((a, b) => a + b, 0);
  if (buyDays === netBuys.length) return 'consistentBuy';
  if (buyDays === 0) return 'consistentSell';
  if (total > 0) return 'netBuy';
  if (total < 0) return 'netSell';
  return 'neutral';
}

async function fetchSupplyDemandKR(code) {
  try {
    const data = await fetchJson(`https://m.stock.naver.com/api/stock/${code}/trend?pageSize=5&page=1`);
    const rows = Array.isArray(data) ? data : data.trends || data.result || [];
    const parseNum = (v) => Number(String(v).replace(/,/g, ''));
    const foreign = rows.map((r) => parseNum(r.foreignerPureBuyQuant ?? r.frgn_qty ?? NaN)).filter((v) => !Number.isNaN(v));
    const organ = rows.map((r) => parseNum(r.organPureBuyQuant ?? r.orgn_qty ?? NaN)).filter((v) => !Number.isNaN(v));
    return {
      foreignTrend5d: netBuysToTrend(foreign),
      institutionTrend5d: netBuysToTrend(organ),
    };
  } catch (e) {
    console.warn(`  [경고] ${code} 수급 수집 실패: ${e.message}`);
    noteFailure('supplyDemand', code, e.message);
    return { foreignTrend5d: null, institutionTrend5d: null };
  }
}

// ---------- 벤치마크 지수 ----------

async function fetchKospiClose() {
  try {
    const candles = await fetchDailyCandlesKR('KOSPI', 5);
    return candles[candles.length - 1].close;
  } catch (e) {
    console.warn(`  [경고] KOSPI 지수 수집 실패: ${e.message}`);
    noteFailure('index', 'KOSPI', e.message);
    return null;
  }
}

async function fetchSpxClose() {
  try {
    const candles = await fetchDailyCandlesUS('^spx', 5);
    return candles[candles.length - 1].close;
  } catch (e) {
    console.warn(`  [경고] S&P500 지수 수집 실패: ${e.message}`);
    noteFailure('index', 'SPX', e.message);
    return null;
  }
}

// ---------- 환율 (국면 판단용) ----------

async function fetchUsdKrw() {
  try {
    const data = await fetchJson('https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW&page=1&pageSize=21');
    const rows = data.result || [];
    if (rows.length === 0) return null;
    const parse = (v) => Number(String(v).replace(/,/g, ''));
    const latest = parse(rows[0].closePrice);
    const past = rows.length >= 21 ? parse(rows[rows.length - 1].closePrice) : null;
    return {
      usdKrwLevel: latest,
      usdKrw20dChangePct: past ? Math.round(((latest - past) / past) * 1000) / 10 : null,
    };
  } catch (e) {
    console.warn(`  [경고] 환율 수집 실패: ${e.message}`);
    noteFailure('fx', 'USDKRW', e.message);
    return null;
  }
}

// ---------- 업종 해석 ----------

function resolveSectorFor(t, fund, market) {
  if (market === 'US') {
    return { sectorType: 'general', sectorResolved: true };
  }
  if (fund.sectorType) {
    return {
      sectorType: fund.sectorType,
      sectorResolved: fund.sectorResolved !== undefined ? fund.sectorResolved : true,
    };
  }
  try {
    const r = resolveSector({ ticker: t.code, name: t.name, sicCode: fund.sicCode });
    for (const w of r.warnings) console.warn(`  [업종] ${w.message}`);
    return { sectorType: r.sectorType, sectorResolved: r.resolved };
  } catch (e) {
    console.warn(`  [경고] ${t.code} 업종 해석 실패(general로 진행): ${e.message}`);
    noteFailure('sector', t.code, e.message);
    return { sectorType: 'general', sectorResolved: false };
  }
}

// ---------- 종목 1건 수집 ----------

async function collectOne(t, fundamentals, prevByTicker) {
  const market = t.market || 'KR';
  const fund = fundamentals.byTicker[t.code] || {};
  const prev = prevByTicker[t.code] || null;

  let technical = {};
  let candlesOk = false;
  let candles = []; // [v3] 저장용 compact 일봉 시계열
  try {
    const rawCandles = market === 'US' ? await fetchDailyCandlesUS(t.code, CANDLE_FETCH) : await fetchDailyCandlesKR(t.code, CANDLE_FETCH);
    technical = computeTechnical(rawCandles);
    candles = toCompactCandles(rawCandles); // [v3]
    candlesOk = true;
  } catch (e) {
    console.warn(`  [경고] ${t.code} 일봉 수집 실패: ${e.message}`);
    noteFailure('candles', t.code, e.message);
    // 폴백: 직전 실행 결과의 기술지표·시계열을 그대로 사용 (하루 사이 크게 변하지 않음)
    if (prev && prev.technical) {
      technical = { ...prev.technical, currentPrice: prev.meta && prev.meta.currentPrice, lastDate: prev.meta && prev.meta.lastDate };
      console.warn(`  [폴백] ${t.code} 직전 일봉 데이터 사용 (${technical.lastDate})`);
    }
    if (prev && Array.isArray(prev.candles)) candles = prev.candles; // [v3] 시계열도 폴백
  }

  let per = null;
  let pbr = null;
  let industryPer = null;
  let supplyDemand = { foreignTrend5d: null, institutionTrend5d: null };

  if (market === 'US') {
    per = fund.per ?? null;
    pbr = fund.pbr ?? null;
  } else {
    await sleep(INTRA_DELAY_MS);
    const valuationInfo = await fetchValuationInfoKR(t.code);
    per = valuationInfo.per;
    pbr = valuationInfo.pbr;
    industryPer = valuationInfo.industryPer;
    if (!valuationInfo.ok && prev && prev.valuation) {
      per = prev.valuation.per ?? null;
      pbr = prev.valuation.pbr ?? null;
    }
    await sleep(INTRA_DELAY_MS);
    supplyDemand = await fetchSupplyDemandKR(t.code);
  }

  // PER 업종평균 대비 배율: 동일업종 PER을 받았으면 개별PER/업종PER, 없으면 재무파일 값 폴백
  const perRelative =
    typeof per === 'number' && per > 0 && typeof industryPer === 'number' && industryPer > 0
      ? Math.round((per / industryPer) * 1000) / 1000
      : (fund.perRelative ?? null);

  const sector = resolveSectorFor(t, fund, market);

  return {
    ok: candlesOk,
    stock: {
      ticker: t.code,
      name: t.name,
      market,
      fundamental: {
        roe: fund.roe,
        roeHistory5y: fund.roeHistory5y,
        debtRatio: fund.debtRatio,
        currentRatio: fund.currentRatio,
        operatingMarginTrend: fund.operatingMarginTrend,
        revenueGrowthYoY: fund.revenueGrowthYoY,
        buybackOrDividendHistory: fund.buybackOrDividendHistory,
        debtRatioRaw: fund.debtRatioRaw,
        sectorType: sector.sectorType,
        sectorResolved: sector.sectorResolved,
      },
      valuation: {
        perRelative,
        industryPer,
        pbr,
        per,
        epsGrowthRate: fund.epsGrowthRate,
        currentPrice: technical.currentPrice,
      },
      technical: {
        maSignal: technical.maSignal,
        rsi: technical.rsi,
        macdSignal: technical.macdSignal,
        volumeConfirmed: technical.volumeConfirmed,
        priceDropPct: technical.priceDropPct,
        reboundVolumeConfirmed: technical.reboundVolumeConfirmed,
      },
      supplyDemand: {
        foreignTrend5d: supplyDemand.foreignTrend5d,
        institutionTrend5d: supplyDemand.institutionTrend5d,
      },
      // [v3] 대시보드 스파크라인·차트용 일봉 시계열 (compact: d/o/h/l/c/v, 최근 CANDLE_KEEP일)
      candles,
      meta: {
        currentPrice: technical.currentPrice ?? null,
        lastDate: technical.lastDate ?? null,
        groups: t.groups || [],
        market,
      },
    },
  };
}

// ---------- 메인 ----------

async function main() {
  const watchlist = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'watchlist.json'), 'utf-8'));
  const fundamentals = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'fundamentals.json'), 'utf-8'));

  fs.mkdirSync(DATA_DIR, { recursive: true });

  let prevByTicker = {};
  try {
    if (fs.existsSync(INPUTS_PATH)) {
      const prev = JSON.parse(fs.readFileSync(INPUTS_PATH, 'utf-8'));
      prevByTicker = Object.fromEntries((prev.stocks || []).map((s) => [s.ticker, s]));
    }
  } catch (e) {
    console.warn(`[경고] 직전 inputs.json 로드 실패(폴백 비활성): ${e.message}`);
  }

  const tickers = watchlist.tickers || [];
  const stocks = [];
  const retryQueue = [];

  console.log(`수집 시작: ${tickers.length}종목 (딜레이 ${REQUEST_DELAY_MS}ms, 재시도 ${MAX_RETRIES}회, 일봉저장 ${CANDLE_KEEP}일)`);
  const startedAt = Date.now();

  for (let i = 0; i < tickers.length; i++) {
    const t = tickers[i];
    console.log(`[${i + 1}/${tickers.length}] ${t.name} (${t.code}, ${t.market || 'KR'})`);
    const r = await collectOne(t, fundamentals, prevByTicker);
    stocks.push(r.stock);
    if (!r.ok) retryQueue.push({ index: stocks.length - 1, ticker: t });
    if (i < tickers.length - 1) await sleep(REQUEST_DELAY_MS);
  }

  if (retryQueue.length > 0) {
    console.log(`\n2차 재시도: ${retryQueue.length}종목 (일봉 실패분)`);
    await sleep(3000);
    for (const { index, ticker } of retryQueue) {
      console.log(`  재시도: ${ticker.name} (${ticker.code})`);
      const r = await collectOne(ticker, fundamentals, prevByTicker);
      if (r.ok) {
        stocks[index] = r.stock;
        console.log(`  ✓ ${ticker.code} 복구`);
      }
      await sleep(REQUEST_DELAY_MS * 2);
    }
  }

  const kospiClose = await fetchKospiClose();
  await sleep(INTRA_DELAY_MS);
  const spxClose = await fetchSpxClose();
  await sleep(INTRA_DELAY_MS);
  const fx = await fetchUsdKrw();

  const elapsed = Math.round((Date.now() - startedAt) / 1000);

  const sectorCount = {};
  let unresolved = 0;
  let withCandles = 0;
  for (const s of stocks) {
    const st = (s.fundamental && s.fundamental.sectorType) || 'general';
    sectorCount[st] = (sectorCount[st] || 0) + 1;
    if (s.fundamental && s.fundamental.sectorResolved === false) unresolved++;
    if (Array.isArray(s.candles) && s.candles.length) withCandles++;
  }

  const output = {
    collectedAt: new Date().toISOString(),
    kospiClose,
    spxClose,
    fx,
    stocks,
    _diagnostics: {
      elapsedSec: elapsed,
      requested: tickers.length,
      collected: stocks.length,
      candleFailures: retryQueue.length,
      withCandles, // [v3] 시계열이 채워진 종목 수
      unresolvedSector: unresolved,
      sectorCount,
      failures: failures.slice(0, 50),
    },
  };
  fs.writeFileSync(INPUTS_PATH, JSON.stringify(output, null, 2), 'utf-8');

  console.log(`\n완료: ${stocks.length}개 종목 → data/inputs.json (${elapsed}초)`);
  console.log(`일봉 시계열: ${withCandles}/${stocks.length}종목 저장`);
  console.log(`업종 분포: ${JSON.stringify(sectorCount)}`);
  if (unresolved > 0) console.log(`⚠ 업종 미분류 ${unresolved}종목 — config/sector-map.json 확인 필요`);
  if (failures.length > 0) {
    console.log(`⚠ 수집 경고 ${failures.length}건`);
    for (const f of failures.slice(0, 20)) console.log(`   ${f.scope} ${f.target}: ${f.message}`);
  }
}

main().catch((e) => {
  console.error('수집 실패:', e);
  process.exit(1);
});
