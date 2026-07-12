/**
 * marketRegimeEngine.js
 *
 * 개별 종목을 보기 전에 "지금 시장 국면이 우호적인가"를 판단합니다.
 * KOSPI/KOSDAQ은 환율, 미국 금리, 반도체 업황, 연기금·외국인 수급에
 * 개별 종목 펀더멘털보다 더 크게 흔들리는 경우가 많아 별도 상위 필터로 분리했습니다.
 *
 * 사용 예:
 *   const { evaluateRegime } = require('./marketRegimeEngine');
 *   const regime = evaluateRegime(macroData);
 *   console.log(regime.grade, regime.action);
 */

const fs = require('fs');
const path = require('path');
const { normalizeByThreshold, weightedAverage } = require('./scoringEngine');

function scoreFx(data, cfg) {
  const items = [];
  const detail = {};

  const levelScore =
    data.usdKrwLevel !== undefined
      ? normalizeByThreshold(
          data.usdKrwLevel,
          { excellent: cfg.metrics.usdKrwLevel.thresholds.stable, poor: cfg.metrics.usdKrwLevel.thresholds.risk },
          true
        )
      : null;
  detail.usdKrwLevel = { label: cfg.metrics.usdKrwLevel.label, value: data.usdKrwLevel, score: levelScore };
  items.push({ score: levelScore, weight: 0.4 });

  const changeScore =
    data.usdKrw20dChangePct !== undefined
      ? normalizeByThreshold(
          Math.abs(data.usdKrw20dChangePct),
          { excellent: cfg.metrics.usdKrw20dChangePct.thresholds.stable, poor: cfg.metrics.usdKrw20dChangePct.thresholds.risk },
          true
        )
      : null;
  detail.usdKrw20dChangePct = { label: cfg.metrics.usdKrw20dChangePct.label, value: data.usdKrw20dChangePct, score: changeScore };
  items.push({ score: changeScore, weight: 0.6 });

  return { score: weightedAverage(items), detail };
}

function scoreUsRatePolicy(data) {
  const items = [];
  const detail = {};

  const directionScore =
    data.fedFundsRateDirection === 'cutting' ? 90 : data.fedFundsRateDirection === 'holding' ? 55 : data.fedFundsRateDirection === 'hiking' ? 20 : null;
  detail.fedFundsRateDirection = { label: 'Fed 정책금리 방향', value: data.fedFundsRateDirection, score: directionScore };
  items.push({ score: directionScore, weight: 0.6 });

  const yieldScore =
    data.us10yTreasuryYieldTrend === 'falling' ? 85 : data.us10yTreasuryYieldTrend === 'flat' ? 55 : data.us10yTreasuryYieldTrend === 'rising' ? 25 : null;
  detail.us10yTreasuryYieldTrend = { label: '미 10년물 국채금리 추세', value: data.us10yTreasuryYieldTrend, score: yieldScore };
  items.push({ score: yieldScore, weight: 0.4 });

  return { score: weightedAverage(items), detail };
}

function scoreSectorCycle(data) {
  const items = [];
  const detail = {};

  const phaseMap = { expansion: 85, peak: 45, contraction: 20, trough: 55 };
  const phaseScore = data.semiconductorCyclePhase ? phaseMap[data.semiconductorCyclePhase] ?? null : null;
  detail.semiconductorCyclePhase = { label: '반도체 업황 사이클', value: data.semiconductorCyclePhase, score: phaseScore };
  items.push({ score: phaseScore, weight: 0.6 });

  const trendMap = { rising: 80, flat: 55, falling: 25 };
  const trendScore = data.memoryPriceTrend ? trendMap[data.memoryPriceTrend] ?? null : null;
  detail.memoryPriceTrend = { label: '메모리 가격 추세', value: data.memoryPriceTrend, score: trendScore };
  items.push({ score: trendScore, weight: 0.4 });

  return { score: weightedAverage(items), detail };
}

function scoreFlowRegime(data) {
  const items = [];
  const detail = {};

  const trendToScore = (t) => {
    if (t === 'consistentBuy') return 100;
    if (t === 'netBuy') return 70;
    if (t === 'neutral') return 50;
    if (t === 'netSell') return 30;
    if (t === 'consistentSell') return 0;
    return null;
  };

  const pensionScore = trendToScore(data.pensionFundTrend20d);
  detail.pensionFundNetBuy20d = {
    label: '연기금등 20일 수급',
    trend: data.pensionFundTrend20d,
    score: pensionScore,
    note: 'KRX 투자자별 매매동향의 연기금등 카테고리, 국민연금 매매의 근사치로 활용',
  };
  items.push({ score: pensionScore, weight: 0.5 });

  const foreignScore = trendToScore(data.foreignTrend20d);
  detail.foreignNetBuy20d = { label: '외국인 20일 수급', trend: data.foreignTrend20d, score: foreignScore };
  items.push({ score: foreignScore, weight: 0.5 });

  return { score: weightedAverage(items), detail };
}

function gradeFromScore(score, regimeGrades) {
  if (score === null || score === undefined) return { grade: 'N/A', action: '데이터 부족 - 판단 보류' };
  const entries = Object.entries(regimeGrades).sort((a, b) => b[1].min - a[1].min);
  for (const [name, cfg] of entries) {
    if (score >= cfg.min) return { grade: name, action: cfg.action };
  }
  return { grade: 'risk', action: regimeGrades.risk.action };
}

function evaluateRegime(macroData, criteria) {
  if (!criteria) {
    const criteriaPath = path.join(__dirname, '..', 'config', 'marketRegime.json');
    criteria = JSON.parse(fs.readFileSync(criteriaPath, 'utf-8'));
  }

  const fx = scoreFx(macroData.fx || {}, criteria.fx);
  const usRatePolicy = scoreUsRatePolicy(macroData.usRatePolicy || {});
  const sectorCycle = scoreSectorCycle(macroData.sectorCycle || {});
  const flowRegime = scoreFlowRegime(macroData.flowRegime || {});

  const weights = criteria.regimeWeights;
  const totalScore = weightedAverage([
    { score: fx.score, weight: weights.fx },
    { score: usRatePolicy.score, weight: weights.usRatePolicy },
    { score: sectorCycle.score, weight: weights.sectorCycle },
    { score: flowRegime.score, weight: weights.flowRegime },
  ]);

  const { grade, action } = gradeFromScore(totalScore, criteria.regimeGrades);

  const specialFlags = [];
  if (macroData.flowRegime && macroData.flowRegime.indexRebalancingWindow) {
    specialFlags.push('indexRebalancingWindow');
  }
  if (macroData.fomcMeetingWithin7Days) specialFlags.push('fomcMeetingWithin7Days');
  if (macroData.majorPensionFundPolicyChange) specialFlags.push('majorPensionFundPolicyChange');

  return {
    regimeScore: totalScore !== null ? Math.round(totalScore * 10) / 10 : null,
    grade,
    action,
    breakdown: {
      fx: { score: fx.score, detail: fx.detail },
      usRatePolicy: { score: usRatePolicy.score, detail: usRatePolicy.detail },
      sectorCycle: { score: sectorCycle.score, detail: sectorCycle.detail },
      flowRegime: { score: flowRegime.score, detail: flowRegime.detail },
    },
    specialFlags,
  };
}

module.exports = { evaluateRegime };
