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
const { adjustSharesOutstanding } = require('./corporateActionAdjustment');

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

/** peg의 epsGrowthRate 안전판 허용치(§17.2). D4에서도 D2/원안과 같은 1%를 권고값으로
 *  둔다 — §6 V5가 여전히 이 선의 최종 근거이지 이 상수가 실측 승격은 아니다. */
const EPS_GROWTH_SHARE_TOLERANCE = 0.01;

/**
 * A3c(발행주식총수)에서 그 사업연도의 istcTotqy를 고르고, corporateActions로
 * D4 보정을 적용한다(docs/A5-3-peg-조정기준-결정브리프.md §16.2·§17.1).
 *
 * a3cRecords가 비어있거나 corporateActions를 안 넘기면(undefined) 보정 없이
 * SHARES_MISSING이나 그대로의 값을 낸다 — 이 함수 자체는 "공시 라벨이 아직
 * 없다"와 "값이 없다"를 구분하지 않는다. 호출부(resolve())가 그 구분을 옮긴다.
 */
function sharesOutstandingFrom(a3cRecords, fiscalYear, asOf, corporateActions) {
  const rec = pit.selectFiscalYear(a3cRecords || [], fiscalYear, asOf);
  if (!rec || typeof rec.istcTotqy !== 'number') {
    return { value: null, withheldBy: 'SHARES_MISSING', factor: null, appliedEvents: [], record: rec || null };
  }
  const adj = adjustSharesOutstanding(rec.istcTotqy, corporateActions, rec.availableFrom);
  if (adj.withheldBy) return { ...adj, record: rec };

  // §17.1의 7번 — 보정후 값에 대한 사후 임계 검사(D2 시절 §4.1 그대로, 대상만 보정후 값).
  if (typeof rec.isuStockTotqy === 'number' && adj.value > rec.isuStockTotqy) {
    return { value: null, withheldBy: 'SHARES_EXCEED_AUTHORIZED', factor: adj.factor,
             appliedEvents: adj.appliedEvents, record: rec };
  }
  if (adj.value >= 1e12) {
    return { value: null, withheldBy: 'SHARES_IMPLAUSIBLE', factor: adj.factor,
             appliedEvents: adj.appliedEvents, record: rec };
  }
  // SHARES_BASIS_UNSTABLE(§2.3b, 행 기준 왕복 A→B→A)은 그 corp의 전체 istcTotqy
  // 이력을 훑어야 잡히는 검사라 이 함수(fiscalYear 1개 단위) 범위 밖이다 — 아직
  // 미구현. corp 단위 감사 스크립트로 별도 구현 필요(DART_MATCH_FAIL 탐지와 같은 부류).
  return { ...adj, record: rec };
}

/**
 * D4 — netIncome(A3)÷보정된 sharesOutstanding(A3c+corporateActions)으로 EPS를
 * 우회 계산해 per·epsGrowthRate·pbr을 낸다(fundamentals.v1.json a3c 블록의
 * 우회식 그대로, docs/A5-3-peg-조정기준-결정브리프.md §17).
 *
 * valuationFrom()(위, A3b EPS 기반)과 다른 함수다 — A3b는 조정 기준 불일치로
 * 중단됐고(주석 참조), 이건 그 문제를 A3+A3c 우회로 피해 간다. resolve()가
 * a3cRecords와 corporateActions를 둘 다 받았을 때만 부른다.
 */
function valuationD4From(fundamentals, a3cRecords, corporateActions, asOf, price) {
  const cur = pit.selectAsOf(fundamentals, asOf);
  if (!cur) return { values: {}, provenance: null };
  const prev = pit.selectFiscalYear(fundamentals, cur.fiscalYear - 1, asOf);

  const sharesCur = sharesOutstandingFrom(a3cRecords, cur.fiscalYear, asOf, corporateActions);
  const sharesPrev = prev ? sharesOutstandingFrom(a3cRecords, prev.fiscalYear, asOf, corporateActions) : null;

  const epsCur = (sharesCur.value && typeof cur.netIncome === 'number')
    ? cur.netIncome / sharesCur.value : null;
  const epsPrev = (prev && sharesPrev && sharesPrev.value && typeof prev.netIncome === 'number')
    ? prev.netIncome / sharesPrev.value : null;

  const per = (price && typeof price.close === 'number' && epsCur !== null && epsCur > 0)
    ? round(price.close / epsCur, 2) : null;
  const pbr = (price && typeof price.close === 'number' && sharesCur.value
               && typeof cur.equity === 'number' && cur.equity > 0)
    ? round((price.close * sharesCur.value) / cur.equity, 2) : null;

  // §17.2 — 비교 대상을 보정후 값으로 바꾼다. splitLike는 이 안전판에 더 이상
  // 안 걸리고(양쪽이 같은 기준으로 이미 보정됐으므로), capitalReal(진짜 희석)은
  // 여전히 걸린다.
  const shareBasisStable = sharesPrev && sharesPrev.value && sharesCur.value
    && Math.abs(sharesCur.value / sharesPrev.value - 1) <= EPS_GROWTH_SHARE_TOLERANCE;
  const epsGrowthRateRaw = (epsPrev !== null && epsPrev !== 0 && epsCur !== null)
    ? round(mul100(epsCur / epsPrev - 1), 1) : null;
  const epsGrowthRate = (epsGrowthRateRaw !== null && shareBasisStable) ? epsGrowthRateRaw : null;

  return {
    values: { per, epsGrowthRate, pbr },
    provenance: {
      fiscalYear: cur.fiscalYear, prevFiscalYear: prev ? prev.fiscalYear : null,
      availableFrom: cur.availableFrom, rceptNo: cur.rceptNo || null,
      sharesOutstanding: {
        cur: { value: sharesCur.value, factor: sharesCur.factor, withheldBy: sharesCur.withheldBy,
               appliedEvents: sharesCur.appliedEvents },
        prev: sharesPrev ? { value: sharesPrev.value, factor: sharesPrev.factor,
                             withheldBy: sharesPrev.withheldBy, appliedEvents: sharesPrev.appliedEvents }
                          : null,
      },
      epsGrowthShareBasisStable: prev ? shareBasisStable : null,
    },
  };
}

/**
 * (ticker, asOf) 하나를 푼다.
 *
 * fundamentals는 **그 corp의 레코드만** 넘겨야 한다. 여러 corp를 섞으면 남의 재무로
 * 채점하고, 그 오류는 점수가 정상 범위에 있어 눈에 띄지 않는다. dividendEps·candles도
 * 같은 corp/ticker 것만 넘긴다.
 *
 * dividendEps·candles·sharesOutstanding은 기본값을 `[]`가 아니라 `undefined`로
 * 둔다 — 호출부가 아예 안 넘긴 것과 빈 배열을 넘긴 것을 구분해야, 이 축들을
 * 아직 모르는 기존 호출부(test-a5-framework.js 등)가 이전과 똑같이 동작한다.
 * technical 키 자체가 안 생기는 것도 그래서다(§ 축 미구축과 같은 원칙).
 * dividendEps는 shareholderReturn(fundamental 축)만 채운다.
 *
 * valuation은 **sharesOutstanding(A3c 레코드)을 넘겼을 때만** 채워진다 — D4
 * 우회식(valuationD4From, A3+A3c 기반)을 쓴다. corporateActions(그 corp의 D4
 * 라벨)는 안 넘기면 빈 배열로 다룬다 — "이 corp는 알려진 기업행위가 없다"와
 * "라벨 자체를 아직 안 넘겼다"를 여기서는 구분하지 않는다. 공시 라벨 백필
 * 단계가 아직 없어(featureRegistry.js blockedBy 참조) 이 구분을 강제할 상류가
 * 없기 때문이다 — 상류가 생기면 이 기본값도 undefined로 좁혀야 한다.
 * 기존 valuationFrom()(A3b 기반)은 여전히 정의만 하고 여기서 안 부른다 —
 * 그 함수 주석 참조.
 */
function resolve({ ticker, corp, asOf, fundamentals = [], dividendEps, candles,
                   sharesOutstanding, corporateActions, price = null,
                   sicCode = null, quality = null }) {
  const f = fundamentalsFrom(fundamentals, asOf);
  const hasDividendEps = dividendEps !== undefined;
  const hasCandles = candles !== undefined;
  const hasSharesOutstanding = sharesOutstanding !== undefined;

  const sr = hasDividendEps ? shareholderReturnFrom(dividendEps, asOf) : null;
  const tech = hasCandles ? technicalFrom(candles, asOf) : null;
  const val = hasSharesOutstanding
    ? valuationD4From(fundamentals, sharesOutstanding, corporateActions || [], asOf, price)
    : null;

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
  if (val && val.provenance) stockData.valuation = val.values;
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
  if (val && val.provenance) {
    for (const [k, v] of Object.entries(val.values)) {
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
      ...(val && val.provenance ? { valuation: val.provenance } : {}),
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
  valuationD4From, sharesOutstandingFrom,
};
