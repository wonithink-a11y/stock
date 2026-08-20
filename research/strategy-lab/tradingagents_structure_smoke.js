#!/usr/bin/env node
/**
 * TradingAgents 구조 smoke — Bull/Bear/Judge 파이프라인이 실제 PIT 데이터로
 * 작동하는지만 확인한다. 성과·예측력·production eligible 여부는 판단하지 않는다
 * (사용자 지시, 2026-08-19). production coverage 게이트를 안 쓰는 대신 대형주만
 * 골라 데이터가 최대한 채워진 상태를 만든다.
 *
 * analyst 단계는 생략한다 — resolver.js/scoringEngine.js(production, read-only
 * 호출)로 이미 구조화한 fundamental/technical raw feature + axis score +
 * coverage를 Bull/Bear에게 그대로 준다.
 *
 * A4/supplyDemand는 이번 smoke에서 제외한다(사용자 지시) — 없는 데이터를
 * 추정·대체하지 않는다.
 *
 * 실행: ANTHROPIC_API_KEY 필요.
 *   ANTHROPIC_API_KEY=... node research/strategy-lab/tradingagents_structure_smoke.js
 *
 * production 코드(lib/·config/)는 읽기만 한다. 산출물은 이 디렉터리 안에만 쓴다.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const ROOT = path.join(__dirname, '..', '..');

const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
const { score } = require(path.join(ROOT, 'lib/scoringEngine'));
const { loadCriteria } = require(path.join(ROOT, 'lib/loadCriteria'));
const { loadPolicies } = require(path.join(ROOT, 'lib/loadPolicies'));

const SAMPLE = [
  { ticker: '005930', corp: '00126380', name: '삼성전자' },
  { ticker: '000660', corp: '00164779', name: 'SK하이닉스' },
  { ticker: '005380', corp: '00164742', name: '현대자동차' },
];
const SNAPSHOT_DATES = ['2021-06-04', '2024-02-29']; // calendar.json snapshotDays 실제 날짜

const PRICE_YEARS = ['2019', '2020', '2021', '2022', '2023', '2024'];
const FUND_YEARS = ['2019', '2020', '2021', '2022', '2023', '2024'];

const MODEL = 'claude-opus-5';
const API_URL = 'https://api.anthropic.com/v1/messages';

function readGzJsonl(relPath) {
  const buf = fs.readFileSync(path.join(ROOT, relPath));
  const text = relPath.endsWith('.gz') ? zlib.gunzipSync(buf).toString('utf8') : buf.toString('utf8');
  return text.split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

function loadPriceSeries(ticker) {
  const rows = [];
  for (const y of PRICE_YEARS) {
    const rel = `data/backfill/price/a2a/${y}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, rel))) continue;
    for (const r of readGzJsonl(rel)) if (r.ticker === ticker) rows.push(r);
  }
  rows.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  return rows;
}

function loadFundamentals(corp) {
  const a3 = [];
  const a3b = [];
  for (const y of FUND_YEARS) {
    const relA3 = `data/backfill/fundamentals/a3/${y}.jsonl.gz`;
    if (fs.existsSync(path.join(ROOT, relA3))) {
      for (const r of readGzJsonl(relA3)) if (r.corp === corp) a3.push(r);
    }
    const relA3b = `data/backfill/fundamentals/a3b/${y}.jsonl.gz`;
    if (fs.existsSync(path.join(ROOT, relA3b))) {
      for (const r of readGzJsonl(relA3b)) if (r.corp === corp) a3b.push(r);
    }
  }
  return { a3, a3b };
}

function pctChange(candles, daysBack) {
  if (candles.length <= daysBack) return null;
  const now = candles[candles.length - 1].close;
  const then = candles[candles.length - 1 - daysBack].close;
  if (!then) return null;
  return Math.round((now / then - 1) * 10000) / 100;
}

function buildSnapshot({ ticker, corp, name }, asOf, priceRows, a3, a3b, criteria, policies) {
  const priceUpTo = priceRows.filter((r) => r.date <= asOf);
  const candles = priceUpTo.slice(-260).map((r) => ({ date: r.date, close: r.close, volume: r.volume }));
  const price = priceUpTo[priceUpTo.length - 1] || null;

  const resolved = resolve({ ticker, corp, asOf, fundamentals: a3, dividendEps: a3b, candles, price });
  const stockData = { ticker, name, dataCutoff: asOf, state: null, ...resolved.stockData };
  const scored = score(stockData, criteria, policies);

  return {
    ticker, name, asOf,
    fundamentalRaw: resolved.stockData.fundamental,
    technicalRaw: resolved.stockData.technical || null,
    fundamentalScore: scored.result.components.fundamental,
    technicalScore: scored.result.components.technical,
    coveragePct: scored.result.confidence.value,
    missing: resolved.missing,
    recentPriceChange: {
      pct5d: pctChange(candles, 5),
      pct20d: pctChange(candles, 20),
      lastClose: price ? price.close : null,
      lastDate: price ? price.date : null,
    },
  };
}

function formatDataReport(s) {
  return [
    `종목: ${s.name}(${s.ticker}) · 기준일(asOf): ${s.asOf}`,
    `[fundamental raw] ${JSON.stringify(s.fundamentalRaw)}`,
    `[technical raw] ${JSON.stringify(s.technicalRaw)}`,
    `[axis score] fundamental=${s.fundamentalScore ?? 'null'} · technical=${s.technicalScore ?? 'null'} (0~100)`,
    `[coverage] ${s.coveragePct}% · 결측 지표: ${s.missing.length ? s.missing.join(', ') : '없음'}`,
    `[최근 가격 변화] 5일 ${s.recentPriceChange.pct5d}% · 20일 ${s.recentPriceChange.pct20d}% (종가 ${s.recentPriceChange.lastClose}, ${s.recentPriceChange.lastDate} 기준)`,
  ].join('\n');
}

async function callClaude({ system, user, format }) {
  const body = {
    model: MODEL,
    max_tokens: 1024,
    output_config: format ? { effort: 'low', format } : { effort: 'low' },
    system,
    messages: [{ role: 'user', content: user }],
  };
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'x-api-key': process.env.ANTHROPIC_API_KEY,
      'anthropic-version': '2023-06-01',
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const json = await res.json();
  if (!res.ok) throw new Error(`API ${res.status}: ${JSON.stringify(json)}`);
  return json;
}

function textOf(resp) {
  const block = (resp.content || []).find((b) => b.type === 'text');
  return block ? block.text : '';
}

const JUDGE_SCHEMA = {
  type: 'json_schema',
  schema: {
    type: 'object',
    properties: {
      grade: { type: 'string', enum: ['STRONG_SELL', 'SELL', 'HOLD', 'BUY', 'STRONG_BUY'] },
      rationale: { type: 'string' },
    },
    required: ['grade', 'rationale'],
    additionalProperties: false,
  },
};

async function runPair(snapshot) {
  const report = formatDataReport(snapshot);

  const bullResp = await callClaude({
    system: '당신은 강세론자(Bull) 애널리스트다. 아래 구조화 데이터만 근거로 이 종목의 강세 논거를 한국어 150단어 내외로 작성한다. 데이터에 없는 사실을 지어내지 않는다.',
    user: report,
  });
  const bullText = textOf(bullResp);

  const bearResp = await callClaude({
    system: '당신은 약세론자(Bear) 애널리스트다. 아래 구조화 데이터만 근거로 이 종목의 약세 논거를 한국어 150단어 내외로 작성한다. 데이터에 없는 사실을 지어내지 않는다.',
    user: report,
  });
  const bearText = textOf(bearResp);

  const judgeResp = await callClaude({
    system: '당신은 리서치 매니저(Judge)다. 아래 원자료와 Bull/Bear 두 논거를 종합해 STRONG_SELL/SELL/HOLD/BUY/STRONG_BUY 중 하나로 판정하고 한 줄 근거를 남긴다.',
    user: `${report}\n\n[Bull 논거]\n${bullText}\n\n[Bear 논거]\n${bearText}`,
    format: JUDGE_SCHEMA,
  });
  const judgeRaw = textOf(judgeResp);
  let judge;
  try {
    judge = JSON.parse(judgeRaw);
  } catch (e) {
    judge = { parseError: e.message, raw: judgeRaw };
  }

  return {
    snapshot,
    bull: bullText,
    bear: bearText,
    judge,
    usage: { bull: bullResp.usage, bear: bearResp.usage, judge: judgeResp.usage },
  };
}

async function main() {
  if (!process.env.ANTHROPIC_API_KEY) {
    console.error('ANTHROPIC_API_KEY가 설정되지 않았습니다. 셸 세션에 export 후 다시 실행하세요.');
    process.exit(1);
  }

  const criteria = loadCriteria('KR').criteria;
  const policies = loadPolicies('KR');

  const results = [];
  const errors = [];

  for (const t of SAMPLE) {
    const priceRows = loadPriceSeries(t.ticker);
    const { a3, a3b } = loadFundamentals(t.corp);
    for (const asOf of SNAPSHOT_DATES) {
      const snapshot = buildSnapshot(t, asOf, priceRows, a3, a3b, criteria, policies);
      console.error(`[${t.ticker} ${asOf}] coverage=${snapshot.coveragePct}% → Bull/Bear/Judge 호출 중...`);
      try {
        const r = await runPair(snapshot);
        results.push(r);
        console.error(`  -> Judge: ${r.judge.grade || '(파싱실패)'}`);
      } catch (e) {
        errors.push({ ticker: t.ticker, asOf, error: e.message });
        console.error(`  -> 오류: ${e.message}`);
      }
    }
  }

  const outDir = path.join(ROOT, 'research/strategy-lab/reports/2026-08-19-tradingagents-structure-smoke');
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, 'results.json');
  fs.writeFileSync(outPath, JSON.stringify({ generatedAt: new Date().toISOString(), pairs: results, errors }, null, 2));

  console.log('\n=== 구조 smoke 체크리스트 ===');
  console.log(`1. 데이터 입력 정상 전달: ${results.length + errors.length}/${SAMPLE.length * SNAPSHOT_DATES.length}쌍 시도`);
  console.log(`2. Bull/Bear 생성: ${results.filter((r) => r.bull && r.bear).length}/${results.length}`);
  console.log(`3. Judge 판정: ${results.filter((r) => r.judge && r.judge.grade).length}/${results.length}`);
  console.log(`4. 출력 구조 저장: ${outPath}`);
  console.log(`5. 오류 없이 종료: ${errors.length === 0 ? 'YES' : `NO (${errors.length}건)`}`);
}

main();
