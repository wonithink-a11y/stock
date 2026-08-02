'use strict';
const { classify } = require('../eventClassifiers/dart');

function toIso8601(yyyymmdd) {
  const s = String(yyyymmdd);
  if (!/^\d{8}$/.test(s)) throw new Error(`Invalid DART date: ${yyyymmdd}`);
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00:00+09:00`;
}

function buildEvent(disclosure) {
  if (!disclosure.stock_code) throw new Error('Invalid disclosure: stock_code missing');
  if (!disclosure.rcept_no) throw new Error('Invalid disclosure: rcept_no missing');
  const type = classify(disclosure.report_nm);
  if (!type) return null;
  return {
    eventId: `dart:${disclosure.rcept_no}`,
    ticker: disclosure.stock_code,
    type,
    occurredAt: toIso8601(disclosure.rcept_dt),
    source: 'dart',
    payload: { reportNm: disclosure.report_nm },
  };
}
module.exports = { buildEvent };
