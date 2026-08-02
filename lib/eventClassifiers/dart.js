'use strict';
function classify(reportNm) {
  const nm = String(reportNm || '').replace(/\s/g, '');
  const isRelease = /해제|재개/.test(nm);
  if (/관리종목/.test(nm)) return isRelease ? 'MANAGEMENT_RELEASE' : 'MANAGEMENT_DESIGNATION';
  if (/거래정지/.test(nm)) return isRelease ? 'TRADING_RESUME' : 'TRADING_HALT';
  if (/상장폐지/.test(nm)) return /실질심사/.test(nm) ? 'DELISTING_REVIEW' : 'DELISTED';
  if (/투자주의환기/.test(nm)) return isRelease ? 'INVESTMENT_WARNING_RELEASE' : 'INVESTMENT_WARNING';
  if (/전환사채|신주인수권부사채|교환사채/.test(nm)) return 'MEZZANINE_ISSUED';
  if (/유상증자/.test(nm)) return 'RIGHTS_OFFERING';
  return null;
}
module.exports = { classify };
