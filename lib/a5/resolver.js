/**
 * A5 리졸버 — (ticker, asOf)를 채점 엔진의 입력으로 바꾼다.
 *
 * 점수를 계산하지 않는다. 그것은 lib/scoringEngine.js의 일이고, 여기서 다시 구현하면
 * 운영과 연구가 다른 점수를 내 백테스트가 검증하는 대상이 운영에서 쓰는 그 점수가
 * 아니게 된다(BF-1.1 §7 A5 인수 조건 4가 강제한다). 이 파일이 하는 것은 셋이다.
 *
 *   1  PIT 규칙으로 어느 레코드를 쓸지 고른다        (pitSelector)
 *   2  그 레코드에서 지표를 유도한다                  (파생이며 저장하지 않는다)
 *   3  어느 레코드가 어느 지표를 만들었는지 남긴다    (provenance)
 *
 * **결측은 절대 채우지 않는다.** 값이 없으면 null이고 그 사실이 coverage로 흘러
 * confidence를 낮춘다. 기본값을 넣으면 '정직한 점수'의 첫 번째 규칙이 무너지고,
 * 무너진 사실이 점수에 남지 않아 아무도 모른다.
 */
'use strict';

const pit = require('./pitSelector');
const { technicalFrom } = require('./technicalFrom');

/** 분모가 0이거나 결측이면 null. 0으로 나눠 Infinity를 내보내지 않는다. */
function ratio(num, den) {
  if (num === null || num === undefined) return null;
  if (den === null || den === undefined || den === 0) return null;
  return num / den;
}

function round(n, d) {
  if (n === null || n === undefined || Number.isNaN(n)) return null;
  const p = Math.pow(10, d);
  return Math.round(n * p) / p;
}

function roeOf(rec) {
  if (!rec) return null;
  return round(mul100(ratio(rec.netIncome, rec.equity)), 1);
}

function mul100(x) {
  return x === null ? null : x * 100;
}

function opMarginOf(rec) {
  if (!rec) return null;
  return round(mul100(ratio(rec.opProfit, rec.revenue)), 2);
}

/**
 * A3 레코드에서 fundamental 지표를 유도한다.
 *
 * 운영 수집기(fetch-fundamentals-kr.js)의 계산과 같은 식을 쓴다. 식이 갈리면 같은
 * 재무에서 다른 점수가 나오고, 그때 백테스트 결과를 운영에 옮길 근거가 사라진다.
 */
function fundamentalsFrom(records, asOf) {
  const cur = pit.selectAsOf(records, asOf);
  if (!cur) {
    return { values: {}, provenance: null, history: [] };
  }
  const hist = pit.selectHistory(records, asOf, 5);
  const prev = hist[1] || null;

  // 결측 연도는 건너뛴다. 앞으로 당겨 채우면 5년 이력이 실제보다 촘촘해 보이고
  // 최솟값이 낙관적으로 나온다 — 그래서 '있는 해만' 모으고 개수를 함께 남긴다.
  const roeHistory5y = hist.map(roeOf).filter((v) => v !== null);

  const mCur = opMarginOf(cur), mPrev = opMarginOf(prev);
  const values = {
    roe: roeOf(cur),
    roeHistory5y,
    debtRatio: round(mul100(ratio(cur.liabilities, cur.equity)), 1),
    // 금융업은 유동 항목이 양식에 없다. null이 정상이며 결측으로 세는 것이 맞다 —
    // 여기서 0이나 대체값을 넣으면 업종 구성이 데이터 품질로 둔갑한다(교훈48).
    currentRatio: round(mul100(ratio(cur.currentAssets, cur.currentLiab)), 1),
    operatingMarginTrend: (mCur !== null && mPrev !== null) ? round(mCur - mPrev, 2) : null,
    revenueGrowthYoY: (prev && cur.revenue !== null && cur.revenue !== undefined
                       && prev.revenue) ? round(mul100(cur.revenue / prev.revenue - 1), 1)
                      : null,
    // 기본값. resolve()가 dividendEps(A3b)를 받으면 shareholderReturnFrom()의
    // 값으로 덮어쓴다 — 여기서는 채우지 않는다(A3만으로는 배당 이력을 모른다).
    buybackOrDividendHistory: null,
  };

  return {
    values,
    // 이 점수를 만든 레코드로 되짚어 가는 유일한 경로다. 없으면 "2019년 A사 점수가
    // 이상하다"에서 멈추고 원인을 못 판다.
    provenance: {
      fiscalYear: cur.fiscalYear, availableFrom: cur.availableFrom,
      rceptNo: cur.rceptNo || null, fsDiv: cur.fsDiv || null,
      periodEnd: cur.periodEnd || null, currency: cur.currency || null,
      freshnessDays: pit.freshnessDays(cur, asOf),
      historyYears: hist.filter(Boolean).map((r) => r.fiscalYear),
      historyRequested: 5,
    },
    history: hist,
  };
}

/**
 * A3b 배당 이력에서 shareholderReturn(fundamental 축)을 유도한다.
 *
 * criteria 정의가 boolean이다 — "최근 5년 이력에 배당이 한 번이라도 있었는가".
 * 이력이 아예 없으면(그 기간 A3b 레코드가 하나도 asOf 이전에 없으면) false가
 * 아니라 null이다 — "배당 안 했다"와 "몰랐다"는 다른 사실이다(교훈57).
 */
function shareholderReturnFrom(records, asOf) {
  const hist = pit.selectHistory(records, asOf, 5).filter(Boolean);
  if (hist.length === 0) return { value: null, provenance: null };
  const value = hist.some((r) => typeof r.dividendPerShare === 'number' && r.dividendPerShare > 0);
  return {
    value,
    provenance: { yearsChecked: hist.map((r) => r.fiscalYear), source: 'A3b.dividendPerShare' },
  };
}

/**
 * A3b EPS(+가격)에서 valuation 축 일부(peg가 필요로 하는 per·epsGrowthRate)를 유도한다.
 *
 * ★ resolve()에 연결하지 않는다(2026-08-12, A5-3 부분 구현 중 실측으로 발견).
 * A2a 가격은 `adjusted:true`(수정주가, 액면분할 등을 소급 반영)인데 A3b EPS는
 * DART 원문 그대로라 소급 조정이 없다. 005930/2016-04-08 실측: price=24,920
 * (2018년 50:1 분할 반영된 값) ÷ eps=126,305(분할 반영 안 됨) = per 0.197 —
 * 명백히 틀린 값이다. 이 함수 자체(공식)는 맞다 — 같은 조정 기준의 price·eps를
 * 받으면 정확하다. 문제는 두 소스의 조정 기준이 다르다는 사실이고, 이건
 * resolver.js가 임의로 배율을 추정해 고칠 일이 아니다(중단 기준: "기존 계약과
 * 충돌"). perRelative를 열 때도 같은 문제를 먼저 풀어야 한다.
 *
 * perRelative·pbr·marginOfSafety도 여기서 만들지 않는다 — perRelative는 횡단면
 * 계산(다른 종목의 PIT EPS·가격이 함께 필요)이라 이 함수의 범위 밖이고, pbr은
 * 발행주식총수가 파이프라인에 없고, marginOfSafety는 소스가 미정이다(A5-3 조사,
 * featureRegistry.js).
 */
function valuationFrom(records, asOf, price) {
  const cur = pit.selectAsOf(records, asOf);
  if (!cur) return { values: {}, provenance: null, selected: null };
  const prev = pit.selectFiscalYear(records, cur.fiscalYear - 1, asOf);

  const per = (price && typeof price.close === 'number'
               && typeof cur.eps === 'number' && cur.eps > 0)
    ? round(price.close / cur.eps, 2) : null;
  const epsGrowthRate = (prev && typeof prev.eps === 'number' && prev.eps !== 0
                         && typeof cur.eps === 'number')
    ? round(mul100(cur.eps / prev.eps - 1), 1) : null;

  return {
    values: { per, epsGrowthRate },
    provenance: {
      fiscalYear: cur.fiscalYear, availableFrom: cur.availableFrom,
      rceptNo: cur.rceptNo || null, freshnessDays: pit.freshnessDays(cur, asOf),
      prevFiscalYear: prev ? prev.fiscalYear : null,
    },
    selected: cur,
  };
}

/**
 * (ticker, asOf) 하나를 푼다.
 *
 * fundamentals는 **그 corp의 레코드만** 넘겨야 한다. 여러 corp를 섞으면 남의 재무로
 * 채점하고, 그 오류는 점수가 정상 범위에 있어 눈에 띄지 않는다. dividendEps·candles도
 * 같은 corp/ticker 것만 넘긴다.
 *
 * dividendEps·candles는 기본값을 `[]`가 아니라 `undefined`로 둔다 — 호출부가 아예
 * 안 넘긴 것과 빈 배열을 넘긴 것을 구분해야, 이 두 축을 아직 모르는 기존 호출부
 * (test-a5-framework.js 등)가 이전과 똑같이 동작한다. technical 키 자체가 안
 * 생기는 것도 그래서다(§ 축 미구축과 같은 원칙). dividendEps는 shareholderReturn
 * (fundamental 축)만 채운다 — valuation은 위 valuationFrom() 주석의 이유로
 * 아직 안 붙인다.
 */
function resolve({ ticker, corp, asOf, fundamentals = [], dividendEps, candles, price = null,
                   sicCode = null, quality = null }) {
  const f = fundamentalsFrom(fundamentals, asOf);
  const hasDividendEps = dividendEps !== undefined;
  const hasCandles = candles !== undefined;

  const sr = hasDividendEps ? shareholderReturnFrom(dividendEps, asOf) : null;
  // valuationFrom()은 정의만 하고 여기서 안 부른다 — 위 valuationFrom 주석 참조
  // (A2a 수정주가 ↔ A3b 원본 EPS 조정 기준 불일치, 실측으로 확인됨).
  const tech = hasCandles ? technicalFrom(candles, asOf) : null;

  const fundamentalValues = {
    ...f.values,
    ...(sr ? { buybackOrDividendHistory: sr.value } : {}),
  };

  const stockData = {
    ticker, name: null,
    // 채점 엔진은 fundamental/valuation/technical/supplyDemand 네 뭉치를 본다(scoringEngine.js 계약, 단수).
    // 없는 축은 넣지 않는다 — 빈 객체를 넣으면 '있는데 전부 결측'과 '아예 없다'가
    // 같은 모양이 되고, 후자는 축 자체가 미구축이라는 다른 사실이다.
    fundamental: fundamentalValues,
    sicCode: sicCode !== null ? sicCode : (f.history[0] && f.history[0].sicCode) || null,
  };
  if (price) stockData.price = price;
  // stockData.valuation은 의도적으로 안 붙인다 — valuationFrom() 주석 참조.
  if (hasCandles) stockData.technical = tech.values;

  const missing = [];
  for (const [k, v] of Object.entries(fundamentalValues)) {
    if (v === null || v === undefined || (Array.isArray(v) && v.length === 0)) missing.push(k);
  }
  if (hasCandles) {
    for (const [k, v] of Object.entries(tech.values)) {
      if (v === null || v === undefined) missing.push(k);
    }
  }

  return {
    ticker, corp, asOf,
    stockData,
    provenance: {
      fundamentals: f.provenance,
      ...(hasDividendEps ? { shareholderReturn: sr.provenance } : {}),
      ...(hasCandles ? { technical: { candleCount: tech.candleCount, lastDate: tech.lastDate } } : {}),
      price: price ? { date: price.date || null, close: price.close || null } : null,
      // sicCode는 '현재의 업종'이라 전 사업연도에 같은 값이 붙는다. A3가 진단에
      // sectorNotPointInTime으로 남긴 한계를 A5가 그대로 물려받는다 — 숨기지 않고
      // 결과에 실어 하류가 알고 쓰게 한다.
      sectorNotPointInTime: true,
      quality: quality ? {
        schema: quality.meta && quality.meta.schema,
        inputDigest: quality.meta && quality.meta.inputDigest,
        sampleComplete: quality.meta && quality.meta.sampleComplete,
      } : null,
    },
    missing,
    // confidence의 freshness·quality 파트. 정책(CP-1.0)이 선언해두고 "파이프라인
    // 미구축이라 항상 null"이라 적어둔 자리를 채운다. 여기서 점수로 바꾸지 않는다 —
    // 척도는 정책의 몫이고, 리졸버는 사실만 넘긴다.
    confidenceInputs: {
      freshnessDays: f.provenance ? f.provenance.freshnessDays : null,
      qualitySampleComplete: quality && quality.meta
        ? quality.meta.sampleComplete : null,
      qualityCoverageRate: quality && quality.coverage && quality.coverage.overall
        ? quality.coverage.overall.rate : null,
    },
    // 고른 레코드가 미래가 아닌지 다시 본다. 선택기를 거쳤으면 항상 통과하지만,
    // 호출부가 레코드를 직접 넣는 경로가 실제 위험이라 여기서 한 번 더 막는다.
    pitViolation: pit.violatesPit(f.history[0], asOf),
  };
}

module.exports = {
  resolve, fundamentalsFrom, shareholderReturnFrom, valuationFrom, roeOf, opMarginOf, ratio,
};
