'use strict';
/**
 * ScoreResult 불변식 검사. RULES 배열 기반.
 * severity·message는 여기 없다 — validation.v1.json이 유일한 출처다.
 * 정책에 없는 규칙은 검사하지 않는다(정책이 코드보다 상위).
 */
const { EngineError } = require('./errorCodes');
const { computeConfidenceValue } = require('./scoringEngine');

const inRange = (v) => v === null || (typeof v === 'number' && v >= 0 && v <= 100);

const RULES = [
  { code: 'INV-001', test: (r) => inRange(r.rawScore) },
  { code: 'INV-002', test: (r) => r.riskPenalty <= 0 },
  { code: 'INV-003', test: (r) => inRange(r.finalScore) },
  { code: 'INV-004', test: (r, p, tol) => {
      if (r.rawScore === null) return true;
      const sum = Object.values(r.components).filter((v) => v !== null).reduce((s, v) => s + v, 0);
      return Math.abs(sum - r.rawScore) <= tol;
    } },
  { code: 'INV-005', test: (r) => inRange(r.confidence.value) },
  { code: 'INV-006', test: (r) => ['coverage', 'freshness', 'quality'].every((k) => inRange(r.confidence[k])) },
  { code: 'INV-007', test: (r, p) => {
      const { value, ...parts } = r.confidence;
      return computeConfidenceValue(parts, p.confidence) === value;
    } },
];

/**
 * @param {object} scoreResult - score()의 반환({meta,result}) 또는 result 단독
 * @param {string} mode - 'strict'(CI: warning도 throw) | 'lenient'(운영: critical만 throw)
 * @returns {Array} 위반 목록 (lenient에서 warning은 여기로만 나온다)
 */
function validate(scoreResult, policies, { mode = 'lenient' } = {}) {
  const r = scoreResult.result || scoreResult;
  const vp = policies.validation;
  const tol = mode === 'strict' ? vp.strictTolerance : vp.lenientTolerance;

  const violations = [];
  for (const rule of RULES) {
    const spec = vp.rules.find((x) => x.code === rule.code);
    if (!spec) continue;
    let ok;
    try { ok = rule.test(r, policies, tol); } catch (err) { ok = false; }
    if (!ok) violations.push({ code: rule.code, errorCode: spec.errorCode, severity: spec.severity, message: spec.message });
  }

  const fatal = violations.filter((v) => v.severity === 'critical' || mode === 'strict');
  if (fatal.length > 0) {
    throw new EngineError({ code: fatal[0].errorCode, message: fatal[0].message },
      `${fatal[0].code}${fatal.length > 1 ? ` 외 ${fatal.length - 1}건` : ''} (ticker=${r.ticker})`);
  }
  return violations;
}

module.exports = { validate, RULES };
