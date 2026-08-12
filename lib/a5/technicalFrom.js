/**
 * A5 technical 축 — scripts/collect.js(v3.4)의 순수 계산 함수를 그대로 복사했다.
 *
 * require(collect.js)로 재사용하지 않는 이유: 그 파일은 module.exports가 없고
 * 파일 하단에서 main()을 즉시 실행하는 라이브 수집 스크립트다. require하면
 * 네트워크 호출이 그대로 실행된다. 복사가 안전한 선택이다 — 공식은 손대지
 * 않았다(BF-1.1 §7 A5 인수 조건 4: 운영과 다른 계산식을 쓰지 않는다).
 *
 * 원본: scripts/collect.js:244-328 (sma·computeMaSignal·computeRsi·ema·
 * computeMacdSignal·computeTechnical). 원본이 바뀌면 이 파일도 같이 봐야 한다.
 */
'use strict';

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

/**
 * candles: [{date, close, volume}, ...] 오름차순 정렬, asOf 이전(포함)만.
 * asOf 이후 캔들이 섞이면 조용히 넘어가지 않고 던진다 — 호출부가 걸러야
 * 정상인데, 여기서도 한 번 더 막는다(resolver.js의 pitViolation과 같은 이유).
 */
function technicalFrom(candles, asOf) {
  const future = candles.filter((c) => c.date > asOf);
  if (future.length > 0) {
    throw new Error(`technicalFrom: asOf(${asOf}) 이후 캔들 ${future.length}건이 섞였다`);
  }
  if (candles.length === 0) {
    return { values: {}, candleCount: 0, lastDate: null };
  }
  const t = computeTechnical(candles);
  return {
    values: {
      maSignal: t.maSignal,
      rsi: t.rsi,
      macdSignal: t.macdSignal,
      volumeConfirmed: t.volumeConfirmed,
      priceDropPct: t.priceDropPct,
      reboundVolumeConfirmed: t.reboundVolumeConfirmed,
    },
    candleCount: candles.length,
    lastDate: t.lastDate,
  };
}

module.exports = { technicalFrom, computeMaSignal, computeRsi, computeMacdSignal, computeTechnical, sma };
