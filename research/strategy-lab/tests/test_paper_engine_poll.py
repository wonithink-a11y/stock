"""engine/live/paperEngine.py의 poll_once() 상태기계 self-check. FakeBroker만
쓴다 - 실제 KIS API는 호출하지 않는다(2026-08-21 사용자 지시 7번, "실제
KIS 모의계좌 주문이 발생하는 자동 실행 테스트는 아직 하지 말 것").

검증 대상(2026-08-21 사용자 지시 1~5번):
  1  enable_live_orders=False면 broker를 한 번도 안 부른다
  3  체결 확인이 주문번호 기반 check_fill()을 거친다(잔고 diff 아님)
  4  STOP/TARGET/TIME_EXIT 상태 전이가 positionStore와 일관됨
  5  미체결(pending)·거부(rejected) 상황에서 중복 매수/매도가 없다
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from engine.live import positionStore
from engine.live.paperEngine import poll_once

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STRATEGY_ID = "test_poll_engine_synth"
KST = timezone(timedelta(hours=9))


class FakeRule:
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "testUniverse": ["TEST1"],
        "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 3},
        "position": {"notionalPerPosition": 1000000, "maxPositions": 1},
    }


class FakeBroker:
    """제출 호출 횟수를 세고, 스크립트로 미리 정한 체결 결과를 순서대로
    돌려준다 - 진짜 비동기성(제출 != 즉시체결)을 흉내낸다."""
    def __init__(self, fill_script=None, price=100.0):
        self.buy_calls = 0
        self.sell_calls = 0
        self.check_fill_calls = 0
        self.current_price_calls = 0
        self._order_seq = 0
        self._fill_script = list(fill_script or [])
        self.price = price

    def submit_buy(self, symbol, quantity):
        self.buy_calls += 1
        self._order_seq += 1
        return f"ORD{self._order_seq}"

    def submit_sell(self, symbol, quantity):
        self.sell_calls += 1
        self._order_seq += 1
        return f"ORD{self._order_seq}"

    def check_fill(self, order_no, order_date, requested_qty):
        self.check_fill_calls += 1
        if self._fill_script:
            return self._fill_script.pop(0)
        return {"fullyFilled": False, "rejected": False, "filledQty": 0, "avgPrice": None, "pending": True}

    def current_price(self, symbol):
        self.current_price_calls += 1
        return self.price


passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _reset():
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def _seed(state):
    positionStore.save(REPO_ROOT, STRATEGY_ID, state)


def test_disabled_flag_never_touches_broker():
    _reset()
    _seed({"TEST1": {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-08-20"}})
    broker = FakeBroker()
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=False)
    ok("disabled: no events", events == [], events)
    ok("disabled: broker never called", broker.buy_calls == 0 and broker.check_fill_calls == 0)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("disabled: state untouched", state["TEST1"]["status"] == "PENDING_ENTRY")
    _reset()


def test_pending_entry_submits_once_then_waits_for_fill():
    """PENDING_ENTRY -> submit_buy 1회 -> ENTRY_SUBMITTED. 같은 poll에서
    두 번 사지 않는다(상태가 바뀌어 다음 분기로 빠지므로)."""
    _reset()
    _seed({"TEST1": {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-08-20"}})
    broker = FakeBroker()
    now = datetime(2026, 8, 21, 9, 5, tzinfo=KST)
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None,
                        enable_live_orders=True, now=now)
    ok("submit_buy called exactly once", broker.buy_calls == 1, broker.buy_calls)
    ok("event is ENTRY_SUBMITTED", [e["type"] for e in events] == ["ENTRY_SUBMITTED"], events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("state -> ENTRY_SUBMITTED with order_no", state["TEST1"]["status"] == "ENTRY_SUBMITTED"
       and state["TEST1"]["order_no"] == "ORD1", state)
    _reset()


def test_pending_fill_does_not_resubmit():
    """ENTRY_SUBMITTED인데 아직 미체결(pending) - 다음 poll에서 submit_buy가
    다시 불리면 안 된다(중복 매수 방지, 지시 5번 핵심)."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": False, "filledQty": 0, "avgPrice": None, "pending": True},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("no resubmission while pending", broker.buy_calls == 0, broker.buy_calls)
    ok("no fill event yet", events == [], events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("still ENTRY_SUBMITTED", state["TEST1"]["status"] == "ENTRY_SUBMITTED")
    _reset()


def test_rejected_entry_reverts_to_pending_for_retry():
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": True, "filledQty": 0, "avgPrice": None, "pending": False},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("rejection event fired", any(e["type"] == "ENTRY_REJECTED" for e in events), events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("reverted to PENDING_ENTRY (order_no cleared)",
       state["TEST1"]["status"] == "PENDING_ENTRY" and "order_no" not in state["TEST1"], state)
    _reset()


def test_fill_confirmed_opens_position_with_correct_price():
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 200.0, "pending": False},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("FILL_ENTRY event", events and events[0]["type"] == "FILL_ENTRY" and events[0]["price"] == 200.0, events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    pos = state["TEST1"]
    ok("OPEN with entry_price from check_fill (not a guess)", pos["status"] == "OPEN" and pos["entry_price"] == 200.0)
    ok("stop/target derived from actual fill price",
       pos["stop_price"] == 190.0 and pos["target_price"] == 220.0, pos)
    _reset()


def test_open_position_stop_triggers_sell_submission():
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0, "entry_date": "2026-08-20",
                      "stop_price": 190.0, "target_price": 220.0, "max_holding_sessions": 3,
                      "sessions_held": 0, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=185.0)  # 스톱 아래
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("submit_sell called once", broker.sell_calls == 1, broker.sell_calls)
    ok("EXIT_SUBMITTED with STOP reason",
       events and events[0]["type"] == "EXIT_SUBMITTED" and events[0]["reason"] == "STOP", events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("state -> EXIT_SUBMITTED", state["TEST1"]["status"] == "EXIT_SUBMITTED")
    _reset()


def test_open_position_no_trigger_does_not_resubmit_and_never_double_sells():
    """가격이 stop/target 사이면 poll을 여러 번 해도 submit_sell이 안 나간다."""
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0, "entry_date": "2026-08-19",
                      "stop_price": 190.0, "target_price": 220.0, "max_holding_sessions": 3,
                      "sessions_held": 1, "lastCountedDate": "2026-08-19"}})
    broker = FakeBroker(price=201.0)
    now = datetime(2026, 8, 20, 10, 0, tzinfo=KST)  # lastCountedDate보다 하루 뒤 - 새 날
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True, now=now)
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True, now=now)
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True, now=now)
    ok("no sell submitted across 3 polls in range", broker.sell_calls == 0, broker.sell_calls)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("sessions_held incremented once despite 3 same-day polls (1 -> 2, not 1 -> 4)",
       state["TEST1"]["sessions_held"] == 2, state["TEST1"]["sessions_held"])
    _reset()


def test_time_exit_after_max_holding_sessions():
    _reset()
    # sessions_held는 최초 OPEN 전이에서 이미 1(진입일=1세션)로 시작한다고
    # 가정 - maxHoldingSessions=3이므로 이후 이틀(서로 다른 날짜)만 더 지나면 된다.
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0, "entry_date": "2026-08-19",
                      "stop_price": 190.0, "target_price": 220.0, "max_holding_sessions": 3,
                      "sessions_held": 2, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=205.0)  # stop/target 사이 - 시간만료로만 나가야 함
    now = datetime(2026, 8, 21, 15, 0, tzinfo=KST)  # 새 날짜 -> sessions_held 3으로 증가
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True, now=now)
    ok("TIME_EXIT triggers sell", events and events[0]["reason"] == "TIME_EXIT", events)
    _reset()


def test_exit_fill_confirmed_removes_position_and_reports_pnl():
    _reset()
    _seed({"TEST1": {"status": "EXIT_SUBMITTED", "quantity": 5, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 190.0, "target_price": 220.0,
                      "max_holding_sessions": 3, "sessions_held": 1, "lastCountedDate": "2026-08-20",
                      "order_no": "ORD2", "order_date": "20260821", "exitReason": "STOP"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 189.5, "pending": False},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("FILL_EXIT_STOP with correct pnl",
       events and events[0]["type"] == "FILL_EXIT_STOP" and events[0]["pnl"] == round((189.5 - 200.0) * 5, 2), events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("position removed after confirmed exit", "TEST1" not in state, state)
    _reset()


def test_rejected_exit_reverts_to_open_no_duplicate_sell():
    _reset()
    _seed({"TEST1": {"status": "EXIT_SUBMITTED", "quantity": 5, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 190.0, "target_price": 220.0,
                      "max_holding_sessions": 3, "sessions_held": 1, "lastCountedDate": "2026-08-20",
                      "order_no": "ORD2", "order_date": "20260821", "exitReason": "STOP"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": True, "filledQty": 0, "avgPrice": None, "pending": False},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("EXIT_REJECTED event", any(e["type"] == "EXIT_REJECTED" for e in events), events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("reverted to OPEN (order fields cleared)",
       state["TEST1"]["status"] == "OPEN" and "order_no" not in state["TEST1"], state)
    ok("sell was not called again in this same poll", broker.sell_calls == 0, broker.sell_calls)
    _reset()


def test_is_still_selected_false_triggers_rebalance_exit_without_price_check():
    """월별 교체매매(pbr_value_v1 등)용 - is_still_selected가 False를 주면
    가격 조회(broker.current_price) 없이 곧장 REBALANCE_EXIT로 매도 제출."""
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 1.0, "target_price": 99999.0,
                      "max_holding_sessions": 999, "sessions_held": 1, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=205.0)  # stop/target 둘 다 안 걸리는 가격
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        is_still_selected=lambda symbol: False)
    ok("REBALANCE_EXIT submitted", events == [{"type": "EXIT_SUBMITTED", "symbol": "TEST1",
                                                "reason": "REBALANCE_EXIT", "orderNo": "ORD1"}], events)
    ok("current_price never called (membership decided first)", broker.current_price_calls == 0)
    _reset()


def test_is_still_selected_true_keeps_holding_continuous_hold():
    """재선택(continuousHoldOnRenewal)됐으면 stop/target도 안 걸리는 한 아무 것도
    안 한다 - 청산도 재매수도 없이 그대로 보유가 이어진다."""
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 1.0, "target_price": 99999.0,
                      "max_holding_sessions": 999, "sessions_held": 1, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=205.0)
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        is_still_selected=lambda symbol: True)
    ok("no exit, no re-entry", events == [], events)
    ok("sell never submitted", broker.sell_calls == 0)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("still OPEN, untouched", state["TEST1"]["status"] == "OPEN", state)
    _reset()


def main():
    test_disabled_flag_never_touches_broker()
    test_pending_entry_submits_once_then_waits_for_fill()
    test_pending_fill_does_not_resubmit()
    test_rejected_entry_reverts_to_pending_for_retry()
    test_fill_confirmed_opens_position_with_correct_price()
    test_open_position_stop_triggers_sell_submission()
    test_open_position_no_trigger_does_not_resubmit_and_never_double_sells()
    test_time_exit_after_max_holding_sessions()
    test_exit_fill_confirmed_removes_position_and_reports_pnl()
    test_rejected_exit_reverts_to_open_no_duplicate_sell()
    test_is_still_selected_false_triggers_rebalance_exit_without_price_check()
    test_is_still_selected_true_keeps_holding_continuous_hold()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'='*40}\npassed {passed} · failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
