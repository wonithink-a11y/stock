'use strict';
/**
 * 백필 manifest 체인 — 단계 간 입력 추적의 유일한 창구.
 *
 * 각 단계는 자기 출력의 해시를 스스로 남기고, 하류는 그것을 '인용'만 한다.
 * 하류가 상류 데이터를 매번 재해싱하면(수백 MB) 연도별 matrix 잡마다 수 분이 날아가고,
 * 정규화 규칙이 스크립트마다 갈라진다.
 *
 * 상류 검증은 경고가 아니라 '실행 거부'다. 경고는 아무도 안 본다.
 *
 * verifyUpstream은 '선언된 상류가 변조됐는가'만 본다. '선언 자체가 빠졌는가'는
 * REQUIRED_UPSTREAM이 본다 — A5가 A1b를 인용하지 않으면 생존편향 상태로 채점된다.
 *
 * 해시 결정론 규칙 (BF-1.1):
 *   - 바이트 해싱 (문자열 변환·인코딩 변환 금지)
 *   - 파일 경로 정렬은 Buffer.compare (localeCompare 금지 — 로케일 의존)
 *   - generatedAt은 해시 대상에서 제외 (실행 시각은 매번 다르다)
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.join(__dirname, '..');
const MANIFEST_DIR = 'data/backfill/manifest';
const SCHEMA_VERSION = 'BF-1.1';
const REGISTRY = 'config/policies/registry.json';

/**
 * 단계별 필수 상류. 여기 있는 stage가 upstream에 없으면 writeManifest가 거부한다.
 * A2·A3는 폐지 종목의 가격·재무가 없으면 생존 편향이 그대로 남으므로 A1b를 필수로 둔다.
 */
const REQUIRED_UPSTREAM = {
  'A0.5': [],
  'A0.7': [],
  'A1a':  ['A0.5', 'A0.7'],
  'A1b':  ['A1a'],
  'A2':   ['A0.5', 'A1a', 'A1b'],
  'A3':   ['A1a', 'A1b'],
  'A4':   ['A0.5', 'A1a'],
  'A5':   ['A0.5', 'A1a', 'A1b', 'A2', 'A3'],
  'A6':   ['A5'],
  'A7':   ['A5'],
};

/** 단계별 필수 정책 해시. --policies 누락은 조용한 재현 불가로 이어진다. */
const REQUIRED_POLICIES = {
  'A1a': ['universe'],
  'A1b': ['universe'],
  'A2':  ['universe'],
};

function hashBytes(buf) {
  return 'sha256:' + crypto.createHash('sha256').update(buf).digest('hex').slice(0, 16);
}

/** 파일 1개의 바이트 해시 */
function hashFile(absOrRel) {
  const abs = path.isAbsolute(absOrRel) ? absOrRel : path.join(ROOT, absOrRel);
  return hashBytes(fs.readFileSync(abs));
}

/** 디렉터리 전체의 결정론적 해시. 경로 정렬은 바이트 비교로 고정한다. */
function hashDir(relDir, ext = '.jsonl') {
  const absDir = path.join(ROOT, relDir);
  if (!fs.existsSync(absDir)) throw new Error(`해시 대상 디렉터리 없음: ${relDir}`);

  const files = [];
  (function walk(d) {
    for (const name of fs.readdirSync(d)) {
      const p = path.join(d, name);
      const st = fs.statSync(p);
      if (st.isDirectory()) walk(p);
      else if (!ext || name.endsWith(ext)) files.push(path.relative(absDir, p));
    }
  })(absDir);

  files.sort((a, b) => Buffer.compare(Buffer.from(a, 'utf8'), Buffer.from(b, 'utf8')));

  const h = crypto.createHash('sha256');
  for (const rel of files) {
    h.update(rel, 'utf8');
    h.update('\t');
    h.update(hashFile(path.join(absDir, rel)), 'utf8');
    h.update('\n');
  }
  return { hash: 'sha256:' + h.digest('hex').slice(0, 16), fileCount: files.length };
}

/**
 * 정책 키 → 파일 바이트 해시. registry의 3개 네임스페이스를 모두 뒤진다.
 * loadPolicies()를 부르지 않는 이유: 그쪽은 criteria까지 읽고 deepFreeze하는 무거운 경로이고,
 * 파이썬 단계가 부르는 CLI에서 엔진 의존성을 끌어올 이유가 없다.
 */
function hashPolicyFiles(keys = []) {
  if (!keys.length) return null;

  const regBuf = fs.readFileSync(path.join(ROOT, REGISTRY));
  const registry = JSON.parse(regBuf.toString('utf8'));

  const ns = {
    policies: registry.policies || {},
    analysisPolicies: registry.analysisPolicies || {},
    dataPolicies: registry.dataPolicies || {},
  };

  const out = { registry: hashBytes(regBuf), registryVersion: registry.version };
  for (const key of keys) {
    const found = Object.entries(ns).filter(([, m]) => Object.prototype.hasOwnProperty.call(m, key));
    if (!found.length) {
      throw new Error(`정책 키 '${key}'가 ${REGISTRY} 어디에도 없다 — 등록 없이 해시를 남기면 추적이 끊긴다`);
    }
    if (found.length > 1) {
      throw new Error(`정책 키 '${key}'가 ${found.map(([n]) => n).join('·')}에 중복 등록됐다 — 어느 층이 읽는 정책인지 모호해진다`);
    }
    out[key] = hashFile(found[0][1][key]);
  }
  return out;
}

function manifestPath(stage) {
  return path.join(ROOT, MANIFEST_DIR, `${stage}.json`);
}

function readManifest(stage) {
  const p = manifestPath(stage);
  if (!fs.existsSync(p)) throw new Error(`상류 manifest 없음: ${stage} — 선행 단계를 먼저 실행하라`);
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

/**
 * 상류 단계들이 선언한 해시와 현재 파일의 실제 해시를 대조한다.
 * 불일치 = 상류가 재수집됐다는 뜻이므로, 하류를 그대로 돌리면 재현 불가능한 결과가 나온다. → throw.
 */
function verifyUpstream(stages) {
  const out = {};
  const drifted = [];
  for (const stage of stages) {
    const m = readManifest(stage);
    const actual = m.targetKind === 'dir'
      ? hashDir(m.target, m.targetExt || '.jsonl').hash
      : hashFile(m.target);
    if (actual !== m.hash) {
      drifted.push(`${stage}: manifest=${m.hash} actual=${actual} (${m.target})`);
    }
    out[stage] = m.hash;
  }
  if (drifted.length) {
    throw new Error(
      '상류 산출물이 manifest와 다르다 — 재수집됐다는 뜻이므로 이 단계를 돌리면 결과를 재현할 수 없다.\n' +
      drifted.map((d) => '  - ' + d).join('\n') +
      '\n해당 상류 단계를 다시 실행해 manifest를 갱신하라.'
    );
  }
  return out;
}

/**
 * @param stage        'A0.5' | 'A1a' | 'A1b' | 'A2' ...
 * @param stageVersion 수집·계산 로직의 버전. 같은 입력·다른 수집기를 구분한다
 * @param target       산출물 경로 (파일 또는 디렉터리, ROOT 상대)
 * @param targetKind   'file' | 'dir'
 * @param upstream     verifyUpstream() 반환값
 * @param policies     정책 키 배열 → policyHash 필드로 출력
 * @param extra        recordCount·_diagnostics 등
 */
function writeManifest({
  stage, stageVersion, target, targetKind = 'file', targetExt,
  upstream = {}, policies = [], extra = {},
}) {
  if (!stage || !stageVersion) throw new Error('stage·stageVersion은 필수다');

  const needU = REQUIRED_UPSTREAM[stage];
  if (needU) {
    const missing = needU.filter((s) => !upstream[s]);
    if (missing.length) {
      throw new Error(
        `${stage}의 필수 상류가 upstream에 없다: ${missing.join(', ')}\n` +
        'verifyUpstream은 선언된 상류의 변조만 잡는다 — 선언 자체가 빠지면 그 단계가 없었던 것처럼 통과한다.\n' +
        `--upstream ${needU.join(',')} 로 재실행하라.`
      );
    }
  }

  const needP = REQUIRED_POLICIES[stage];
  if (needP) {
    const missing = needP.filter((k) => !policies.includes(k));
    if (missing.length) {
      throw new Error(`${stage}의 필수 정책 해시가 없다: ${missing.join(', ')} — --policies ${needP.join(',')} 를 붙여라`);
    }
  }

  let hash, fileCount = null;
  if (targetKind === 'dir') { const r = hashDir(target, targetExt || '.jsonl'); hash = r.hash; fileCount = r.fileCount; }
  else hash = hashFile(target);

  const policyHash = hashPolicyFiles(policies);

  const m = {
    schemaVersion: SCHEMA_VERSION,
    stage,
    stageVersion,
    target,
    targetKind,
    ...(targetExt ? { targetExt } : {}),
    hash,
    ...(fileCount !== null ? { fileCount } : {}),
    upstream,
    ...(policyHash ? { policyHash } : {}),
    ...extra,
    generatedAt: new Date().toISOString(),  // 해시 대상 아님 — 매 실행 달라진다
  };

  fs.mkdirSync(path.join(ROOT, MANIFEST_DIR), { recursive: true });
  fs.writeFileSync(manifestPath(stage), JSON.stringify(m, null, 2) + '\n', 'utf8');
  return m;
}

module.exports = {
  hashBytes, hashFile, hashDir, hashPolicyFiles,
  readManifest, writeManifest, verifyUpstream,
  MANIFEST_DIR, SCHEMA_VERSION, REQUIRED_UPSTREAM, REQUIRED_POLICIES,
};
