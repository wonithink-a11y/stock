'use strict';
const { classify, CLASSIFIER_VERSION } = require('../eventClassifiers/dart');

function toIso8601(yyyymmdd) {
  const s = String(yyyymmdd);
  if (!/^\d{8}$/.test(s)) throw new Error(`Invalid DART date: ${yyyymmdd}`);
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00:00+09:00`;
}

function buildEvents(disclosure) {
  if (!disclosure.stock_code) throw new Error('Invalid disclosure: stock_code missing');
  if (!disclosure.rcept_no)   throw new Error('Invalid disclosure: rcept_no missing');
  const occurredAt = toIso8601(disclosure.rcept_dt);

  return classify(disclosure.report_nm).map((type, seq) => ({
    eventId: `dart:${disclosure.rcept_no}#${seq}`,
    ticker: disclosure.stock_code,
    type,
    occurredAt,
    // rcept_dt는 일 단위라 동일자 이벤트 순서를 구분 못함 → rcept_no + seq를 tiebreaker로 고정
    sortKey: `${disclosure.rcept_dt}:${disclosure.rcept_no}:${String(seq).padStart(2, '0')}`,
    source: 'dart',
    classifierVersion: CLASSIFIER_VERSION,
    payload: { reportNm: disclosure.report_nm, rceptNo: disclosure.rcept_no },
  }));
}

module.exports = { buildEvents };
