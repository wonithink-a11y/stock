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

const { scoreStock, score } = require('./scoringEngine');

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

/**
 * V2는 grade를 저장하지 않는다(UI가 계산 — 프로젝트_현황.md §5).
 * 백테스트는 등급별 버킷 성과를 봐야 하므로 여기서만 동일 임계값으로 계산한다.
 * 이 값은 backtester 내부 집계용일 뿐 ScoreResult 스키마에 추가되지 않는다.
 */
function gradeFromScore(finalScore) {
  if (finalScore === null || finalScore === undefined) return 'N/A';
  if (finalScore >= 80) return 'A';
  if (finalScore >= 65) return 'B';
  if (finalScore >= 50) return 'C';
  if (finalScore >= 35) return 'D';
  return 'E';
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

/**
 * 표본 편입 조건 — **채점 엔진이 모집단을 정하지 않는다.**
 *
 * 엔진은 coverage 를 계산하고 여기가 그 값으로 판정한다. V1 의 grade 문자열
 * ('유보 (데이터 커버리지 5% < 기준 60%)')을 판정에 쓰지 않는 이유가 둘이다 —
 * 엔진이 모집단을 끌고 가는 역전이고, gradeKey 가 charAt(0) 이라 '유' 로 깨진다.
 *
 * 사유는 **배타적**이며 우선순위가 고정이다. 겹치면 같은 스냅샷이 두 번 세어지고
 * excludedByReason 의 합이 excluded 와 어긋난다.
 *
 *   1  NOT_SCORED             score === null      — 뒤의 검사를 하지 않는다
 *   2  INSUFFICIENT_COVERAGE  coverage 미달
 *   3  PIT_INVALID            dataCutoff 가 스냅샷 기준일보다 뒤다 (look-ahead)
 *   -  eligible
 *
 * ★ PIT 는 **잴 수 있을 때만** 잰다. dataCutoff 가 없는 것은 위반이 아니라 미측정이다.
 *   둘을 합치면 옛 스냅샷이 통째로 빠지고, 그것은 '검사해서 걸렀다'로 기록된다.
 *   원본 snap.stockData.dataCutoff 를 읽는다 — V2 경로가 채워 넣는 기본값
 *   (dataCutoff || snap.date)을 보면 이 검사는 구성상 항상 통과한다(교훈72).
 */

/** 통계적 판단의 최소 표본. horizon 단위로 적용한다. */
const MIN_SAMPLE = 30;

const EXCLUSION = {
  NOT_SCORED: 'NOT_SCORED',
  INSUFFICIENT_COVERAGE: 'INSUFFICIENT_COVERAGE',
  PIT_INVALID: 'PIT_INVALID',
  NO_FORWARD_RETURN: 'NO_FORWARD_RETURN',
};

/** 이 백테스터가 **잴 수단을 갖고 있지 않은** 축. 0으로 채우지 않는다(교훈57). */
const UNMEASURED_REASONS = [
  // 스냅샷에 폐지 여부가 없다. 붙이려면 A1b·A2b 조인이 필요하고 그것은 별도 작업이다.
  'DELISTED_STATUS_UNMEASURED',
  // dataCutoff 가 없는 스냅샷. '검사했는데 실패'(PIT_INVALID)와 다른 상태다.
  'PIT_STATUS_UNMEASURED',
];

function classifyBase(s) {
  if (s.score === null || s.score === undefined) return EXCLUSION.NOT_SCORED;
  if (!(s.coverage && s.coverage.sufficient)) return EXCLUSION.INSUFFICIENT_COVERAGE;
  const cutoff = s.snap && s.snap.stockData ? s.snap.stockData.dataCutoff : undefined;
  if (cutoff && s.snap.date && cutoff > s.snap.date) return EXCLUSION.PIT_INVALID;
  return null;
}

function hasForwardReturn(s, h) {
  return !!(s.snap.forwardReturns && typeof s.snap.forwardReturns[h] === 'number');
}

/** 버킷의 IC. 표본 수는 여기서 안 낸다 — runBacktest 가 icSampleCount 로 따로 준다. */
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
 *   policies: loadPolicies('KR'),                       // [P10] 있으면 V2 score() 사용, 없으면 V1 scoreStock() (기본, 하위호환)
 * }
 *
 * [P10] V2 경로 주의: 과거 스냅샷(docs/data/history/*.json)은 그 시점의 state(리스크 상태)를
 * 기록하지 않는다 — STEP2 state 쓰기가 히스토리보다 나중에 활성화됐다. 여기서 "현재" state를
 * 과거 스냅샷에 갖다 붙이면 look-ahead bias(미래 정보 유입)가 된다. 그래서 snap.stockData.state가
 * 없으면 riskPenalty=0으로 채점한다(정직한 결측 — 있지도 않은 리스크를 지어내지 않는다).
 * analyze.js가 history 스냅샷에 state를 함께 기록하기 시작한 날짜 이후 데이터부터
 * riskPenalty가 실제로 반영된다.
 */
function runBacktest(snapshots, criteria, options = {}) {
  const horizons = options.horizons || ['d20', 'd60', 'd120'];
  const cost = options.transactionCostPct !== undefined ? options.transactionCostPct : 0.3;
  const favorableRegimes = options.favorableRegimes || ['favorable'];
  const entryGrades = options.entryGrades || ['A', 'B'];

  // 1. 전 스냅샷 스코어링 — options.policies 유무로 V1/V2 분기 (하위호환: 없으면 기존 V1 그대로)
  const scored = snapshots.map((snap) => {
    if (options.policies) {
      const stockDataV2 = { ...snap.stockData, dataCutoff: snap.stockData.dataCutoff || snap.date };
      const envelope = score(stockDataV2, criteria, options.policies);
      const r = envelope.result;
      return {
        snap,
        score: r.finalScore,
        grade: gradeFromScore(r.finalScore),
        coverage: { sufficient: r.confidence.value !== null && r.confidence.value >= 60, coveragePct: r.confidence.coverage },
        regime: regimeOf(snap, options.regimeByDate),
      };
    }
    const result = scoreStock(snap.stockData, criteria);
    return {
      snap,
      score: result.totalScore,
      grade: gradeKey(result.grade),
      coverage: result.dataCoverage,
      regime: regimeOf(snap, options.regimeByDate),
    };
  });

  // 1.5 표본 편입 — score !== null 은 조건이 아니라 조건의 부재였다. coverage 는
  //     두 엔진 모두 이미 계산해 두고(188·197행) 아무도 쓰지 않았다.
  const excludedByReason = {};
  const usable = [];
  for (const s of scored) {
    const why = classifyBase(s);
    if (why) excludedByReason[why] = (excludedByReason[why] || 0) + 1;
    else usable.push(s);
  }
  const pitMeasurable = scored.filter(
    (s) => s.snap && s.snap.stockData && s.snap.stockData.dataCutoff).length;

  // horizon 단위 편입. 최근 스냅샷은 d20 은 있고 d120 이 없다 — 하나의 boolean 으로
  // 묶으면 그 스냅샷이 d20 분석에서까지 빠지거나(과소), 반대로 d120 IC 만 조용히
  // 작아진다. 그러면 "IC 를 어떤 종목으로 계산했는가"에 답할 수 없다.
  const byHorizon = {};
  const icSampleCount = {};
  for (const h of horizons) {
    const n = usable.filter((s) => hasForwardReturn(s, h)).length;
    icSampleCount[h] = n;
    byHorizon[h] = {
      eligible: n,
      excludedByReason: { [EXCLUSION.NO_FORWARD_RETURN]: usable.length - n },
    };
  }

  const population = {
    totalCandidates: scored.length,
    // horizon 과 무관한 기본 모집단. byHorizon.*.eligible 과 이름을 섞지 않는다 —
    // 저쪽이 실제 IC 계산 표본이다.
    eligible: usable.length,
    excluded: scored.length - usable.length,
    excludedByReason,
    byHorizon,
    unmeasuredReasons: UNMEASURED_REASONS,
    // 못 잰 것을 0으로 적지 않되, 얼마나 잴 수 있었는지는 남긴다.
    pitCheckedCount: pitMeasurable,
    pitUnmeasuredCount: scored.length - pitMeasurable,
  };

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
  // 표본 부족은 horizon 단위로 판정한다. usable.length 로 재면 forward return 이 없는
  // 스냅샷까지 세어 실제 IC 표본보다 큰 수를 보게 된다 — d20 은 147건인데 d120 은
  // 21건인 상태가 '표본 147건'으로 뭉뚱그려진다.
  const thin = horizons.filter((h) => icSampleCount[h] < MIN_SAMPLE);
  if (thin.length) {
    verdicts.push(
      `표본 부족: ${thin.map((h) => `${h} ${icSampleCount[h]}건`).join(' · ')} ` +
      `(최소 ${MIN_SAMPLE}건, 권장 100건). 이 구간의 IC·등급 성과는 판단 근거가 되지 않습니다.`
    );
  }
  if (population.excluded > 0) {
    const parts = Object.entries(excludedByReason).map(([k, v]) => `${k} ${v}`).join(' · ');
    verdicts.push(
      `후보 ${population.totalCandidates}건 중 ${population.eligible}건이 표본이고 ` +
      `${population.excluded}건을 제외했습니다 (${parts}). ` +
      `폐지 여부와 PIT 는 이 백테스터가 재지 못합니다 — population.unmeasuredReasons 참조.`
    );
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
    // horizon 과 무관한 기본 표본 수. IC 표본은 horizon 마다 다르므로 icSampleCount 를 본다.
    sampleCount: usable.length,
    transactionCostPct: cost,
    ic,
    // ic[h] 는 숫자 형태를 유지한다(소비자 스키마 보존). 표본 수는 여기서 따로 준다 —
    // 없으면 IC 0.02 가 21건에서 나온 것인지 147건에서 나온 것인지 알 수 없다.
    icSampleCount,
    population,
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

module.exports = {
  runBacktest, spearmanIC, regimeOf, computeHorizonStats, gradeFromScore,
  // 표본 편입 계약. 회귀가 이 둘을 직접 밟는다 — runBacktest 를 통해서만 보면
  // 우선순위가 뒤집혀도 합계가 맞아 통과한다.
  classifyBase, EXCLUSION, UNMEASURED_REASONS, MIN_SAMPLE,
};
