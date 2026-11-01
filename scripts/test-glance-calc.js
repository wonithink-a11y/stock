// 종목 상세 '한눈에' 탭의 순수 계산 검사 — docs/index.html 의 `// <glance-calc>` ~ `// </glance-calc>` 구간을 그대로 떼어 돌린다.
// (대시보드는 빌드가 없어 함수를 import 할 수 없다. 구간을 고치면 이 검사가 같은 코드를 본다.)
//   1) 목표가 변경 집계: 합성 사례(중복·신규·유지·의견만·ptp 보완·창 경계) + 실제 invest-opinion.json 대조(삼성전자 상향1·하향2, 삼성생명 유지1)
//   2) 강점·약점: 문턱 15점 경계, 점수/중앙값 결측이면 판정 안 함, 실제 latest.json(삼성전자 재무 강점, 삼성생명 기술 강점)
//   3) 수급 기간 합: 5·20·60일 합 = 직접 합, 행 부족·결측이면 null(0 으로 안 채움)
//   4) 검증 비율 산식 전제: 지표별 기여 합 = 총점 — 해독 탭의 decodeCompute 를 실제 기준표·근거 파일로 돌려 전 종목 대조
//   5) 홈 시장 국면 막대 구간 경계 = config/marketRegime.json regimeGrades
// 실행: node scripts/test-glance-calc.js  (네트워크 불필요)
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'docs/index.html'), 'utf8');
const readJson = p => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));
let fails = 0, checks = 0;
const ok = (cond, msg) => { checks++; if (!cond) { fails++; console.log('  FAIL', msg); } };

function grab(re, what) { const m = html.match(re); if (!m) { console.log('FAIL 구간 못 찾음:', what); process.exit(1); } return m[0]; }
const calc = grab(/\/\/ <glance-calc>[\s\S]*?\/\/ <\/glance-calc>/, 'glance-calc');
const cats = grab(/const DECODE_CATS = \[[^\n]*\];/, 'DECODE_CATS');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(`${cats}\n${calc}\nthis.api = { glTargetRevisions, glStrengths, glFlowSums, GL_STRONG, GL_REV_DAYS, DECODE_CATS };`, ctx);
const { glTargetRevisions, glStrengths, glFlowSums, GL_STRONG, GL_REV_DAYS } = ctx.api;

// ---- 1) 목표가 변경 ----
{
  const R = (d, b, tp, ptp = null, t = 'X') => ({ d, t, b, tp, ptp });
  const rows = [
    R('20260901', 'A', 100), R('20261005', 'A', 120, 100),          // 상향(ptp)
    R('20261006', 'A', 120, 120), R('20261006', 'A', 120, 120),      // 유지 + 같은 날 같은 값 중복
    R('20260920', 'B', 200), R('20261010', 'B', 150, null),          // ptp 없음 → 기록으로 보완 → 하향
    R('20261012', 'C', 300),                                         // 신규(이전 없음)
    R('20261013', 'D', null), R('20261014', 'D', 0),                 // 의견만(목표가 없음) 2
    R('20260930', 'E', 50, 40),                                      // 창 밖(30일 전 = 10-01 미만)
    R('20261015', 'A', 999, 1, 'Y'),                                 // 다른 종목
  ];
  const v = glTargetRevisions(rows, 'X', '20261031');
  ok(GL_REV_DAYS === 30, 'GL_REV_DAYS 30');
  ok(v.from === '20261001', `창 시작 10-01 (got ${v.from})`);
  ok(v.up === 1 && v.down === 1 && v.same === 1 && v.fresh === 1, `상1·하1·유1·신1 (got ${v.up}/${v.down}/${v.same}/${v.fresh})`);
  ok(v.dup === 1, `중복 1 (got ${v.dup})`);
  ok(v.noTarget === 2, `의견만 2 (got ${v.noTarget})`);
  ok(v.filled === 1, `ptp 보완 1 (got ${v.filled})`);
  ok(v.brokers === 3, `증권사 3곳 (got ${v.brokers})`);
  ok(v.items[0].d === '20261012', '목록은 최근 것부터');
  const empty = glTargetRevisions(rows, 'NONE', '20261031');
  ok(empty.up + empty.down + empty.same + empty.fresh + empty.noTarget === 0, '없는 종목은 전부 0');
  ok(glTargetRevisions(null, 'X', '20261031').up === 0, 'rows 없음 → 0');

  // 실제 파일: ptp 가 같은 증권사 직전 목표가와 같은지(전제) + 두 사례
  const O = readJson('docs/data/invest-opinion.json');
  const by = {};
  for (const x of [...O.rows].sort((p, q) => p.d.localeCompare(q.d))) (by[x.t + '|' + x.b] = by[x.t + '|' + x.b] || []).push(x);
  let agree = 0, differ = 0;
  for (const l of Object.values(by)) for (let i = 1; i < l.length; i++) if (l[i].ptp != null && l[i - 1].tp != null) (l[i].ptp === l[i - 1].tp ? agree++ : differ++);
  ok(differ === 0, `ptp = 같은 증권사 직전 목표가 (일치 ${agree} · 불일치 ${differ})`);
  if (O.asOf === '20261031') {   // 데이터가 매일 바뀌므로 사례 대조는 이 기준일에서만(다른 날엔 전제 검사만 돈다)
    const s = glTargetRevisions(O.rows, '005930', O.asOf), l = glTargetRevisions(O.rows, '032830', O.asOf);
    ok(s.up === 1 && s.down === 2 && s.same === 0, `삼성전자 상1·하2 (got ${s.up}/${s.down}/${s.same})`);
    ok(l.same === 1 && l.up === 0 && l.down === 0, `삼성생명 유지1 (got ${l.up}/${l.down}/${l.same})`);
  } else console.log(`  (사례 대조 생략: invest-opinion asOf ${O.asOf} ≠ 20261031)`);
}

// ---- 2) 강점·약점 ----
{
  const mk = (t, f, v, te, s, market = 'KR') => ({ ticker: t, market, breakdown: { fundamental: { score: f }, valuation: { score: v }, technical: { score: te }, supplyDemand: { score: s } } });
  const pool = [mk('a', 50, 50, 50, 50), mk('b', 50, 50, 50, 50), mk('c', 50, 50, 50, null)];
  const me = mk('me', 50 + GL_STRONG, 50 + GL_STRONG - 0.1, 50 - GL_STRONG, null);
  pool.push(me);
  const w = glStrengths(me, pool);
  ok(GL_STRONG === 15, 'GL_STRONG 15');
  ok(w.strong.map(x => x.k).join() === 'fundamental', `+15 은 강점, +14.9 는 생략 (got ${w.strong.map(x => x.k)})`);
  ok(w.weak.map(x => x.k).join() === 'technical', `−15 는 약점 (got ${w.weak.map(x => x.k)})`);
  ok(!w.strong.concat(w.weak).some(x => x.k === 'supplyDemand'), '점수 결측 범주는 판정 안 함');
  ok(glStrengths(mk('u', 90, 90, 90, 90, 'US'), pool).strong.length === 0, '같은 시장 중앙값이 없으면 판정 안 함');
  ok(glStrengths(null, pool).strong.length === 0, 'r 없음 → 빈 결과');
  const L = readJson('docs/data/latest.json').results;
  const sam = L.find(x => x.ticker === '005930'), life = L.find(x => x.ticker === '032830');
  if (sam && life && sam.lastDate === '20261030') {
    const a = glStrengths(sam, L), b = glStrengths(life, L);
    ok(a.strong.map(x => x.k).join() === 'fundamental' && !a.weak.length, `삼성전자 강점 재무만 (got ${a.strong.map(x => x.k)} / ${a.weak.map(x => x.k)})`);
    ok(b.strong.map(x => x.k).join() === 'technical' && !b.weak.length, `삼성생명 강점 기술만 (got ${b.strong.map(x => x.k)} / ${b.weak.map(x => x.k)})`);
  } else console.log('  (강점 사례 대조 생략: latest.json 기준일이 10-30 이 아님)');
}

// ---- 3) 수급 기간 합 ----
{
  const rows = Array.from({ length: 60 }, (_, i) => ({ date: `2026-08-${String(i).padStart(2, '0')}`, foreign: i + 1, institution: -(i + 1), individual: 0 }));
  const f = glFlowSums(rows);
  const sum = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i).reduce((p, q) => p + q, 0);
  ok(f.by.foreign[5] === sum(56, 60) && f.by.foreign[20] === sum(41, 60) && f.by.foreign[60] === sum(1, 60), '외국인 5·20·60일 합 = 마지막 n행 합');
  ok(f.by.institution[5] === -sum(56, 60), '기관 음수 합');
  ok(f.by.individual[20] === 0, '진짜 0 은 0');
  ok(f.asOf === rows[59].date, '기준일 = 마지막 행 날짜');
  const short = glFlowSums(rows.slice(0, 10));
  ok(short.by.foreign[5] != null && short.by.foreign[20] === null && short.by.foreign[60] === null, '행이 창보다 적으면 null');
  const hole = rows.map((r, i) => (i === 57 ? { ...r, foreign: null } : r));
  const h = glFlowSums(hole);
  ok(h.by.foreign[5] === null && h.by.institution[5] === -sum(56, 60), '창 안 결측이면 그 줄만 null(0 으로 안 채움)');
  ok(glFlowSums([]).asOf === null && glFlowSums([]).by.foreign[5] === null, '빈 자료 → null');
  const F = readJson('docs/data/stock-flows.json').byTicker['005930'];
  if (F && F.length >= 60) {
    const g = glFlowSums(F), direct = F.slice(-20).reduce((p, q) => p + q.foreign, 0);
    ok(g.by.foreign[20] === direct, '실제 삼성전자 외국인 20일 합 = 직접 합');
  }
}

// ---- 4) 검증 비율 산식 전제: Σ 지표 기여 = 총점 ----
{
  const fnSrc = grab(/function decodeCompute\(r\) \{[\s\S]*?\n\}\n/, 'decodeCompute');
  const reg = readJson('config/policies/registry.json');
  const criteria = {};
  for (const m of ['KR', 'US']) { const e = reg.criteria && reg.criteria[m]; if (e) criteria[m] = { version: e.version, data: readJson(e.path) }; }
  const evidence = readJson('docs/factor-evidence.json');
  const L = readJson('docs/data/latest.json').results;
  const c2 = { state: { decodeRefs: { evidence, criteria }, latest: { results: L }, sectorStrength: null, themeStrength: null, flows: null, events: null }, ensureFlows() {}, Date };
  vm.createContext(c2);
  vm.runInContext(`${cats}\n${fnSrc}\nthis.dc = decodeCompute;`, c2);
  let n = 0, worst = 0, badShare = 0;
  for (const r of L) {
    if (r.totalScore == null) continue;
    const c = c2.dc(r); n++;
    worst = Math.max(worst, Math.abs(c.total - r.totalScore));
    if (c.validatedShare != null && (c.validatedShare < -1e-9 || c.validatedShare + (c.rejectedShare || 0) > 1 + 1e-9)) badShare++;
  }
  ok(n > 0 && worst <= 0.1, `지표 기여 합 = 총점 (${n}종목, 최대 차이 ${worst.toFixed(3)} ≤ 0.1 — 반올림)`);
  ok(badShare === 0, `검증+기각 비율 0~1 (위반 ${badShare})`);
  const basisOut = L.filter(r => r.basis && !r.basis.includes('supplyDemand')).length;
  console.log(`  참고: 총점 basis 에 수급이 없는 종목 ${basisOut}/${L.length} — 화면에 '총점 미반영' 표시`);
}

// ---- 5) 홈 시장 국면 막대의 구간 경계 = config/marketRegime.json regimeGrades.min (그림이 등급과 어긋나지 않게) ----
{
  const src = grab(/const REGIME_BANDS = \[[^\n]*\];/, 'REGIME_BANDS');
  const c3 = {}; vm.createContext(c3); vm.runInContext(`${src}\nthis.b = REGIME_BANDS;`, c3);
  const g = readJson('config/marketRegime.json').regimeGrades;
  const want = Object.entries(g).map(([k, v]) => [k, v.min]).sort((x, y) => x[1] - y[1]);
  const got = c3.b.map(x => [x.k, x.min]);
  ok(JSON.stringify(got) === JSON.stringify(want), `REGIME_BANDS = regimeGrades (got ${JSON.stringify(got)} want ${JSON.stringify(want)})`);
}

console.log(`${fails ? 'FAIL' : 'OK'} test-glance-calc: ${checks - fails}/${checks}`);
process.exit(fails ? 1 : 0);
