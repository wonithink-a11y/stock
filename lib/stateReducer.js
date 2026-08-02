'use strict';
function validatePolicy(p) { if (!p || !p.events) throw new Error('Invalid stateMapPolicy'); }
function validateEvent(e) {
  if (!e || !e.type) throw new Error('Invalid event');
  if (!e.occurredAt) throw new Error('Invalid event.occurredAt');
}
function validateState(s) {
  if (!s) throw new Error('Invalid prevState');
  if (!Array.isArray(s.riskStates)) throw new Error('Invalid state.riskStates');
  if (!Array.isArray(s.activeMeta)) throw new Error('Invalid state.activeMeta');
}

function reduce(prevState, event, stateMapPolicy) {
  validateState(prevState);
  validateEvent(event);
  validatePolicy(stateMapPolicy);

  const rule = stateMapPolicy.events[event.type];
  if (!rule) return prevState;

  const next = { ...prevState, updatedAt: event.occurredAt };
  if (rule.add) {
    next.riskStates = Array.from(new Set([...prevState.riskStates, rule.add]));
    next.activeMeta = [
      ...prevState.activeMeta.filter((m) => m.code !== rule.add),
      { code: rule.add, activatedAt: event.occurredAt, ttlDays: rule.ttlDays || null },
    ].sort((a, b) => a.code.localeCompare(b.code));
  } else if (rule.remove) {
    next.riskStates = prevState.riskStates.filter((s) => s !== rule.remove);
    next.activeMeta = prevState.activeMeta.filter((m) => m.code !== rule.remove);
  } else {
    next[rule.field] = rule.value;
  }
  return next;
}
module.exports = { reduce, validateState, validateEvent, validatePolicy };
