'use strict';
/**
 * 정책 일괄 로더 — 정책 provenance의 단일 산출점.
 *
 *   versions          → ScoreResult.meta.policies 원본 (score()가 실제로 읽는 정책만)
 *   analysisVersions  → 분석 단계(A6) 정책. 점수에 관여하지 않으므로 versions와 섞지 않는다
 *   hashes            → 파일 바이트 sha256. 버전을 안 올린 채 내용만 고친 경우를 잡는다
 *
 * 해시를 여기서 만드는 이유: 소비자(백필·analyze·backtest)가 각자 계산하면 정규화 규칙이
 * 갈라진다. 파일을 읽는 지점이 하나뿐이어야 해시도 하나다.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { loadCriteria } = require('./loadCriteria');

const ROOT = path.join(__dirname, '..');
const CACHE = new Map();

function deepFreeze(obj) {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    for (const v of Object.values(obj)) deepFreeze(v);
  }
  return obj;
}

/** 바이트를 그대로 해싱한다. 문자열로 변환해 해싱하면 개행·BOM·로케일이 끼어 플랫폼마다 갈린다. */
function hashBytes(buf) {
  return 'sha256:' + crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16);
}

function readPolicyFile(rel) {
  const buf = fs.readFileSync(path.join(ROOT, rel));
  return { json: JSON.parse(buf.toString('utf8')), hash: hashBytes(buf) };
}

function loadPolicies(market = 'KR') {
  if (CACHE.has(market)) return CACHE.get(market);

  const reg = readPolicyFile('config/policies/registry.json');
  const registry = reg.json;
  const hashes = { registry: reg.hash };

  // ── score()가 읽는 정책 ──
  const P = {};
  for (const [key, rel] of Object.entries(registry.policies)) {
    const f = readPolicyFile(rel);
    if (!f.json.version) throw new Error(`${key}에 version이 없다 — meta.policies 스탬프가 불가능하다`);
    P[key] = f.json;
    hashes[key] = f.hash;
  }

  // ── 분석 단계 정책 (A6). versions에 넣지 않는다 — meta.policies는 '점수를 만든 정책'만이다 ──
  const A = {};
  const analysisVersions = {};
  for (const [key, rel] of Object.entries(registry.analysisPolicies || {})) {
    const f = readPolicyFile(rel);
    if (!f.json.version) throw new Error(`${key}(analysis)에 version이 없다 — 재현성 스탬프가 불가능하다`);
    if (Object.prototype.hasOwnProperty.call(P, key)) {
      throw new Error(`${key}가 policies와 analysisPolicies에 중복 등록됐다 — 어느 쪽이 점수에 관여하는지 모호해진다`);
    }
    A[key] = f.json;
    analysisVersions[key] = f.json.version;
    hashes[key] = f.hash;
  }
  // ── 수집 단계 정책 (A1a·A2). versions에도 analysisVersions에도 넣지 않는다 ──
  const D = {};
  const dataVersions = {};

  for (const [key, rel] of Object.entries(registry.dataPolicies || {})) {
    const f = readPolicyFile(rel);

    if (!f.json.version) {
      throw new Error(`${key}(data)에 version이 없다 — 재현성 스탬프가 불가능하다`);
    }

    if (
      Object.prototype.hasOwnProperty.call(P, key) ||
      Object.prototype.hasOwnProperty.call(A, key)
    ) {
      throw new Error(
        `${key}가 둘 이상의 네임스페이스에 등록됐다 — 어느 층이 읽는 정책인지 모호해진다`
      );
    }

    D[key] = f.json;
    dataVersions[key] = f.json.version;
    hashes[key] = f.hash;
  }
  const cr = loadCriteria(market);
  hashes.criteria = hashBytes(fs.readFileSync(path.join(ROOT, cr.path)));

  // 과거 점수 재현의 유일한 근거. 여기 없는 정책은 엔진이 쓰지 않는다.
  const versions = { criteria: cr.version };
  for (const key of Object.keys(P)) versions[key] = P[key].version;

  const result = deepFreeze({
  market,
  registryVersion: registry.version,
  criteria: cr.criteria,
  criteriaPath: cr.path,

  ...P,

  analysis: A,
  data: D,

  versions,
  analysisVersions,
  dataVersions,

  hashes,
});
  CACHE.set(market, result);
  return result;
}

function _clearCache() { CACHE.clear(); }

module.exports = { loadPolicies, _clearCache };
