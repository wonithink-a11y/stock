'use strict';

const STATE_SCHEMA_VERSION = 'ST-1.0';

function validatePolicy(p) {
  if (!p || !p.events) throw new Error('Invalid stateMapPolicy');
}

function validateEvent(e) {
  if (!e || !e.type) throw new Error('Invalid event');
  if (!e.occurredAt) throw new Error('Invalid event.occurredAt');
  if (!e.sortKey) throw new Error('Invalid event.sortKey');
}

function validateState(s) {
  if (!s) throw new Error('Invalid prevState');
  if (!Array.isArray(s.riskStates)) throw new Error('Invalid state.riskStates');
  if (!Array.isArray(s.activeMeta)) throw new Error('Invalid state.activeMeta');
}

function initState(ticker) {
  return {
    schemaVersion: STATE_SCHEMA_VERSION,
    ticker,
    listingStatus: 'NORMAL',
    tradingState: 'NORMAL',
    riskStates: [],
    activeMeta: [],
    lastSortKey: null,
    lastEventId: null,
    updatedAt: null,
  };
}

function reduce(prevState, event, stateMapPolicy) {
  validateState(prevState);
  validateEvent(event);
  validatePolicy(stateMapPolicy);

  // REDUCE-006: 이미 반영된 시점 이하의 이벤트는 무시(역순 방어 + 재실행 멱등)
  if (prevState.lastSortKey && event.sortKey <= prevState.lastSortKey) return prevState;

  const rule = stateMapPolicy.events[event.type];

  const next = {
    ...prevState,
    schemaVersion: STATE_SCHEMA_VERSION,
    lastSortKey: event.sortKey,
    lastEventId: event.eventId || null,
    updatedAt: event.occurredAt,
  };

  // 미매핑 이벤트(*_PENDING 등) → 상태는 그대로, 커서만 전진
  if (!rule) return next;

  if (rule.add) {
    // REDUCE-007: 같은 위험이 이미 활성이면 activatedAt을 보존한다(TTL 재설정 금지).
    // 유상증자 하나가 결정→발행가액→청약→발행결과→권리락으로 여러 건 공시되는데,
    // 매번 activatedAt을 갱신하면 30일 TTL이 실질 3개월로 늘어난다.
    // 이벤트 이력은 그대로 남는다 — next는 항상 새 객체라 커서·updatedAt은 전진하고 appendHistory도 실행된다.
    const existing = prevState.activeMeta.find((m) => m.code === rule.add);
    next.riskStates = Array.from(new Set([...prevState.riskStates, rule.add]));
    next.activeMeta = [
      ...prevState.activeMeta.filter((m) => m.code !== rule.add),
      existing
        ? { ...existing }
        : { code: rule.add, activatedAt: event.occurredAt, ttlDays: rule.ttlDays ?? null },
    ].sort((a, b) => a.code.localeCompare(b.code));
  } else if (rule.remove) {
    next.riskStates = prevState.riskStates.filter((s) => s !== rule.remove);
    next.activeMeta = prevState.activeMeta.filter((m) => m.code !== rule.remove);
  } else {
    next[rule.field] = rule.value;
  }

  return next;
}

module.exports = {
  reduce,
  initState,
  validateState,
  validateEvent,
  validatePolicy,
  STATE_SCHEMA_VERSION,
};
