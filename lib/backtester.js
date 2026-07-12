/**
 * backtester.js
 *
 * 스코어링 모델의 "검증 방식"을 담당하는 모듈.
 * recommendationTracker(앞으로의 기록)와 달리, 과거 시점 스냅샷 데이터로
 * 모델이 실제로 예측력이 있었는지를 소급 검증합니다.
 *
 * 입력 스냅샷 형식:
 * {
 *   date: '2024-03-15',            // 스냅샷 기준일
 *   stockData: { ... },            // 그 시점의 scoreStock() 입력 데이터 (미래 정보 포함 금지!)
 *   forwardReturns: { d20: 5.2, d60: 11.0, d120: 18.3 },   // 기준일 이후 실제 수익률(%)
 *   benchmarkReturns: { d20: 1.1, d60: 3.0, d120: 5.5 }    // 같은 기간 KOSPI/KOSDAQ 수익률(%)
 * }
 *
 * 핵심 산출물:
 *  1. 등급별 성과: A등급이 정말 B~E보다 잘 갔는가 (단조성 검증)
 *  2. IC (Information Coefficient): 점수 순위와 수익률 순위의 스피어만 상관계수.
 *     +0.05 이상이면 실무적으로 의미 있는 예측력, 0 근처면 점수가 무작위와 다름없음.
 *  3. 승률·벤치마크 대비 초과수익: 거래비용 차감 후 기준
 *
 * ⚠️ 주의: 스냅샷의 stockData에 기준일 이후 정보가 섞이면(예: 그 해 연간 실적을
 * 연초 스냅샷에 입력) 백테스트가 낙관적으로 왜곡됩니다(look-ahead bias).
 * 반드시 "그 시점에 알 수 있었던 데이터"만 넣으세요.
 */

const { scoreStock } = require('./scoringEngine');

// 스피어만 순위 상관계수
function spearmanIC(pairs) {
  // pairs: [{ x, y }]
  const valid = pairs.filter((p) => typeof p.x === 'number' && typeof p.y === 'number');
  const n = valid.length;
  if (n < 3) return null;

  const rank = (values) => {
    const sorted = values.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
    const ranks = new Array(n);
    sorted.forEach((item, r) => {
      ranks[item.i] = r + 1;
    });
    return ranks;
  };

  const rx = rank(valid.map((p) => p.x));
  const ry = rank(valid.map((p) => p.y));
  const dSquaredSum = rx.reduce((sum, r, i) => sum + (r - ry[i]) ** 2, 0);
  return 1 - (6 * dSquaredSum) / (n * (n * n - 1));
}

function mean(arr) {
  return arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
}

function median(arr) {
  if (arr.length === 0) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 === 0 ? (s[m - 1] + s[m]) / 2 : s[m];
}

function gradeKey(grade) {
  if (!grade) return 'N/A';
  return grade.charAt(0); // 'A (강력 매수 후보)' → 'A'
}

/**
 * @param {Array} snapshots - 위 형식의 스냅샷 배열
 * @param {object} criteria - criteria.json (미제공시 scoreStock이 기본 로드)
 * @param {object} options - { horizons: ['d20','d60','d120'], transactionCostPct: 0.3 }
 *   transactionCostPct: 왕복 거래비용(수수료+세금+슬리피지) 추정치. 기본 0.3%.
 */
function runBacktest(snapshots, criteria, options = {}) {
  const horizons = options.horizons || ['d20', 'd60', 'd120'];
  const cost = options.transactionCostPct !== undefined ? options.transactionCostPct : 0.3;

  // 1. 전 스냅샷 스코어링
  const scored = snapshots.map((snap) => {
    const result = scoreStock(snap.stockData, criteria);
    return { snap, score: result.totalScore, grade: gradeKey(result.grade), coverage: result.dataCoverage };
  });

  const usable = scored.filter((s) => s.score !== null);

  // 2. 등급별 버킷 성과
  const gradeOrder = ['A', 'B', 'C', 'D', 'E'];
  const byGrade = {};
  for (const g of gradeOrder) {
    const bucket = usable.filter((s) => s.grade === g);
    if (bucket.length === 0) continue;

    const horizonStats = {};
    for (const h of horizons) {
      const returns = bucket
        .map((s) => (s.snap.forwardReturns ? s.snap.forwardReturns[h] : undefined))
        .filter((r) => typeof r === 'number')
        .map((r) => r - cost); // 거래비용 차감
      const excess = bucket
        .map((s) => {
          const fr = s.snap.forwardReturns ? s.snap.forwardReturns[h] : undefined;
          const br = s.snap.benchmarkReturns ? s.snap.benchmarkReturns[h] : undefined;
          return typeof fr === 'number' && typeof br === 'number' ? fr - br - cost : undefined;
        })
        .filter((r) => typeof r === 'number');

      horizonStats[h] = {
        count: returns.length,
        avgReturnPct: mean(returns) !== null ? Math.round(mean(returns) * 100) / 100 : null,
        medianReturnPct: median(returns) !== null ? Math.round(median(returns) * 100) / 100 : null,
        winRatePct: returns.length > 0 ? Math.round((returns.filter((r) => r > 0).length / returns.length) * 1000) / 10 : null,
        avgExcessVsBenchmarkPct: mean(excess) !== null ? Math.round(mean(excess) * 100) / 100 : null,
      };
    }
    byGrade[g] = { count: bucket.length, horizons: horizonStats };
  }

  // 3. IC (점수 ↔ 미래수익률 순위 상관)
  const ic = {};
  for (const h of horizons) {
    ic[h] = spearmanIC(
      usable.map((s) => ({
        x: s.score,
        y: s.snap.forwardReturns ? s.snap.forwardReturns[h] : undefined,
      }))
    );
    if (ic[h] !== null) ic[h] = Math.round(ic[h] * 1000) / 1000;
  }

  // 4. 등급 단조성: 상위 등급 평균수익 > 하위 등급 평균수익인지 (첫 번째 horizon 기준)
  const h0 = horizons[0];
  const gradeAvgs = gradeOrder
    .filter((g) => byGrade[g] && byGrade[g].horizons[h0].avgReturnPct !== null)
    .map((g) => ({ grade: g, avg: byGrade[g].horizons[h0].avgReturnPct }));
  let monotonic = true;
  for (let i = 1; i < gradeAvgs.length; i++) {
    if (gradeAvgs[i - 1].avg <= gradeAvgs[i].avg) monotonic = false;
  }

  // 5. 판정 요약
  const verdicts = [];
  if (usable.length < 30) {
    verdicts.push(`표본 ${usable.length}건은 통계적 판단에 부족합니다. 최소 30건, 권장 100건 이상을 모으세요.`);
  }
  const icValues = horizons.map((h) => ic[h]).filter((v) => v !== null);
  if (icValues.length > 0) {
    const avgIC = mean(icValues);
    if (avgIC >= 0.05) verdicts.push(`평균 IC ${Math.round(avgIC * 1000) / 1000}: 점수에 유의미한 예측력이 있어 보입니다.`);
    else if (avgIC >= 0) verdicts.push(`평균 IC ${Math.round(avgIC * 1000) / 1000}: 예측력이 약합니다. 가중치 재조정 또는 지표 교체를 검토하세요.`);
    else verdicts.push(`평균 IC ${Math.round(avgIC * 1000) / 1000}: 점수가 오히려 역방향입니다. 모델 구조를 재검토하세요.`);
  }
  verdicts.push(
    monotonic && gradeAvgs.length >= 2
      ? '등급 단조성 충족: 상위 등급이 하위 등급보다 평균적으로 좋은 성과.'
      : '등급 단조성 불충족: 등급이 성과 순서를 예측하지 못합니다. categoryWeights 튜닝이 필요합니다.'
  );
  if (byGrade.A && byGrade.A.horizons[h0].avgExcessVsBenchmarkPct !== null && byGrade.A.horizons[h0].avgExcessVsBenchmarkPct <= 0) {
    verdicts.push('A등급이 거래비용 차감 후 벤치마크를 이기지 못했습니다. 이 상태로는 지수 추종보다 나을 근거가 없습니다.');
  }

  return {
    sampleCount: usable.length,
    transactionCostPct: cost,
    ic,
    byGrade,
    gradeMonotonic: monotonic,
    verdicts,
  };
}

module.exports = { runBacktest, spearmanIC };
