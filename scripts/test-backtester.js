#!/usr/bin/env node
'use strict';
/**
 * 백테스트 표본 편입 계약 회귀 — 합성 스냅샷으로 모집단 정의를 밟는다.
 *   node scripts/test-backtester.js
 *
 * 지키려는 것 하나다: **"IC 를 어떤 종목으로 계산했는가"에 답할 수 있는가.**
 *
 * 이 축이 무너지는 방식은 조용하다 — IC 도 등급 표도 정상으로 보이고, 분모만 틀린다.
 * 실제로 그랬다: 편입 조건이 `score !== null` 하나였고, 두 엔진이 계산해 둔 coverage 는
 * 쓰이지 않았으며(backtester.js 188·197행), 유보 종목은 gradeKey 의 charAt(0) 때문에
 * grade '유' 가 되어 등급 버킷에서만 빠지고 IC 에는 그대로 들어갔다.
 *
 * 밟는 분기:
 *   1. 제외 사유가 배타적이고 우선순위가 고정인가
 *   2. PIT 는 잴 수 있을 때만 재는가 (dataCutoff 부재 ≠ 위반)
 *   3. 편입이 두 층인가 — population.eligible 과 byHorizon.*.eligible 이 다른 것을 세는가
 *   4. 표본 부족 판정이 horizon 단위인가
 *   5. 모집단이 엔진 선택과 무관한가 (V1/V2 가 같은 표본을 낸다)
 *   6. 못 재는 축을 0으로 적지 않는가
 */
const assert = require('assert');
const {
  runBacktest, classifyBase, EXCLUSION, UNMEASURED_REASONS, MIN_SAMPLE,
} = require('../lib/backtester');
const { loadPolicies } = require('../lib/loadPolicies');

let pass = 0, fail = 0;
const ok = (label, cond, detail = '') => {
  console.log(`${cond ? '  OK    ' : '  FAIL  '}${label}${!cond && detail ? `  — ${detail}` : ''}`);
  cond ? pass++ : fail++;
};

const P = loadPolicies('KR');
const C = P.criteria;

// 커버리지가 충분한 입력(전 축)과 부족한 입력(기술만). 실측: 0.79 대 0.05.
const FULL = {
  fundamental: { roe: 14.2, debtRatio: 45, currentRatio: 250, operatingMarginTrend: 3,
                 revenueGrowth: 8, roeHistory5y: [9, 11, 12, 14, 14.2],
                 buybackOrDividendHistory: true },
  valuation: { per: 12, pbr: 1.2, perRelative: 0.8, epsGrowthRate: 15 },
  technical: { rsi: 55, macdSignal: 'bullish', maCross: 'golden', volumeRatio: 1.2 },
  supplyDemand: { foreignTrend5d: 'netBuy', institutionTrend5d: 'neutral',
                  largeShareholderChangePct: 0.5, buybackOrRetirementAnnounced: true },
};
const THIN = { technical: FULL.technical };

const snap = (i, { thin = false, fr = { d20: 5, d60: 8, d120: 11 }, cutoff, date = '2024-03-15' } = {}) => ({
  date,
  stockData: { ticker: `00000${i}`.slice(-6), ...(thin ? THIN : FULL),
               ...(cutoff ? { dataCutoff: cutoff } : {}) },
  forwardReturns: fr,
});

// ── 1. 제외 사유는 배타적이고 우선순위가 고정이다 ────────────────────
console.log('[1] 제외 사유 — 배타적 · 우선순위 고정');

ok('score 가 null 이면 NOT_SCORED 다',
   classifyBase({ score: null, coverage: { sufficient: false }, snap: { date: 'x' } })
   === EXCLUSION.NOT_SCORED);
ok('score 가 null 이면 coverage 를 보지 않는다 (두 번 세지 않는다)',
   classifyBase({ score: null, coverage: undefined, snap: { date: 'x' } })
   === EXCLUSION.NOT_SCORED);
ok('coverage 미달은 INSUFFICIENT_COVERAGE 다',
   classifyBase({ score: 70, coverage: { sufficient: false }, snap: { date: '2024-03-15' } })
   === EXCLUSION.INSUFFICIENT_COVERAGE);
ok('둘 다 통과하면 eligible (null) 이다',
   classifyBase({ score: 70, coverage: { sufficient: true },
                  snap: { date: '2024-03-15', stockData: {} } }) === null);

// ── 2. PIT 는 잴 수 있을 때만 잰다 ────────────────────────────────
console.log('\n[2] PIT — 부재는 위반이 아니라 미측정이다');

ok('dataCutoff 가 스냅샷 기준일보다 뒤면 PIT_INVALID (look-ahead)',
   classifyBase({ score: 70, coverage: { sufficient: true },
                  snap: { date: '2024-03-15', stockData: { dataCutoff: '2024-04-01' } } })
   === EXCLUSION.PIT_INVALID);
ok('같은 날은 위반이 아니다',
   classifyBase({ score: 70, coverage: { sufficient: true },
                  snap: { date: '2024-03-15', stockData: { dataCutoff: '2024-03-15' } } }) === null);
ok('앞선 날은 위반이 아니다',
   classifyBase({ score: 70, coverage: { sufficient: true },
                  snap: { date: '2024-03-15', stockData: { dataCutoff: '2024-03-01' } } }) === null);
ok('★ dataCutoff 가 없으면 제외하지 않는다 (검사 불가와 검사 실패는 다르다)',
   classifyBase({ score: 70, coverage: { sufficient: true },
                  snap: { date: '2024-03-15', stockData: {} } }) === null);

// V2 경로는 dataCutoff 를 snap.date 로 채워 넣는다. 그 값을 보면 검사가 항상 통과한다.
const rV2 = runBacktest([snap(1, { cutoff: '2024-04-01' })], C, { policies: P });
ok('★ V2 가 채워 넣는 기본값이 아니라 원본 dataCutoff 를 본다 (구성상 통과 방지)',
   rV2.population.excludedByReason[EXCLUSION.PIT_INVALID] === 1,
   JSON.stringify(rV2.population.excludedByReason));

// ── 3. 편입은 두 층이다 ──────────────────────────────────────────
console.log('\n[3] 두 층 — population.eligible 과 byHorizon.*.eligible 은 다른 것을 센다');

const mixed = [
  ...Array.from({ length: 5 }, (_, i) => snap(i)),                                  // 전부 있음
  ...Array.from({ length: 3 }, (_, i) => snap(10 + i, { fr: { d20: 4 } })),         // d20 만
  ...Array.from({ length: 2 }, (_, i) => snap(20 + i, { thin: true })),             // 커버리지 미달
];
const r = runBacktest(mixed, C, { policies: P });
const pop = r.population;

ok('totalCandidates 가 전체 스냅샷 수다', pop.totalCandidates === 10, String(pop.totalCandidates));
ok('커버리지 미달 2건이 제외된다',
   pop.excludedByReason[EXCLUSION.INSUFFICIENT_COVERAGE] === 2,
   JSON.stringify(pop.excludedByReason));
ok('population.eligible 은 horizon 과 무관한 8건이다', pop.eligible === 8, String(pop.eligible));
ok('excluded + eligible == totalCandidates',
   pop.eligible + pop.excluded === pop.totalCandidates);
ok('excludedByReason 의 합이 excluded 와 같다 (사유가 배타적이라는 증거)',
   Object.values(pop.excludedByReason).reduce((a, b) => a + b, 0) === pop.excluded,
   `${JSON.stringify(pop.excludedByReason)} vs ${pop.excluded}`);

ok('★ d20 은 8건, d120 은 5건 — horizon 마다 표본이 다르다',
   pop.byHorizon.d20.eligible === 8 && pop.byHorizon.d120.eligible === 5,
   `d20=${pop.byHorizon.d20.eligible} d120=${pop.byHorizon.d120.eligible}`);
ok('d120 에서 빠진 3건이 NO_FORWARD_RETURN 으로 기록된다',
   pop.byHorizon.d120.excludedByReason[EXCLUSION.NO_FORWARD_RETURN] === 3,
   JSON.stringify(pop.byHorizon.d120.excludedByReason));
ok('★ d120 이 없다고 그 스냅샷을 d20 에서까지 빼지 않는다',
   pop.byHorizon.d20.eligible > pop.byHorizon.d120.eligible);
ok('icSampleCount 가 horizon 별 실제 IC 표본이다',
   r.icSampleCount.d20 === 8 && r.icSampleCount.d120 === 5,
   JSON.stringify(r.icSampleCount));
ok('sampleCount 는 기본 표본(8)이고 IC 표본과 이름을 섞지 않는다',
   r.sampleCount === 8 && r.sampleCount !== r.icSampleCount.d120);

// ── 4. 표본 부족은 horizon 단위 판정이다 ──────────────────────────
console.log('\n[4] 표본 부족 — horizon 단위');

const many = [
  ...Array.from({ length: 40 }, (_, i) => snap(i, { fr: { d20: (i % 7) - 3 } })),   // d20 만 40건
];
const r2 = runBacktest(many, C, { policies: P });
const thinVerdict = r2.verdicts.find((v) => v.startsWith('표본 부족'));
ok('d20 40건은 충분, d60·d120 0건은 부족으로 갈라 판정한다',
   !!thinVerdict && thinVerdict.includes('d60 0건') && thinVerdict.includes('d120 0건')
   && !thinVerdict.includes('d20'), thinVerdict || '(판정 없음)');
ok(`MIN_SAMPLE 이 ${MIN_SAMPLE} 로 노출된다`, MIN_SAMPLE === 30);
ok('제외가 있으면 모집단 구성을 판정에 남긴다',
   r.verdicts.some((v) => v.includes('후보 10건 중 8건이 표본')),
   JSON.stringify(r.verdicts.filter((v) => v.includes('후보'))));

// ── 5. 모집단은 엔진 선택과 무관하다 ──────────────────────────────
console.log('\n[5] V1 / V2 — 같은 표본을 낸다');

const v1 = runBacktest(mixed, C, {});                 // policies 없음 → V1
const v2 = runBacktest(mixed, C, { policies: P });    // → V2
ok('★ V1 과 V2 의 population.eligible 이 같다 (엔진이 모집단을 끌고 가지 않는다)',
   v1.population.eligible === v2.population.eligible,
   `V1=${v1.population.eligible} V2=${v2.population.eligible}`);
ok('제외 사유 분포도 같다',
   JSON.stringify(v1.population.excludedByReason) === JSON.stringify(v2.population.excludedByReason),
   `${JSON.stringify(v1.population.excludedByReason)} vs ${JSON.stringify(v2.population.excludedByReason)}`);
ok('horizon 별 표본도 같다',
   JSON.stringify(v1.icSampleCount) === JSON.stringify(v2.icSampleCount));

// 유보 종목이 IC 에 섞이던 경로가 실제로 막혔는가
const withThin = runBacktest([...Array.from({ length: 4 }, (_, i) => snap(i)),
                              snap(99, { thin: true })], C, { policies: P });
ok('★ 커버리지 미달 종목이 IC 표본에 안 들어간다 (예전엔 들어갔다)',
   withThin.icSampleCount.d20 === 4, String(withThin.icSampleCount.d20));
ok('그 종목이 등급 버킷에도 없다 (두 곳의 분모가 일치한다)',
   Object.values(withThin.byGrade).reduce((a, g) => a + g.count, 0) === 4,
   JSON.stringify(Object.fromEntries(
     Object.entries(withThin.byGrade).map(([k, v]) => [k, v.count]))));

// ── 6. 못 재는 축을 0으로 적지 않는다 ─────────────────────────────
console.log('\n[6] 미측정 — 0으로 채우지 않는다 (교훈57)');

ok('unmeasuredReasons 에 폐지 여부와 PIT 미측정이 선언된다',
   UNMEASURED_REASONS.includes('DELISTED_STATUS_UNMEASURED')
   && UNMEASURED_REASONS.includes('PIT_STATUS_UNMEASURED'),
   JSON.stringify(UNMEASURED_REASONS));
ok('★ DELISTED 를 excludedByReason 에 0으로 적지 않는다 ("폐지 종목이 없다"로 읽힌다)',
   !Object.keys(pop.excludedByReason).some((k) => k.startsWith('DELISTED')),
   JSON.stringify(pop.excludedByReason));
ok('PIT 를 몇 건 잴 수 있었는지는 남긴다',
   pop.pitCheckedCount === 0 && pop.pitUnmeasuredCount === 10,
   `checked=${pop.pitCheckedCount} unmeasured=${pop.pitUnmeasuredCount}`);
const rc = runBacktest([snap(1, { cutoff: '2024-03-01' }), snap(2)], C, { policies: P });
ok('dataCutoff 가 있는 것만 checked 로 센다',
   rc.population.pitCheckedCount === 1 && rc.population.pitUnmeasuredCount === 1,
   `checked=${rc.population.pitCheckedCount} unmeasured=${rc.population.pitUnmeasuredCount}`);

// ── 7. 기존 소비자 스키마 보존 ────────────────────────────────────
console.log('\n[7] 스키마 보존 — scripts/backtest-report.js 가 읽는 모양');

for (const k of ['sampleCount', 'transactionCostPct', 'ic', 'byGrade', 'gradeMonotonic',
                 'regimeAnalysis', 'verdicts']) {
  ok(`result.${k} 가 그대로 있다`, k in r);
}
ok('ic[h] 는 숫자 또는 null 이다 (객체로 바꾸지 않았다)',
   Object.values(r.ic).every((v) => v === null || typeof v === 'number'),
   JSON.stringify(r.ic));

console.log(`\n${'='.repeat(54)}`);
console.log(`통과 ${pass} · 실패 ${fail}`);
process.exit(fail === 0 ? 0 : 1);
