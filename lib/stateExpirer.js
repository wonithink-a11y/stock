'use strict';

/**
 * TTL 만료 전담. Reducer는 이벤트만 처리하고 시간 경과는 여기서만 다룬다.
 *
 * REDUCE-007이 activatedAt을 최초 발생 시점으로 고정하므로, activeMeta를 걷어내는 주체는
 * 이 함수뿐이다. 배치가 돌지 않으면 만료된 위험이 영구히 남고, 이후 같은 위험이 새로
 * 발생해도 Reducer가 기존 meta를 재사용해 즉시 만료 대상이 된다.
 */

/**
 * ttlDays 의미: null/undefined = 만료 없음(해제 공시로만 풀림), 0 = 즉시 만료, N = N일 경과 시 만료.
 * Reducer의 `rule.ttlDays ?? null`과 같은 규약이다.
 *
 * @param {object} state    ST-1.0 state
 * @param {string} nowIso   기준 시각(KST ISO)
 * @returns {object}        만료 대상이 없으면 입력과 **동일 참조**를 반환한다(= 쓰기 없음)
 */
function expireState(state, nowIso) {
  const now = Date.parse(nowIso);
  if (Number.isNaN(now)) throw new Error(`Invalid nowIso: ${nowIso}`);
  if (!Array.isArray(state.activeMeta) || !Array.isArray(state.riskStates)) {
    throw new Error(`Invalid state: ${state && state.ticker}`);
  }

  const expired = [];
  const keptMeta = state.activeMeta.filter((m) => {
    if (m.ttlDays == null) return true;                // null/undefined만 "TTL 없음". 0은 즉시 만료다
    const at = Date.parse(m.activatedAt);
    if (Number.isNaN(at)) return true;                 // 판독 불가 → 유지. 임의 삭제하지 않는다
    if ((now - at) / 86400000 < m.ttlDays) return true;
    expired.push(m.code);
    return false;
  });

  if (expired.length === 0) return state;

  // 만료된 코드만 제거한다. meta가 없는 riskStates(구버전·수동 주입)는 건드리지 않는다.
  const gone = new Set(expired);
  return {
    ...state,
    riskStates: state.riskStates.filter((c) => !gone.has(c)),
    activeMeta: keptMeta,
    updatedAt: nowIso,          // lastSortKey는 이벤트 커서이므로 절대 건드리지 않는다(REDUCE-006)
  };
}

module.exports = { expireState };
