/**
 * portfolioAdvisor.js
 *
 * 보유 종목(수량/평균매입가/현재가)에 scoringEngine의 종목 점수와
 * marketRegimeEngine의 시장 국면을 결합해 참고용 신호를 만듭니다.
 *
 * ⚠️ 투자자문이 아닙니다. 매도/매수/보유를 "결정"해주는 도구가 아니라,
 * 여러 신호를 한 화면에 모아 보여주는 참고자료 생성기입니다.
 * 최종 판단은 항상 사용자 본인의 몫입니다.
 *
 * 설계 원칙: 평가손익(수익/손실 여부)은 신호 산출에 절대 관여하지 않습니다.
 * "손실 중이니 물타기/손절" 같은 감정적 판단을 피하고, 종목 자체의 펀더멘털·기술적
 * 신호와 손익 현황을 분리해서 보여주기 위함입니다.
 */

const { scoreStock } = require('./scoringEngine');
const { evaluateRegime } = require('./marketRegimeEngine');

/**
 * 종목 점수 + 시장 국면을 조합해 참고 신호를 산출합니다.
 * 순수 규칙 기반이라 로직이 투명하게 드러납니다 (블랙박스 아님).
 */
function deriveSignal(stockScore, regimeGrade, warnings = []) {
  // 경고 플래그(데드캣바운스, 고부채 등)가 있으면 신호를 보수적으로 하향 조정
  const hasCriticalWarning = warnings.some((w) =>
    ['deadCatBounce', 'auditOpinionNonStandard', 'majorShareholderSelloff'].includes(w)
  );

  if (stockScore === null || stockScore === undefined) {
    return { action: '판단 보류', reason: '점수 산출에 필요한 데이터가 부족합니다.' };
  }

  // 시장 국면이 risk면 종목 점수와 무관하게 신규 비중 확대는 보수적으로 제한
  if (regimeGrade === 'risk') {
    if (stockScore >= 65) {
      return {
        action: '유지 (신규 확대는 보류)',
        reason: '종목 자체 신호는 긍정적이나 시장 전체 유동성 리스크가 커서 비중 확대는 신중하게 접근하는 것을 참고하세요.',
      };
    }
    return {
      action: '비중 축소 고려',
      reason: '종목 신호도 약하고 시장 국면도 위험 구간이라 리스크 관리를 우선 검토할 만합니다.',
    };
  }

  let action, reason;
  if (stockScore >= 80) {
    action = '비중 확대 고려';
    reason = '펀더멘털·기술적·수급 신호가 전반적으로 긍정적입니다.';
  } else if (stockScore >= 65) {
    action = '유지 (긍정적)';
    reason = '긍정적 신호가 우세하나 확대보다는 현 비중 유지가 참고할 만합니다.';
  } else if (stockScore >= 50) {
    action = '유지 (중립 관찰)';
    reason = '뚜렷한 방향성 신호가 약해 추가 관찰이 필요합니다.';
  } else if (stockScore >= 35) {
    action = '비중 축소 고려';
    reason = '부정적 신호가 우세합니다. 비중 축소를 검토할 만한 근거가 있습니다.';
  } else {
    action = '매도 검토';
    reason = '펀더멘털·기술적 신호 모두 부정적입니다.';
  }

  if (hasCriticalWarning) {
    reason += ' 단, 경고 신호가 감지되어 있어 더 보수적으로 접근하는 것을 참고하세요.';
    if (action === '비중 확대 고려') action = '유지 (확대는 보류)';
  }

  return { action, reason };
}

/**
 * @param {object} holding - { ticker, name, quantity, avgPrice, currentPrice }
 * @param {object} analysisData - scoreStock()에 넣을 종목 분석 원시 데이터
 * @param {object} regimeResult - evaluateRegime()의 결과 (여러 종목에 재사용 가능하므로 외부에서 1회 계산해 전달)
 * @param {object} criteria - criteria.json (미제공시 기본 로드)
 */
function evaluateHolding(holding, analysisData, regimeResult, criteria) {
  const stockResult = scoreStock({ ...analysisData, ticker: holding.ticker, name: holding.name }, criteria);

  const currentValue = holding.quantity * holding.currentPrice;
  const investedValue = holding.quantity * holding.avgPrice;
  const unrealizedPnL = currentValue - investedValue;
  const unrealizedPnLPct = investedValue !== 0 ? (unrealizedPnL / investedValue) * 100 : null;

  const signal = deriveSignal(stockResult.totalScore, regimeResult.grade, stockResult.warnings);

  return {
    ticker: holding.ticker,
    name: holding.name,
    quantity: holding.quantity,
    avgPrice: holding.avgPrice,
    currentPrice: holding.currentPrice,
    currentValue,
    investedValue,
    unrealizedPnL,
    unrealizedPnLPct: unrealizedPnLPct !== null ? Math.round(unrealizedPnLPct * 100) / 100 : null,

    stockScore: stockResult.totalScore,
    stockGrade: stockResult.grade,
    stockWarnings: stockResult.warnings,

    marketRegime: regimeResult.grade,

    referenceSignal: signal.action,
    signalReason: signal.reason,

    breakdown: stockResult.breakdown,
  };
}

/**
 * 여러 보유 종목을 일괄 평가합니다.
 *
 * @param {Array} holdings - [{ ticker, name, quantity, avgPrice, currentPrice, analysisData }]
 * @param {object} macroData - evaluateRegime()에 넣을 거시 데이터
 * @param {object} criteria - criteria.json (미제공시 기본 로드)
 */
function evaluatePortfolio(holdings, macroData, criteria) {
  const regimeResult = evaluateRegime(macroData);

  const results = holdings.map((h) => evaluateHolding(h, h.analysisData, regimeResult, criteria));

  const totalCurrentValue = results.reduce((sum, r) => sum + r.currentValue, 0);
  const totalInvestedValue = results.reduce((sum, r) => sum + r.investedValue, 0);
  const totalUnrealizedPnL = totalCurrentValue - totalInvestedValue;
  const totalUnrealizedPnLPct = totalInvestedValue !== 0 ? (totalUnrealizedPnL / totalInvestedValue) * 100 : null;

  return {
    marketRegime: { grade: regimeResult.grade, score: regimeResult.regimeScore, action: regimeResult.action },
    holdings: results,
    summary: {
      totalCurrentValue,
      totalInvestedValue,
      totalUnrealizedPnL,
      totalUnrealizedPnLPct: totalUnrealizedPnLPct !== null ? Math.round(totalUnrealizedPnLPct * 100) / 100 : null,
    },
  };
}

module.exports = { evaluateHolding, evaluatePortfolio, deriveSignal };
