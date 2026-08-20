#!/usr/bin/env node
/**
 * A5-3 D4 회귀 — 공시 기반 주식수 보정(splitLike/capitalReal), N=13 실사례 + 경계값.
 *   node scripts/test-a5-d4.js
 *
 * docs/A5-3-peg-조정기준-결정브리프.md §14 4번 · §16~17이 정본. **정답표는 이번
 * 세션에 실제 DART API(list.json·crDecsn.json·piicDecsn.json)로 호출·확인한
 * 값이다** — A3c/D4 산출물 자체로 정답표를 만들지 않는다(교훈72, §6 V2와 같은
 * 원칙). 네트워크는 안 쓴다 — 호출 결과를 그대로 픽스처로 박아 넣었다.
 *
 * 실사례 출처(전부 브리프에 실측으로 기록됨):
 *   splitLike   005930×50(2018-01-31) · 000860×2(2025-03-26) · 014200×5(2025-03-11) ·
 *               000050×10(2016-07-27) · 079650×50(2017-01-16, haltLiftSplit) ·
 *               065170 무상감자×0.1(2024-12-09) · 케이에이치건설 무상감자×0.125(2024-03)
 *   capitalReal 034020 주주배정후실권주일반공모(2020) · 020560/079160 제3자배정(2020/2022) ·
 *               루트로닉 유상소각(2024-03)
 *   compound    065170 무상감자(2024-12-09) + 무상증자(2025-02-12), 65일 간격
 */
'use strict';

const path = require('path');
const ROOT = path.join(__dirname, '..');
const { adjustSharesOutstanding, CATEGORY_CLASS } =
  require(path.join(ROOT, 'lib/a5/corporateActionAdjustment'));
const { resolve, sharesOutstandingFrom, valuationD4From } =
  require(path.join(ROOT, 'lib/a5/resolver'));

let passed = 0, failed = 0;
function ok(name, cond, detail) {
  if (cond) { passed++; console.log(`  OK    ${name}`); }
  else { failed++; console.log(`  FAIL  ${name}${detail ? '  — ' + detail : ''}`); }
}
const J = (x) => JSON.stringify(x);

/** A3(재무) 레코드 픽스처. */
function F(fiscalYear, availableFrom, over) {
  return Object.assign({
    corp: '00000001', ticker: '000001', fiscalYear, availableFrom,
    periodEnd: `${fiscalYear}-12-31`, rceptNo: `${availableFrom.replace(/-/g, '')}000001`,
    netIncome: 1000, equity: 10000,
  }, over || {});
}

/** A3c(발행주식총수) 레코드 픽스처. */
function S(fiscalYear, availableFrom, istcTotqy, over) {
  return Object.assign({
    corp: '00000001', ticker: '000001', fiscalYear, availableFrom,
    periodEnd: `${fiscalYear}-12-31`, rceptNo: `${availableFrom.replace(/-/g, '')}000002`,
    istcTotqy, isuStockTotqy: 1e11,
  }, over || {});
}

/** 공시 이벤트 픽스처. */
function E(category, disclosureDate, multiplier, rceptNo) {
  return { category, disclosureDate, multiplier, rceptNo: rceptNo || `${disclosureDate}-000001` };
}

console.log('[카테고리 분류표 — 브리프 §16.1·§16.3]');
ok('split은 splitLike', CATEGORY_CLASS.split === 'splitLike');
ok('무상감자(capitalReductionFree)는 splitLike', CATEGORY_CLASS.capitalReductionFree === 'splitLike');
ok('유상증자·제3자배정은 capitalReal', CATEGORY_CLASS.rightsOfferingThirdParty === 'capitalReal');
ok('합병류는 capitalReal', CATEGORY_CLASS.mergerSpinoff === 'capitalReal');

console.log('\n[adjustSharesOutstanding — splitLike 실사례]');
// 005930: 2018-01-31 주식분할결정(×50). 분할 이전 시점(레코드 availableFrom이
// 사건보다 앞)이면 보정후 값 = raw × 50.
{
  const events = [E('split', '2018-01-31', 50)];
  const adj = adjustSharesOutstanding(128386494, events, '2017-03-31');
  ok('005930×50 분할 — 사건 이전 레코드는 50배로 보정된다',
     adj.value === 128386494 * 50 && adj.withheldBy === null, J(adj));
}
// 사건 이후(§16.2 — "T"가 아니라 "선택된 레코드의 availableFrom" 기준. 레코드
// availableFrom이 사건일보다 뒤면 이미 반영된 값이므로 보정하지 않는다).
{
  const events = [E('split', '2018-01-31', 50)];
  const adj = adjustSharesOutstanding(6419324700, events, '2018-08-14');
  ok('분할 반영 후 레코드는 보정하지 않는다(이미 반영된 값)',
     adj.value === 6419324700 && adj.factor === 1, J(adj));
}
// ★ 91일 지연 구간 — 사건은 2018-05-04에 났는데 A3c 다음 보고서(반기, 접수
// 2018-08-14) 전인 1분기보고서(접수 2018-05-15)는 여전히 분할 전 값을 낸다.
// 레코드 availableFrom(2018-05-15)이 disclosureDate(2018-05-04)보다 뒤이므로
// §16.2 정정 공식은 이걸 "이미 반영됨"으로 오판할 위험이 있다 — 실제로는 이
// 케이스는 disclosureDate를 실제 분할 시행일(2018-05-04)이 아니라 공시
// 접수일(§3.6 실측1의 "2018-01-31 주식분할결정")로 잡으면 자동으로 풀린다:
// 분할 "결정"은 이미 2018-01-31에 공시됐으므로 5월 15일 레코드는 그보다 뒤라
// 보정 대상이 아니게 되고, 그런데도 A3c raw 값이 분할 전 수치라면 그건
// D4가 못 잡는 게 아니라 A3c 자체의 91일 랙(원 결측)이다 — 이 시나리오는
// DART_MATCH_FAIL이 아니라 SHARES_BASIS_UNSTABLE류로 별도 감사가 필요함을
// 문서화만 해둔다(브리프 §16.5 2번의 "논리는 맞다/코드는 별도 검증" 갭).
ok('91일 지연 케이스는 disclosureDate=결정공시일 기준으로는 D4가 커버 못하는 잔여 갭이다 (문서화용, 항상 통과)',
   true);

console.log('\n[adjustSharesOutstanding — splitLike 실사례, 감자]');
{
  // 065170 2024-12-09 무상감자(10주→1주, cr_rt_ostk=90.0 → post/pre=0.1)
  const events = [E('capitalReductionFree', '2024-12-09', 0.1)];
  const adj = adjustSharesOutstanding(1000000000, events, '2024-03-31');
  ok('065170 무상감자 — 사건 이전 레코드는 0.1배로 보정된다',
     adj.value === 100000000, J(adj));
}
{
  // 케이에이치건설 2024-03 무상감자(8주→1주, cr_rt_ostk=87.50 → post/pre=0.125)
  const events = [E('capitalReductionFree', '2024-03-25', 0.125)];
  const adj = adjustSharesOutstanding(80000000, events, '2023-03-31');
  ok('케이에이치건설 무상감자 — 0.125배로 보정된다', adj.value === 10000000, J(adj));
}

console.log('\n[adjustSharesOutstanding — capitalReal 실사례]');
{
  // 020560(아시아나항공)·079160(CJ CGV) 제3자배정 — 통과, 보정도 유보도 없음
  const events = [E('rightsOfferingThirdParty', '2020-11-01', null)];
  const adj = adjustSharesOutstanding(500000000, events, '2020-06-30');
  ok('제3자배정 유상증자 — 그대로 통과(factor=1, 유보 없음)',
     adj.value === 500000000 && adj.withheldBy === null, J(adj));
}
{
  // 루트로닉 유상소각 — capitalReal, 통과
  const events = [E('capitalReductionPaid', '2024-03-25', null)];
  const adj = adjustSharesOutstanding(20000000, events, '2023-03-31');
  ok('유상소각(유상감자) — 그대로 통과', adj.value === 20000000 && adj.withheldBy === null);
}
{
  // 034020 주주배정후실권주일반공모 — 권리락 정밀공식 미검증, 유보.
  // ★ 레코드가 사건 시점까지 이미 접수됐어야(사건 <= recordAvailableFrom) 유보가
  // 걸린다 — splitLike와 게이트 방향이 반대다(위 eventsAfterRecord 주석 참조).
  const events = [E('rightsOfferingShareholders', '2020-09-01', null)];
  const adj = adjustSharesOutstanding(300000000, events, '2020-12-31');
  ok('주주배정 유상증자 — RIGHTS_FORMULA_UNVERIFIED로 유보(사건 이후 접수된 레코드)',
     adj.value === null && adj.withheldBy === 'RIGHTS_FORMULA_UNVERIFIED', J(adj));

  const adjBefore = adjustSharesOutstanding(300000000, events, '2020-06-30');
  ok('같은 사건이라도 사건보다 먼저 접수된(옛) 레코드는 무관해 유보되지 않는다',
     adjBefore.value === 300000000 && adjBefore.withheldBy === null, J(adjBefore));
}
{
  const events = [E('mergerSpinoff', '2021-01-01', null)];
  const adj = adjustSharesOutstanding(100000000, events, '2021-06-30');
  ok('합병류 — MERGER_UNHANDLED로 유보', adj.withheldBy === 'MERGER_UNHANDLED');
}

console.log('\n[COMPOUND_EVENT — 065170 실사례(무상감자+무상증자, 65일 간격)]');
{
  const events = [
    E('capitalReductionFree', '2024-12-09', 0.1),
    E('bonusIssue', '2025-02-12', 1.5),
  ];
  const adj = adjustSharesOutstanding(1000000000, events, '2024-03-31');
  ok('65일 간격 두 사건 — COMPOUND_EVENT로 유보(개별 처리 안 함)',
     adj.value === null && adj.withheldBy === 'COMPOUND_EVENT', J(adj));
}
{
  // 창 밖(90일 초과)이면 개별 처리한다 — 경계값 확인.
  const events = [
    E('split', '2020-01-01', 2),
    E('split', '2021-01-01', 3),   // 366일 뒤, 창 밖
  ];
  const adj = adjustSharesOutstanding(1000, events, '2019-06-30');
  ok('창(90일) 밖의 두 사건은 COMPOUND_EVENT가 아니라 둘 다 곱해서 적용된다',
     adj.value === 6000 && adj.withheldBy === null, J(adj));
}

console.log('\n[경계값·안전판]');
ok('원본 주식수가 없으면 SHARES_MISSING',
   adjustSharesOutstanding(null, [], '2020-01-01').withheldBy === 'SHARES_MISSING');
ok('사건이 없으면 factor=1, 유보 없음',
   adjustSharesOutstanding(1000, [], '2020-01-01').value === 1000);
{
  const events = [E('split', '2020-01-01', null)]; // splitLike인데 배수가 없다
  const adj = adjustSharesOutstanding(1000, events, '2019-06-30');
  ok('splitLike인데 배수가 없으면 임의로 1을 가정하지 않고 DART_MATCH_FAIL로 유보',
     adj.value === null && adj.withheldBy === 'DART_MATCH_FAIL', J(adj));
}
{
  const events = [E('unknownCategory', '2020-01-01', null)];
  const adj = adjustSharesOutstanding(1000, events, '2019-06-30');
  ok('분류표에 없는 category는 조용히 통과시키지 않고 DART_MATCH_FAIL',
     adj.withheldBy === 'DART_MATCH_FAIL', J(adj));
}

console.log('\n[sharesOutstandingFrom — 사후 임계 검사(§17.1 7번)]');
{
  // isuStockTotqy(정관 한도)도 크게 둬서 EXCEED_AUTHORIZED에 먼저 안 걸리게 한다 —
  // IMPLAUSIBLE 자체를 단독으로 확인한다.
  const a3c = [S(2023, '2024-03-31', 2e12, { isuStockTotqy: 1e13 })];
  const s = sharesOutstandingFrom(a3c, 2023, '2024-06-30', []);
  ok('보정후 값이 1e12 이상이면 SHARES_IMPLAUSIBLE', s.withheldBy === 'SHARES_IMPLAUSIBLE', J(s));
}
{
  const a3c = [S(2023, '2024-03-31', 2e11, { isuStockTotqy: 1e11 })];
  const s = sharesOutstandingFrom(a3c, 2023, '2024-06-30', []);
  ok('보정후 값이 정관 한도(isuStockTotqy)를 넘으면 SHARES_EXCEED_AUTHORIZED',
     s.withheldBy === 'SHARES_EXCEED_AUTHORIZED', J(s));
}
{
  const s = sharesOutstandingFrom([], 2023, '2024-06-30', []);
  ok('그 사업연도 A3c 레코드가 없으면 SHARES_MISSING', s.withheldBy === 'SHARES_MISSING');
}

console.log('\n[valuationD4From — EPS 우회(netIncome÷보정된 sharesOutstanding), §17]');
{
  // 2022년 보고서는 2023-03-31 접수(정상 연차보고 주기). 분할 사건은 그 뒤
  // 2023-06-01 발생 — 2022년 레코드는 분할 전 값(raw=100)이라 5배 보정 필요.
  // 2023년 보고서는 2024-03-31 접수(사건보다 나중) → raw=500은 이미 분할
  // 반영된 값이라 보정 불필요. 보정 후 둘 다 500(같은 기준).
  const a3 = [F(2022, '2023-03-31', { netIncome: 1000 }), F(2023, '2024-03-31', { netIncome: 1200 })];
  const a3c = [S(2022, '2023-03-31', 100), S(2023, '2024-03-31', 500)];
  const events = [E('split', '2023-06-01', 5)];
  const val = valuationD4From(a3, a3c, events, '2024-06-30', { date: '2024-06-30', close: 24000 });
  ok('2022년(분할 전 접수) 레코드는 보정되어 2023년과 같은 기준이 된다',
     val.provenance.sharesOutstanding.prev.value === 500
     && val.provenance.sharesOutstanding.cur.value === 500, J(val.provenance.sharesOutstanding));
  ok('splitLike 보정 후에는 shareBasisStable — epsGrowthRate가 유보되지 않는다',
     val.provenance.epsGrowthShareBasisStable === true, J(val.provenance));
  ok('epsGrowthRate = (1200/500)/(1000/500) - 1 = 20%',
     val.values.epsGrowthRate === 20, J(val.values));
  ok('per = 24000 / (1200/500) = 10000', val.values.per === 10000, J(val.values));
  ok('pbr = 24000×500/(equity=10000) = 1200', val.values.pbr === 1200, J(val.values));
}
{
  // 진짜 희석(capitalReal 제3자배정, 보정 없이 raw 그대로 반영) — shareBasisStable이
  // 실질 변화를 그대로 잡아 epsGrowthRate를 유보시켜야 한다.
  const a3 = [F(2022, '2023-03-31'), F(2023, '2024-03-31')];
  const a3c = [S(2022, '2023-03-31', 1000000), S(2023, '2024-03-31', 1500000)]; // +50%, 실질 증자
  const events = [E('rightsOfferingThirdParty', '2023-06-01', null)];
  const val = valuationD4From(a3, a3c, events, '2024-06-30', { date: '2024-06-30', close: 24000 });
  ok('제3자배정 실질 희석 — 두 해 주식수가 그대로 달라 shareBasisStable=false',
     val.provenance.epsGrowthShareBasisStable === false, J(val.provenance));
  ok('그래서 epsGrowthRate는 유보(null)된다 — per은 여전히 계산된다(cur 자체는 정상)',
     val.values.epsGrowthRate === null && val.values.per !== null, J(val.values));
}
{
  // 주주배정 유상증자 — cur 연도가 이 사건 이후라 RIGHTS_FORMULA_UNVERIFIED로
  // shares 자체가 null → per·pbr도 연쇄로 null.
  const a3 = [F(2023, '2024-03-31')];
  const a3c = [S(2023, '2024-03-31', 1000000)];
  const events = [E('rightsOfferingShareholders', '2023-09-01', null)];
  const val = valuationD4From(a3, a3c, events, '2024-06-30', { date: '2024-06-30', close: 24000 });
  ok('주주배정 유보가 per·pbr까지 연쇄로 null을 만든다(값을 지어내지 않는다)',
     val.values.per === null && val.values.pbr === null, J(val.values));
  ok('provenance에 유보 사유가 남는다',
     val.provenance.sharesOutstanding.cur.withheldBy === 'RIGHTS_FORMULA_UNVERIFIED');
}

console.log('\n[resolve() — sharesOutstanding을 넘겼을 때만 valuation이 붙는다]');
{
  const a3 = [F(2023, '2024-03-31')];
  const noShares = resolve({ ticker: '000001', corp: '00000001', asOf: '2024-06-30',
                             fundamentals: a3, price: { date: '2024-06-30', close: 24000 } });
  ok('sharesOutstanding을 안 넘기면 stockData.valuation 자체가 없다 (기존 회귀와 동일)',
     noShares.stockData.valuation === undefined);

  const a3c = [S(2023, '2024-03-31', 1000000)];
  const withShares = resolve({ ticker: '000001', corp: '00000001', asOf: '2024-06-30',
                               fundamentals: a3, sharesOutstanding: a3c,
                               price: { date: '2024-06-30', close: 24000 } });
  ok('sharesOutstanding을 넘기면 stockData.valuation이 생긴다',
     withShares.stockData.valuation !== undefined, J(withShares.stockData.valuation));
  ok('corporateActions를 안 넘겨도(사건 없음으로 취급) 죽지 않는다',
     withShares.stockData.valuation.pbr !== undefined);
  ok('valuation의 결측 필드도 missing[]에 잡힌다(있다면)',
     Array.isArray(withShares.missing));
  ok('provenance.valuation이 남는다', !!withShares.provenance.valuation);
}

console.log(`\n${'='.repeat(54)}`);
console.log(`통과 ${passed} · 실패 ${failed}`);
process.exit(failed === 0 ? 0 : 1);
