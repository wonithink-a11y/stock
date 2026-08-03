'use strict';
/**
 * criteria 스냅샷 단일 로더.
 *   registry.json → config/criteria/{market}-{version}.json
 *
 * 스냅샷 디렉터리 밖 경로와 version 불일치는 로드 시점에 거부한다.
 * 결과는 프로세스 단위 캐시 + deep freeze — 캐시는 참조 공유라
 * 한 곳에서 criteria를 변형하면 이후 전 종목의 채점이 조용히 오염된다.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const SNAPSHOT_DIR = 'config/criteria/';
const CACHE = new Map();

function deepFreeze(obj) {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    for (const v of Object.values(obj)) deepFreeze(v);
  }
  return obj;
}

function loadCriteria(market = 'KR') {
  if (CACHE.has(market)) return CACHE.get(market);

  const registry = JSON.parse(fs.readFileSync(path.join(ROOT, 'config/policies/registry.json'), 'utf8'));
  const entry = (registry.criteria || {})[market];
  if (!entry) throw new Error(`registry.criteria에 ${market} 항목이 없다`);
  if (!String(entry.path).startsWith(SNAPSHOT_DIR)) {
    throw new Error(`criteria는 스냅샷에서만 로드한다: ${entry.path} (재현성 계약 위반)`);
  }

  const file = JSON.parse(fs.readFileSync(path.join(ROOT, entry.path), 'utf8'));
  if (file.version !== entry.version) {
    throw new Error(
      `criteria 버전 불일치: ${entry.path}=${file.version} vs registry=${entry.version}. ` +
      '스냅샷은 수정하지 말고 새 버전 파일을 만들어라.'
    );
  }
  if (!file.categoryWeights || Object.keys(file.categoryWeights).length === 0) {
    throw new Error(`${market} criteria에 categoryWeights가 없다 (AX002)`);
  }

  const result = deepFreeze({ criteria: file, version: entry.version, path: entry.path });
  CACHE.set(market, result);
  return result;
}

/** 테스트 전용 — 같은 프로세스에서 registry를 바꿔가며 검증할 때만 쓴다 */
function _clearCache() { CACHE.clear(); }

module.exports = { loadCriteria, _clearCache };
