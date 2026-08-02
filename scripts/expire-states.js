#!/usr/bin/env node
/**
 * STEP3 — TTL 만료 배치. 평일 06:00 KST.
 *   node scripts/expire-states.js
 *
 * data/state/*.json 만 읽고 쓴다. 외부 API를 호출하지 않으므로 실패 지점이 파일 I/O뿐이다.
 * 종목 하나가 깨져도 나머지는 처리한다(fail-soft). 변경분이 없으면 파일을 쓰지 않는다.
 */
'use strict';
const { getState, putState, listStates } = require('../lib/stateStore');
const { expireState } = require('../lib/stateExpirer');

const kstNow = () => new Date(Date.now() + 9 * 3600e3).toISOString().replace(/\.\d{3}Z$/, '+09:00');

function main() {
  const now = kstNow();
  const tickers = listStates();
  const changed = [];
  const failed = [];

  for (const ticker of tickers) {
    try {
      const prev = getState(ticker);
      const next = expireState(prev, now);
      if (next === prev) continue;
      putState(next);
      changed.push({
        ticker,
        expired: prev.riskStates.filter((c) => !next.riskStates.includes(c)),
        remaining: next.riskStates,
      });
    } catch (err) {
      failed.push({ ticker, reason: err.message });
    }
  }

  console.log(`🕛 expire-states @ ${now}`);
  console.log(`   state 파일 ${tickers.length}건 · 만료 ${changed.length}건 · 실패 ${failed.length}건`);
  changed.forEach((c) => console.log(`   - ${c.ticker}: ${c.expired.join(',')} 만료 → 잔여 [${c.remaining.join(',')}]`));
  failed.forEach((f) => console.log(`   ! ${f.ticker}: ${f.reason}`));

  // 파일 I/O 실패는 조용히 넘기면 위험이 영구히 남는다. 워크플로를 빨갛게 만든다.
  process.exit(failed.length === 0 ? 0 : 1);
}

main();
