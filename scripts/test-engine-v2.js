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
chk(a.meta.policies.riskPenalty === 'RP-1.2' && a.meta.policies.criteria === '2.2', '① meta.policies 스탬프');
chk(Object.isFrozen(a.result), '① ScoreResult immutable');
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
process.exit(fail === 0 ? 0 : 1);
