#!/usr/bin/env node
'use strict';
const { score } = require('../lib/scoringEngine');
const { validate } = require('../lib/validator');
const { loadPolicies } = require('../lib/loadPolicies');

let pass = 0, fail = 0;
const chk = (c, l) => { console.log(`${c ? '✅' : '❌'} ${l}`); c ? pass++ : fail++; };

const P = loadPolicies('KR');
const C = P.criteria;

// ① 정상 종목 — state 없음
const base = { ticker: '005930', name: '삼성전자',
  fundamental: { roe: 14.2, debtRatio: 45, currentRatio: 250, operatingMarginTrend: 3, revenueGrowth: 8, roeHistory5y: [9, 11, 12, 14, 14.2], buybackOrDividendHistory: true },
  valuation: { per: 12, pbr: 1.2, perRelative: 0.8, epsGrowthRate: 15 },
  technical: { rsi: 55, macdSignal: 'bullish', maCross: 'golden', volumeRatio: 1.2 },
  supplyDemand: { foreignTrend5d: 'netBuy', institutionTrend5d: 'neutral', largeShareholderChangePct: 0.5, buybackOrRetirementAnnounced: true } };

const a = score(base, C, P);
chk(a.result.finalScore !== null && a.result.finalScore === a.result.rawScore, '① state 없음 → 감점 0, finalScore == rawScore');
chk(a.result.tradeAllowed === true && a.result.tradingState === 'NORMAL', '① tradingState 기본값 NORMAL');
chk(a.meta.policies.riskPenalty === 'RP-1.2' && a.meta.policies.criteria === C.version, '① meta.policies 스탬프');
chk(a.meta.policies.flagCodes === 'FC-1.1', '① flagCodes 버전 스탬프');
chk(Object.isFrozen(a.result) && Object.isFrozen(a.meta), '① ScoreResult immutable');
chk(validate(a, P, { mode: 'strict' }).length === 0, '① strict 검증 위반 0');

// ② 감점 누적 + 거래정지 — 점수와 매매가능여부는 다른 축이다
const b = score({ ...base, state: { riskStates: ['MEZZANINE_ACTIVE', 'RIGHTS_OFFERING_ACTIVE'], listingStatus: 'NORMAL', tradingState: 'HALTED' } }, C, P);
chk(b.result.riskPenalty === -18, '② stackable 누적 -8 + -10 = -18');
chk(b.result.finalScore === Math.round((b.result.rawScore - 18) * 10) / 10, '② finalScore = rawScore + riskPenalty');
chk(b.result.tradeAllowed === false && b.result.finalScore > 0, '② 거래정지여도 점수는 남는다(감점 아님)');
chk(b.result.flags.includes('TRADE_BLOCKED') && b.result.flags.includes('HIGH_RISK'), '② flags 생성');

// ③ exclusiveGroup — 관리종목(-25)과 투자주의환기(-15)는 큰 쪽 하나만
const c = score({ ...base, state: { riskStates: ['INVESTMENT_WARNING'], listingStatus: 'MANAGED', tradingState: 'NORMAL' } }, C, P);
chk(c.result.adjustments.length === 1 && c.result.riskPenalty === -25, '③ exclusiveGroup 중복 감점 없음');

// ④ 축 결측 → renormalize. 결측에 0점을 주지 않는다.
const d = score({ ticker: 'X', fundamental: base.fundamental }, C, P);
chk(d.result.components.technical === null && d.result.rawScore !== null, '④ 결측 축 null 유지 + 나머지로 재정규화');
chk(d.result.flags.includes('MISSING_DATA') && d.result.flags.includes('PARTIAL_CALCULATION'), '④ 결측 flags');
chk(d.result.confidence.value !== null && d.result.confidence.freshness === null, '④ ignoreNull — freshness 결측이 confidence를 끌어내리지 않음');

console.log(`\n엔진 V2: ${pass} passed, ${fail} failed`);

// ============================================================
// P9 확장 — 경계값 / INV-004 tolerance 경계 / strict-lenient 분기 /
//           정책 최악조합(-43) / 동결 위반 시 throw
// ============================================================

// ⑤ rawScore 하한 clamp — 전 지표 최저값 + 정책 최악조합(-43)이 rawScore를
//    한참 밑돈다. finalScore가 음수로 새지 않고 0에서 멈추는지 확인한다.
// maSignal 최고/최저는 criteria에서 뽑는다 — v2.3에서 점수 방향이 반전됐고,
// 이 두 테스트가 재는 것은 신호 이름이 아니라 rawScore clamp 경계다.
const MA_SIGNALS = C.technical.indicators.movingAverageCross.signals;
const MA_BEST = Object.keys(MA_SIGNALS).reduce((a, b) => (MA_SIGNALS[b] > MA_SIGNALS[a] ? b : a));
const MA_WORST = Object.keys(MA_SIGNALS).reduce((a, b) => (MA_SIGNALS[b] < MA_SIGNALS[a] ? b : a));

const worst = {
  ticker: 'WORST', name: '최악케이스',
  fundamental: { roe: 0, roeHistory5y: [0, 0, 0, 0, 0], debtRatio: 300, currentRatio: 50,
                 operatingMarginTrend: -1, revenueGrowthYoY: -10, buybackOrDividendHistory: false },
  valuation: { perRelative: 3, pbr: 5, per: 10, epsGrowthRate: -5, marginOfSafety: -1 },
  technical: { maSignal: MA_WORST, rsi: 100, macdSignal: 'bearishCross', volumeConfirmed: false },
  supplyDemand: { foreignTrend5d: 'consistentSell', institutionTrend5d: 'consistentSell',
                  largeShareholderChangePct: -5, buybackOrRetirementAnnounced: false },
  state: { riskStates: ['MEZZANINE_ACTIVE', 'RIGHTS_OFFERING_ACTIVE', 'INVESTMENT_WARNING'],
           listingStatus: 'MANAGED', tradingState: 'HALTED' },
};
const e5 = score(worst, C, P);
chk(e5.result.rawScore !== null && e5.result.rawScore < 10, `⑤ 최저 입력 → rawScore ${e5.result.rawScore} (0에 근접)`);
chk(e5.result.riskPenalty === -43, `⑤ 정책 최악조합 riskPenalty ${e5.result.riskPenalty} === -43`);
chk(e5.result.finalScore === 0, `⑤ rawScore+riskPenalty < 0이어도 finalScore 0에서 clamp (음수 미유출)`);
chk(validate(e5, P, { mode: 'lenient' }).length === 0, '⑤ 하한 clamp 결과도 INV 위반 없음 (SC001 안 던짐)');

// ⑥ rawScore 상한부 — 전 지표 최고값(RSI 구조상 정확히 100은 불가, 최댓값 근접)
//    으로 rawScore가 100을 넘거나 SC001을 던지지 않는지, 무위험이면 finalScore==rawScore인지 확인.
const best = {
  ticker: 'BEST', name: '최고케이스',
  fundamental: { roe: 15, roeHistory5y: [12, 13, 14, 15, 15], debtRatio: 50, currentRatio: 200,
                 operatingMarginTrend: 0.5, revenueGrowthYoY: 15, buybackOrDividendHistory: true },
  valuation: { perRelative: 0.7, pbr: 0.8, per: 5, epsGrowthRate: 50, marginOfSafety: 0.4 },
  technical: { maSignal: MA_BEST, rsi: 55, macdSignal: 'bullishCross', volumeConfirmed: true },
  supplyDemand: { foreignTrend5d: 'consistentBuy', institutionTrend5d: 'consistentBuy',
                  largeShareholderChangePct: 5, buybackOrRetirementAnnounced: true },
};
const e6 = score(best, C, P);
chk(e6.result.rawScore !== null && e6.result.rawScore <= 100 && e6.result.rawScore > 95, `⑥ 최고 입력 → rawScore ${e6.result.rawScore} (상한 근접, 100 미초과)`);
chk(e6.result.riskPenalty === 0 && e6.result.finalScore === e6.result.rawScore, '⑥ 위험상태 없음 → finalScore === rawScore');
chk(validate(e6, P, { mode: 'strict' }).length === 0, '⑥ strict 모드에서도 위반 없음');

// ⑦ 정책 조합 최악 케이스 — exclusiveGroup(R102 vs R107)은 더 큰 감점(R102 -25)만 채택되고
//    stackable(R103 -8, R105 -10)은 누적되어 -43이 나오는지 (§7.3 문서 수치와 대조)
chk(e5.result.adjustments.length === 3, '⑦ exclusiveGroup 충돌 시 R107 제외 3건만 채택(R102·R103·R105)');
chk(!e5.result.adjustments.some((a) => a.code === 'R107'), '⑦ R107은 R102보다 감점이 작아 exclusiveGroup에서 탈락');
chk(e5.result.adjustments.reduce((s, a) => s + a.penalty, 0) === -43, '⑦ 최악조합 합산 -43 (§7.3 문서 수치 일치)');

// ⑧+⑨ INV-004 tolerance 경계 + strict/lenient 모드 분기
//     validate()를 score() 없이 직접 호출 — Σcomponents와 rawScore의 차이(diff)만 통제한다.
const conf100 = { value: 100, coverage: 100, freshness: null, quality: null }; // INV-005~007 항상 통과하도록 고정
const mkSyn = (diff) => ({
  ticker: 'SYN', rawScore: 70, riskPenalty: 0, finalScore: 70,
  components: { fundamental: 70 + diff, valuation: 0, technical: 0, supplyDemand: 0 },
  confidence: conf100,
});
chk(validate(mkSyn(0.4), P, { mode: 'lenient' }).length === 0, '⑧ lenient tolerance(0.5) 이내(0.4) → 통과');
{
  const v = validate(mkSyn(0.6), P, { mode: 'lenient' });
  chk(v.length === 1 && v[0].code === 'INV-004', '⑧ lenient tolerance(0.5) 초과(0.6) → 위반 반환(throw 아님, warning)');
}
chk(validate(mkSyn(0.005), P, { mode: 'strict' }).length === 0, '⑨ strict tolerance(0.01) 이내(0.005) → 통과');
{
  let threw = false;
  try { validate(mkSyn(0.02), P, { mode: 'strict' }); } catch (e) { threw = e.errorCode === 'SC002'; }
  chk(threw, '⑨ strict 모드는 severity=warning인 INV-004도 즉시 throw (모드가 severity를 압도)');
}

// ⑩ 동결(freeze) 위반 시 throw — §16 교훈18 회귀 방지: production에서 봉투만 얼리던 구버전 버그 재발 확인
{
  let t1 = false;
  try { a.result.finalScore = 999; } catch (err) { t1 = true; }
  chk(t1 && a.result.finalScore !== 999, '⑩ dev: 최상위 result 프로퍼티 변경 → throw + 원본 보존');

  let t2 = false;
  try { a.result.components.fundamental = -1; } catch (err) { t2 = true; }
  chk(t2, '⑩ dev: 중첩 객체(components)까지 deep freeze로 변경 차단');

  const prevEnv = process.env.NODE_ENV;
  process.env.NODE_ENV = 'production';
  const prod = score(base, C, P);
  process.env.NODE_ENV = prevEnv;

  let t3 = false;
  try { prod.result.finalScore = 999; } catch (err) { t3 = true; }
  chk(t3 && prod.result.finalScore !== 999, '⑩ production: 봉투+meta+result 3개는 여전히 frozen (§9.4 확정안 준수)');
}

console.log(`\n엔진 V2 (P9 포함): ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
