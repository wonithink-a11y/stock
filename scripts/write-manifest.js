#!/usr/bin/env node
'use strict';
/**
 * manifest 기록 CLI — 파이썬 단계(A0.5·A1·A2·A4)가 해시를 직접 계산하지 않게 하기 위한 얇은 래퍼.
 * 해시 구현이 JS/파이썬 두 곳에 생기면 정규화 규칙이 반드시 갈라진다(교훈16).
 *
 * 사용:
 *   node scripts/write-manifest.js --stage A1a --stageVersion A1a.1 \
 *        --target data/backfill/universe/a1a --kind dir --ext .jsonl \
 *        --upstream A0.5 --policies universe \
 *        --extra '{"recordCount":2579}'
 */
const { writeManifest, verifyUpstream } = require('../lib/backfillManifest');

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const i = argv.indexOf('--' + k); return i >= 0 ? argv[i + 1] : d; };
const list = (k) => (arg(k, '') || '').split(',').map((s) => s.trim()).filter(Boolean);

const stage = arg('stage');
const stageVersion = arg('stageVersion');
const target = arg('target');
if (!stage || !stageVersion || !target) {
  console.error('--stage --stageVersion --target 은 필수다');
  process.exit(1);
}

const upstreamStages = list('upstream');
const upstream = upstreamStages.length ? verifyUpstream(upstreamStages) : {};
const policies = list('policies');

const m = writeManifest({
  stage,
  stageVersion,
  target,
  targetKind: arg('kind', 'file'),
  targetExt: arg('ext', null),
  upstream,
  policies,
  extra: JSON.parse(arg('extra', '{}')),
});

const pk = m.policyHash ? Object.keys(m.policyHash).filter((k) => k !== 'registryVersion') : [];
console.log(
  `manifest ${stage} (${stageVersion}) → ${m.hash}` +
  (m.fileCount != null ? ` · ${m.fileCount} files` : '') +
  (m.recordCount != null ? ` · ${m.recordCount} records` : '') +
  (pk.length ? ` · policyHash[${pk.join(',')}]` : '')
);
