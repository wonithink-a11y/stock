/**
 * backtester.js (v2.1 - 시장 국면 조건부 분석 추가)
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
 *   benchmarkReturns: { d20: 1.1, d60: 3.0, d120: 5.5 },   // 같은 기간 KOSPI/KOSDAQ 수익률(%)
 *   regimeGrade: 'favorable'       // (선택) 그 시점 시장 국면 - marketRegimeEngine 산출
 * }
 *
 * ─ v2.1 추가 ─
 * 시장 국면(regime) 조건부 분석: "국면이 우호적일 때만 진입했다면 승률이 어땠나"를 산출합니다.
 * 국면 정보는 아래 순서로 찾습니다(기존 스냅샷을 고치지 않아도 소급 적용 가능):
 *   1) snap.regimeGrade
 *   2) snap.regime.grade
 *   3) snap.stockData.marketRegime.grade
 *   4) options.regimeByDate[snap.date]   ← 과거 regime.json 이력을 날짜별 맵으로 주입
 * 국면 정보가 하나도 없으면 regimeAnalysis.available=false 로 반환하고
 * 나머지 결과는 기존과 100% 동일합니다.
 *
 * 핵심 산출물:
 *  1. 등급별 성과: A등급이 정말 B~E보다 잘 갔는가 (단조성 검증)
 *  2. IC (Information Coefficient): 점수 순위와 수익률 순위의 스피어만 상관계수.
 *  3. 승률·벤치마크 대비 초과수익: 거래비용 차감 후 기준
 *  4. 국면별 성과 + 국면×등급 교차표 + "국면 필터의 효과" 비교
 *
 * ⚠️ look-ahead bias 주의: 스냅샷의 stockData·regimeGrade 에 기준일 이후 정보가
 * 섞이면 백테스트가 낙관적으로 왜곡됩니다. 국면 역시 "그날 알 수 있었던 국면"이어야 합니다.
 */

const { scoreStock } = require('./scoringEngine');

// 스피어만 순위 상관계수
function spearmanIC(pairs) {
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

function r2(v) {
  return v === null || v === undefined ? null : Math.round(v * 100) / 100;
}

function gradeKey(grade) {
  if (!grade) return 'N/A';
  return grade.charAt(0); // 'A (강력 매수 후보)' → 'A'
}

/** 스냅샷에서 시장 국면을 찾는다 (여러 경로 지원, 없으면 null) */
function regimeOf(snap, regimeByDate) {
  if (snap.regimeGrade) return snap.regimeGrade;
  if (snap.regime && snap.regime.grade) return snap.regime.grade;
  if (snap.stockData && snap.stockData.marketRegime && snap.stockData.marketRegime.grade) {
    return snap.stockData.marketRegime.grade;
  }
  if (regimeByDate && snap.date && regimeByDate[snap.date]) return regimeByDate[snap.date];
  return null;
}

/** 버킷(스코어링된 스냅샷 배열)의 기간별 성과 통계 */
function computeHorizonStats(bucket, horizons, cost) {
  const stats = {};
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

    stats[h] = {
      count: returns.length,
      avgReturnPct: r2(mean(returns)),
      medianReturnPct: r2(median(returns)),
      winRatePct: returns.length > 0 ? Math.round((returns.filter((r) => r > 0).length / returns.length) * 1000) / 10 : null,
      avgExcessVsBenchmarkPct: r2(mean(excess)),
      // 기대값 = 승률×평균이익 − 패률×평균손실 (승률만 보는 착시 방지)
      expectancyPct: returns.length > 0 ? r2(mean(returns)) : null,
      payoffRatio: (() => {
        const wins = returns.filter((r) => r > 0);
        const losses = returns.filter((r) => r <= 0).map((r) => Math.abs(r));
        const aw = mean(wins);
        const al = mean(losses);
        return aw !== null && al !== null && al !== 0 ? Math.round((aw / al) * 100) / 100 : null;
      })(),
    };
  }
  return stats;
}

/** 버킷의 IC */
function bucketIC(bucket, horizons) {
  const ic = {};
  for (const h of horizons) {
    const v = spearmanIC(
      bucket.map((s) => ({ x: s.score, y: s.snap.forwardReturns ? s.snap.forwardReturns[h] : undefined }))
    );
    ic[h] = v === null ? null : Math.round(v * 1000) / 1000;
  }
  return ic;
}

/**
 * @param {Array} snapshots - 위 형식의 스냅샷 배열
 * @param {object} criteria - criteria.json (미제공시 scoreStock이 기본 로드)
 * @param {object} options - {
 *   horizons: ['d20','d60','d120'],
 *   transactionCostPct: 0.3,
 *   regimeByDate: { '2026-07-17': 'favorable', ... },   // 선택: 과거 국면 이력 주입
 *   favorableRegimes: ['favorable'],                    // '우호적'으로 볼 국면
 *   entryGrades: ['A','B'],                             // 진입 대상 등급
 * }
 */
function runBacktest(snapshots, criteria, options = {}) {
  const horizons = options.horizons || ['d20', 'd60', 'd120'];
  const cost = options.transactionCostPct !== undefined ? options.transactionCostPct : 0.3;
  const favorableRegimes = options.favorableRegimes || ['favorable'];
  const entryGrades = options.entryGrades || ['A', 'B'];

  // 1. 전 스냅샷 스코어링
  const scored = snapshots.map((snap) => {
    const result = scoreStock(snap.stockData, criteria);
    return {
      snap,
      score: result.totalScore,
      grade: gradeKey(result.grade),
      coverage: result.dataCoverage,
      regime: regimeOf(snap, options.regimeByDate),
    };
  });

  const usable = scored.filter((s) => s.score !== null);

  // 2. 등급별 버킷 성과
  const gradeOrder = ['A', 'B', 'C', 'D', 'E'];
  const byGrade = {};
  for (const g of gradeOrder) {
    const bucket = usable.filter((s) => s.grade === g);
    if (bucket.length === 0) continue;
    byGrade[g] = { count: bucket.length, horizons: computeHorizonStats(bucket, horizons, cost) };
  }

  // 3. IC (점수 ↔ 미래수익률 순위 상관)
  const ic = bucketIC(usable, horizons);

  // 4. 등급 단조성 (첫 번째 horizon 기준)
  const h0 = horizons[0];
  const gradeAvgs = gradeOrder
    .filter((g) => byGrade[g] && byGrade[g].horizons[h0].avgReturnPct !== null)
    .map((g) => ({ grade: g, avg: byGrade[g].horizons[h0].avgReturnPct }));
  let monotonic = true;
  for (let i = 1; i < gradeAvgs.length; i++) {
    if (gradeAvgs[i - 1].avg <= gradeAvgs[i].avg) monotonic = false;
  }

  // 5. ★ 시장 국면 조건부 분석
  const withRegime = usable.filter((s) => s.regime);
  const regimeAnalysis = buildRegimeAnalysis(withRegime, usable, {
    horizons, cost, h0, favorableRegimes, entryGrades,
  });

  // 6. 판정 요약
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
  verdicts.push(...regimeAnalysis.verdicts);

  return {
    sampleCount: usable.length,
    transactionCostPct: cost,
    ic,
    byGrade,
    gradeMonotonic: monotonic,
    regimeAnalysis,
    verdicts,
  };
}

/** 국면별 · 국면×등급 · 국면필터 효과 */
function buildRegimeAnalysis(withRegime, usable, ctx) {
  const { horizons, cost, h0, favorableRegimes, entryGrades } = ctx;

  if (withRegime.length === 0) {
    return {
      available: false,
      reason:
        '스냅샷에 시장 국면(regimeGrade) 정보가 없습니다. 수집 시 regimeGrade 를 기록하거나, ' +
        'runBacktest 의 options.regimeByDate 로 과거 국면 이력을 주입하세요.',
      verdicts: [],
    };
  }

  // 국면별 성과
  const regimeNames = [...new Set(withRegime.map((s) => s.regime))];
  const byRegime = {};
  for (const r of regimeNames) {
    const bucket = withRegime.filter((s) => s.regime === r);
    byRegime[r] = {
      count: bucket.length,
      horizons: computeHorizonStats(bucket, horizons, cost),
      ic: bucketIC(bucket, horizons),
    };
  }

  // 국면 × 등급 교차표
  const gradeOrder = ['A', 'B', 'C', 'D', 'E'];
  const byRegimeAndGrade = {};
  for (const r of regimeNames) {
    byRegimeAndGrade[r] = {};
    for (const g of gradeOrder) {
      const bucket = withRegime.filter((s) => s.regime === r && s.grade === g);
      if (bucket.length === 0) continue;
      byRegimeAndGrade[r][g] = { count: bucket.length, horizons: computeHorizonStats(bucket, horizons, cost) };
    }
  }

  // ★ 국면 필터 효과: 진입등급(A·B) 전 구간 vs 우호 국면만 vs 비우호 국면만
  const isFav = (s) => favorableRegimes.includes(s.regime);
  const entry = withRegime.filter((s) => entryGrades.includes(s.grade));
  const all = entry;
  const fav = entry.filter(isFav);
  const unfav = entry.filter((s) => !isFav(s));

  const filterComparison = {
    entryGrades,
    favorableRegimes,
    allRegimes: { count: all.length, horizons: computeHorizonStats(all, horizons, cost) },
    favorableOnly: { count: fav.length, horizons: computeHorizonStats(fav, horizons, cost) },
    unfavorableOnly: { count: unfav.length, horizons: computeHorizonStats(unfav, horizons, cost) },
  };

  // 국면 필터가 실제로 엣지를 주는가
  const a = filterComparison.allRegimes.horizons[h0];
  const f = filterComparison.favorableOnly.horizons[h0];
  const u = filterComparison.unfavorableOnly.horizons[h0];
  filterComparison.edge = {
    horizon: h0,
    winRateDeltaPp: f.winRatePct !== null && a.winRatePct !== null ? Math.round((f.winRatePct - a.winRatePct) * 10) / 10 : null,
    avgReturnDeltaPct: f.avgReturnPct !== null && a.avgReturnPct !== null ? r2(f.avgReturnPct - a.avgReturnPct) : null,
    favVsUnfavReturnPct: f.avgReturnPct !== null && u.avgReturnPct !== null ? r2(f.avgReturnPct - u.avgReturnPct) : null,
  };

  // 판정
  const verdicts = [];
  const coveragePct = Math.round((withRegime.length / usable.length) * 100);
  if (coveragePct < 100) {
    verdicts.push(`국면 정보가 있는 스냅샷은 ${withRegime.length}/${usable.length}건(${coveragePct}%)입니다.`);
  }
  if (fav.length < 10 || unfav.length < 10) {
    verdicts.push(
      `국면별 표본이 부족합니다(우호 ${fav.length}건 / 비우호 ${unfav.length}건). ` +
        '각 30건 이상 쌓이기 전 결과는 참고용으로만 보세요.'
    );
  }
  const d = filterComparison.edge;
  if (d.avgReturnDeltaPct !== null) {
    if (d.avgReturnDeltaPct > 0 && (d.winRateDeltaPp === null || d.winRateDeltaPp >= 0)) {
      verdicts.push(
        `국면 필터 효과(+): 우호 국면에서만 진입 시 평균수익 ${d.avgReturnDeltaPct > 0 ? '+' : ''}${d.avgReturnDeltaPct}%p, ` +
          `승률 ${d.winRateDeltaPp > 0 ? '+' : ''}${d.winRateDeltaPp}%p (전 구간 진입 대비, ${h0}).`
      );
    } else {
      verdicts.push(
        `국면 필터 효과 없음/음(-): 우호 국면 한정 진입이 전 구간 대비 평균수익 ${d.avgReturnDeltaPct}%p. ` +
          '사이클 필터가 엣지를 주지 못하고 있습니다(표본 부족일 수 있음).'
      );
    }
  }
  return { available: true, byRegime, byRegimeAndGrade, filterComparison, verdicts };
}

module.exports = { runBacktest, spearmanIC, regimeOf, computeHorizonStats };
