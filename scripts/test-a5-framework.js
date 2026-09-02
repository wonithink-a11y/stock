#!/usr/bin/env node
/**
 * A5 프레임워크 회귀 — PIT 선택 · 피처 레지스트리 · 리졸버.
 *   node scripts/test-a5-framework.js
 *
 * 네트워크도 백필 산출물도 필요 없다. 지키려는 것은 하나다:
 * **A5는 asOf 시점에 알 수 있었던 것만 쓴다.** 이 축이 무너지면 점수도 등급도
 * 정상으로 보이고 백테스트만 좋아진다. 조용한 실패라 여기서 막는다.
 */
'use strict';

const path = require('path');
const ROOT = path.join(__dirname, '..');
const pit = require(path.join(ROOT, 'lib/a5/pitSelector'));
const reg = require(path.join(ROOT, 'lib/a5/featureRegistry'));
const { resolve, fundamentalsFrom, shareholderReturnFrom, valuationFrom } =
  require(path.join(ROOT, 'lib/a5/resolver'));
const criteria = require(path.join(ROOT, 'lib/loadCriteria')).loadCriteria('KR').criteria;

let passed = 0, failed = 0;
function ok(name, cond, detail) {
  if (cond) { passed++; console.log(`  OK    ${name}`); }
  else { failed++; console.log(`  FAIL  ${name}${detail ? '  — ' + detail : ''}`); }
}
const J = (x) => JSON.stringify(x);

/** 재무 레코드 픽스처. availableFrom이 계약의 축이다. */
function R(fiscalYear, availableFrom, over) {
  return Object.assign({
    corp: '00000001', ticker: '000001', fiscalYear, availableFrom,
    periodEnd: `${fiscalYear}-12-31`, rceptNo: `${availableFrom.replace(/-/g, '')}000001`,
    fsDiv: 'CFS', currency: 'KRW', sicCode: '26',
    currentAssets: 200, currentLiab: 100, liabilities: 400, equity: 1000,
    revenue: 1000, opProfit: 100, netIncome: 50,
  }, over || {});
}

/** A3b(EPS·배당) 레코드 픽스처. availableFrom은 A3b 원본 포맷(YYYYMMDD)이다. */
function RB(fiscalYear, availableFrom, over) {
  return Object.assign({
    corp: '00000001', ticker: '000001', fiscalYear, availableFrom,
    periodEnd: `${fiscalYear}1231`, rceptNo: `${availableFrom}000001`,
    eps: 1000, dividendPerShare: 0, dividendRowPresent: true, dividendStockKnd: '보통주',
  }, over || {});
}

/** OHLCV 캔들 픽스처. n일치, 오름차순, 임의 걷는 종가로 채운다(재현성 위해 결정적). */
function candlesFixture(n, startDate, startClose = 10000) {
  const out = [];
  let close = startClose;
  const start = new Date(startDate + 'T00:00:00Z');
  for (let i = 0; i < n; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    close = Math.round(close * (1 + ((i % 7) - 3) / 200)); // 결정적 등락 (±1.5%대)
    out.push({ date: d.toISOString().slice(0, 10), close, volume: 100000 + (i % 5) * 1000 });
  }
  return out;
}

console.log('[PIT 선택 — asOf 시점에 알 수 있었던 것만]');
const recs = [
  R(2020, '2021-03-31'),
  R(2021, '2022-03-31'),
  R(2022, '2023-03-31'),
];
ok('asOf 이전의 가장 최근 사업연도를 고른다',
   pit.selectAsOf(recs, '2023-06-30').fiscalYear === 2022);
ok('아직 공시되지 않은 레코드는 고르지 않는다 (규칙 1)',
   pit.selectAsOf(recs, '2023-03-30').fiscalYear === 2021,
   J(pit.selectAsOf(recs, '2023-03-30')));
ok('공시 당일은 알 수 있었다 (경계는 이상이다)',
   pit.selectAsOf(recs, '2023-03-31').fiscalYear === 2022);
ok('아무것도 몰랐던 시점은 null (0이나 빈 레코드가 아니다)',
   pit.selectAsOf(recs, '2020-01-01') === null);

// 정정공시 — 같은 (corp, fiscalYear)에 availableFrom이 여럿. 중복이 아니라 사실이다.
const restated = recs.concat([R(2022, '2023-11-15', { netIncome: 70 })]);
ok('정정 전 시점은 원본을 본다 (최신 정정본을 쓰면 미래를 본다)',
   pit.selectAsOf(restated, '2023-06-30').netIncome === 50,
   J(pit.selectAsOf(restated, '2023-06-30').availableFrom));
ok('정정 후 시점은 정정본을 본다 (그 시점까지의 마지막 정정본)',
   pit.selectAsOf(restated, '2023-12-01').netIncome === 70);
ok('같은 사업연도의 정정본이 더 최신 연도를 이기지 않는다 (규칙 2가 3보다 먼저)',
   pit.selectAsOf(restated.concat([R(2023, '2024-03-31')]), '2024-06-30')
     .fiscalYear === 2023);

console.log('\n[이력 — 연도마다 따로 고른다]');
// 한 레코드의 전기 열을 쓰면 그 값의 availableFrom이 '그 보고서 접수일'이 되어
// 과거를 실제보다 늦게 안 것으로 기록한다(교훈47). 연도마다 독립 선택이라야 한다.
const h = pit.selectHistory(restated, '2023-12-01', 3);
ok('요청한 개수만큼 돌려준다', h.length === 3, String(h.length));
ok('최신 연도부터 거슬러 간다',
   h[0].fiscalYear === 2022 && h[1].fiscalYear === 2021 && h[2].fiscalYear === 2020);
ok('이력의 각 해도 asOf 이전 것만 쓴다 (정정본 반영)',
   h[0].netIncome === 70 && h[0].availableFrom === '2023-11-15');
const hEarly = pit.selectHistory(restated, '2023-06-30', 3);
ok('같은 이력이라도 asOf가 다르면 다른 정정본을 쓴다',
   hEarly[0].netIncome === 50, J(hEarly[0].availableFrom));

// 빈 해를 앞으로 당겨 채우면 5년 이력이 실제보다 촘촘해 보이고 최솟값이 낙관적이 된다.
const gapped = [R(2018, '2019-03-31'), R(2020, '2021-03-31'), R(2021, '2022-03-31')];
const hg = pit.selectHistory(gapped, '2022-06-30', 3);
ok('없는 해는 null로 남긴다 (당겨 채우지 않는다)',
   hg[0].fiscalYear === 2021 && hg[1].fiscalYear === 2020 && hg[2] === null,
   J(hg.map((r) => (r ? r.fiscalYear : null))));

console.log('\n[미래 참조 방어]');
ok('선택기를 거친 레코드는 위반이 아니다',
   pit.violatesPit(pit.selectAsOf(recs, '2023-06-30'), '2023-06-30') === false);
ok('직접 넣은 미래 레코드는 잡는다 (호출부가 선택기를 우회하는 경로)',
   pit.violatesPit(R(2023, '2024-03-31'), '2023-06-30') === true);
ok('freshness는 며칠 묵었는지를 사실로 낸다 (점수로 바꾸지 않는다)',
   pit.freshnessDays(R(2022, '2023-03-31'), '2023-06-30') === 91,
   String(pit.freshnessDays(R(2022, '2023-03-31'), '2023-06-30')));

console.log('\n[포맷 정규화 — A3b는 availableFrom을 YYYYMMDD로 쓴다]');
// A3 'YYYY-MM-DD' · A3b 'YYYYMMDD'. 정규화 없이 문자열째 비교하면 '-'가 숫자보다
// 작아 asOf와 같은 해의 압축형 레코드가 전부 미래로 읽힌다(실측 2,752/25,531건,
// 2026-08-12) — A3b 계약의 원본 포맷은 그대로 두고 pitSelector 안에서만 정규화한다.
ok('압축형을 하이픈형으로 정규화한다', pit.normDate('20240321') === '2024-03-21');
ok('이미 하이픈형이면 그대로 둔다', pit.normDate('2024-03-21') === '2024-03-21');
ok('모르는 형식은 조용히 잘못 비교하지 않고 던진다 (교훈57)',
   (() => { try { pit.normDate('2024/03/21'); return false; } catch (e) { return true; } })());

ok('★ asOf와 같은 해의 압축형 레코드가 더 이상 미래로 오판되지 않는다 (실측 재현)',
   pit.lte('20260429', '2026-08-12') === true);
ok('압축형 asOf도 같은 규칙으로 정규화된다',
   pit.lte('2026-04-29', '20260812') === true);
ok('실제로 미래인 압축형 레코드는 여전히 걸러진다',
   pit.lte('20270101', '2026-08-12') === false);

const mixed = [
  R(2023, '2024-03-31'),                                 // A3 형식
  R(2024, '20250321', { rceptNo: '20250321000001' }),     // A3b 형식
];
ok('A3·A3b 레코드가 섞여도 asOf 시점에 맞는 최신 연도를 고른다',
   pit.selectAsOf(mixed, '2025-06-30').fiscalYear === 2024,
   J(pit.selectAsOf(mixed, '2025-06-30')));
ok('압축형 레코드가 아직 이르면 그 앞 연도로 물러난다 (규칙 1)',
   pit.selectAsOf(mixed, '2025-02-01').fiscalYear === 2023,
   J(pit.selectAsOf(mixed, '2025-02-01')));
ok('압축형·하이픈형 동률 타이브레이크도 정규화 기준으로 비교한다 (규칙 3)',
   pit.selectFiscalYear([R(2023, '2023-11-15'), R(2023, '20240110', { rceptNo: 'x' })],
     2023, '2024-06-30').availableFrom === '20240110');

ok('freshnessDays가 압축형에서도 NaN이 아니라 숫자를 낸다 (기존은 100% null이었다)',
   typeof pit.freshnessDays(R(2024, '20250321'), '2025-06-30') === 'number',
   String(pit.freshnessDays(R(2024, '20250321'), '2025-06-30')));
ok('압축형 freshnessDays 값이 실제 경과일과 맞는다',
   pit.freshnessDays(R(2024, '20250321'), '2025-06-30') === 101,
   String(pit.freshnessDays(R(2024, '20250321'), '2025-06-30')));

console.log('\n[피처 레지스트리 — 가용성이 값이다]');
const aw = reg.availableWeight(criteria);
ok('계산 가능 가중치를 수치로 낸다', typeof aw.total === 'number', J(aw.total));
// 2026-08-21 — pbr·peg available:true 전환(A3d 재수집 완료) 후 0.65로
// minimumDataCoverage(0.6)를 넘었다. 운영 투입 가능/불가는 이 값이 답하지
// featureRegistry 구현 여부가 답하지 않는다(이 파일 상단 원칙) — 지금은
// 넘긴 쪽이라 부등호를 뒤집는다.
ok('minimumDataCoverage를 넘는다 (2026-08-21, A3d 재수집으로 pbr·peg 전환 후)',
   aw.total >= criteria.minimumDataCoverage,
   `${aw.total} vs ${criteria.minimumDataCoverage}`);
ok('technical은 통째로 가용하다',
   aw.byCategory.technical.availableFraction === 1);
ok('valuation은 절반 가용하다 (pbr·peg는 available, perRelative·marginOfSafety는 아직)',
   aw.byCategory.valuation.availableFraction === 0.5, J(aw.byCategory.valuation));
ok('supplyDemand는 통째로 불가하다 (A4 미정)',
   aw.byCategory.supplyDemand.availableFraction === 0);
ok('fundamental은 통째로 가용하다 (2026-08-12, shareholderReturn 구현 완료)',
   aw.byCategory.fundamental.availableFraction === 1,
   J(aw.byCategory.fundamental));

// A3b를 할지 말지의 근거가 되는 수치. 문서의 주장이 아니라 코드가 답한다.
const unlockA3b = reg.weightUnlockedBy(criteria, 'A3b');
const unlockA4 = reg.weightUnlockedBy(criteria, 'A4');
ok('A3b가 여는 가중치를 계산한다', unlockA3b > 0, String(unlockA3b));
ok('A4가 여는 가중치를 계산한다', unlockA4 > 0, String(unlockA4));
ok('A3b + A4로도 marginOfSafety는 안 열린다 (소스 미정)',
   reg.FEATURES.marginOfSafety.stage === null);
ok('막힌 피처마다 이유가 있다 (blockedBy 없는 false가 없다)',
   reg.blockers().filter((b) => b.stage !== null && !b.blockedBy).length === 0,
   J(reg.blockers().filter((b) => b.stage !== null && !b.blockedBy)));

console.log('\n[리졸버 — 결측은 채우지 않는다]');
const r1 = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                     fundamentals: restated, price: { date: '2023-06-30', close: 5000 } });
ok('PIT 규칙으로 고른 레코드에서 지표를 유도한다',
   r1.stockData.fundamental.roe === 5, J(r1.stockData.fundamental.roe));
ok('부채비율을 낸다 (liabilities / equity)',
   r1.stockData.fundamental.debtRatio === 40);
ok('유동비율을 낸다', r1.stockData.fundamental.currentRatio === 200);
ok('provenance가 어느 레코드였는지 지목한다',
   r1.provenance.fundamentals.fiscalYear === 2022
   && r1.provenance.fundamentals.availableFrom === '2023-03-31',
   J(r1.provenance.fundamentals));
ok('provenance에 rceptNo가 있다 (원 공시로 되짚어 간다)',
   !!r1.provenance.fundamentals.rceptNo);
ok('sicCode의 PIT 아님을 결과에 실어 보낸다 (숨기지 않는다)',
   r1.provenance.sectorNotPointInTime === true);
ok('미래 참조가 없다', r1.pitViolation === false);

// 금융업 양식 — 유동 항목이 없다. null이 정상이고 대체값을 넣지 않는다.
const fin = [R(2022, '2023-03-31', { currentAssets: null, currentLiab: null })];
const rf = resolve({ ticker: '000002', corp: '00000002', asOf: '2023-06-30',
                     fundamentals: fin });
ok('금융업의 유동비율은 null이다 (0이나 대체값이 아니다)',
   rf.stockData.fundamental.currentRatio === null);
ok('결측 지표가 missing 목록에 남는다',
   rf.missing.includes('currentRatio'), J(rf.missing));

// A3b 전까지 비어 있어야 하는 값. 채우면 계약 위반이다.
ok('배당 이력은 null이다 (A3b 전까지 채우지 않는다)',
   r1.stockData.fundamental.buybackOrDividendHistory === null);
ok('배당 이력이 missing에 잡힌다',
   r1.missing.includes('buybackOrDividendHistory'));

// 0으로 나누기 — Infinity를 내보내면 하류가 그것을 점수로 만든다.
const zero = [R(2022, '2023-03-31', { equity: 0, revenue: 0 })];
const rz = resolve({ ticker: '000003', corp: '00000003', asOf: '2023-06-30',
                     fundamentals: zero });
ok('자본이 0이면 ROE는 null이다 (Infinity가 아니다)',
   rz.stockData.fundamental.roe === null, J(rz.stockData.fundamental.roe));
ok('매출이 0이면 영업이익률 추세도 null이다',
   rz.stockData.fundamental.operatingMarginTrend === null);

// 레코드가 하나도 없는 시점 — 빈 값이 아니라 '아무것도 몰랐다'로 남아야 한다.
const rEmpty = resolve({ ticker: '000004', corp: '00000004', asOf: '2015-01-01',
                         fundamentals: restated });
ok('아무것도 몰랐던 시점은 provenance가 null이다',
   rEmpty.provenance.fundamentals === null);
ok('그때도 pitViolation은 false다 (없는 것은 위반이 아니다)',
   rEmpty.pitViolation === false);

// confidence 파트 — 정책이 선언만 하고 비워둔 자리를 채운다.
ok('freshness를 confidence 입력으로 넘긴다',
   typeof r1.confidenceInputs.freshnessDays === 'number',
   J(r1.confidenceInputs));
const rq = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                     fundamentals: restated,
                     quality: { meta: { schema: 'QR-1.0', inputDigest: 'sha256:x',
                                        sampleComplete: false },
                                coverage: { overall: { rate: 0.53 } } } });
ok('품질 리포트가 confidence 입력으로 흐른다',
   rq.confidenceInputs.qualitySampleComplete === false
   && rq.confidenceInputs.qualityCoverageRate === 0.53, J(rq.confidenceInputs));
ok('품질 출처가 provenance에 남는다 (어느 리포트로 채점했는가)',
   rq.provenance.quality.inputDigest === 'sha256:x');

console.log('\n[shareholderReturn — A3b 배당 이력]');
const divYes = [RB(2021, '20220331', { dividendPerShare: 0 }), RB(2022, '20230331', { dividendPerShare: 500 })];
const rSrYes = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                         fundamentals: restated, dividendEps: divYes });
ok('5년 이력 중 한 해라도 배당 있으면 true',
   rSrYes.stockData.fundamental.buybackOrDividendHistory === true);
ok('dividendEps를 넘겨도 stockData.valuation은 안 생긴다 (아래 조정 기준 불일치 참조)',
   rSrYes.stockData.valuation === undefined);

const divNo = [RB(2021, '20220331', { dividendPerShare: 0 }), RB(2022, '20230331', { dividendPerShare: 0 })];
const rSrNo = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                        fundamentals: restated, dividendEps: divNo });
ok('전 이력 무배당이면 false다 (null이 아니다 — 확인한 사실이다)',
   rSrNo.stockData.fundamental.buybackOrDividendHistory === false);

const rSrEmpty = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                           fundamentals: restated, dividendEps: [] });
ok('그 시점 A3b 레코드가 하나도 없으면 null이다 (false로 지어내지 않는다)',
   rSrEmpty.stockData.fundamental.buybackOrDividendHistory === null);
ok('dividendEps를 아예 안 넘긴 기존 호출은 그대로 null이다 (회귀 없음)',
   r1.stockData.fundamental.buybackOrDividendHistory === null
   && r1.stockData.valuation === undefined);

console.log('\n[valuationFrom — 공식은 맞다. resolve()엔 아직 안 붙인다]');
// ★ resolve()가 안 부르므로 여기서는 valuationFrom()을 직접 호출해 "공식 자체는
// 맞다"만 확인한다. price·eps 조정 기준이 같다는 전제에서만 유효하다 — 그 전제가
// 실제로는 안 맞는다는 게 이번 조사의 결론이다(A2a adjusted:true vs A3b 원본 EPS).
const epsGrow = [RB(2021, '20220331', { eps: 1000 }), RB(2022, '20230331', { eps: 1200 })];
const valDirect = valuationFrom(epsGrow, '2023-06-30', { date: '2023-06-30', close: 24000 });
ok('per = price / eps (같은 조정 기준이라는 전제하에)',
   valDirect.values.per === 20, J(valDirect.values));
ok('epsGrowthRate = (당해eps/전해eps - 1) * 100',
   valDirect.values.epsGrowthRate === 20, J(valDirect.values));
ok('valuation provenance가 선택된 fiscalYear를 남긴다',
   valDirect.provenance.fiscalYear === 2022);

const epsFuture = [RB(2021, '20220331', { eps: 1000 }), RB(2022, '20990101', { eps: 9999 })];
const valPit = valuationFrom(epsFuture, '2023-06-30', { date: '2023-06-30', close: 24000 });
ok('asOf 이후 EPS 레코드는 선택되지 않는다 (미래를 보지 않는다)',
   valPit.provenance.fiscalYear === 2021, J(valPit.provenance));

const epsNoPrev = [RB(2022, '20230331', { eps: 1200 })];
const valNoPrev = valuationFrom(epsNoPrev, '2023-06-30', { date: '2023-06-30', close: 24000 });
ok('전년 EPS가 없으면 epsGrowthRate는 null이다 (0이 아니다)',
   valNoPrev.values.epsGrowthRate === null, J(valNoPrev.values));

const epsLoss = [RB(2022, '20230331', { eps: -500 })];
const valLoss = valuationFrom(epsLoss, '2023-06-30', { date: '2023-06-30', close: 24000 });
ok('적자(EPS<=0)면 per는 null이다 (음수 PER을 만들지 않는다)',
   valLoss.values.per === null, J(valLoss.values));

// ★ 실측(005930/2016-04-08)을 그대로 재현 — A2a 수정주가와 A3b 원본 EPS를
// 그대로 나누면 이렇게 말이 안 되는 값이 나온다는 걸 회귀로 못 박는다.
// resolve()가 이 값을 stockData에 붙이지 않는 게 바로 이 이유다.
const samsungLike = [RB(2015, '20160330', { eps: 126305 })];
const valSamsung = valuationFrom(samsungLike, '2016-04-08', { date: '2016-04-08', close: 24920 });
ok('조정 기준이 다른 price/eps를 그대로 나누면 비정상적으로 낮은 PER이 나온다 (알려진 결함, 미사용)',
   valSamsung.values.per < 1, J(valSamsung.values));

console.log('\n[technical — A2a 캔들 기반, scripts/collect.js 계산식 재사용]');
const candles70 = candlesFixture(70, '2023-01-02');
const rTech = resolve({ ticker: '000001', corp: '00000001', asOf: candles70[candles70.length - 1].date,
                        fundamentals: restated, candles: candles70 });
ok('70일 캔들이면 maSignal이 계산된다 (MA60 성립)',
   rTech.stockData.technical.maSignal !== null && rTech.stockData.technical.maSignal !== undefined,
   J(rTech.stockData.technical));
ok('RSI가 계산된다 (14일 이상)',
   typeof rTech.stockData.technical.rsi === 'number', J(rTech.stockData.technical.rsi));
ok('MACD는 35일 미만이면 null이다',
   resolve({ ticker: '000001', corp: '00000001', asOf: candlesFixture(20, '2023-01-02').slice(-1)[0].date,
            fundamentals: restated, candles: candlesFixture(20, '2023-01-02') })
     .stockData.technical.macdSignal === null);
ok('candles를 아예 안 넘기면 technical 키 자체가 없다 (축 미구축과 구분)',
   r1.stockData.technical === undefined);

let threwOnFuture = false;
try {
  resolve({ ticker: '000001', corp: '00000001', asOf: '2023-01-01',
           fundamentals: restated, candles: candlesFixture(70, '2023-01-02') });
} catch (e) { threwOnFuture = true; }
ok('asOf 이전 날짜인데 미래 캔들이 섞이면 조용히 넘기지 않고 던진다', threwOnFuture);

console.log('\n[supplyDemand — A4 수급 기반, scripts/collect.js netBuysToTrend 재사용]');
// 외국인은 buyVolume/sellVolume.외국인만, 기관은 8개 카테고리 중 금융투자 하나에만
// 몰아넣어도 합산 로직(netVolumeOf)은 동일하게 검증된다.
function sdRec(date, foreignNet, instNet) {
  return {
    ticker: '000001', date,
    buyVolume: { 외국인: Math.max(foreignNet, 0), 금융투자: Math.max(instNet, 0) },
    sellVolume: { 외국인: Math.max(-foreignNet, 0), 금융투자: Math.max(-instNet, 0) },
  };
}
const sdConsistentBuy = ['2023-06-26', '2023-06-27', '2023-06-28', '2023-06-29', '2023-06-30']
  .map((d) => sdRec(d, 100, 100));
const rSdBuy = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                         fundamentals: restated, supplyDemandRecords: sdConsistentBuy });
ok('5일 연속 순매수면 consistentBuy',
   rSdBuy.stockData.supplyDemand.foreignTrend5d === 'consistentBuy' &&
   rSdBuy.stockData.supplyDemand.institutionTrend5d === 'consistentBuy',
   J(rSdBuy.stockData.supplyDemand));

const sdMixedNetBuy = [
  sdRec('2023-06-26', 100, -50), sdRec('2023-06-27', -30, 100),
  sdRec('2023-06-28', 50, -10), sdRec('2023-06-29', -10, 50), sdRec('2023-06-30', 20, 20),
];
const rSdMixed = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                           fundamentals: restated, supplyDemandRecords: sdMixedNetBuy });
ok('일별 부호가 섞여도 5일 합계가 양수면 netBuy (consistentBuy 아님)',
   rSdMixed.stockData.supplyDemand.foreignTrend5d === 'netBuy', J(rSdMixed.stockData.supplyDemand));

ok('supplyDemandRecords를 아예 안 넘기면 supplyDemand 키 자체가 없다 (축 미구축과 구분)',
   r1.stockData.supplyDemand === undefined);

const sdWithFuture = [...sdConsistentBuy, sdRec('2023-07-05', -999, -999)];
const rSdPit = resolve({ ticker: '000001', corp: '00000001', asOf: '2023-06-30',
                         fundamentals: restated, supplyDemandRecords: sdWithFuture });
ok('asOf 이후 레코드가 섞여도 조용히 걸러내고 그 이하만 쓴다 (PIT, 미래의 -999가 안 섞여야 consistentBuy 유지)',
   rSdPit.stockData.supplyDemand.foreignTrend5d === 'consistentBuy', J(rSdPit.stockData.supplyDemand));

const rSdEmpty = resolve({ ticker: '000005', corp: '00000005', asOf: '2023-06-30',
                           fundamentals: restated, supplyDemandRecords: [] });
ok('그 종목 A4 레코드가 아예 없으면 null이다 (지어내지 않는다)',
   rSdEmpty.stockData.supplyDemand.foreignTrend5d === null &&
   rSdEmpty.stockData.supplyDemand.institutionTrend5d === null,
   J(rSdEmpty.stockData.supplyDemand));

console.log('\n[점수 계산을 다시 구현하지 않는다]');
const src = require('fs').readFileSync(path.join(ROOT, 'lib/a5/resolver.js'), 'utf8');
ok('리졸버가 categoryWeights를 읽지 않는다 (가중은 엔진의 몫)',
   !src.includes('categoryWeights'));
ok('리졸버가 finalScore를 만들지 않는다',
   !src.includes('finalScore') && !src.includes('totalScore'));

console.log(`\n${'='.repeat(54)}`);
console.log(`통과 ${passed} · 실패 ${failed}`);
process.exit(failed === 0 ? 0 : 1);
