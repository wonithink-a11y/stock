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
const { resolve, fundamentalsFrom } = require(path.join(ROOT, 'lib/a5/resolver'));
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
ok('지금은 minimumDataCoverage에 못 미친다 (운영 투입 불가이지 구현 불가가 아니다)',
   aw.total < criteria.minimumDataCoverage,
   `${aw.total} vs ${criteria.minimumDataCoverage}`);
ok('technical은 통째로 가용하다',
   aw.byCategory.technical.availableFraction === 1);
ok('valuation은 통째로 불가하다', aw.byCategory.valuation.availableFraction === 0);
ok('supplyDemand는 통째로 불가하다 (A4 미정)',
   aw.byCategory.supplyDemand.availableFraction === 0);
ok('fundamental은 부분 가용이다 (shareholderReturn만 막혔다)',
   aw.byCategory.fundamental.availableFraction > 0
   && aw.byCategory.fundamental.availableFraction < 1,
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
   r1.stockData.fundamentals.roe === 5, J(r1.stockData.fundamentals.roe));
ok('부채비율을 낸다 (liabilities / equity)',
   r1.stockData.fundamentals.debtRatio === 40);
ok('유동비율을 낸다', r1.stockData.fundamentals.currentRatio === 200);
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
   rf.stockData.fundamentals.currentRatio === null);
ok('결측 지표가 missing 목록에 남는다',
   rf.missing.includes('currentRatio'), J(rf.missing));

// A3b 전까지 비어 있어야 하는 값. 채우면 계약 위반이다.
ok('배당 이력은 null이다 (A3b 전까지 채우지 않는다)',
   r1.stockData.fundamentals.buybackOrDividendHistory === null);
ok('배당 이력이 missing에 잡힌다',
   r1.missing.includes('buybackOrDividendHistory'));

// 0으로 나누기 — Infinity를 내보내면 하류가 그것을 점수로 만든다.
const zero = [R(2022, '2023-03-31', { equity: 0, revenue: 0 })];
const rz = resolve({ ticker: '000003', corp: '00000003', asOf: '2023-06-30',
                     fundamentals: zero });
ok('자본이 0이면 ROE는 null이다 (Infinity가 아니다)',
   rz.stockData.fundamentals.roe === null, J(rz.stockData.fundamentals.roe));
ok('매출이 0이면 영업이익률 추세도 null이다',
   rz.stockData.fundamentals.operatingMarginTrend === null);

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

console.log('\n[점수 계산을 다시 구현하지 않는다]');
const src = require('fs').readFileSync(path.join(ROOT, 'lib/a5/resolver.js'), 'utf8');
ok('리졸버가 categoryWeights를 읽지 않는다 (가중은 엔진의 몫)',
   !src.includes('categoryWeights'));
ok('리졸버가 finalScore를 만들지 않는다',
   !src.includes('finalScore') && !src.includes('totalScore'));

console.log(`\n${'='.repeat(54)}`);
console.log(`통과 ${passed} · 실패 ${failed}`);
process.exit(failed === 0 ? 0 : 1);
