/**
 * scoringEngine.js (v2.2 - 업종별 기준 확대 + 오채점 경고/비고 출력)
 *
 * criteria.json(v2.2)의 기준을 바탕으로 종목 데이터를 입력받아
 * 카테고리별 점수(0~100)와 종합 점수를 계산합니다.
 *
 * v2.1 → v2.2 변경점:
 *  - sectorOverrides가 valuation 카테고리에도 적용됨. PBR/PER의 '정상 범위'는
 *    업종 간 차이가 부채비율보다 오히려 큽니다(은행 PBR 0.4 vs 바이오 5.0).
 *    v2.1은 fundamental에만 분기가 걸려 있어 밸류에이션 오채점이 그대로 남아 있었습니다.
 *  - sectorCaution 필드 신설: 임계값 조정만으로는 보정 불가능한 구조적 왜곡을
 *    사용자에게 문장으로 전달합니다(점수에는 일절 반영하지 않음). 대시보드 비고란용.
 *  - 경고 플래그 3종 추가: sectorAdjusted / unmappedSector / lowSectorConfidence
 *  - debtRatio 원값 채점을 'financial' 하드코딩에서 meta.useRawDebtRatio 플래그로 일반화
 *
 * 하위 호환:
 *  - sectorType이 없거나 'general'이면 v2.0과 100% 동일한 점수가 나옵니다.
 *  - criteria에 sectorOverrides가 없으면(구 v2.0 파일) 모든 분기가 비활성화되어
 *    역시 기존과 동일하게 동작합니다. 엔진만 배포하고 criteria를 빠뜨려도 오채점이 없습니다.
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
  if (!thresholds) return null;

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

// ---------- 업종 분기 ----------

/** 데이터에서 업종 구분을 읽는다. 없으면 'general' (기존 동작 유지) */
function sectorTypeOf(data) {
  const f = data.fundamental || {};
  return f.sectorType || data.sectorType || 'general';
}

/** 수집기(sectorResolver)가 업종을 확정했는지. 명시적 false일 때만 미분류로 취급 */
function sectorResolvedOf(data) {
  const f = data.fundamental || {};
  const v = f.sectorResolved !== undefined ? f.sectorResolved : data.sectorResolved;
  return v === undefined ? true : v !== false;
}

function sectorConfigOf(criteria, sector) {
  return (criteria && criteria.sectorOverrides && criteria.sectorOverrides[sector]) || null;
}

/**
 * criteria.sectorOverrides[sector].<category>.metrics[key] 를 기본 meta 위에 병합.
 * @returns {{ meta, overridden }} overridden=true면 이 지표는 업종 기준으로 채점됨
 */
function resolveMeta(criteria, sector, category, key, baseMeta) {
  const sc = sectorConfigOf(criteria, sector);
  const ov = sc && sc[category] && sc[category].metrics && sc[category].metrics[key];
  if (!ov) return { meta: baseMeta, overridden: false };
  return { meta: { ...baseMeta, ...ov }, overridden: true };
}

// ---------- 카테고리별 계산 ----------

function scoreFundamental(data, criteria, tracker) {
  const cfg = criteria.fundamental.metrics;
  const f = data.fundamental || {};
  const sector = sectorTypeOf(data);
  const items = [];
  const detail = {};

  for (const [key, baseMeta] of Object.entries(cfg)) {
    const { meta, overridden } = resolveMeta(criteria, sector, 'fundamental', key, baseMeta);

    // 업종 특성상 산출 불가한 지표는 평가에서 제외 (커버리지 분모에서도 빠짐)
    if (meta.excluded === true) {
      detail[key] = {
        label: baseMeta.label,
        raw: undefined,
        score: null,
        excluded: true,
        sectorAdjusted: sector,
        reason: meta.excludedReason || `${sector} 업종 특성상 평가 제외`,
      };
      tracker.excluded.push({ label: baseMeta.label, reason: detail[key].reason });
      continue;
    }

    let score = null;
    let raw;

    if (key === 'roeConsistency') {
      // 5년 ROE 최저값으로 평가 (한 해라도 크게 무너진 기업 필터)
      raw = Array.isArray(f.roeHistory5y) && f.roeHistory5y.length > 0 ? Math.min(...f.roeHistory5y) : undefined;
      score = normalizeByThreshold(raw, meta.thresholds);
    } else if (key === 'shareholderReturn') {
      raw = f.buybackOrDividendHistory;
      if (raw !== undefined && raw !== null) score = raw ? 100 : 40;
    } else if (key === 'debtRatio' && overridden && meta.useRawDebtRatio === true) {
      // 금융업 등: 수집기가 debtRatio를 null로 두고 원값을 debtRatioRaw에 보존한다.
      // ★ 업종 임계값(sectorOverrides)이 실제로 설정된 경우에만 원값을 채점한다.
      //   criteria를 함께 올리지 않은 부분 배포에서는 이 분기를 타지 않아
      //   기존과 동일하게 '결측'으로 남는다(오채점·오경고 방지).
      raw = f.debtRatioRaw !== undefined && f.debtRatioRaw !== null ? f.debtRatioRaw : f.debtRatio;
      score = normalizeByThreshold(raw, meta.thresholds, meta.lowerIsBetter === true);
    } else {
      raw = f[key];
      score = normalizeByThreshold(raw, meta.thresholds, meta.lowerIsBetter === true);
    }

    detail[key] = { label: baseMeta.label, raw, score };
    if (overridden) {
      detail[key].sectorAdjusted = sector;
      detail[key].baseThresholds = baseMeta.thresholds;
      detail[key].appliedThresholds = meta.thresholds;
      tracker.adjusted.push(baseMeta.label);
    }
    items.push({ score, weight: meta.weight });
  }

  return { score: weightedAverage(items), detail, coverage: coverageOf(items), sector };
}

function scoreValuation(data, criteria, tracker) {
  const cfg = criteria.valuation.metrics;
  const v = data.valuation || {};
  const sector = sectorTypeOf(data);
  const items = [];
  const detail = {};

  // v2.2: 밸류에이션도 업종 분기. PBR/PER의 정상 범위는 업종 간 차이가 매우 큼.
  const metaOf = (key) => resolveMeta(criteria, sector, 'valuation', key, cfg[key]);

  const applyAdjust = (key, node, overridden, baseMeta, meta) => {
    if (!overridden) return;
    node.sectorAdjusted = sector;
    node.baseThresholds = baseMeta.thresholds;
    node.appliedThresholds = meta.thresholds;
    tracker.adjusted.push(baseMeta.label);
  };

  // PER (업종평균 대비)
  {
    const { meta, overridden } = metaOf('perRelative');
    if (meta.excluded === true) {
      detail.perRelative = {
        label: cfg.perRelative.label,
        score: null,
        excluded: true,
        sectorAdjusted: sector,
        reason: meta.excludedReason || `${sector} 업종 특성상 평가 제외`,
      };
      tracker.excluded.push({ label: cfg.perRelative.label, reason: detail.perRelative.reason });
    } else {
      const score = normalizeByThreshold(v.perRelative, meta.thresholds, true);
      detail.perRelative = { label: cfg.perRelative.label, raw: v.perRelative, score };
      applyAdjust('perRelative', detail.perRelative, overridden, cfg.perRelative, meta);
      items.push({ score, weight: meta.weight });
    }
  }

  // PBR
  {
    const { meta, overridden } = metaOf('pbr');
    const score = normalizeByThreshold(v.pbr, meta.thresholds, true);
    detail.pbr = { label: cfg.pbr.label, raw: v.pbr, score };
    applyAdjust('pbr', detail.pbr, overridden, cfg.pbr, meta);
    items.push({ score, weight: meta.weight });
  }

  // PEG (피터 린치)
  {
    const { meta, overridden } = metaOf('peg');
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
        : normalizeByThreshold(peg, meta.thresholds, true);
    detail.peg = { label: cfg.peg.label, peg, score };
    applyAdjust('peg', detail.peg, overridden, cfg.peg, meta);
    items.push({ score, weight: meta.weight });
  }

  // 안전마진 (그레이엄) - 내재가치 미산출 시 결측 처리
  {
    const { meta, overridden } = metaOf('marginOfSafety');
    let margin = null;
    if (typeof v.intrinsicValue === 'number' && typeof v.currentPrice === 'number' && v.intrinsicValue > 0) {
      margin = (v.intrinsicValue - v.currentPrice) / v.intrinsicValue;
    } else if (typeof v.marginOfSafety === 'number') {
      margin = v.marginOfSafety;
    }
    const score = normalizeByThreshold(margin, meta.thresholds);
    detail.marginOfSafety = { label: cfg.marginOfSafety.label, marginOfSafety: margin, score };
    applyAdjust('marginOfSafety', detail.marginOfSafety, overridden, cfg.marginOfSafety, meta);
    items.push({ score, weight: meta.weight });
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

  // 거래량 동반 - 미입력 시 결측 처리
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

  // 미입력 시 결측 처리
  let buybackScore = null;
  if (s.buybackOrRetirementAnnounced === true) buybackScore = 100;
  else if (s.buybackOrRetirementAnnounced === false) buybackScore = 50;
  detail.buybackOrRetirement = { label: cfg.buybackOrRetirement.label, announced: s.buybackOrRetirementAnnounced, score: buybackScore };
  items.push({ score: buybackScore, weight: cfg.buybackOrRetirement.weight });

  return { score: weightedAverage(items), detail, coverage: coverageOf(items) };
}

// ---------- 경고 플래그 ----------

function collectWarnings(data, technicalWarnings, criteria, sectorCaution) {
  const warnings = [...technicalWarnings];
  const f = data.fundamental || {};
  const sector = sectorTypeOf(data);

  // 업종별 부채비율 경고 임계값 (금융업은 예금·보험부채 탓에 구조적으로 높음)
  const table = (criteria && criteria.warningThresholds && criteria.warningThresholds.debtRatioHigh) || {};
  const hasSectorLimit = table[sector] !== undefined;
  const limit = hasSectorLimit ? table[sector] : (table.general !== undefined ? table.general : 200);
  // 업종 임계값이 설정된 경우에만 원값으로 판정 (미설정 시 debtRatio=null → 경고 없음)
  const dr =
    hasSectorLimit && f.debtRatioRaw !== undefined && f.debtRatioRaw !== null ? f.debtRatioRaw : f.debtRatio;

  if (dr !== undefined && dr !== null && dr >= limit) warnings.push('debtRatioAbove200');
  if (data.consecutiveOperatingLoss === true) warnings.push('consecutiveOperatingLoss');
  if (data.auditOpinionNonStandard === true) warnings.push('auditOpinionNonStandard');
  if (data.supplyDemand && data.supplyDemand.majorShareholderSelloff === true) warnings.push('majorShareholderSelloff');

  // v2.2 업종 관련 플래그
  if (sectorCaution) {
    if (sectorCaution.adjustedMetrics.length > 0 || sectorCaution.excludedMetrics.length > 0) {
      warnings.push('sectorAdjusted');
    }
    if (sectorCaution.confidence === 'low') warnings.push('lowSectorConfidence');
  }
  if (!sectorResolvedOf(data)) warnings.push('unmappedSector');

  return warnings;
}

// ---------- 업종 비고(대시보드 표시용) ----------

const CONFIDENCE_LABEL = {
  high: '스코어링 신뢰도 높음',
  medium: '스코어링 신뢰도 보통 — 비고 확인 권장',
  low: '스코어링 신뢰도 낮음 — 점수보다 비고를 우선 확인',
};

/**
 * 점수에는 전혀 반영되지 않는 '해석 주의사항'을 만들어 반환합니다.
 * 대시보드 비고란 / 알림 하단에 그대로 출력하는 것을 전제로 합니다.
 */
function buildSectorCaution(data, criteria, tracker) {
  const sector = sectorTypeOf(data);
  const resolved = sectorResolvedOf(data);
  const sc = sectorConfigOf(criteria, sector);

  // 업종 미분류: 기본 기준으로 채점됐다는 사실 자체를 알린다
  if (!resolved) {
    return {
      sector: sector,
      label: '업종 미분류',
      confidence: 'low',
      confidenceLabel: CONFIDENCE_LABEL.low,
      notes: [
        'DART 표준산업분류 코드를 받지 못해 제조업 일반 기준으로 채점했습니다.',
        '금융·건설·해운·항공·바이오·유틸리티·리츠라면 부채비율과 밸류에이션이 크게 잘못 채점됩니다.',
        'config/sector-map.json의 byTicker에 이 종목의 sectorType을 지정하세요.',
      ],
      adjustedMetrics: [],
      excludedMetrics: [],
      summary: '업종 미분류 — 일반 기준으로 채점됨(오채점 가능)',
    };
  }

  if (!sc) return null; // general 등: 기본 기준이 맞는 업종. 비고 없음.

  const adjusted = Array.from(new Set(tracker.adjusted));
  const excluded = tracker.excluded;
  const confidence = sc.sectorConfidence || 'medium';

  const parts = [];
  if (adjusted.length) parts.push(`${adjusted.length}개 지표를 업종 기준으로 조정`);
  if (excluded.length) parts.push(`${excluded.length}개 지표 평가 제외`);

  return {
    sector,
    label: sc.label || sector,
    confidence,
    confidenceLabel: CONFIDENCE_LABEL[confidence] || CONFIDENCE_LABEL.medium,
    notes: Array.isArray(sc.cautions) ? sc.cautions.slice() : [],
    adjustedMetrics: adjusted,
    excludedMetrics: excluded,
    summary: `${sc.label || sector} — ${CONFIDENCE_LABEL[confidence] || ''}${parts.length ? ' / ' + parts.join(', ') : ''}`,
  };
}

// ---------- 메인 함수 ----------

/**
 * @param {object} stockData - 종목별 원시 데이터
 * @param {object} criteria - criteria.json을 파싱한 객체 (미제공시 기본 파일 로드)
 */
function scoreStock(stockData, criteria) {
  if (!criteria) {
    const criteriaPath = path.join(__dirname, '..', 'config', 'criteria.json');
    criteria = JSON.parse(fs.readFileSync(criteriaPath, 'utf-8'));
  }

  // 업종 조정 내역 수집기 (비고란 생성용)
  const tracker = { adjusted: [], excluded: [] };

  const fundamental = scoreFundamental(stockData, criteria, tracker);
  const valuation = scoreValuation(stockData, criteria, tracker);
  const technical = scoreTechnical(stockData, criteria);
  const supplyDemand = scoreSupplyDemand(stockData, criteria);

  const weights = criteria.categoryWeights;
  const totalScore = weightedAverage([
    { score: fundamental.score, weight: weights.fundamental },
    { score: valuation.score, weight: weights.valuation },
    { score: technical.score, weight: weights.technical },
    { score: supplyDemand.score, weight: weights.supplyDemand },
  ]);

  const sectorCaution = buildSectorCaution(stockData, criteria, tracker);
  const warnings = collectWarnings(stockData, technical.warnings || [], criteria, sectorCaution);

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
    sectorType: fundamental.sector,
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
    // v2.2: 대시보드 비고란용. null이면 표시할 주의사항 없음(기본 기준이 적정한 업종).
    sectorCaution,
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

module.exports = { scoreStock, normalizeByThreshold, weightedAverage, buildSectorCaution };
