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
               'tickerContractViolations',
               // 수집 계약(FN-1.3). resume 판정을 정책 version이 아니라 계약 해시로
               // 바꾸면서 하나의 산출물이 여러 정책 버전에 걸칠 수 있게 됐다 —
               // 어느 버전들이 이것을 만들었는지가 값으로 남아야 그 완화가 기록을
               // 잃지 않는다. 해시가 둘 이상이면 다른 규칙의 레코드가 섞인 것이다.
               'collectionPolicyVersions', 'collectionContractHashes',
               // 하드 실패로 0레코드인 법인. done도 남은 것도 아닌 세 번째 상태이며,
               // 이 칸이 없으면 그런 법인이 완료로 계산되어 빈 데이터가 게이트를
               // 그대로 지나간다. 승인 여부(open)와 재시도 가능 여부를 함께 남긴다 —
               // retryable=true는 아직 모르는 것이지 못 하는 것이 아니다.
               'corpsHardSkipped', 'corpsHardSkippedOpen', 'hardSkippedByRetryable',
               // 승인된 공백. 목록과 개수를 함께 남기는 이유는 approvalHash가 '어느
               // 버전의 승인 목록인가'만 고정하고 '무엇을 승인했는가'는 말하지 않기
               // 때문이다. declaredNotInHardSkipped는 실제 공백에 대응하지 않는 승인이며,
               // 오래된 승인이 미래의 공백을 미리 덮는 것이 이 체계가 조용해지는 경로다.
               'declaredGaps', 'declaredGapsCount', 'declaredNotInHardSkipped',
               // 일부 연도만 실패하고 레코드는 나온 법인. 세지 않으면 부분 공백이
               // 완전 수집과 구분되지 않는다.
               'corpsPartialHard',
               // 상태 손상. 둘 다 비어 있어야 정상이고, 비어 있다는 것 자체가 기록이다.
               //   S  샤드 하나로 잴 수 있는 성질 — done ∩ hardSkipped == ∅ ·
               //      계약 해시 존재 · done + hardSkipped <= assigned
               //   M  병합해야만 잴 수 있는 성질 — Σ corpsAssigned == 대상 법인 수 ·
               //      샤드 간 corpsDone 배타
               // 옛 stateConservationViolations는 제거했다. conservationOk가 remaining을
               // 유도한 뒤 그 등식을 재확인해 구성상 항상 참이었고, 남겨두면 다음 사람이
               // 그 true를 상태의 건강으로 읽는다(교훈72).
               // Measurable 플래그가 따로 있는 이유는 M1의 분모에 빠진 항이 있을 수
               // 있어서다. 0으로 읽으면 그 차이가 '샤딩이 달라졌다'로 보고돼 실제
               // 원인을 가린다 — 잴 수 없으면 판정하지 않고 그 사실을 남긴다(교훈57).
               'stateInvariantViolations', 'stateMergedViolations',
               'corpsAssignedSum', 'corpsAssignedSumMeasurable',
               // M3 — 한 법인의 레코드가 한 샤드에서만 나왔는가. M2가 상태를 보는 것과
               // 달리 이쪽은 산출물을 본다. 어느 샤드에서 온 레코드인지는 병합하는
               // 순간에만 알 수 있고(레코드에 샤드 번호는 없다) 합치면 사라진다.
               // 둘은 서로소이며 원인이 다르다 — 복제는 dedup·샤드 할당, 분산은
               // 샤드 분할을 가리킨다. 합쳐 두면 어느 층을 팔지 진단이 말해주지 않는다.
               'duplicateRecordKeysAcrossShards', 'recordDistributionAcrossShards',
               // 법인별 공백 사유 — collect만 알 수 있고 산출물에는 흔적이 없다.
               // 없는 행은 이유를 말하지 않으므로 이 표가 없으면 "A사 2021 없음"이
               // 정상 사실(013)인지 손실(파싱 실패·조회 실패)인지 영영 모른다.
               // finalize가 _shards/를 지우므로 여기가 유일한 생존 기록이다.
               'recordGaps', 'recordGapCorps', 'recordGapReasons',
               // 산출물 일관성 — 병합 결과의 법인이 전부 어느 샤드의 corpsDone에
               // 있는가. 샤드별 검사는 자기 상태만 보므로 병합에서 남의 레코드가
               // 섞이는 경우는 여기서만 보인다. 부분집합이지 등식이 아니다.
               'recordCorpsNotInDone'],
    // sicCode는 '현재의 업종'이라 전 사업연도에 같은 값이 붙는다. A3가 모르는 축이다.
    trueFlags: ['sectorNotPointInTime'],
    forbidden: ['smokeTest'],
  },

  'A3b': {
    file: 'data/backfill/fundamentals/a3b/_diagnostics.json',
    required: ['fundamentalsPolicy', 'stageVersion', 'shardCount', 'rowCount',
               // 격자 축. A3 산출물에서 읽으므로 몇 셀을 계획했는지가 남아야
               // scannedCells 와의 대조가 성립한다(A3b-1.0 §3·§7).
               'gridMode', 'reuseCorps', 'reuseCells', 'missingCorps', 'plannedCells',
               // ★ 스캔 기록. A3가 빈 gaps를 pop해서 798법인 중 599의 '조회 여부'가
               // 사라진 자리다. 이 필드가 없으면 같은 공백이 A3b에서 다시 생긴다.
               'scannedCells', 'scannedCorps', 'dartStatusDistribution', 'rejectReasons',
               // ★ rceptNoPresentRate 의 분모. 스캔 셀이 아니라 '행이 돌아온 셀'이다 —
               // 013(보고서 없음)을 분모에 넣으면 '보고서가 없다'가 'rcept_no 를 안
               // 준다'로 읽힌다. 분모가 없으면 비율을 판정할 수 없다(교훈57).
               'respondedCells',
               // PIT 축. A3의 존재 이유와 같고, 조용히 무너지는 축이다.
               'epsNumericRate', 'pitContractViolationSample',
               // 배당 세 갈래. 하나로 뭉치면 무배당과 결측이 같은 모양이 된다(§5.1).
               'dividendThreeWayDistribution',
               // 목표 집단의 확보율. 전체 비율만 보면 폐지 그룹이 현재 상장을 가린다.
               'currentListedEpsRate', 'currentListedCorps',
               // A3 rceptNo 대조. amended 는 정정공시이며 결함이 아니다(§4).
               'rceptNoVsA3', 'rceptNoPresentRate'],
    // A3b가 '모른다'고 선언하는 축은 없다 — 대신 스캔 기록이 그 자리를 대신한다.
    trueFlags: [],
    forbidden: ['smokeTest'],
  },

  'A3c': {
    file: 'data/backfill/fundamentals/a3c/_diagnostics.json',
    required: ['fundamentalsPolicy', 'stageVersion', 'shardCount', 'rowCount',
               // 격자 축. A3b와 같되 cellMultiplier(4)가 추가다 — reprtCode 4종을
               // 전부 도는 게 A3c의 정의적 차이라 이 값이 없으면 격자가 왜 4배인지
               // 산출물만으로 못 되짚는다.
               'gridMode', 'reuseCorps', 'reuseCells', 'missingCorps', 'plannedCells',
               'cellMultiplier',
               // ★ 스캔 기록. A3/A3b와 같은 이유(교훈75) — 결과 없이도 스캔 여부를 남긴다.
               'scannedCells', 'scannedCorps', 'dartStatusDistribution', 'rejectReasons',
               // PIT 축.
               'pitContractViolationSample', 'rceptNoPresentRate', 'availableFromParsableRate',
               // A3c 고유 — istc_totqy 확보율과 PIT+tie-break+carry-forward 규칙을
               // 전체 수집분에 재생한 결과. docs/A3c-정책초안.md §2가 이 값들로
               // 검증됐고, 여기 없으면 그 검증이 probed(40법인)에서 이 수집분으로
               // 이어졌는지 산출물만으로 못 확인한다.
               'istcTotqyRowFoundRate', 'replayMetrics'],
    trueFlags: [],
    forbidden: ['smokeTest'],
  },

  'A3d': {
    file: 'data/backfill/fundamentals/a3d/_diagnostics.json',
    required: ['fundamentalsPolicy', 'stageVersion', 'shardCount', 'rowCount',
               // 대상·완료 축. A3d는 격자가 (corp) 하나뿐이라 A3c의 cellMultiplier류가
               // 없다 — 그 대신 corpsIncomplete가 완료 여부의 유일한 척도다.
               'targetCorps', 'corpsDone', 'corpsIncomplete', 'callsTotal',
               // 분류·거절 사유. A3/A3b/A3c와 같은 이유(교훈75) — 결과 없이도
               // 왜 없는지를 남긴다.
               'rejected', 'listErrors', 'categoryDistribution',
               // A3d 고유 — splitLike 중 a3cBracket 소스의 정합성 척도. 이 값이
               // 없으면 000860류 검증(§19.1)이 이 수집분에 실제로 이어졌는지
               // 산출물만으로 못 확인한다.
               'bracketOutOfToleranceRate', 'bracketSamples'],
    trueFlags: [],
    forbidden: ['smokeTest'],
  },

  'A4': {
    file: 'data/backfill/supplyDemand/a4/_diagnostics.json',
    required: ['supplyDemandPolicy', 'environment', 'shardCount', 'rowCount',
               'rowCountAfterValidation', 'calendarStart', 'calendarEnd',
               'actualDataFrom', 'actualDataTo', 'years', 'totalGzBytes',
               // 구조 계약 위반 카운트 — 전부 FAIL(0)이라 여기 있는 것 자체가
               // 게이트가 실제로 돌았다는 증거다.
               'dateContractViolations', 'tickerContractViolations',
               'categoryKeySetViolations',
               // 시장 청산 조건(순매수를 저장하지 않으므로 매수-매도 카테고리 합이
               // 0인지로 항등식을 대신 검사한다) 위반과 표본.
               'marketClearingViolations', 'marketClearingViolationSample',
               // 커버리지 — 대상(A1a)·확보·비율. 분모가 없으면 tickersWithData
               // 하나만으로는 좋은지 나쁜지 판정할 수 없다.
               'candidateCount', 'tickersWithData', 'tickersWithDataRate',
               'emptyCount', 'missingRate', 'expectedDaysPerTicker',
               // UNRESOLVED — 종목별 실패 사유 전량. 없으면 "그 종목 왜 없지"가
               // 재수집 없이는 영영 답 없는 질문이 된다(교훈75).
               'unresolvedCount', 'unresolvedRate', 'unresolved'],
    trueFlags: [],
    forbidden: ['smokeTest'],
  },

  'A5': {
    file: 'data/backfill/scores/_diagnostics.json',
    required: ['corpsAssigned', 'corpsDone', 'corpsIncomplete', 'noPriceAtAsOf',
               'assembleFailed', 'assembleFailedRate', 'validateViolations',
               'exitReasonUnknown', 'written', 'recordCount', 'perYearCounts', 'years'],
    trueFlags: [],
    // --limit·--universeLimit(스모크 테스트)의 산출물이 정상 산출로 승격되는
    // 경로를 막는다(A2a·A2b·A3~A3d와 동일 원칙, 한 방향 훅).
    forbidden: ['smokeTest'],
  },

  'EO': {
    file: 'data/backfill/exitOverlay/_diagnostics.json',
    required: ['stageVersion', 'exitOverlayPolicy', 'overlayVersion',
               'exitAtConfirmedTotal', 'tierA', 'tierB', 'tierBListErrorRate',
               'totalClassified', 'totalUnknown', 'classifiedRate', 'distribution'],
    trueFlags: [],
    // 스모크/드라이런 산출물이 정상 산출로 승격되는 경로를 막는다
    // (A2a·A2b·A3~A3d·A5와 동일 원칙, --promote 없이는 애초에 파일 자체가 없다).
    forbidden: ['smokeTest'],
  },

  'A8': {
    file: 'data/backfill/shortSelling/a8/_diagnostics.json',
    required: ['shortSellingPolicy', 'environment', 'shardCount', 'rowCount',
               'rowCountAfterValidation', 'calendarStart', 'calendarEnd',
               'actualDataFrom', 'actualDataTo', 'years', 'totalGzBytes',
               // 구조 계약 위반 카운트 — 전부 FAIL(0). A4와 달리 종목당 1콜(카테고리
               // 구조 없음)이라 categoryKeySetViolations·marketClearingViolations는
               // 해당 없음 - 애초에 잴 대상 자체가 없다(교훈73, 병합에서만 잴 수
               // 있는 걸 샤드 쪽에 두지 않는 것과 같은 이유로 여기서도 없는 축을
               // 있는 척 만들지 않는다).
               'dateContractViolations', 'tickerContractViolations',
               // 커버리지 — 대상(A1a)·확보·비율.
               'candidateCount', 'tickersWithData', 'tickersWithDataRate',
               'emptyCount', 'missingRate', 'expectedDaysPerTicker',
               // UNRESOLVED — 종목별 실패 사유 전량(교훈75).
               'unresolvedCount', 'unresolvedRate', 'unresolved'],
    trueFlags: [],
    forbidden: ['smokeTest'],
  },
};

// 표 자체를 먼저 검사한다. 새 단계를 추가하면서 키 이름을 틀리면(file → path 같은)
// 그 단계에서만 죽는데, 그 순간은 워크플로 한복판이라 이미 수집을 마친 뒤다.
// 쓰는 시점에 강제하는 편이 읽는 시점의 발견보다 안전하다(교훈73).
for (const [name, spec] of Object.entries(CONTRACT)) {
  for (const k of ['file', 'required', 'trueFlags']) {
    if (spec[k] === undefined) {
      console.error(`진단 계약 표가 깨졌다: ${name}에 '${k}'가 없다 (키 이름 오타?)`);
      process.exit(1);
    }
  }
}

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
