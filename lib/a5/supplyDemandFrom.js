/**
 * A5 supplyDemand 축 — scripts/collect.js(netBuysToTrend·fetchSupplyDemandKR)의
 * 순수 분류 로직을 그대로 복사했다(BF-1.1 §7 A5 인수 조건 4: 운영과 다른 계산식을
 * 쓰지 않는다). require(collect.js)로 재사용하지 않는 이유는 lib/a5/technicalFrom.js
 * 와 동일 — 그 파일은 module.exports가 없고 파일 하단에서 main()을 즉시 실행하는
 * 라이브 수집 스크립트다. 복사가 안전한 선택이다(원본 무변경).
 *
 * 운영(scripts/collect.js)은 네이버 API가 이미 합산해 준 "외국인/기관" 일별 순매수
 * 수량(quant)을 그대로 쓴다. 과거 임의 시점을 물을 수 없는 라이브 전용 API라
 * 10년 백필(A5)에는 애초에 쓸 수 없다 — 대신 A4(data/backfill/supplyDemand/a4/,
 * KRX 투자자별 매매대금·수량 원본, PIT-safe)에서 같은 의미의 값을 만든다.
 *
 * 카테고리 매핑(scripts/probe-a4-supplydemand-vertical-slice.js가 이미 검증해
 * 둔 구성 재사용): 외국인=['외국인'], 기관=[금융투자·보험·투신·사모·은행·
 * 기타금융·연기금·기타법인]. 기타외국인·개인·전체는 제외 — 네이버가 주는
 * "외국인/기관" 2분류에 가장 가까운 매핑이다. 단 그 확률 스크립트의
 * trendFromWindow()는 "잠정 분류(production 규칙 아님, 일수 기준)"라고 스스로
 * 명시한 placeholder였다 — 여기서는 그 대신 production의 진짜 규칙
 * (netBuysToTrend, 합계 기준)을 그대로 쓴다.
 *
 * 원본: scripts/collect.js:432-441(netBuysToTrend). 원본이 바뀌면 이 파일도
 * 같이 봐야 한다.
 */
'use strict';

const FOREIGN_CATEGORIES = ['외국인'];
const INSTITUTION_CATEGORIES = ['금융투자', '보험', '투신', '사모', '은행', '기타금융', '연기금', '기타법인'];

/** scripts/collect.js:432 netBuysToTrend 그대로 복사 - 계산식 변경 없음. */
function netBuysToTrend(netBuys) {
  if (!netBuys || netBuys.length === 0) return null;
  const buyDays = netBuys.filter((v) => v > 0).length;
  const total = netBuys.reduce((a, b) => a + b, 0);
  if (buyDays === netBuys.length) return 'consistentBuy';
  if (buyDays === 0) return 'consistentSell';
  if (total > 0) return 'netBuy';
  if (total < 0) return 'netSell';
  return 'neutral';
}

function netVolumeOf(rec, categories) {
  let net = 0;
  for (const c of categories) {
    net += (rec.buyVolume[c] || 0) - (rec.sellVolume[c] || 0);
  }
  return net;
}

/**
 * records: 그 종목의 A4 원본 전체 기간(정렬·asOf 필터 불문 - fundamentalsFrom과
 * 같은 계약, 여기서 asOf 이하만 골라 정렬한다 - PIT는 여기서 강제한다).
 * 최근 5거래일로 5일 추세를 낸다. 5일이 안 차도(신규상장 등) 있는 만큼만 쓴다 -
 * netBuysToTrend가 임의 길이를 받으므로 운영과 동일한 관용도.
 */
function supplyDemandFrom(records, asOf) {
  const sorted = (records || [])
    .filter((r) => r.date <= asOf)
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const window = sorted.slice(-5);
  if (window.length === 0) {
    return { values: { foreignTrend5d: null, institutionTrend5d: null }, windowSize: 0, lastDate: null };
  }
  const foreignNet = window.map((r) => netVolumeOf(r, FOREIGN_CATEGORIES));
  const institutionNet = window.map((r) => netVolumeOf(r, INSTITUTION_CATEGORIES));
  return {
    values: {
      foreignTrend5d: netBuysToTrend(foreignNet),
      institutionTrend5d: netBuysToTrend(institutionNet),
    },
    windowSize: window.length,
    lastDate: window[window.length - 1].date,
  };
}

module.exports = { supplyDemandFrom, netBuysToTrend, FOREIGN_CATEGORIES, INSTITUTION_CATEGORIES };
