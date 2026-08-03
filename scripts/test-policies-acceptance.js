#!/usr/bin/env node
/**
 * STEP4 정책 파일 Acceptance 테스트 — 파일 **단독** 계약 검증
 *   node scripts/test-policies-acceptance.js
 *
 * test-policies.js(교차 정합성)보다 먼저 돌린다. 파일 자체가 깨진 상태에서 교차 검사를 하면
 * 원인이 어느 파일인지 로그로 구분되지 않는다.
 * 첫 실패에서 멈추지 않고 전부 모아 보고한다 — 정책 파일은 한 번에 여러 개를 고치기 때문이다.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const load = (p) => JSON.parse(fs.readFileSync(path.join(ROOT, p), 'utf8'));

const results = [];
function chk(cond, label) { results.push({ ok: !!cond, label }); }
// 파일 하나가 없거나 JSON이 깨져도 나머지 검사 결과는 보여야 한다.
// 정책 파일은 한 번에 여러 개를 고치므로, 첫 파일에서 스택트레이스로 죽으면 나머지를 못 본다.
function section(label, fn) {
  try { fn(); } catch (err) { chk(false, `${label}: 로드 실패 — ${err.code === 'ENOENT' ? '파일 없음' : err.message}`); }
}
function uniq(arr, label) {
  const seen = new Set(), dup = [];
  arr.forEach((x) => (seen.has(x) ? dup.push(x) : seen.add(x)));
  chk(dup.length === 0, `${label} 중복 없음${dup.length ? ` (중복: ${dup.join(',')})` : ''}`);
}
const isVersion = (v) => typeof v === 'string' && v.length > 0;

// ── registry.json ───────────────────────────────────────────────
section('registry', () => {
  const r = load('config/policies/registry.json');
  chk(isVersion(r.version), 'registry: version 존재');
  chk(r.policies && Object.keys(r.policies).length > 0, 'registry: policies 목록 존재');
  const paths = Object.values(r.policies || {});
  uniq(paths, 'registry.policies path');
  chk(paths.every((p) => fs.existsSync(path.join(ROOT, p))), 'registry: 모든 policy path 실재');
  const cr = Object.values(r.criteria || {});
  chk(cr.length > 0, 'registry: criteria 항목 존재');
  chk(cr.every((c) => c.path && isVersion(c.version)), 'registry: criteria 각 항목에 path·version');
  chk(cr.every((c) => fs.existsSync(path.join(ROOT, c.path))), 'registry: 모든 criteria path 실재');
  uniq(cr.map((c) => c.path), 'registry.criteria path');
});
// ── criteria snapshot 계약 ─────────────────────────────────────
section('criteria snapshot', () => {
  const r = load('config/policies/registry.json');
  for (const [market, c] of Object.entries(r.criteria || {})) {
    const id = `criteria[${market}]`;
    chk(String(c.path).startsWith('config/criteria/'), `${id}: 스냅샷 디렉터리 경로`);
    chk(path.basename(c.path) === `${market}-${c.version}.json`, `${id}: 파일명 == {market}-{version}.json`);
    chk(!/-(KR|US)$/i.test(c.version), `${id}: version에 시장 접미사 없음`);
    const abs = path.join(ROOT, c.path);
    chk(fs.existsSync(abs), `${id}: 스냅샷 파일 실재`);
    if (!fs.existsSync(abs)) continue;
    const f = load(c.path);
    chk(f.version === c.version, `${id}: 파일 version == registry version`);
    chk(Object.keys(f.categoryWeights || {}).length > 0, `${id}: categoryWeights 존재 (AX002)`);
  }
  // 잔존 alias 금지 — 남아 있으면 미이관 리더가 조용히 옛 파일을 계속 읽는다
  chk(!fs.existsSync(path.join(ROOT, 'config/criteria.json')), 'config/criteria.json 잔존 alias 없음');
  chk(!fs.existsSync(path.join(ROOT, 'config/criteria-us.json')), 'config/criteria-us.json 잔존 alias 없음');
  // 구버전 스냅샷이 config/criteria/ 에 남아 있는 것은 정상이다 — orphan 검사는 넣지 않는다.
});
// ── riskPenalty.v1.json ─────────────────────────────────────────
section('riskPenalty', () => {
  const p = load('config/policies/riskPenalty.v1.json');
  const FIELDS = ['riskStates', 'listingStatus', 'tradingState'];
  chk(isVersion(p.version), 'riskPenalty: version 존재');
  chk(typeof p.provisional === 'boolean', 'riskPenalty: provisional boolean');
  chk(Array.isArray(p.rules) && p.rules.length > 0, 'riskPenalty: rules 배열 존재');
  uniq((p.rules || []).map((r) => r.code), 'riskPenalty.code');
  for (const r of p.rules || []) {
    const id = `riskPenalty[${r.code}]`;
    chk(typeof r.penalty === 'number' && r.penalty <= 0, `${id}: penalty <= 0`);
    chk(Number.isInteger(r.penalty), `${id}: penalty 정수`);
    chk(!(r.exclusiveGroup && r.stackable), `${id}: exclusiveGroup·stackable 동시 지정 아님`);
    if (r.enabled === false) {
      chk(typeof r.disabledReason === 'string' && r.disabledReason.length > 0, `${id}: disabledReason 존재`);
      continue;                                   // 비활성 규칙은 matchField/State를 요구하지 않는다
    }
    chk(FIELDS.includes(r.matchField), `${id}: matchField ∈ {${FIELDS.join(',')}}`);
    chk(typeof r.matchState === 'string' && r.matchState.length > 0, `${id}: matchState 문자열 존재`);
    chk(r.matchState !== 'NORMAL', `${id}: matchState가 NORMAL이 아님 (항상 발동 방지)`);
    chk(typeof r.category === 'string' && typeof r.reason === 'string', `${id}: category·reason 존재`);
  }
});

// ── confidence.v1.json ──────────────────────────────────────────
section('confidence', () => {
  const p = load('config/policies/confidence.v1.json');
  const w = p.weights || {};
  const vals = Object.values(w);
  chk(isVersion(p.version), 'confidence: version 존재');
  chk(vals.length > 0, 'confidence: weights 존재');
  chk(Math.abs(vals.reduce((a, b) => a + b, 0) - 1) < 1e-9, 'confidence: weights 합계 = 1');
  chk(vals.every((v) => typeof v === 'number' && v >= 0 && v <= 1), 'confidence: 각 weight 0~1');
  chk(p.ignoreNull === true, 'confidence: ignoreNull === true');
  const t = p.thresholds || {};
  chk(t.veryLowConfidence < t.lowConfidence, 'confidence: veryLow < low 임계값');
});

// ── validation.v1.json ──────────────────────────────────────────
section('validation', () => {
  const p = load('config/policies/validation.v1.json');
  chk(isVersion(p.version), 'validation: version 존재');
  chk(p.strictTolerance < p.lenientTolerance, 'validation: strict < lenient tolerance');
  chk(Array.isArray(p.rules) && p.rules.length > 0, 'validation: rules 배열 존재');
  uniq((p.rules || []).map((r) => r.code), 'validation.rule code');
  for (const r of p.rules || []) {
    chk((p.severities || []).includes(r.severity), `validation[${r.code}]: severity ∈ ${JSON.stringify(p.severities)}`);
    chk(typeof r.message === 'string' && r.message.length > 0, `validation[${r.code}]: message 존재`);
    chk(typeof r.errorCode === 'string' && r.errorCode.length > 0, `validation[${r.code}]: errorCode 존재`);
  }
});

// ── missingAxis.v1.json ─────────────────────────────────────────
section('missingAxis', () => {
  const p = load('config/policies/missingAxis.v1.json');
  chk(isVersion(p.version), 'missingAxis: version 존재');
  chk(['renormalize', 'zeroFill'].includes(p.mode), 'missingAxis: mode ∈ {renormalize,zeroFill}');
  // 축별 fallback은 두지 않는다. 축 확장은 §6 동결 대상이고, 축마다 다른 결측 처리는
  // 축 간 점수 비교 가능성을 깨뜨린다. 전역 mode 하나만 유지한다.
  chk(p.perAxis === undefined, 'missingAxis: 축별 예외 없음(전역 mode 단일)');
});

// ── trading.v1.json ─────────────────────────────────────────────
section('trading', () => {
  const p = load('config/policies/trading.v1.json');
  chk(isVersion(p.version), 'trading: version 존재');
  chk(Array.isArray(p.blockedStates) && p.blockedStates.length > 0, 'trading: blockedStates 존재');
  uniq(p.blockedStates || [], 'trading.blockedStates');
  chk((p.blockedStates || []).every((s) => typeof s === 'string' && s !== 'NORMAL'),
    'trading: blockedStates에 NORMAL 없음');
});

// ── flagCodes.json ──────────────────────────────────────────────
section('flagCodes', () => {
  const p = load('config/policies/flagCodes.json');
  chk(isVersion(p.version), 'flagCodes: version 존재');
  const groups = p.groups || {};
  const all = Object.values(groups).flat();
  chk(all.length > 0, 'flagCodes: 코드 존재');
  uniq(all.map((f) => f.code), 'flagCodes.code');
  chk(all.every((f) => typeof f.description === 'string' && f.description.length > 0),
    'flagCodes: 모든 코드에 description');
  chk(all.every((f) => /^[A-Z][A-Z0-9_]*$/.test(f.code)), 'flagCodes: 코드 표기 UPPER_SNAKE');
});
// ── lib 모듈 export 계약 (붙여넣기 잘림 탐지) ──────────────────
// CommonJS는 module.exports가 통째로 없어도 문법 오류가 아니라 {} 를 내보낸다.
// 웹 UI 붙여넣기 잘림은 항상 파일 끝에서 일어나므로, 소비자가 호출할 때까지 잠복한다.
section('lib exports', () => {
  const EXPECT = {
    'lib/loadCriteria.js':          ['loadCriteria'],
    'lib/loadPolicies.js':          ['loadPolicies'],
    'lib/errorCodes.js':            ['E', 'throwErr', 'EngineError'],
    'lib/validator.js':             ['validate', 'RULES'],
    'lib/scoringEngine.js':         ['score', 'scoreStock', 'computeRiskPenalty', 'computeConfidenceValue'],
    'lib/stateReducer.js':          [],
    'lib/stateExpirer.js':          [],
    'lib/stateStore.js':            [],
    'lib/eventClassifiers/dart.js': [],
    'lib/eventBuilders/dart.js':    [],
  };
  for (const [rel, keys] of Object.entries(EXPECT)) {
    let m = null;
    try { m = require(path.join(ROOT, rel)); }
    catch (err) { chk(false, `${rel}: require 실패 — ${err.message}`); continue; }
    chk(Object.keys(m).length > 0, `${rel}: export 존재(파일 잘림 아님)`);
    for (const k of keys) chk(typeof m[k] !== 'undefined', `${rel}: ${k} export`);
  }
});
// ── 보고 ────────────────────────────────────────────────────────
const failed = results.filter((r) => !r.ok);
failed.forEach((r) => console.log(`❌ ${r.label}`));
console.log(`\n정책 Acceptance: ${results.length - failed.length} passed, ${failed.length} failed`);
process.exit(failed.length === 0 ? 0 : 1);
