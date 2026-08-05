#!/usr/bin/env node
'use strict';
/**
 * 진단 계약 검증 — "빌드 성공 = 실제로 아무 일도 안 함"을 잡는 단일 창구.
 *   node scripts/verify-diagnostics.js A1b
 *
 * 왜 필요했나: 커밋 7cd0361이 build-universe-a1a.py의 `if __name__ == "__main__"`을
 * 지웠을 때, 스크립트는 세 번의 워크플로 실행 내내 아무 일도 안 하고 exit 0으로 끝났다.
 * manifest 스텝은 별도 node 스크립트라 generatedAt만 갱신했고, 아무도 눈치채지 못했다.
 *
 * 왜 워크플로 인라인이 아니라 여기인가: 같은 계약이 YAML 세 곳에 python heredoc으로
 * 복사돼 있으면 필드를 추가할 때 한 곳만 고치는 경로가 생긴다. 계약은 표 하나여야 하고,
 * 그 표는 검사 대상 스크립트가 아니라 검사자 쪽에 있어야 한다 —
 * 산출하는 쪽이 계약도 들고 있으면 둘이 같이 틀린다.
 *
 * 진단 payload를 version/flags/summary로 재구조화하지 않은 이유: 실제 결함은 '계약이
 * 세 벌'이라는 것이지 '필드가 평평하다'가 아니다. 중첩은 A0.7·A1a 산출 스크립트 전부를
 * 건드리면서 잡히는 버그는 하나도 늘리지 않는다.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');

/** 모든 단계 공통. 인수 조건 게이트가 실제로 돌았다는 증거다. */
const COMMON = ['acceptancePassed', 'acceptanceFails', 'acceptanceWarns'];

/**
 * 단계별 계약.
 *   required : 존재해야 하는 필드. 리팩터링에서 조용히 사라지면 즉시 실패한다
 *   trueFlags: 값이 반드시 true여야 하는 플래그. 그 단계가 '모른다'고 선언한 축이며,
 *              사라지면 하류가 미확정값을 확정값으로 읽는다
 */
const CONTRACT = {
  'A0.7': {
    file: 'data/backfill/dart/_diagnostics.json',
    required: ['snapshotDate', 'maxModifyDate', 'corpCount', 'stockHolderCountRaw',
               'finalCount', 'tickerReuse', 'httpStage', 'zipStage', 'xmlStage'],
    trueFlags: [],
  },
  'A1a': {
    file: 'data/backfill/universe/a1a/_diagnostics.json',
    required: ['universePolicy', 'sourceRows', 'exactDuplicateRemoved', 'partialDuplicates',
               'konexExcluded', 'spacExcluded', 'tickerCollisions', 'excludedCorpMissing',
               'finalCount', 'excludedCount'],
    trueFlags: [],
  },
  'A1b': {
    file: 'data/backfill/universe/a1b/_diagnostics.json',
    required: ['universePolicy', 'baseCount', 'subtractCounts', 'candidatesAfterCorpDiff',
               'tickerSafetyNetRemoved', 'finalCount', 'tickerReuse'],
    trueFlags: ['exitReasonPending', 'listingHistoryUnverified'],
  },
  'A2a': {
    file: 'data/backfill/price/a2a/_diagnostics.json',
    required: ['pricePolicy', 'environment', 'shardCount', 'rowCount',
               'rowCountAfterExclusion', 'calendarStart', 'actualDataFrom', 'actualDataTo',
               'expectedRows', 'missingRate', 'datesNotInCalendar', 'years',
               // 품질 제외는 개수가 아니라 사유별 분포까지 남는다 — A5가 사유를 그대로
               // 노출하고, 소스가 고쳐지면 특정 사유만 재검증할 수 있어야 한다.
               'qualityExcluded', 'qualityExcludedCount', 'qualityExcludedByReason',
               'qualityExcludedRate',
               // 검사에서 제외한 비교쌍은 침묵하지 않는다 — 무엇을 안 봤는지가 기록이다
               'zeroVolumeTransitions', 'suspendedGapTransitions', 'comparableTransitions',
               // 전체 기준과 산출물(제외 후) 기준을 함께 남긴다. 후자가 A5의
               // returnTransition이 실제로 걷어낼 규모다
               'keptZeroVolumeTransitions', 'keptComparableTransitions',
               // 관측 전용(게이트 아님)
               'frontTruncatedTickers', 'frontTruncatedTickerDays',
               'rowsBeforeListedAt', 'tickersWithRowsBeforeListedAt'],
    trueFlags: [],
    // 부분 수집(--limit)이 정상 산출로 승격되는 경로를 막는다. 한 방향 훅이다 —
    // 이 플래그는 통과를 만들 수 없고 거부만 만든다.
    forbidden: ['smokeTest'],
  },
  'A2b': {
    file: 'data/backfill/price/a2b/_diagnostics.json',
    required: ['pricePolicy', 'environment', 'shardCount', 'rowCount',
               'rowCountAfterExclusion', 'calendarStart', 'calendarEnd',
               'actualDataFrom', 'actualDataTo', 'years', 'totalGzBytes',
               // 기대 모델의 근거를 값으로 남긴다. A2a 기준(캘린더 끝)으로 되돌아가면
               // 누락률이 90%대로 튀는데, basis가 없으면 그것이 수집 실패로 읽힌다.
               'expectedRowsBasis', 'expectedRows', 'missingRate',
               'datesNotInCalendar', 'tickerContractViolations',
               // 품질 판별은 A2a와 공유하는 계약이라 같은 관측치를 남긴다
               'qualityExcluded', 'qualityExcludedCount', 'qualityExcludedByReason',
               'qualityExcludedRate', 'zeroVolumeTransitions', 'suspendedGapTransitions',
               'comparableTransitions', 'keptZeroVolumeTransitions',
               'keptComparableTransitions',
               // 커버리지 — 분모를 셋 다 남긴다. 후보 전체(51.6%)를 커버리지로 읽는
               // 오독이 정찰의 핵심 경고였고, 분모가 하나만 남으면 그 오독이 되돌아온다.
               'candidateCount', 'tickersWithData', 'tickersInAnalysisWindow',
               'tickersOutOfAnalysisWindow', 'rawCandidateCoverageRate', 'analysisFrom',
               'emptyCount', 'emptyRate', 'exceptionCount',
               // exitAt 축. A1b가 비워둔 칸을 채우는 것이 A2b의 두 번째 산출물이다.
               // dartModifyDate와의 차이 분포는 '그것이 폐지일이 아니다'의 실측이다.
               'exitRecordCount', 'exitAtVsDartModifyDate', 'exitAtSemanticsNote',
               // A1b 차집합의 오분류 신호(지금도 거래 중일 가능성)
               'stillTradingSuspects', 'stillTradingSuspectCount'],
    // A2b가 '모른다'고 선언하는 축 둘. 사라지면 하류가 추정을 확정으로 읽는다 —
    // 확보 실패를 구간 밖으로 본 것은 가정이고, exitAt은 폐지 효력일이 아니다.
    trueFlags: ['coverageAssumesFailuresOutOfWindow', 'exitAtIsLastTradedNotEffectiveDate'],
    forbidden: ['smokeTest'],
  },
  'A3': {
    file: 'data/backfill/fundamentals/a3/_diagnostics.json',
    required: ['fundamentalsPolicy', 'stageVersion', 'shardCount', 'rowCount',
               'fiscalYearFrom', 'fiscalYearTo', 'fiscalYearToExpectedByRule', 'years',
               'totalGzBytes',
               // 수집이 며칠에 걸치므로 산출물은 혼합 시점 스냅샷일 수 있다. PIT는
               // 깨지지 않지만(레코드마다 자기 availableFrom을 든다) 재현성은 깨진다 —
               // 재수집으로 해시가 바뀌었을 때 정정공시를 후보로 지목할 유일한 근거다.
               'collectionWindow',
               // PIT 축. A3의 존재 이유이자 유일하게 조용히 무너지는 축이다 —
               // 위반이 있어도 점수와 등급은 정상으로 보이고, 백테스트만 좋아진다.
               'availableFromNotAfterPeriodEnd', 'disclosureLagDays',
               // 정정공시를 병합하지 않았다는 증거. 병합하면 '그 시점에 알던 값'이 사라진다.
               'restatedFiscalYears',
               // 계약 2 — 연도별 매칭 성공률. 전체 평균은 한 해의 붕괴를 가리므로
               // 연도별 표와 중앙값 대비 낙폭을 함께 남긴다.
               'yearCoverage', 'accountCoverageByYear', 'yearCoverageMedian',
               'yearCoverageDropped', 'yearsWithNoData', 'fiscalYearOutOfRange',
               // 커버리지 — 분자에 무엇을 넣었는지까지 남긴다. 계정 목록이 바뀌면
               // 같은 이름의 비율이 다른 것을 재게 된다.
               'coverageRate', 'coverageRequiredAccounts',
               // 그룹별 확보율. 전체 비율만 두면 현재 상장분 2,579가 폐지분 1,222의
               // 공백을 가린다(A2b 정찰에서 배운 분모 문제).
               'corpsWithData', 'corpsTargeted', 'corpsWithDataByGroup',
               'corpsWithDataRateByGroup',
               // 계약 3 — 이상치는 제거 대상이 아니라 보고 대상이다
               'roeComputable', 'roeAbsOutlierCount', 'roeAbsOutlierRate',
               'roeAbsOutlierSample', 'negativeEquityCount', 'negativeEquityRate',
               // 어느 수단으로 계정을 잡았는지. 매칭률이 떨어졌을 때 소스 변화인지
               // 이름 변주인지 사후에 가르는 유일한 근거다.
               'accountSourceDistribution', 'accountMappingHitRateByAccount',
               'fsDivDistribution', 'sicCodeMissing',
               // PIT 앵커 파싱률과 그 분모. periodEnd를 못 읽은 보고서는 레코드가 되지
               // 않으므로 산출물에는 흔적이 없다 — 확보 보고서의 절반을 잃어도
               // periodEndMissing은 0이다. 분모가 남지 않는 손실이라 여기서만 보인다.
               'reportsFound', 'recordRejected', 'periodEndParsedRate',
               'tickerContractViolations'],
    // sicCode는 '현재의 업종'이라 전 사업연도에 같은 값이 붙는다. A3가 모르는 축이다.
    trueFlags: ['sectorNotPointInTime'],
    forbidden: ['smokeTest'],
  },
};

const stage = process.argv[2];
const c = CONTRACT[stage];
if (!c) {
  console.error(`알 수 없는 단계: ${stage || '(없음)'} — 사용: node scripts/verify-diagnostics.js <${Object.keys(CONTRACT).join('|')}>`);
  process.exit(1);
}

const abs = path.join(ROOT, c.file);
if (!fs.existsSync(abs)) {
  console.error(`${c.file} 없음 — 빌드가 진단조차 남기지 않았다. 중단 경로에도 진단은 남아야 한다(교훈39)`);
  process.exit(1);
}

let d;
try {
  d = JSON.parse(fs.readFileSync(abs, 'utf8'));
} catch (e) {
  console.error(`${c.file} 파싱 불가: ${e.message}`);
  process.exit(1);
}

const errs = [];

// 경로를 잘못 물린 워크플로는 '다른 단계의 정상 진단'을 읽고 통과한다.
if (d.stage !== stage) errs.push(`stage 필드가 ${JSON.stringify(d.stage)}다 — ${stage}의 진단이 아니다 (경로 오배선)`);
if (d.aborted === true) errs.push(`aborted=true (${d.abortReason || '사유 없음'}) — 중단된 실행이다`);

for (const k of [...COMMON, ...c.required]) {
  if (!(k in d)) errs.push(`${k} 필드 없음 — main() 진입 여부 또는 리팩터링 누락 의심`);
}
for (const k of c.trueFlags) {
  if (d[k] !== true) errs.push(`${k}=${JSON.stringify(d[k])} — true여야 한다. ${stage}가 모르는 것을 아는 것처럼 하류로 넘긴다`);
}
for (const k of c.forbidden || []) {
  if (k in d) errs.push(`${k} 플래그가 있다 — 부분 수집·시험 실행의 산출물은 정상 산출로 승격될 수 없다`);
}

if ('acceptancePassed' in d && d.acceptancePassed !== true) {
  errs.push(`acceptancePassed=${JSON.stringify(d.acceptancePassed)} — Build는 성공인데 인수 조건은 실패다`);
}
if ('acceptanceFails' in d && (!Array.isArray(d.acceptanceFails) || d.acceptanceFails.length)) {
  errs.push(`acceptanceFails=${JSON.stringify(d.acceptanceFails)} — 빈 배열이어야 한다`);
}
if ('acceptanceWarns' in d && !Array.isArray(d.acceptanceWarns)) {
  errs.push('acceptanceWarns가 배열이 아니다');
}

if (errs.length) {
  console.error(`❌ ${stage} 진단 계약 위반 ${errs.length}건 — ${c.file}`);
  for (const e of errs) console.error(`  - ${e}`);
  process.exit(1);
}

const warns = d.acceptanceWarns.length;
console.log(`OK: ${stage} 진단 계약 통과 (필드 ${COMMON.length + c.required.length} · 플래그 ${c.trueFlags.length} · WARN ${warns}건)`);
if (warns) for (const w of d.acceptanceWarns) console.log(`  WARN ${w}`);
