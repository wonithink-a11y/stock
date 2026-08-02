'use strict';
const CLASSIFIER_VERSION = 'DC-1.1';

const NEG     = /해제|해소|재개|취소|철회|기각|각하|제외|종료/;   // 상태 종료 방향
const PENDING = /예고|우려|사유발생|사유추가|이의신청|신청서/;     // 미확정

// 그룹별 독립 판정 → 복합 공시("관리종목지정 및 매매거래정지")에서 다중 이벤트 산출
function classify(reportNm) {
  const nm = String(reportNm || '').replace(/\s/g, '');
  const out = [];

  if (/관리종목/.test(nm)) {
    out.push(PENDING.test(nm) ? 'MANAGEMENT_DESIGNATION_PENDING'
           : NEG.test(nm)     ? 'MANAGEMENT_RELEASE'
           :                    'MANAGEMENT_DESIGNATION');
  }
  if (/거래정지/.test(nm)) {
    out.push(PENDING.test(nm) ? 'TRADING_HALT_PENDING'
           : NEG.test(nm)     ? 'TRADING_RESUME'
           :                    'TRADING_HALT');
  }
  if (/상장폐지/.test(nm)) {
    out.push(PENDING.test(nm)    ? 'DELISTING_REVIEW_PENDING'
           : NEG.test(nm)        ? 'DELISTING_REVIEW_RELEASE'
           : /실질심사/.test(nm) ? 'DELISTING_REVIEW'
           : /확정|결정/.test(nm)? 'DELISTED'
           :                       'DELISTING_REVIEW');   // 불명확 시 보수적으로 심사단계
  }
  if (/투자주의환기/.test(nm)) {
    out.push(PENDING.test(nm) ? 'INVESTMENT_WARNING_PENDING'
           : NEG.test(nm)     ? 'INVESTMENT_WARNING_RELEASE'
           :                    'INVESTMENT_WARNING');
  }
  if (/전환사채|신주인수권부사채|교환사채/.test(nm) && !NEG.test(nm)) out.push('MEZZANINE_ISSUED');
  if (/유상증자/.test(nm) && !NEG.test(nm)) out.push('RIGHTS_OFFERING');

  return out;
}

module.exports = { classify, CLASSIFIER_VERSION };
