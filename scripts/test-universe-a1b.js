#!/usr/bin/env node
/**
 * A1b 회귀 테스트 — 폐지 이력 유니버스
 *   node scripts/test-universe-a1b.js
 *
 * 인수 조건은 build-universe-a1b.py가 자기 산출물에 대해 검사한다. 여기서 보는 것은
 * 그것과 독립적인 두 가지다.
 *   1) 알려진 폐지사가 실제로 후보에 들어왔는가 — 차집합이 통째로 망가져도 개수 임계는
 *      통과할 수 있다. 개수는 분포를 보지 못한다.
 *   2) 산출물 스키마가 계약대로인가 — exitAt/exitReason이 추정으로 채워지는 순간
 *      백테스트에 look-ahead가 들어간다.
 *
 * 알려진 폐지 목록을 정책 파일이 아니라 여기 인라인으로 두는 이유: 정책은 시스템 동작을
 * 정의하고, 회귀 테스트는 구현이 계속 그 동작을 내는지 검증한다. 섞으면 픽스처를 늘렸을 때
 * 정책과 어긋난다. 저장소에 tests/ 디렉터리가 없고 DC-1.3 골든셋 57건도
 * scripts/test-classifier.js 안에 인라인이라, 그 관례를 따른다.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const OUT = 'data/backfill/universe/a1b/delisted.jsonl';
const A1A_CURRENT = 'data/backfill/universe/a1a/current.jsonl';
const A1A_EXCLUDED = 'data/backfill/universe/a1a/excluded.jsonl';

/**
 * 알려진 폐지 5건. 이름으로 찾되 매칭된 corp_code를 로그에 출력한다 —
 * 다음 버전에서 corp_code 하드코딩으로 승격한다. 이름 표기는 흔들리지만 corp_code는 안 흔들린다.
 *
 * 부분 일치가 아니라 완전 일치로 찾는다. '데코'를 includes로 찾으면 데코앤에프·한솔홈데코가
 * 같이 걸려 "찾았다"가 거짓이 된다.
 */
const KNOWN_DELISTED = ['한빛네트', '엔플렉스', '동서정보기술', '데코', '희훈디앤지'];

const FIELDS = ['corp', 'ticker', 'corpName', 'exitReason', 'exitAt', 'dartModifyDate', 'source'];
const CORP_PATTERN = /^[0-9]{8}$/;
const TICKER_PATTERN = /^[0-9A-Z]{6}$/;

let pass = 0, fail = 0;
function ok(cond, msg) {
  if (cond) { pass++; } else { fail++; console.log(`[FAIL] ${msg}`); }
}

function readJsonl(rel) {
  const abs = path.join(ROOT, rel);
  if (!fs.existsSync(abs)) {
    console.error(`${rel} 없음 — 해당 단계를 먼저 실행하라 (python scripts/build-universe-a1b.py)`);
    process.exit(1);
  }
  return fs.readFileSync(abs, 'utf8').split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
}

const rows = readJsonl(OUT);
console.log(`A1b 후보 ${rows.length}건`);

/* ── 1. 알려진 폐지 5건 ─────────────────────────────────────── */
for (const name of KNOWN_DELISTED) {
  const hits = rows.filter((r) => r.corpName === name);
  // 0건 = 차집합이 폐지사를 삼켰다(생존편향 회귀).
  // 2건 이상 = 동명이인이므로 이 이름은 더 이상 식별자가 아니다 → corp_code 하드코딩으로 올린다.
  ok(hits.length === 1,
    `알려진 폐지 "${name}" 매칭 ${hits.length}건 (1이어야 함)` +
    (hits.length ? ` — ${hits.map((h) => `${h.corp}/${h.ticker}`).join(' ')}` : ''));
  if (hits.length) {
    const h = hits[0];
    console.log(`   ${name.padEnd(8)} corp=${h.corp} ticker=${h.ticker} dartModifyDate=${h.dartModifyDate}`);
  }
}

/* ── 2. 산출물 스키마 계약 ──────────────────────────────────── */
const badKeys = rows.filter((r) => {
  const k = Object.keys(r);
  return k.length !== FIELDS.length || k.some((x, i) => x !== FIELDS[i]);
});
ok(badKeys.length === 0,
  `필드 구성·순서가 계약과 다른 레코드 ${badKeys.length}건 (${FIELDS.join(',')})`);

ok(rows.every((r) => r.exitAt === null),
  `exitAt 전건 null — dartModifyDate를 폐지일로 승격하면 백테스트에 look-ahead가 들어간다 ` +
  `(위반 ${rows.filter((r) => r.exitAt !== null).length}건)`);
ok(rows.every((r) => r.exitReason === 'UNKNOWN'),
  `exitReason 전건 UNKNOWN (위반 ${rows.filter((r) => r.exitReason !== 'UNKNOWN').length}건)`);
ok(rows.every((r) => r.source === 'DART_CORPCODE_DIFF'),
  `source 전건 DART_CORPCODE_DIFF (위반 ${rows.filter((r) => r.source !== 'DART_CORPCODE_DIFF').length}건)`);
ok(rows.every((r) => CORP_PATTERN.test(r.corp)),
  `corp 계약 ^[0-9]{8}$ 위반 ${rows.filter((r) => !CORP_PATTERN.test(r.corp)).length}건`);
ok(rows.every((r) => TICKER_PATTERN.test(r.ticker)),
  `ticker 계약 ^[0-9A-Z]{6}$ 위반 ${rows.filter((r) => !TICKER_PATTERN.test(r.ticker)).length}건`);

const corps = rows.map((r) => r.corp);
ok(new Set(corps).size === corps.length,
  `corp 유일성 — 중복 ${corps.length - new Set(corps).size}건`);

/* ── 3. A1a와의 교집합 (빌드 스크립트와 독립적으로 다시 잰다) ─ */
const a1a = [...readJsonl(A1A_CURRENT), ...readJsonl(A1A_EXCLUDED)];
const a1aCorp = new Set(a1a.map((r) => r.corp).filter(Boolean));
const a1aTicker = new Set(a1a.map((r) => r.ticker));
const icorp = rows.filter((r) => a1aCorp.has(r.corp));
const iticker = rows.filter((r) => a1aTicker.has(r.ticker));
ok(icorp.length === 0, `A1a ∩ A1b (corp) ${icorp.length}건 — ${icorp.slice(0, 5).map((r) => r.corp)}`);
ok(iticker.length === 0, `A1a ∩ A1b (ticker) ${iticker.length}건 — ${iticker.slice(0, 5).map((r) => r.ticker)}`);

/* ── 4. ticker 재사용은 통과 대상이 아니라 관측 대상이다 ────── */
const byTicker = new Map();
for (const r of rows) {
  if (!byTicker.has(r.ticker)) byTicker.set(r.ticker, []);
  byTicker.get(r.ticker).push(r);
}
const reuse = [...byTicker.entries()].filter(([, v]) => v.length > 1);
console.log(`   ticker 재사용 후보 ${reuse.length}건 (실패 조건 아님 — 재사용은 사실이다)`);

console.log(fail ? `\n❌ A1b 회귀 테스트 실패 ${fail}건 / 통과 ${pass}건`
                 : `\n✅ A1b 회귀 테스트 전체 통과 (${pass}건)`);
process.exit(fail ? 1 : 0);
