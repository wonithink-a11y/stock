'use strict';
const fs = require('fs');
const path = require('path');
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

function loadPolicies(market = 'KR') {
  if (CACHE.has(market)) return CACHE.get(market);

  const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'config/policies/registry.json'), 'utf8'));
  const P = {};
  for (const [key, rel] of Object.entries(registry.policies)) {
    P[key] = JSON.parse(fs.readFileSync(path.join(ROOT, rel), 'utf8'));
    if (!P[key].version) throw new Error(`${key}에 version이 없다 — meta.policies 스탬프가 불가능하다`);
  }
  const cr = loadCriteria(market);

  // 과거 점수 재현의 유일한 근거. 여기 없는 정책은 엔진이 쓰지 않는다.
  const versions = { criteria: cr.version };
  for (const key of Object.keys(P)) versions[key] = P[key].version;

  const result = deepFreeze({
    market,
    registryVersion: registry.version,
    criteria: cr.criteria,
    criteriaPath: cr.path,
    ...P,
    versions,
  });
  CACHE.set(market, result);
  return result;
}

function _clearCache() { CACHE.clear(); }

module.exports = { loadPolicies, _clearCache };
