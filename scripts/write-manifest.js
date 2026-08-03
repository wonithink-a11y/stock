#!/usr/bin/env node
'use strict';
/**
 * manifest 기록 CLI — 파이썬 단계(A0.5·A1·A2·A4)가 해시를 직접 계산하지 않게 하기 위한 얇은 래퍼.
 * 해시 구현이 JS/파이썬 두 곳에 생기면 정규화 규칙이 반드시 갈라진다(교훈16).
 *
 * 사용:
 *   node scripts/write-manifest.js --stage A0.5 --stageVersion A0.5.0 \
 *        --target data/backfill/calendar.json [--kind dir] [--ext .jsonl] \
 *        [--upstream A0.5,A1] [--extra '{"recordCount":123}']
 */
const { writeManifest, verifyUpstream } = require('../lib/backfillManifest');

const argv = process.argv.slice(2);
const arg = (k, d = null) => { const i = argv.indexOf('--' + k); return i >= 0 ? argv[i + 1] : d; };

const stage = arg('stage');
const stageVersion = arg('stageVersion');
const target = arg('target');
if (!stage || !stageVersion || !target) {
  console.error('--stage --stageVersion --target 은 필수다');
  process.exit(1);
}

const upstreamStages = (arg('upstream', '') || '').split(',').map((s) => s.trim()).filter(Boolean);
const upstream = upstreamStages.length ? verifyUpstream(upstreamStages) : {};

const m = writeManifest({
  stage,
  stageVersion,
  target,
  targetKind: arg('kind', 'file'),
  targetExt: arg('ext', null),
  upstream,
  extra: JSON.parse(arg('extra', '{}')),
});
console.log(`manifest ${stage} (${stageVersion}) → ${m.hash}` + (m.fileCount != null ? ` · ${m.fileCount} files` : ''));
