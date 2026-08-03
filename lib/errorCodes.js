'use strict';
/**
 * 엔진 에러 코드 정의.
 * severity는 여기 없다 — 불변식의 '검사 로직'만 코드에 있고 '위반 시 취급'은 validation.v1.json에 있다.
 * RP001·FL001·AX002는 정책 판단이 아니라 엔진/정책 파일 자체의 결함이므로 항상 즉시 throw한다.
 */
const E = {
  SC001_ScoreOutOfRange:           { code: 'SC001', message: '점수가 0~100 범위를 벗어났다' },
  SC002_ComponentMismatch:         { code: 'SC002', message: 'Σcomponents와 rawScore가 허용오차를 넘게 어긋난다' },
  CF001_ConfidenceFormulaMismatch: { code: 'CF001', message: 'confidence.value가 정책 공식과 불일치한다' },
  CF002_ConfidenceOutOfRange:      { code: 'CF002', message: 'confidence 값이 0~100 또는 null이 아니다' },
  AX001_MissingAxis:               { code: 'AX001', message: 'criteria에 있는 축의 스코어러가 없다' },
  AX002_EmptyCriteria:             { code: 'AX002', message: 'categoryWeights가 비어 있다' },
  PN001_PositivePenalty:           { code: 'PN001', message: 'riskPenalty가 양수다 — Adjustment는 감점 전용이다' },
  RP001_UnknownMatchField:         { code: 'RP001', message: 'riskPenalty 규칙의 matchField가 알 수 없는 축이다' },
  FL001_UnknownFlag:               { code: 'FL001', message: '엔진이 flagCodes에 없는 flag를 생성했다' },
};

class EngineError extends Error {
  constructor(spec, detail) {
    super(`[${spec.code}] ${spec.message}${detail !== undefined && detail !== null ? ` — ${detail}` : ''}`);
    this.name = 'EngineError';
    this.errorCode = spec.code;
    this.detail = detail === undefined ? null : detail;
  }
}

function throwErr(spec, detail) { throw new EngineError(spec, detail); }

module.exports = { E, EngineError, throwErr };
