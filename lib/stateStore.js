'use strict';
const fs = require('fs'), path = require('path');
const ROOT = path.join(__dirname, '..');
const STATE_DIR = path.join(ROOT, 'data', 'state');
const HIST_DIR  = path.join(ROOT, 'data', 'state-history');
const { initState } = require('./stateReducer');

function getState(ticker) {
  const p = path.join(STATE_DIR, `${ticker}.json`);
  if (!fs.existsSync(p)) return initState(ticker);
  const s = JSON.parse(fs.readFileSync(p, 'utf8'));
  return { ...initState(ticker), ...s };          // 구버전 필드 결손 보정
}
function putState(state) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  fs.writeFileSync(path.join(STATE_DIR, `${state.ticker}.json`), JSON.stringify(state, null, 2));
}
function appendHistory(event) {
  const year = event.occurredAt.slice(0, 4);      // 연도 분할 — 파일 생성 전 확정
  const dir = path.join(HIST_DIR, year);
  fs.mkdirSync(dir, { recursive: true });
  fs.appendFileSync(path.join(dir, `${event.ticker}.jsonl`), JSON.stringify(event) + '\n');
}
function listStates() {
  if (!fs.existsSync(STATE_DIR)) return [];
  return fs.readdirSync(STATE_DIR).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5));
}
module.exports = { getState, putState, appendHistory, listStates, STATE_DIR, HIST_DIR };
