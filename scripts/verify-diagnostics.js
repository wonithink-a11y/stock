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
               'calendarStart', 'actualDataFrom', 'actualDataTo', 'rollingWindowLoss',
               'expectedRows', 'missingRate', 'dailyChangeViolationCount', 'years'],
    trueFlags: [],
    // 부분 수집(--limit)이 정상 산출로 승격되는 경로를 막는다. 한 방향 훅이다 —
    // 이 플래그는 통과를 만들 수 없고 거부만 만든다.
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
