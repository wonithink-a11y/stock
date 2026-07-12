/**
 * collect.js
 *
 * 관심종목(한국+미국)의 시세·밸류에이션·기술지표·수급 데이터를 수집해
 * data/inputs.json 으로 저장합니다 (analyze.js의 입력).
 *
 * 데이터 소스:
 *  [한국 KR]
 *  - 일봉/현재가: fchart.stock.naver.com (비공식이지만 오래 유지된 엔드포인트)
 *  - PER/PBR: m.stock.naver.com API
 *  - 외국인/기관 수급: m.stock.naver.com API
 *  [미국 US]
 *  - 일봉/현재가: stooq.com CSV (무료, 키 불필요)
 *  - PER/PBR: config/fundamentals.json 수동 입력 (분기 1회)
 *  - 수급: 없음 (KRX식 일별 수급 데이터가 미국엔 없음 - criteria-us.json에서 카테고리 비활성)
 *  [공통]
 *  - 재무(ROE/부채비율 등): config/fundamentals.json (수동 갱신, 추후 DART/SEC 자동화 지점)
 *
 * 설계 원칙: 수집 실패는 에러로 죽지 않고 해당 필드를 결측(null)으로 남깁니다.
 * 스코어링 엔진이 결측을 커버리지로 처리하므로, 일부 소스가 죽어도 파이프라인은 계속 돕니다.
 *
 * ⚠️ 미국 시세는 시차 때문에 "전일(미국 기준) 종가"입니다. 평일 16:40 KST 실행 시점엔
 * 미국 장이 아직 안 열렸거나 마감 직후이므로 이게 정상 동작입니다.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const DATA_DIR = path.join(ROOT, 'data');

const UA = { 'User-Agent': 'Mozilla/5.0 (compatible; stock-scoring-app)' };

async function fetchText(url) {
  const res = await fetch(url, { headers: UA });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return res.text();
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: UA });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return res.json();
}

// ---------- 일봉 수집: 한국 (fchart: XML 형태) ----------

async function fetchDailyCandlesKR(symbol, count = 140) {
  const url = `https://fchart.stock.naver.com/sise.nhn?symbol=${symbol}&timeframe=day&count=${count}&requestType=0`;
  const xml = await fetchText(url);
  const candles = [];
  const re = /<item data="([^"]+)"\s*\/>/g;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const [date, open, high, low, close, volume] = m[1].split('|');
    candles.push({ date, close: Number(close), volume: Number(volume) });
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
      return { date: date.replace(/-/g, ''), close: Number(close), volume: Number(volume) || 0 };
    })
    .filter((c) => !Number.isNaN(c.close));
  if (candles.length === 0) throw new Error(`일봉 데이터 없음: ${ticker}`);
  return candles.slice(-count); // 과거 → 최신 순
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

  // 최근 5일 낙폭 (데드캣바운스 감지용)
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
  const out = { per: null, pbr: null };
  try {
    const data = await fetchJson(`https://m.stock.naver.com/api/stock/${code}/integration`);
    const infos = data.totalInfos || [];
    for (const info of infos) {
      const value = parseFloat(String(info.value).replace(/[,배]/g, ''));
      if (info.code === 'per' && !Number.isNaN(value)) out.per = value;
      if (info.code === 'pbr' && !Number.isNaN(value)) out.pbr = value;
    }
  } catch (e) {
    console.warn(`  [경고] ${code} 밸류에이션 수집 실패: ${e.message}`);
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
    return null;
  }
}

async function fetchSpxClose() {
  try {
    const candles = await fetchDailyCandlesUS('^spx', 5);
    return candles[candles.length - 1].close;
  } catch (e) {
    console.warn(`  [경고] S&P500 지수 수집 실패: ${e.message}`);
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
    return null;
  }
}

// ---------- 메인 ----------

async function main() {
  const watchlist = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'watchlist.json'), 'utf-8'));
  const fundamentals = JSON.parse(fs.readFileSync(path.join(ROOT, 'config', 'fundamentals.json'), 'utf-8'));

  fs.mkdirSync(DATA_DIR, { recursive: true });

  const stocks = [];
  for (const t of watchlist.tickers) {
    const market = t.market || 'KR';
    console.log(`수집 중: ${t.name} (${t.code}, ${market})`);
    const fund = fundamentals.byTicker[t.code] || {};

    let technical = {};
    try {
      const candles = market === 'US' ? await fetchDailyCandlesUS(t.code) : await fetchDailyCandlesKR(t.code);
      technical = computeTechnical(candles);
    } catch (e) {
      console.warn(`  [경고] ${t.code} 일봉 수집 실패: ${e.message}`);
    }

    let per = null;
    let pbr = null;
    let supplyDemand = { foreignTrend5d: null, institutionTrend5d: null };

    if (market === 'US') {
      // 미국: PER/PBR은 fundamentals.json 수동 입력, 수급 데이터 없음
      per = fund.per ?? null;
      pbr = fund.pbr ?? null;
    } else {
      const valuationInfo = await fetchValuationInfoKR(t.code);
      per = valuationInfo.per;
      pbr = valuationInfo.pbr;
      supplyDemand = await fetchSupplyDemandKR(t.code);
    }

    stocks.push({
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
      },
      valuation: {
        perRelative: fund.perRelative,
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
      meta: {
        currentPrice: technical.currentPrice ?? null,
        lastDate: technical.lastDate ?? null,
        groups: t.groups || [],
        market,
      },
    });
  }

  const kospiClose = await fetchKospiClose();
  const spxClose = await fetchSpxClose();
  const fx = await fetchUsdKrw();

  const output = {
    collectedAt: new Date().toISOString(),
    kospiClose,
    spxClose,
    fx,
    stocks,
  };
  fs.writeFileSync(path.join(DATA_DIR, 'inputs.json'), JSON.stringify(output, null, 2), 'utf-8');
  console.log(`완료: ${stocks.length}개 종목 → data/inputs.json`);
}

main().catch((e) => {
  console.error('수집 실패:', e);
  process.exit(1);
});
