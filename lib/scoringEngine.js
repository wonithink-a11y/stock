/**
 * scoringEngine.js (v2)
 *
 * criteria.json(v2)의 기준을 바탕으로 종목 데이터를 입력받아
 * 카테고리별 점수(0~100)와 종합 점수를 계산합니다.
 *
 * v1 대비 변경점:
 *  - guru 카테고리 제거 → valuation으로 대체 (fundamental과의 지표 이중계산 제거)
 *  - RSI: 과매도 가점 → 감점 + 경고 플래그 (추세 확인 지표로 역할 변경)
 *  - 결측 지표에 기본 점수를 주지 않고 전부 null(결측) 처리
 *  - 데이터 커버리지(입력된 지표 비율) 산출, 부족하면 등급 유보
 *
 * 사용 예:
 *   const { scoreStock } = require('./scoringEngine');
 *   const result = scoreStock(stockData, criteria);
 *   console.log(result.totalScore, result.grade, result.dataCoverage);
 */

const fs = require('fs');
const path = require('path');

// ---------- 유틸 ----------

/**
 * 값이 임계값 구간 중 어디에 속하는지에 따라 0~100 사이로 선형 정규화.
 * lowerIsBetter가 true면 값이 낮을수록 높은 점수.
 */
function normalizeByThreshold(value, thresholds, lowerIsBetter = false) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;

  const { excellent, good, poor } = thresholds;
  if (excellent === undefined || poor === undefined) return null;

  // good이 없으면 excellent-poor 사이 선형보간
  const mid = good !== undefined ? good : (excellent + poor) / 2;

  let score;
  if (!lowerIsBetter) {
    if (value >= excellent) score = 100;
    else if (value <= poor) score = 0;
    else if (value >= mid) {
      score = 70 + ((value - mid) / (excellent - mid)) * 30;
    } else {
      score = ((value - poor) / (mid - poor)) * 70;
    }
  } else {
    if (value <= excellent) score = 100;
    else if (value >= poor) score = 0;
    else if (value <= mid) {
      score = 70 + ((mid - value) / (mid - excellent)) * 30;
    } else {
      score = ((poor - value) / (poor - mid)) * 70;
    }
  }
  return Math.max(0, Math.min(100, score));
}

function weightedAverage(items) {
  // items: [{ score, weight }]
  const valid = items.filter((i) => i.score !== null && i.score !== undefined);
  if (valid.length === 0) return null;
  const totalWeight = valid.reduce((sum, i) => sum + i.weight, 0);
  if (totalWeight === 0) return null;
  const weightedSum = valid.reduce((sum, i) => sum + i.score * i.weight, 0);
  return weightedSum / totalWeight;
}

function coverageOf(items) {
  const valid = items.filter((i) => i.score !== null && i.score !== undefined).length;
  return { valid, total: items.length };
}

// ---------- 카테고리별 계산 ----------

function scoreFundamental(data, criteria) {
  const cfg = criteria.fundamental.metrics;
  const f = data.fundamental || {};
  const items = [];
  const detail = {};

  for (const [key, meta] of Object.entries(cfg)) {
    let score = null;
    let raw;

    if (key === 'roeConsistency') {
      // 5년 ROE 최저값으로 평가 (한 해라도 크게 무너진 기업 필터)
      raw = Array.isArray(f.roeHistory5y) && f.roeHistory5y.length > 0 ? Math.min(...f.roeHistory5y) : undefined;
      score = normalizeByThreshold(raw, meta.thresholds);
    } else if (key === 'shareholderReturn') {
      raw = f.buybackOrDividendHistory;
      if (raw !== undefined && raw !== null) score = raw ? 100 : 40;
    } else {
      raw = f[key];
      score = normalizeByThreshold(raw, meta.thresholds, meta.lowerIsBetter === true);
    }

    detail[key] = { label: meta.label, raw, score };
    items.push({ score, weight: meta.weight });
  }

  return { score: weightedAverage(items), detail, coverage: coverageOf(items) };
}

function scoreValuation(data, criteria) {
  const cfg = criteria.valuation.metrics;
  const v = data.valuation || {};
  const items = [];
  const detail = {};

  // PER (업종평균 대비)
  {
    const score = normalizeByThreshold(v.perRelative, cfg.perRelative.thresholds, true);
    detail.perRelative = { label: cfg.perRelative.label, raw: v.perRelative, score };
    items.push({ score, weight: cfg.perRelative.weight });
  }

  // PBR
  {
    const score = normalizeByThreshold(v.pbr, cfg.pbr.thresholds, true);
    detail.pbr = { label: cfg.pbr.label, raw: v.pbr, score };
    items.push({ score, weight: cfg.pbr.weight });
  }

  // PEG (피터 린치)
  {
    let peg = null;
    if (typeof v.per === 'number' && typeof v.epsGrowthRate === 'number' && v.epsGrowthRate > 0) {
      peg = v.per / v.epsGrowthRate;
    } else if (typeof v.peg === 'number') {
      peg = v.peg;
    }
    // 이익이 역성장(epsGrowthRate <= 0)이면 PEG 정의 불가 → 최저점 처리
    const score =
      typeof v.epsGrowthRate === 'number' && v.epsGrowthRate <= 0
        ? 0
        : normalizeByThreshold(peg, cfg.peg.thresholds, true);
    detail.peg = { label: cfg.peg.label, peg, score };
    items.push({ score, weight: cfg.peg.weight });
  }

  // 안전마진 (그레이엄) - 내재가치 미산출 시 결측 처리
  {
    let margin = null;
    if (typeof v.intrinsicValue === 'number' && typeof v.currentPrice === 'number' && v.intrinsicValue > 0) {
      margin = (v.intrinsicValue - v.currentPrice) / v.intrinsicValue;
    } else if (typeof v.marginOfSafety === 'number') {
      margin = v.marginOfSafety;
    }
    const score = normalizeByThreshold(margin, cfg.marginOfSafety.thresholds);
    detail.marginOfSafety = { label: cfg.marginOfSafety.label, marginOfSafety: margin, score };
    items.push({ score, weight: cfg.marginOfSafety.weight });
  }

  return { score: weightedAverage(items), detail, coverage: coverageOf(items) };
}

function scoreTechnical(data, criteria) {
  const cfg = criteria.technical;
  const t = data.technical || {};
  const items = [];
  const detail = {};
  const warnings = [];

  // 이동평균 크로스
  {
    const raw = cfg.indicators.movingAverageCross.signals[t.maSignal];
    const score = raw !== undefined ? raw : null;
    detail.movingAverageCross = { label: cfg.indicators.movingAverageCross.label, signal: t.maSignal, score };
    items.push({ score, weight: cfg.indicatorWeights.movingAverageCross });
  }

  // RSI - 구간(zone) 기반. 과매도는 가점이 아니라 감점 + 경고
  {
    let score = null;
    if (typeof t.rsi === 'number') {
      for (const zone of cfg.indicators.rsi.zones) {
        if (t.rsi <= zone.max) {
          score = zone.score;
          if (zone.warning) warnings.push(zone.warning);
          break;
        }
      }
    }
    detail.rsi = { label: cfg.indicators.rsi.label, value: t.rsi, score };
    items.push({ score, weight: cfg.indicatorWeights.rsi });
  }

  // MACD
  {
    let score = null;
    if (t.macdSignal === 'bullishCross') score = 100;
    else if (t.macdSignal === 'bearishCross') score = 0;
    else if (t.macdSignal === 'neutral') score = 50;
    detail.macd = { label: cfg.indicators.macd.label, signal: t.macdSignal, score };
    items.push({ score, weight: cfg.indicatorWeights.macd });
  }

  // 거래량 동반 - 미입력 시 결측 처리 (v1은 미입력에도 40점을 부여했음)
  {
    let score = null;
    if (t.volumeConfirmed === true) score = 100;
    else if (t.volumeConfirmed === false) score = 30;
    detail.volumeConfirmation = { label: cfg.indicators.volumeConfirmation.label, confirmed: t.volumeConfirmed, score };
    items.push({ score, weight: cfg.indicatorWeights.volumeConfirmation });
  }

  // 데드캣바운스 경고 (점수에 반영하지 않고 별도 플래그)
  if (t.priceDropPct !== undefined && t.priceDropPct <= -10 && t.reboundVolumeConfirmed === false) {
    warnings.push('deadCatBounce');
  }

  return { score: weightedAverage(items), detail, warnings, coverage: coverageOf(items) };
}

function scoreSupplyDemand(data, criteria) {
  const cfg = criteria.supplyDemand.metrics;
  const s = data.supplyDemand || {};
  const items = [];
  const detail = {};

  const trendToScore = (trend) => {
    if (trend === 'consistentBuy') return 100;
    if (trend === 'netBuy') return 70;
    if (trend === 'neutral') return 50;
    if (trend === 'netSell') return 30;
    if (trend === 'consistentSell') return 0;
    return null;
  };

  const foreignScore = trendToScore(s.foreignTrend5d);
  detail.foreignNetBuy5d = { label: cfg.foreignNetBuy5d.label, trend: s.foreignTrend5d, score: foreignScore };
  items.push({ score: foreignScore, weight: cfg.foreignNetBuy5d.weight });

  const institutionScore = trendToScore(s.institutionTrend5d);
  detail.institutionNetBuy5d = { label: cfg.institutionNetBuy5d.label, trend: s.institutionTrend5d, score: institutionScore };
  items.push({ score: institutionScore, weight: cfg.institutionNetBuy5d.weight });

  const shareholderScore =
    s.largeShareholderChangePct !== undefined
      ? normalizeByThreshold(s.largeShareholderChangePct, { excellent: 2, good: 0, poor: -2 })
      : null;
  detail.largeShareholderChange = { label: cfg.largeShareholderChange.label, changePct: s.largeShareholderChangePct, score: shareholderScore };
  items.push({ score: shareholderScore, weight: cfg.largeShareholderChange.weight });

  // 미입력 시 결측 처리 (v1은 미입력을 '공시 없음(50점)'으로 취급했음)
  let buybackScore = null;
  if (s.buybackOrRetirementAnnounced === true) buybackScore = 100;
  else if (s.buybackOrRetirementAnnounced === false) buybackScore = 50;
  detail.buybackOrRetirement = { label: cfg.buybackOrRetirement.label, announced: s.buybackOrRetirementAnnounced, score: buybackScore };
  items.push({ score: buybackScore, weight: cfg.buybackOrRetirement.weight });

  return { score: weightedAverage(items), detail, coverage: coverageOf(items) };
}

// ---------- 경고 플래그 ----------

function collectWarnings(data, technicalWarnings) {
  const warnings = [...technicalWarnings];
  const f = data.fundamental || {};

  if (f.debtRatio !== undefined && f.debtRatio >= 200) warnings.push('debtRatioAbove200');
  if (data.consecutiveOperatingLoss === true) warnings.push('consecutiveOperatingLoss');
  if (data.auditOpinionNonStandard === true) warnings.push('auditOpinionNonStandard');
  if (data.supplyDemand && data.supplyDemand.majorShareholderSelloff === true) warnings.push('majorShareholderSelloff');

  return warnings;
}

// ---------- 메인 함수 ----------

/**
 * @param {object} stockData - 종목별 원시 데이터 (config/exampleInput.json 형식 참고)
 * @param {object} criteria - criteria.json을 파싱한 객체 (미제공시 기본 파일 로드)
 */
function scoreStock(stockData, criteria) {
  if (!criteria) {
    const criteriaPath = path.join(__dirname, '..', 'config', 'criteria.json');
    criteria = JSON.parse(fs.readFileSync(criteriaPath, 'utf-8'));
  }

  const fundamental = scoreFundamental(stockData, criteria);
  const valuation = scoreValuation(stockData, criteria);
  const technical = scoreTechnical(stockData, criteria);
  const supplyDemand = scoreSupplyDemand(stockData, criteria);

  const weights = criteria.categoryWeights;
  const totalScore = weightedAverage([
    { score: fundamental.score, weight: weights.fundamental },
    { score: valuation.score, weight: weights.valuation },
    { score: technical.score, weight: weights.technical },
    { score: supplyDemand.score, weight: weights.supplyDemand },
  ]);

  const warnings = collectWarnings(stockData, technical.warnings || []);

  // 데이터 커버리지: 전체 지표 중 실제 입력된 비율
  const coverages = [fundamental.coverage, valuation.coverage, technical.coverage, supplyDemand.coverage];
  const validCount = coverages.reduce((sum, c) => sum + c.valid, 0);
  const totalCount = coverages.reduce((sum, c) => sum + c.total, 0);
  const overallCoverage = totalCount > 0 ? validCount / totalCount : 0;
  const minCoverage = criteria.minimumDataCoverage !== undefined ? criteria.minimumDataCoverage : 0.6;
  const coverageSufficient = overallCoverage >= minCoverage;

  return {
    ticker: stockData.ticker || null,
    name: stockData.name || null,
    totalScore: totalScore !== null ? Math.round(totalScore * 10) / 10 : null,
    grade: coverageSufficient
      ? gradeFromScore(totalScore)
      : `유보 (데이터 커버리지 ${Math.round(overallCoverage * 100)}% < 기준 ${Math.round(minCoverage * 100)}%)`,
    dataCoverage: {
      overall: Math.round(overallCoverage * 100) / 100,
      sufficient: coverageSufficient,
      byCategory: {
        fundamental: fundamental.coverage,
        valuation: valuation.coverage,
        technical: technical.coverage,
        supplyDemand: supplyDemand.coverage,
      },
    },
    breakdown: {
      fundamental: { score: round1(fundamental.score), detail: fundamental.detail },
      valuation: { score: round1(valuation.score), detail: valuation.detail },
      technical: { score: round1(technical.score), detail: technical.detail },
      supplyDemand: { score: round1(supplyDemand.score), detail: supplyDemand.detail },
    },
    warnings,
  };
}

function round1(v) {
  return v === null || v === undefined ? null : Math.round(v * 10) / 10;
}

function gradeFromScore(score) {
  if (score === null || score === undefined) return 'N/A';
  if (score >= 80) return 'A (강력 매수 후보)';
  if (score >= 65) return 'B (긍정적)';
  if (score >= 50) return 'C (중립/관찰)';
  if (score >= 35) return 'D (부정적)';
  return 'E (회피 권장)';
}

module.exports = { scoreStock, normalizeByThreshold, weightedAverage };
