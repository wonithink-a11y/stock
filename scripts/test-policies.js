#!/usr/bin/env node
/**
 * STEP4 정책 파일 정합성 테스트
 *   node scripts/test-policies.js
 *
 * 정책 파일은 JSON이라 오타가 런타임에야 드러난다. 여기서 잡아야 할 것은 문법이 아니라
 * **파일 사이의 어긋남**이다. riskPenalty가 stateMap이 만들지 않는 상태를 가리키면
 * 그 규칙은 영원히 발동하지 않고, 아무도 눈치채지 못한다.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const load = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));

const registry = load('config/policies/registry.json');
const P = {};
for (const [key, rel] of Object.entries(registry.policies)) P[key] = load(rel);

// ---- registry: 참조 무결성 ----
for (const [key, rel] of Object.entries(registry.policies)) {
  assert.ok(fs.existsSync(path.join(ROOT, rel)), `registry.policies.${key} 경로 없음: ${rel}`);
  assert.ok(P[key].version, `${key}에 version 없음 — meta.policies 스탬프가 불가능해진다`);
}
for (const [market, c] of Object.entries(registry.criteria)) {
  const file = load(c.path);
  // criteria는 복사본을 두지 않으므로, 원본이 바뀌었는데 registry가 안 바뀌는 상황만 막으면 된다.
  assert.strictEqual(file.version, c.version,
    `${market} criteria 버전 불일치: ${c.path}=${file.version} vs registry=${c.version}. ` +
    'criteria를 고쳤으면 registry의 version도 올려야 과거 점수가 재현된다.');
  assert.ok(Object.keys(file.categoryWeights || {}).length > 0, `${market} categoryWeights 비어 있음 (AX002)`);
}

// ---- riskPenalty: 감점 전용 + 상태 교차 검증 ----
const rp = P.riskPenalty;
// stateMap이 어느 축에 어떤 값을 만들어내는지 축별로 모은다.
// 한 Set에 섞으면 listingStatus의 값과 riskStates의 원소가 이름만 같아도 통과해버린다.
const producible = { riskStates: new Set(), listingStatus: new Set(), tradingState: new Set() };
for (const rule of Object.values(P.stateMap.events)) {
  if (rule.add) producible.riskStates.add(rule.add);
  if (rule.field === 'listingStatus' || rule.field === 'tradingState') producible[rule.field].add(rule.value);
}
const codes = new Set();
for (const r of rp.rules) {
  assert.ok(!codes.has(r.code), `중복 code: ${r.code}`);
  codes.add(r.code);
  assert.ok(r.penalty <= 0, `PN001 — ${r.code} penalty가 양수다: ${r.penalty}. Adjustment는 감점 전용이다`);
  if (r.enabled === false) { assert.ok(r.disabledReason, `${r.code}: enabled=false면 disabledReason 필수`); continue; }
  assert.ok(r.matchState, `${r.code}: 활성 규칙에 matchState가 없다`);
  assert.ok(producible[r.matchField].has(r.matchState),
    `${r.code}: stateMap이 ${r.matchField} 축에 "${r.matchState}"를 만들지 않는다 — 영원히 발동하지 않는 死규칙`);
  assert.ok(r.category && r.reason, `${r.code}: adjustments 출력에 쓰이는 category/reason 누락`);
  assert.ok(!(r.exclusiveGroup && r.stackable), `${r.code}: exclusiveGroup과 stackable은 동시 성립 불가`);
}
// 최악의 조합에서도 finalScore가 0 밑으로 내려가 clamp에 의존하지 않는지 확인(정보 손실 방지)
const worst = (() => {
  const groups = {};
  let sum = 0;
  for (const r of rp.rules.filter((x) => x.enabled !== false)) {
    if (r.exclusiveGroup) groups[r.exclusiveGroup] = Math.min(groups[r.exclusiveGroup] ?? 0, r.penalty);
    else sum += r.penalty;
  }
  return sum + Object.values(groups).reduce((a, b) => a + b, 0);
})();
assert.ok(worst >= -100, `최대 감점 ${worst} — 100점을 넘어 clamp되면 감점 크기가 점수에서 사라진다`);
console.log(`   riskPenalty 최대 감점: ${worst}점 (동시 발동 최악 조합)`);

// ---- trading ----
assert.ok(P.trading.blockedStates.length > 0);
P.trading.blockedStates.forEach((s) =>
  assert.ok(producible.tradingState.has(s),
    `trading.blockedStates "${s}"를 stateMap이 tradingState에 만들지 않는다`));
// 매매차단과 감점을 같은 사실에 이중으로 물리지 않는다
const dbl = rp.rules.filter((r) => r.enabled !== false
  && r.matchField === 'tradingState' && P.trading.blockedStates.includes(r.matchState));
assert.strictEqual(dbl.length, 0,
  `${dbl.map((r) => r.code)}: 거래정지 상태에 감점까지 걸려 있다. Trading과 Risk는 다른 축이다`);

// ---- confidence ----
const w = P.confidence.weights;
const wsum = Object.values(w).reduce((a, b) => a + b, 0);
assert.ok(Math.abs(wsum - 1) < 1e-9, `confidence.weights 합이 1이 아니다: ${wsum}`);
assert.strictEqual(P.confidence.ignoreNull, true,
  'freshness/quality가 미구축인 동안 ignoreNull=false면 전 종목이 LOW_CONFIDENCE가 된다');
assert.ok(P.confidence.thresholds.veryLowConfidence < P.confidence.thresholds.lowConfidence);

// ---- validation / missingAxis ----
assert.ok(P.validation.strictTolerance < P.validation.lenientTolerance);
assert.ok(['renormalize', 'zeroFill'].includes(P.missingAxis.mode));

// ---- flagCodes: 중복 없는 단일 정의처 ----
const all = Object.values(P.flagCodes.groups).flat().map((f) => f.code);
assert.ok(all.includes('TRADE_BLOCKED'), 'evaluateTradingState가 세우는 TRADE_BLOCKED가 정의되어 있지 않다');
assert.ok(all.includes('LOW_CONFIDENCE'));

// ---- dataPolicies: universe ----
// registry.policies에만 걸린 위 루프가 이 파일을 보지 않는다. 수집 단계(A1a·A1b)만 읽는
// 정책이라 오타가 나면 Actions 실행 중에야 드러나고, 그때는 이미 네트워크 수집이 끝난 뒤다.
const uni = load(registry.dataPolicies.universe);
assert.ok(uni.version, 'universe에 version 없음 — manifest.policyHash 추적이 끊긴다');
new RegExp(uni.tickerPattern);  // 컴파일 실패는 여기서 나야 한다

const a1b = uni.a1b;
assert.ok(a1b, `${uni.version}: a1b 블록 없음 — A1b가 임계값을 스크립트에 하드코딩하게 된다`);
assert.ok(!('tickerPattern' in a1b),
  'a1b에 tickerPattern을 복제하지 않는다 — 최상위 값과 갈라지면 두 단계가 다른 계약을 쓴다');
assert.ok(a1b.acceptance.candidateMin < a1b.acceptance.candidateMax,
  `a1b 후보 임계 역전: [${a1b.acceptance.candidateMin}, ${a1b.acceptance.candidateMax}]`);
assert.ok(a1b.acceptance.candidateMax > 0,
  'a1b candidateMax는 상한이다 — 없거나 0이면 A1a 파손으로 후보가 폭증해도 통과한다');
assert.strictEqual(a1b.exitAtDefault, null,
  'a1b exitAtDefault는 null이어야 한다 — A1b는 폐지일을 모른다');
assert.strictEqual(a1b.exitReasonDefault, 'UNKNOWN',
  'a1b exitReasonDefault는 UNKNOWN이어야 한다 — 사유 부여는 EP-1.1에서 기각됐다');
assert.strictEqual(a1b.diffKey, 'corp', 'a1b 차집합 키는 corp다 — ticker로 바꾸면 재사용 폐지사가 사라진다');
assert.strictEqual(a1b.safetyNetKey, 'ticker', 'a1b 안전망 키는 ticker다');
assert.ok(a1b.base && Array.isArray(a1b.subtract) && a1b.subtract.length >= 2,
  'a1b는 base 1개와 차집합 대상 2개(current·excluded)를 선언해야 한다 — excluded가 빠지면 KONEX·SPAC 180건이 폐지 후보로 샌다');
for (const rel of [a1b.base, ...a1b.subtract]) {
  assert.ok(/^data\/backfill\//.test(rel), `a1b 입력 경로가 백필 산출물이 아니다: ${rel}`);
}

// ---- dataPolicies: price ----
const price = load(registry.dataPolicies.price);
assert.ok(price.version, 'price에 version 없음');
assert.ok(price.source.adjusted === true,
  'price.source.adjusted는 true여야 한다 — raw 경로는 pykrx 1.2.8에서 죽어 있고, 미수정 가격은 technical 축을 오염시킨다');
assert.ok(price.source.requiredVersion,
  'requiredVersion 없음 — 정책은 요구 버전, manifest는 실행 버전을 남긴다. 요구가 없으면 대조가 불가능하다');
assert.strictEqual(price.output.gzipMtime, 0,
  'gzipMtime은 0이어야 한다 — 기본값(현재 시각)이면 내용이 같아도 매 실행 해시가 달라져 manifest가 재수집 판정 기능을 잃는다');
assert.strictEqual(price.output.partition, 'year',
  '저장 축은 연도다. 샤드로 바꾸면 실행 축과 묶여 샤드 수 변경이 전량 재수집이 된다');
assert.ok(price.shards >= 1 && Number.isInteger(price.shards), 'shards는 1 이상 정수');
assert.ok(price.acceptance.dailyChangeAbsMax > 0.3,
  '일간 변동 임계가 가격제한폭(상하 30%) 이하면 정상 등락을 위반으로 잡는다');
assert.ok(price.probeTickers.length >= 2,
  '대량 루프 전 정찰은 2회 이상이다 — 1회는 일시 실패와 경로 차단을 구분하지 못한다(교훈32)');
assert.deepStrictEqual(price.output.sortKey, ['date', 'ticker'],
  '정렬 키가 바뀌면 산출 바이트가 바뀌어 하류 전체가 재실행된다');

// PR-1.1 — 첫 수집이 드러낸 세 가지를 계약으로 고정한다
assert.strictEqual(price.expectedRows.basis, 'firstTradedDate',
  'listedAt은 현재 시장의 상장일이라 이전상장 종목에서 기대행을 과소 계산한다 — 기준은 실제 최초 거래일이다');
assert.ok(price.dailyChange.requireBothVolumePositive && price.dailyChange.requireAdjacentTradingDay,
  '변동률은 체결이 있었던 인접 거래일끼리만 잰다. 거래정지 기준가와 체결가를 비교하면 가짜 점프가 나온다');
assert.ok(price.acceptance.qualityExcludedRateMax > 0 && price.acceptance.qualityExcludedRateMax < 1,
  '품질 제외율 상한이 없으면 위반 종목을 자동 제외하는 구조가 게이트를 영원히 통과시킨다');
assert.strictEqual(price.acceptance.residualDailyChangeViolations, 0,
  '제외 후 잔여 위반은 0이어야 한다 — 아니면 제외가 실제로 안 된 것이다');
assert.ok(price.qualityExclusion.file.endsWith(price.output.format),
  `품질 제외 파일이 ${price.output.format}가 아니면 manifest 디렉터리 해시(targetExt) 밖에 남는다`);
assert.ok(price.qualityExclusion.reasons.length >= 1,
  '제외 사유 코드가 없으면 A5가 왜 빠졌는지 모르고, 소스가 고쳐져도 재검증 대상을 못 고른다');
// A2의 품질 검사와 A5의 수익률 계산이 전이 정의를 공유해야 한다. volume>0이 갈라지면
// A2가 걷어낸 오염이 A5의 점수로 되돌아온다 — 인접 조건만 용도에 따라 다르다(§5.3).
assert.strictEqual(price.returnTransition.requireBothVolumePositive,
  price.dailyChange.requireBothVolumePositive,
  'A2 검사와 A5 수익률의 volume>0 조건이 갈라졌다 — 거래정지일 기준가가 수익률로 들어간다');
assert.ok(price.returnTransition.consumers.includes('A5'),
  'returnTransition의 소비자에 A5가 없으면 공유 계약이 아니라 A2 전용 규칙이다');
assert.strictEqual(price.rollingWindow.observeOnly, true,
  '롤링 윈도우 손실은 관측 전용이다 — 워밍업 구간이고 복구 불가라 게이트로 쓰면 정당한 실패를 만든다');

// PR-1.3 — 전체는 FAIL, 종목별은 WARN. 같은 지표가 아니다:
// 전체는 파이프라인 건전성을, 종목별은 개별 종목의 거래 특성(장기 거래정지)을 잰다.
assert.ok(price.acceptance.missingRateMax > 0,
  'missingRateMax 없음 — 전체 누락률은 PR-1.3에서 FAIL로 승격됐다');
assert.ok(price.acceptance.perTickerMissingRateWarn > price.acceptance.missingRateMax,
  '종목별 임계가 전체보다 낮으면 장기 거래정지 종목이 전체 게이트보다 먼저 걸린다');
assert.ok(!('missingRateWarn' in price.acceptance),
  'missingRateWarn이 남아 있다 — 승격 후 옛 키가 남으면 어느 쪽이 유효한지 모호해진다');
assert.ok(price.measured && price.measured.missingRate <= price.acceptance.missingRateMax,
  '실측 기준선이 임계를 넘는다 — 기준선이 이미 실패 상태면 임계가 근거를 잃는다');

// PR-1.4 — a2b 블록. A2a와 공유하는 것과 A2b가 덮어쓰는 것의 경계가 계약이다.
const a2b = price.a2b;
assert.ok(a2b, 'price에 a2b 블록 없음 — PR-1.4 미만이다');
assert.notStrictEqual(a2b.output.dir, price.output.dir,
  'A2a와 산출 디렉터리가 같으면 manifest 디렉터리 해시가 두 단계를 한 덩어리로 묶는다 — 한쪽 재수집이 다른 쪽 하류까지 재실행시킨다');
assert.ok(a2b.output.shardDir && !price.output.dir.includes(a2b.output.shardDir),
  '샤드 경로가 A2a와 겹치면 A2a finalize가 A2b 샤드를 병합한다');
assert.strictEqual(a2b.output.gzipMtime, 0,
  'a2b도 gzip mtime을 0으로 고정해야 manifest가 재수집 판정 기능을 유지한다');
assert.strictEqual(a2b.expectedRows.basis, 'listingPeriod',
  '폐지 종목의 기대 거래일은 상장기간으로 한정한다 — A2a 기준(캘린더 끝)이면 폐지 이후가 전부 누락으로 잡혀 누락률이 90%대가 된다');
assert.strictEqual(a2b.exitAt.source, 'lastTradedDate',
  'exitAt은 마지막 거래일에서만 온다 — dartModifyDate는 DART 레코드 수정일이라 폐지와 인과가 없다');
assert.ok(a2b.exitAt.file.endsWith(a2b.output.format),
  `exitAt 파일이 ${a2b.output.format}가 아니면 manifest 디렉터리 해시(targetExt) 밖에 남는다`);
assert.strictEqual(a2b.coverage.assumesFailuresOutOfWindow, true,
  '확보 실패를 구간 밖으로 본 것은 가정이다 — 스탬프가 없으면 나중에 사실로 굳는다');
assert.strictEqual(a2b.circuitBreaker.ignoreConsecutiveEmpty, true,
  'A2b에서 빈 응답은 정상 결과다(정찰 실측 591/1222) — A2a식 연속 빈 응답 서킷은 정상 수집을 멈춘다');
assert.ok(a2b.circuitBreaker.consecutiveExceptions > 0,
  '예외 서킷까지 없으면 루프 도중 경로가 막혀도 끝까지 돈다');
// 규모 FAIL 둘만 정찰 실측(전수 1,222건)에 근거한다. 실측 아래여야 게이트가 의미를 갖고,
// 너무 낮으면 상류를 되풀이하는 임계가 된다(교훈45).
assert.ok(a2b.acceptance.minTickersWithData > 0
  && a2b.acceptance.minTickersWithData < 631,
  'minTickersWithData가 정찰 실측(631) 이상이면 첫 실행부터 실패한다');
assert.ok(a2b.acceptance.minTickersInAnalysisWindow > 0
  && a2b.acceptance.minTickersInAnalysisWindow < 572,
  'minTickersInAnalysisWindow가 정찰 실측(572) 이상이면 첫 실행부터 실패한다');
assert.ok(a2b.acceptance.minTickersInAnalysisWindow <= a2b.acceptance.minTickersWithData,
  '분석 구간 내 종목은 확보 종목의 부분집합이다 — 임계가 뒤집히면 통과 불가능한 계약이 된다');
assert.strictEqual(a2b.acceptance.residualDailyChangeViolations, 0,
  '품질 제외 후 잔여 위반은 0이어야 한다 — A2a와 같은 판별을 쓰므로 같은 기준이다');
assert.ok(!('exitAtMismatchLastRow' in a2b.acceptance),
  'exitAt을 마지막 가격행과 비교하는 검사는 동어반복이라 아무것도 막지 못한다(교훈45) — 출처 계약으로 대체됐다');
assert.ok(a2b.acceptance.qualityExcludedRateWarn > 0,
  '폐지 종목의 품질 제외율에는 실측이 없다 — WARN으로 시작해 첫 수집 후 승격한다');

// ---- dataPolicies: fundamentals (FN-1.0) ----
const fund = load(registry.dataPolicies.fundamentals);
assert.ok(fund.version, 'fundamentals에 version 없음');
assert.strictEqual(fund.output.gzipMtime, 0,
  'gzip mtime이 0이 아니면 내용이 같아도 매 실행 바이트가 달라져 manifest가 재수집 판정 기능을 잃는다');
assert.strictEqual(fund.output.partition, 'fiscalYear',
  '저장 축은 fiscalYear다 — 실행 축(샤드)과 묶이면 샤드 수 변경이 곧 전량 재수집이 된다');
assert.ok(fund.shards >= 1 && Number.isInteger(fund.shards), 'shards는 1 이상 정수');
assert.ok(fund.probeCorps.length >= 2,
  '정찰은 2회 이상이어야 한다(교훈32) — 1회면 그 법인의 특수사정과 경로 차단이 구분되지 않는다');

// PIT 계약 — 이 세 줄이 A3의 존재 이유다. 하나라도 느슨해지면 백테스트에 look-ahead가 들어간다.
assert.strictEqual(fund.pointInTime.contract, 'availableFrom > periodEnd',
  'PIT 계약이 바뀌었다 — 회계기간말이 아니라 공시 접수일부터 그 숫자를 알 수 있다(BF-1.1 §7 A3 계약 1)');
assert.strictEqual(fund.acceptance.availableFromNotAfterPeriodEnd, 0,
  '계약 1 위반 허용치는 0이다 — 위반이 있다는 것은 로직 반전이거나 periodEnd 파싱 오류다');
assert.strictEqual(fund.acceptance.availableFromMissing, 0,
  'availableFrom 없는 레코드는 시점을 모르는 재무값이다 — A5가 그것을 언제든 쓸 수 있는 값으로 읽는다');
assert.strictEqual(fund.pointInTime.periodEndSource, 'thstrm_dt',
  'periodEnd는 보고서가 말하는 값이어야 한다 — 결산월로 계산하면 결산월 변경 이력과 어긋나고 폐지 법인엔 그 필드가 없다');

// 중복 키가 (corp, fiscalYear)가 아니라 (corp, fiscalYear, availableFrom)인 이유:
// 정정공시는 중복이 아니라 사실이다. 병합하면 '그 시점에 알던 값'이 사라진다.
assert.deepStrictEqual(fund.output.sortKey, ['fiscalYear', 'corp', 'availableFrom'],
  '정렬 키에 availableFrom이 없으면 정정공시가 있는 (corp, fiscalYear)의 순서가 소스 반환 순서에 의존해 해시가 갈린다');
assert.ok(fund.output.fields[0] === 'corp',
  '조인 키는 corp_code다(계약 4) — ticker를 첫 필드로 두면 조인 키로 오해된다');

// 커버리지 분자에서 유동자산·유동부채를 뺐는가. 넣으면 금융업 구성이 커버리지로 위장한다.
assert.ok(!fund.accounts.requiredForCoverage.includes('currentAssets')
       && !fund.accounts.requiredForCoverage.includes('currentLiab'),
  '유동자산·유동부채는 금융업에서 구조적으로 결측이다 — 커버리지 분자에 넣으면 업종 구성이 데이터 품질로 둔갑한다');
for (const k of fund.accounts.requiredForCoverage) {
  assert.ok(k in fund.accounts.spec, `requiredForCoverage의 ${k}가 spec에 없다 — 잡을 수 없는 계정을 분자로 센다`);
}
assert.ok(fund.accounts.matchOrder[0] === 'id',
  'IFRS 태그를 1순위로 둔다 — 주요계정 응답에는 태그가 없어 실질은 이름 매칭이지만, 전체 재무제표로 되돌아갈 때 같은 코드가 동작해야 한다');

// FN-1.1 — 정찰이 뒤집은 선택. 전체 재무제표는 thstrm_dt를 주지 않아(실측 0/240)
// 계약 1을 잴 수단 자체가 없다. 되돌리려면 periodEnd를 얻을 다른 경로가 먼저 있어야 한다.
assert.strictEqual(fund.source.endpoint, 'fnlttSinglAcnt.json',
  '엔드포인트가 바뀌었다 — 전체 재무제표에는 thstrm_dt가 없어 회계기간말을 못 읽고, 수집기가 전건을 PERIOD_END_UNPARSED로 버린다(정찰 실측 240/240 대 0/240)');
assert.ok(fund.source.thstrmOnlyNote,
  '주요계정은 전기·전전기를 함께 준다 — 그것을 쓰면 안 된다는 근거가 정책에 없으면 다음 사람이 호출량을 줄이려고 쓴다(교훈47)');
assert.ok(fund.probed && !fund.probed.measured,
  'probed는 표본 정찰이다. measured와 이름을 섞으면 표본으로 잰 값이 전수의 게이트 기준선이 된다');
assert.strictEqual(fund.probed.fnlttSinglAcnt.availableFromNotAfterPeriodEnd, 0,
  '정찰에서 계약 1 위반이 있었다면 수집을 시작하기 전에 원인을 먼저 밝혀야 한다');

// FN-1.2 — PIT 앵커 파싱률. 실측 전인데도 FAIL인 유일한 임계다.
// 근거는 실패가 이분적이라는 것이다(정찰 240/240 대 0/240) — 서서히 나빠지지 않는다.
// 정찰과 수집이 같은 임계를 쓰는지도 본다. 갈라지면 정찰이 통과시킨 소스를 수집이
// 거부하거나 그 반대가 된다.
assert.ok(fund.acceptance.periodEndParsedRateMin >= 0.99,
  'periodEnd 파싱률 임계가 없거나 느슨하다 — 이 값은 품질 등급이 아니라 소스·파서의 구조 변화를 잡는 선이다');
assert.strictEqual(fund.acceptance.periodEndParsedRateMin,
  fund.probeAcceptance.periodEndParsedRateMin,
  '정찰과 수집의 임계가 갈라졌다 — 정찰이 통과시킨 소스를 수집이 거부하게 된다');

assert.ok(fund.fiscalYearFrom >= 2015,
  'fnlttSinglAcntAll은 2015 사업연도부터 제공된다 — 그 이전을 요구하면 전건 013이 된다');
assert.ok(fund.fiscalYearTo >= fund.fiscalYearFrom, 'fiscalYear 구간이 뒤집혔다');
assert.ok(fund.quota.dailyCallLimit > fund.quota.safetyMarginCalls * 2,
  '안전 여유분이 일 한도의 절반을 넘으면 예산이 아니라 제약이 된다');
// 여유분의 하한은 감이 아니라 실측이다 — 같은 키를 쓰는 운영 워크플로의 최악 겹침이
// 하루 약 1,000건이다(disclosures 200 + quarterly-fundamentals 400 + add-ticker 400).
// 이보다 작으면 백필이 운영의 한도를 먹는다. 백필은 한 번 돌고 운영은 매일 돈다.
assert.ok(fund.quota.safetyMarginCalls >= 1000,
  '안전 여유분이 운영 워크플로의 최악 겹침(약 1,000건)보다 작다 — A3가 남의 한도를 먹는다');
assert.strictEqual(fund.collectionWindow.recordDays, true,
  '수집 창을 안 남기면 재수집으로 해시가 바뀌었을 때 정정공시인지 버그인지 가를 근거가 없다');
assert.ok(fund.stopAfterConsecutiveEmptyYears >= 2,
  '조기 종료가 1이면 1년 결산 공백 뒤에 재개된 보고서를 통째로 놓친다');

// FN-1.0은 실측 전이다. measured 블록이 생기기 전에 WARN 임계가 FAIL로 올라가면
// 근거 없는 게이트가 된다(PR-1.0 → PR-1.3이 밟은 경로의 반대).
if (!fund.measured) {
  for (const k of ['minCorpsWithDataWarn', 'coverageRateMinWarn', 'yearCoverageDropWarn',
                   'roeAbsOutlierRateWarn', 'negativeEquityRateWarn']) {
    assert.ok(k in fund.acceptance,
      `${k} 없음 — 실측 전 임계는 사라지는 것이 아니라 WARN으로 존재해야 관측이 남는다`);
  }
}

console.log(`   universe ${uni.version}: a1b 후보 임계 [${a1b.acceptance.candidateMin}, ${a1b.acceptance.candidateMax}]`);
console.log(`   price ${price.version}: 샤드 ${price.shards} · 요구 pykrx ${price.source.requiredVersion} · 일간 임계 ±${price.acceptance.dailyChangeAbsMax * 100}%`);
console.log(`   fundamentals ${fund.version}: 사업연도 ${fund.fiscalYearFrom}~${fund.fiscalYearTo} · 샤드 ${fund.shards} · 일 한도 ${fund.quota.dailyCallLimit}${fund.measured ? '' : ' (실측 전 — 커버리지 임계는 WARN)'}`);
console.log(`✅ 정책 파일 전체 통과 (${Object.keys(registry.policies).length}개 + criteria ${Object.keys(registry.criteria).length}개 + data ${Object.keys(registry.dataPolicies).length}개)`);
