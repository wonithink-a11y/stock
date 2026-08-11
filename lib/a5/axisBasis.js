/**
 * 축 basis — **"이 점수는 어떤 축 집합 위에서 매겨졌는가."**
 *
 * 재정규화(MA-1.0)는 이미 구현돼 있고 결측 축을 뺀 나머지로 점수를 낸다. 남은 문제는
 * 계산이 아니라 **비교**다 — 서로 다른 축 집합 위에서 매겨진 두 점수를 한 순위표에
 * 놓으면 같은 회사 품질이 다른 모델로 채점된 채 나란히 선다.
 *
 * 실측 (fundamental·technical 입력이 완전히 동일한 두 종목):
 *
 *   EPS 있음   {F 41.1, V 35.3, T 17.9, S null}   실효 가중치 F 43.75 · V 37.50 · T 18.75
 *   EPS 없음   {F 65.8, V null,  T 28.7, S null}   실효 가중치 F 70.00 · T 30.00
 *   flags      양쪽 모두 ["LOW_CONFIDENCE","MISSING_DATA","PARTIAL_CALCULATION"] — 동일
 *
 * 그래서 basis는 **선언이 먼저 있고 관측이 그것과 대조돼야 한다.** 관측에서 basis를
 * 유도해 그 관측을 검사하면 항상 통과한다(교훈72). 선언은 SB-1.0에 있다.
 *
 * **이 모듈은 판정하지 않는다 — 판정에 필요한 사실을 만든다.** withhold 여부는 소비자가
 * 정한다(백테스트 표본 편입에서 '채점 엔진이 모집단을 정하지 않는다'로 가른 것과 같다).
 */
'use strict';

/**
 * 축이 basis에 드는 조건은 둘이다 — 점수가 있고, **가중치가 0이 아니다.**
 *
 * 둘째가 없으면 US가 오판된다. US-2.2는 supplyDemand 가중치를 0으로 선언했으므로
 * 그 축에 값이 들어와도 점수에 기여하지 않는다. 기여하지 않는 축 때문에 종목을
 * 빼면 0을 곱할 값이 있고 없고로 모집단이 갈린다.
 *
 * @param axisScores {{[axis]: number|null}} 축 점수. V1은 breakdown.<axis>.score,
 *        V2는 components.<axis>가 같은 자리에서 null이 된다(둘 다 축 전체가 비었을 때만).
 * @param categoryWeights criteria.categoryWeights
 * @returns {string[]} 정렬된 축 이름. 정렬하는 이유는 basisKey가 순서에 흔들리지 않기 위해서다
 */
function basisOf(axisScores, categoryWeights) {
  const w = categoryWeights || {};
  return Object.keys(w)
    .filter((a) => w[a] > 0 && axisScores[a] !== null && axisScores[a] !== undefined)
    .sort();
}

/** 비교용 단일 키. 사람이 읽고 로그에서 grep 할 수 있어야 한다. */
function basisKey(basis) {
  return basis.length ? basis.join('+') : '(없음)';
}

/**
 * criteria가 정의하는 **완전한** 모델의 축 집합. 가중치 0인 축은 여기에도 없다.
 * 선언 basis가 이것과 같으면 그 모델이 곧 운영 모델이고, 좁으면 제한된 모델이다.
 */
function operationalBasis(criteria) {
  const w = (criteria && criteria.categoryWeights) || {};
  return Object.keys(w).filter((a) => w[a] > 0).sort();
}

/** 선언된 모델을 꺼낸다. 없는 id는 조용히 기본값으로 대체하지 않는다 — 미선언과 오타를 가른다. */
function resolveModel(scoreBasisPolicy, modelId) {
  const models = (scoreBasisPolicy && scoreBasisPolicy.models) || {};
  const m = models[modelId];
  if (!m) {
    throw new Error(
      `axisModel '${modelId}'가 ${scoreBasisPolicy && scoreBasisPolicy.version}에 없다. ` +
      `선언된 것: ${Object.keys(models).join(' · ') || '(없음)'}`
    );
  }
  return { id: modelId, ...m, basis: [...m.basis].sort() };
}

/** 그 종목이 선언 basis 위에서 채점됐는가. 넓어도(축이 더 살아도) 다른 모델이다. */
function matchesModel(basis, model) {
  return basisKey(basis) === basisKey(model.basis);
}

/**
 * 산출물에 실을 스탬프. **서로 다른 모델이라는 사실이 결과에서 사라지지 않게 하는 자리다.**
 *
 * `matchesOperationalModel`은 저장된 선언이 아니라 criteria와의 대조로 매번 계산한다 —
 * 정책에 boolean으로 적어 두면 criteria가 바뀔 때 둘이 갈리고, 갈린 쪽이 참으로 읽힌다.
 */
function describeModel(model, criteria) {
  const opBasis = operationalBasis(criteria);
  return {
    axisModel: model.id,
    market: model.market,
    basis: model.basis,
    excludedAxes: model.excludedAxes || {},
    operationalBasis: opBasis,
    matchesOperationalModel: basisKey(model.basis) === basisKey(opBasis),
    ...(model.promotionRule ? { promotionRule: model.promotionRule } : {}),
  };
}

/** 선언하지 않은 실행. '검사해서 통과'가 아니라 '재지 않았다'로 남긴다(교훈57). */
const UNDECLARED_MODEL = {
  axisModel: 'UNDECLARED',
  note: 'axisModel을 선언하지 않은 실행이다. basis를 재지 않았으므로 이 산출물이 어느 모델인지 알 수 없다. population.unmeasuredReasons 참조.',
};

module.exports = {
  basisOf, basisKey, operationalBasis, resolveModel, matchesModel, describeModel,
  UNDECLARED_MODEL,
};
