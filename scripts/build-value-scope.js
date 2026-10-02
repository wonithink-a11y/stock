#!/usr/bin/env node
/**
 * 'PIT 가치 검증 범위' 표 → docs/data/value-scope.json
 *
 * 왜 필요한가: 대시보드 점수의 가치 축은 KIS 가 주는 PER·PBR(현재 주식수 기준)을 쓰지만, 검증 패널(A5)의
 * 가치 축은 A3d 기업행위로 주식수를 시점 보정해야만 만든다. 분할·증자·합병 이력이 복잡한 종목은 보정을
 * 보류(withheldBy)해서 PIT 가치가 없다 — 패널에서 가치 점수가 있는 행은 연도별 50~55% 뿐이다.
 * 우리가 '가치 신호가 있다'고 검증한 범위는 이 절반이다. 화면이 그 경계를 보여주려고 만든다.
 *
 * 하는 일: 관심종목 KR 마다 lib/a5/resolver.js 의 resolve() 를 최신 A2a 일자 기준으로 읽기 전용 호출해
 *   inScope(PER/PBR 산출 여부) 와 보류 사유(withheldBy)를 적는다.
 * 하지 않는 일: 점수 계산·정책·전략 선정 불변. 가치 값을 대체하지 않는다(이 파일은 값이 아니라 범위만 말한다).
 *   '신뢰도' 같은 종합 평가로 바꾸지 않는다 — 범위와 사유만.
 *
 * 사용: node scripts/build-value-scope.js [--asOf YYYY-MM-DD] [--out 경로] [--selftest]
 *   --asOf  기본은 A2a 의 actualDataTo. 패널(A5) 스냅샷일과 대조 검증할 때 쓴다.
 *   --out   기본 docs/data/value-scope.json. 검증용 실행은 저장소 밖 경로로 쓴다.
 * 입력 날짜가 같고 데이터가 같으면 산출물이 바이트 동일하다(타임스탬프 없음) — 워크플로가 변경 없음으로 건너뛴다.
 */
'use strict';

const fs = require('fs');
const zlib = require('zlib');
const path = require('path');
const ROOT = path.join(__dirname, '..');

const A3D_CATEGORIES = [
  'split', 'reverseOrConsolidation', 'bonusIssue', 'capitalReductionFree',
  'capitalReductionPaid', 'capitalReductionUnknown', 'rightsOfferingThirdParty',
  'rightsOfferingShareholders', 'mergerSpinoff',
];

function readJsonl(rel, keep) {
  let buf = fs.readFileSync(path.join(ROOT, rel));
  if (rel.endsWith('.gz')) buf = zlib.gunzipSync(buf);
  const out = [];
  let start = 0;
  for (let i = 0; i < buf.length; i++) {
    if (buf[i] !== 0x0a) continue;
    if (i > start) { const r = JSON.parse(buf.toString('utf8', start, i)); if (!keep || keep(r)) out.push(r); }
    start = i + 1;
  }
  if (start < buf.length) { const r = JSON.parse(buf.toString('utf8', start)); if (!keep || keep(r)) out.push(r); }
  return out;
}

const yearFiles = (dir) => fs.readdirSync(path.join(ROOT, dir)).filter((f) => /^\d{4}\.jsonl\.gz$/.test(f)).map((f) => `${dir}/${f}`);

/** resolve() 결과에서 PIT 가치 범위 판정. 순수 함수 — selftest 가 이걸 검사한다. */
function judge(resolved, hasPrice) {
  const v = (resolved && resolved.stockData && resolved.stockData.valuation) || {};
  const inScope = v.pbr != null || v.per != null;
  if (inScope) return { inScope: true, reason: null };
  if (!hasPrice) return { inScope: false, reason: 'NO_PRICE' };
  const prov = (resolved && resolved.provenance && resolved.provenance.valuation) || {};
  const so = prov.sharesOutstanding || {};
  const reason = (so.cur && so.cur.withheldBy) || (so.prev && so.prev.withheldBy) || 'NO_VALUATION_INPUT';
  return { inScope: false, reason };
}

function selftest() {
  const ok = (c, m) => { if (!c) { console.error('selftest 실패: ' + m); process.exit(1); } };
  ok(judge({ stockData: { valuation: { pbr: 1.2, per: null } } }, true).inScope === true, 'pbr 만 있어도 범위 안');
  ok(judge({ stockData: { valuation: { pbr: null, per: 9 } } }, true).inScope === true, 'per 만 있어도 범위 안');
  const w = judge({ stockData: { valuation: {} }, provenance: { valuation: { sharesOutstanding: { cur: { withheldBy: 'MERGER_UNHANDLED' } } } } }, true);
  ok(!w.inScope && w.reason === 'MERGER_UNHANDLED', '보류 사유가 그대로 나온다');
  ok(judge({ stockData: { valuation: {} } }, false).reason === 'NO_PRICE', '가격 없음 구분');
  ok(judge({ stockData: { valuation: {} } }, true).reason === 'NO_VALUATION_INPUT', '사유 불명은 일반 코드');
  ok(judge(null, true).inScope === false, 'null 방어');
  console.log('selftest OK - judge()');
}

function main() {
  const args = process.argv.slice(2);
  if (args.includes('--selftest')) return selftest();
  const arg = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : null; };

  const diag = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/backfill/price/a2a/_diagnostics.json'), 'utf8'));
  const asOf = arg('--asOf') || diag.actualDataTo;
  const outPath = arg('--out') || path.join(ROOT, 'docs/data/value-scope.json');

  const watch = JSON.parse(fs.readFileSync(path.join(ROOT, 'config/watchlist.json'), 'utf8')).tickers.filter((t) => (t.market || 'KR') === 'KR');
  const uni = new Map(readJsonl('data/backfill/universe/a1a/current.jsonl').map((r) => [r.ticker, r]));
  const corps = new Set(watch.map((t) => (uni.get(t.code) || {}).corp).filter(Boolean));

  const byCorp = (dir) => {
    const m = new Map();
    for (const f of yearFiles(dir)) for (const r of readJsonl(f, (x) => corps.has(x.corp))) {
      if (!m.has(r.corp)) m.set(r.corp, []);
      m.get(r.corp).push(r);
    }
    return m;
  };
  const a3 = byCorp('data/backfill/fundamentals/a3');
  const a3b = byCorp('data/backfill/fundamentals/a3b');
  const a3c = byCorp('data/backfill/fundamentals/a3c');
  const actions = new Map();
  for (const cat of A3D_CATEGORIES) {
    const p = `data/backfill/fundamentals/a3d/${cat}.jsonl.gz`;
    if (!fs.existsSync(path.join(ROOT, p))) continue;
    for (const r of readJsonl(p, (x) => corps.has(x.corp))) {
      if (!actions.has(r.corp)) actions.set(r.corp, []);
      actions.get(r.corp).push({ ...r, category: cat });
    }
  }

  const { resolve } = require(path.join(ROOT, 'lib/a5/resolver'));
  const { findPrice, findCandles } = require(path.join(ROOT, 'lib/a5/priceSource'));

  const byTicker = {};
  const reasons = {};
  let inScopeN = 0;
  for (const t of watch) {
    const u = uni.get(t.code);
    let j;
    if (!u) j = { inScope: false, reason: 'NOT_IN_UNIVERSE' };
    else {
      const price = findPrice(t.code, asOf);
      const { candles } = findCandles(t.code, asOf, 260);
      try {
        const resolved = resolve({
          ticker: t.code, corp: u.corp, asOf,
          fundamentals: a3.get(u.corp) || [], price, dividendEps: a3b.get(u.corp) || [],
          candles, sharesOutstanding: a3c.get(u.corp) || [], corporateActions: actions.get(u.corp) || [],
          supplyDemandRecords: [],
        });
        j = judge(resolved, !!price);
      } catch (e) {
        j = { inScope: false, reason: 'RESOLVE_ERROR' };
      }
    }
    byTicker[t.code] = j;
    if (j.inScope) inScopeN += 1; else reasons[j.reason] = (reasons[j.reason] || 0) + 1;
  }

  const out = {
    schemaVersion: 'VS-1.0',
    asOf,
    note: 'PIT 가치(PER/PBR) 산출 가능 여부. 점수·정책과 무관한 표시용 범위표 — 값 대체·신뢰도 평가 아님.',
    summary: { total: watch.length, inScope: inScopeN, outOfScope: watch.length - inScopeN, reasons },
    byTicker,
  };
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(out, null, 1) + '\n', 'utf8');
  console.log(`value-scope ${asOf}: 범위 안 ${inScopeN}/${watch.length} · 밖 ${watch.length - inScopeN}`, JSON.stringify(reasons));
}

main();
