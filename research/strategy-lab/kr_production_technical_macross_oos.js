// research/strategy-lab 컨벤션대로 로컬 전용(커밋 안 함).
//
// production 채점 엔진(config/criteria/KR-2.2.json, lib/scoringEngine.js)의
// technical 축이 A5 10년 백필(data/backfill/scores/, 2016-2026)에서 지속적으로
// 마이너스 IC(-0.033, 2016-2025)를 보인 원인을 이동평균크로스(MA크로스, 기술
// 축 내부 가중치 35%로 최대)로 좁힌 뒤, "MA크로스 반전"이 TRAIN에서만 고른
// 대안이 VALID·TEST(둘 다 한 번도 안 본 구간)에서도 유지되는지 검증한다.
//
// 새 계산식을 만들지 않는다 - lib/a5/technicalFrom.js(scripts/collect.js와
// 동일 공식, production과 다른 계산식 금지 원칙)와 lib/scoringEngine.js의
// weightedAverage()를 그대로 재사용한다. A2a 가격이력으로 하위지표(maSignal·
// rsi·macdSignal·volumeConfirmed)를 다시 계산하고, A5가 이미 계산해 둔
// fundamental·valuation 점수와 fwd.d20(실제 20영업일 선행수익률)은 그대로
// 재사용한다(중복 계산 안 함, 재현성 확보).
//
// 분할: TRAIN 2016-01~2021-12(6y,60%) VALID 2022-01~2023-06(1.5y,15%)
//       TEST 2023-07~2025-12(2.5y,25%) - 10년을 60/15/25로 근사.
//
// 사용: node research/strategy-lab/kr_production_technical_macross_oos.js
// (저장소 루트에서 실행 - lib/ require 경로가 상대경로)
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const readline = require('readline');
const { computeTechnical } = require('../../lib/a5/technicalFrom');
const { loadCriteria } = require('../../lib/loadCriteria');
const { spearmanIC, gradeFromScore } = require('../../lib/backtester');

const ROOT = path.join(__dirname, '..', '..');
const PRICE_DIR = path.join(ROOT, 'data', 'backfill', 'price', 'a2a');
const SCORES_DIR = path.join(ROOT, 'data', 'backfill', 'scores');

async function readJsonlGz(filePath, onLine) {
  const rl = readline.createInterface({
    input: fs.createReadStream(filePath).pipe(zlib.createGunzip()),
    crlfDelay: Infinity,
  });
  for await (const line of rl) {
    if (line.trim()) onLine(JSON.parse(line));
  }
}

const crit = loadCriteria('KR').criteria;
const maScoreTable = crit.technical.indicators.movingAverageCross.signals;
const rsiZones = crit.technical.indicators.rsi.zones;
const catWeights = crit.categoryWeights; // fundamental .35 / valuation .30 / technical .15 / supplyDemand .20
function rsiScoreOf(rsi) {
  if (typeof rsi !== 'number') return null;
  for (const z of rsiZones) if (rsi <= z.max) return z.score;
  return null;
}
function macdScoreOf(sig) {
  if (sig === 'bullishCross') return 100;
  if (sig === 'bearishCross') return 0;
  if (sig === 'neutral') return 50;
  return null;
}
function volScoreOf(v) {
  if (v === true) return 100;
  if (v === false) return 30;
  return null;
}
function weightedAverage(items) {
  const valid = items.filter((i) => i.score !== null && i.score !== undefined);
  if (valid.length === 0) return null;
  const tw = valid.reduce((s, i) => s + i.weight, 0);
  if (tw === 0) return null;
  return valid.reduce((s, i) => s + i.score * i.weight, 0) / tw;
}

function split(date) {
  if (date < '2022-01-01') return 'TRAIN';
  if (date < '2023-07-01') return 'VALID';
  return 'TEST';
}

async function main() {
  console.log('A2a 가격이력 로드 중...');
  const byTicker = new Map();
  const priceFiles = fs.readdirSync(PRICE_DIR).filter(f => f.endsWith('.jsonl.gz')).sort();
  for (const f of priceFiles) {
    await readJsonlGz(path.join(PRICE_DIR, f), (rec) => {
      if (typeof rec.close !== 'number') return;
      let arr = byTicker.get(rec.ticker);
      if (!arr) { arr = []; byTicker.set(rec.ticker, arr); }
      arr.push({ date: rec.date, close: rec.close, volume: rec.volume });
    });
  }
  for (const arr of byTicker.values()) arr.sort((a, b) => (a.date < b.date ? -1 : 1));
  console.log(`  ${byTicker.size}종목 로드 완료`);

  console.log('\nA5 2016-2025 스코어 로드 + 기술지표 재계산 중...');
  const scoreFiles = fs.readdirSync(SCORES_DIR).filter(f => /^(201[6-9]|202[0-5])\.jsonl\.gz$/.test(f)).sort();
  const rows = [];
  for (const f of scoreFiles) {
    await readJsonlGz(path.join(SCORES_DIR, f), (rec) => {
      if (rec._meta) return;
      if (rec.fwdStatus?.d20 !== 'OK') return;
      const candles = byTicker.get(rec.t);
      if (!candles) return;
      // 이진탐색으로 asOf(rec.d) 이하 최대 인덱스 - PIT 안전
      let lo = 0, hi = candles.length - 1, idx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (candles[mid].date <= rec.d) { idx = mid; lo = mid + 1; } else hi = mid - 1;
      }
      if (idx < 59) return; // MA60 워밍업 최소
      const window = candles.slice(Math.max(0, idx - 119), idx + 1); // 최근 120일이면 충분
      const tech = computeTechnical(window);
      const maScore = maScoreTable[tech.maSignal] ?? null;
      const rsiScore = rsiScoreOf(tech.rsi);
      const macdScore = macdScoreOf(tech.macdSignal);
      const volScore = volScoreOf(tech.volumeConfirmed);
      rows.push({
        date: rec.d,
        split: split(rec.d),
        fwd20: rec.fwd.d20,
        fundamental: rec.c.fundamental,
        valuation: rec.c.valuation,
        supplyDemand: rec.c.supplyDemand ?? null,
        techBaseline: weightedAverage([
          { score: maScore, weight: 0.35 }, { score: rsiScore, weight: 0.15 },
          { score: macdScore, weight: 0.25 }, { score: volScore, weight: 0.25 },
        ]),
        techExcludeMA: weightedAverage([
          { score: rsiScore, weight: 0.15 }, { score: macdScore, weight: 0.25 }, { score: volScore, weight: 0.25 },
        ]),
        techInvertMA: weightedAverage([
          { score: maScore === null ? null : 100 - maScore, weight: 0.35 }, { score: rsiScore, weight: 0.15 },
          { score: macdScore, weight: 0.25 }, { score: volScore, weight: 0.25 },
        ]),
      });
    });
  }
  console.log(`  ${rows.length}건`);

  function finalScoreOf(r, techField) {
    // supplyDemand는 2026-09-02 재백필(ce7a723)로 실제 값이 들어왔다. 결측이면
    // weightedAverage가 null 항목을 빼고 나머지 가중치로 재정규화하므로(A5 실제
    // 동작과 동일) 구·신 백필 어느 쪽에도 그대로 쓸 수 있다.
    return weightedAverage([
      { score: r.fundamental, weight: catWeights.fundamental },
      { score: r.valuation, weight: catWeights.valuation },
      { score: r[techField], weight: catWeights.technical },
      { score: r.supplyDemand, weight: catWeights.supplyDemand },
    ]);
  }

  function report(subset, label) {
    console.log(`\n--- ${label} (n=${subset.length}) ---`);
    for (const [name, techField] of [
      ['원본(MA크로스 포함)', 'techBaseline'],
      ['변형B: MA크로스 제외', 'techExcludeMA'],
      ['변형C: MA크로스 반전', 'techInvertMA'],
    ]) {
      const pairs = [];
      const bucket = {};
      for (const r of subset) {
        const fin = finalScoreOf(r, techField);
        if (fin === null) continue;
        pairs.push({ x: fin, y: r.fwd20 });
        const g = gradeFromScore(fin);
        (bucket[g] = bucket[g] || []).push(r.fwd20);
      }
      const ic = pairs.length >= 30 ? spearmanIC(pairs) : null;
      const gradeStr = ['A', 'B', 'C', 'D', 'E'].map(g => {
        const v = bucket[g];
        if (!v || !v.length) return `${g}=n/a`;
        const avg = (v.reduce((a, b) => a + b, 0) / v.length * 100).toFixed(2);
        const win = (v.filter(x => x > 0).length / v.length * 100).toFixed(1);
        return `${g}(n=${v.length},avg=${avg}%,win=${win}%)`;
      }).join('  ');
      console.log(`  ${name.padEnd(24)} n=${pairs.length}  IC=${ic !== null ? ic.toFixed(4) : 'n/a'}`);
      console.log(`    ${gradeStr}`);
    }
  }

  const byS = { TRAIN: [], VALID: [], TEST: [] };
  for (const r of rows) byS[r.split].push(r);
  report(byS.TRAIN, 'TRAIN 2016-01~2021-12');
  report(byS.VALID, 'VALID 2022-01~2023-06');
  report(byS.TEST, 'TEST  2023-07~2025-12');
}

main().catch(e => { console.error(e); process.exit(1); });
