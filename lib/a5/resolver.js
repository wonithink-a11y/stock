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
    // A3b가 오기 전까지 null이다. 채우지 않는 것이 계약이다.
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
 * (ticker, asOf) 하나를 푼다.
 *
 * fundamentals는 **그 corp의 레코드만** 넘겨야 한다. 여러 corp를 섞으면 남의 재무로
 * 채점하고, 그 오류는 점수가 정상 범위에 있어 눈에 띄지 않는다.
 */
function resolve({ ticker, corp, asOf, fundamentals = [], price = null,
                   sicCode = null, quality = null }) {
  const f = fundamentalsFrom(fundamentals, asOf);

  const stockData = {
    ticker, name: null,
    // 채점 엔진은 fundamentals/valuation/technical/supplyDemand 네 뭉치를 본다.
    // 없는 축은 넣지 않는다 — 빈 객체를 넣으면 '있는데 전부 결측'과 '아예 없다'가
    // 같은 모양이 되고, 후자는 축 자체가 미구축이라는 다른 사실이다.
    fundamentals: f.values,
    sicCode: sicCode !== null ? sicCode : (f.history[0] && f.history[0].sicCode) || null,
  };
  if (price) stockData.price = price;

  const missing = Object.entries(f.values)
    .filter(([, v]) => v === null || v === undefined
            || (Array.isArray(v) && v.length === 0))
    .map(([k]) => k);

  return {
    ticker, corp, asOf,
    stockData,
    provenance: {
      fundamentals: f.provenance,
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

module.exports = { resolve, fundamentalsFrom, roeOf, opMarginOf, ratio };
