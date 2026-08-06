/**
 * A5 피처 레지스트리 — 어떤 지표가 어느 소스에서 오는가, 지금 공급 가능한가.
 *
 * criteria(KR-2.2)는 '무엇을 채점하는가'를 정하고 여기는 '그것을 어디서 가져오는가'를
 * 정한다. 둘을 한 파일에 두면 동결된 criteria를 소스 사정 때문에 고치게 된다 —
 * criteria는 불변 스냅샷이고 소스는 계속 바뀐다.
 *
 * **가장 중요한 것은 available 플래그다.** "지금 백필로 채점이 되는가"를 문서의
 * 주장이 아니라 **값**으로 만든다. A3b가 들어오면 이 파일의 플래그 몇 개가 true로
 * 바뀌고 availableWeight()의 수치가 따라 움직인다 — 사람이 문서를 고쳐 맞추는 것이
 * 아니라 코드가 스스로 답한다.
 *
 * 게이트로 쓰지 않는다. 이 값은 '착수 가능한가'가 아니라 '운영 투입 가능한가'를
 * 답한다 — 프레임워크는 available이 false인 피처가 있어도 구현되고 테스트된다.
 * 결측은 정상 경로이며 missingAxis.renormalize와 confidence.coverage가 받는다.
 */
'use strict';

/**
 * stage — 그 피처를 공급하는 백필 단계.
 * available — 지금 그 단계가 실제로 그 값을 주는가. 스펙이 아니라 실측이다.
 * blockedBy — false인 이유. 사람이 읽고 무엇을 만들지 정하는 자리다.
 */
const FEATURES = {
  // ── fundamental ────────────────────────────────────────────
  roe:                  { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['netIncome', 'equity'] },
  roeConsistency:       { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['netIncome', 'equity'], history: 5,
                          note: 'roeHistory5y. 연도마다 PIT 선택을 따로 한다(교훈47)' },
  debtRatio:            { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['liabilities', 'equity'] },
  currentRatio:         { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['currentAssets', 'currentLiab'],
                          note: '금융업은 양식상 부재. null이 정상이다(교훈48)' },
  operatingMarginTrend: { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['opProfit', 'revenue'], history: 2 },
  revenueGrowthYoY:     { category: 'fundamental', stage: 'A3', available: true,
                          needs: ['revenue'], history: 2 },
  shareholderReturn:    { category: 'fundamental', stage: 'A3b', available: false,
                          needs: ['dividendPerShare'],
                          blockedBy: 'alotMatter 미수집 — 주요계정에 배당 항목이 없다' },

  // ── valuation ──────────────────────────────────────────────
  perRelative:          { category: 'valuation', stage: 'A3b', available: false,
                          needs: ['eps', 'close', 'sicCode'], crossSectional: true,
                          blockedBy: 'EPS 미수집 (alotMatter)',
                          note: '업종 중앙값 대비. 평균이 아니다 — 적자 종목의 PER이 튄다' },
  pbr:                  { category: 'valuation', stage: 'A3b', available: false,
                          needs: ['equity', 'sharesOutstanding', 'close'],
                          blockedBy: '발행주식총수가 파이프라인 어디에도 없다' },
  peg:                  { category: 'valuation', stage: 'A3b', available: false,
                          needs: ['eps', 'close'], history: 2,
                          blockedBy: 'PER 기반이라 EPS를 따라간다' },
  marginOfSafety:       { category: 'valuation', stage: null, available: false,
                          needs: ['intrinsicValue'],
                          blockedBy: 'criteria가 "자동화 난이도 높음"을 명시한다. 소스 미정' },

  // ── technical ──────────────────────────────────────────────
  // 개별 지표를 나열하지 않는다. 전부 같은 입력(OHLCV)에서 나오고 지표별로 소스가
  // 갈리지 않으므로, 갈리지 않는 축을 쪼개면 표만 길어지고 잡는 것이 없다.
  __technical:          { category: 'technical', stage: 'A2a+A2b', available: true,
                          needs: ['ohlcv'], wholeCategory: true },

  // ── supplyDemand ───────────────────────────────────────────
  __supplyDemand:       { category: 'supplyDemand', stage: 'A4', available: false,
                          needs: ['flows'], wholeCategory: true,
                          blockedBy: 'A4 인수 조건 미정. 가용성만 확인됨(naver 축)' },
};

/**
 * 카테고리 안에서 그 피처가 차지하는 비중. criteria의 metric weight를 읽는다 —
 * 여기에 숫자를 복사하면 criteria를 고칠 때 두 곳이 갈린다.
 */
function metricWeight(criteria, category, key) {
  const m = criteria[category] && criteria[category].metrics;
  if (!m || !m[key]) return null;
  const w = m[key].weight;
  return typeof w === 'number' ? w : null;
}

/**
 * 지금 공급 가능한 가중치의 합. criteria의 categoryWeights × 카테고리 내 가용 비중.
 *
 * 이 값이 minimumDataCoverage 미만이면 **운영 투입**이 막힌다 — 구현이 막히는 것이
 * 아니다. 둘을 섞으면 "점수가 안 나오니 개발도 못 한다"가 되어, 결측을 정상 경로로
 * 다루는 이 엔진의 설계(missingAxis.renormalize)와 정면으로 어긋난다.
 */
function availableWeight(criteria) {
  const cw = criteria.categoryWeights || {};
  const byCategory = {};
  let total = 0;

  for (const category of Object.keys(cw)) {
    const entries = Object.entries(FEATURES).filter(([, f]) => f.category === category);
    const whole = entries.find(([, f]) => f.wholeCategory);
    let frac;
    if (whole) {
      // 카테고리 통째로 가용/불가. 지표별로 소스가 갈리지 않는 축이다.
      frac = whole[1].available ? 1 : 0;
    } else {
      // 지표별 가중의 합. criteria에 weight가 없는 지표는 분모에서도 빠진다 —
      // 0으로 읽으면 분모가 커져 가용 비율이 실제보다 낮게 나온다(모르는 것은 0이 아니다).
      let ok = 0, all = 0;
      for (const [key, f] of entries) {
        const w = metricWeight(criteria, category, key);
        if (w === null) continue;
        all += w;
        if (f.available) ok += w;
      }
      frac = all > 0 ? ok / all : 0;
    }
    byCategory[category] = { weight: cw[category], availableFraction: round4(frac),
                             contribution: round4(cw[category] * frac) };
    total += cw[category] * frac;
  }
  return { total: round4(total), byCategory };
}

/** 무엇이 막고 있는가 — 사람이 읽고 다음 단계를 정하는 표. */
function blockers() {
  return Object.entries(FEATURES)
    .filter(([, f]) => !f.available)
    .map(([key, f]) => ({ key, category: f.category, stage: f.stage,
                          blockedBy: f.blockedBy || null }));
}

/** 그 단계가 들어오면 얼마가 열리는가. A3b를 할지 말지의 근거가 되는 수치다. */
function weightUnlockedBy(criteria, stage) {
  const before = availableWeight(criteria).total;
  const patched = {};
  for (const [k, f] of Object.entries(FEATURES)) {
    patched[k] = f.stage === stage ? { ...f, available: true } : f;
  }
  const saved = Object.assign({}, FEATURES);
  try {
    Object.keys(FEATURES).forEach((k) => { FEATURES[k] = patched[k]; });
    return round4(availableWeight(criteria).total - before);
  } finally {
    Object.keys(saved).forEach((k) => { FEATURES[k] = saved[k]; });
  }
}

function round4(n) {
  return Math.round(n * 10000) / 10000;
}

module.exports = { FEATURES, availableWeight, blockers, weightUnlockedBy, metricWeight };
