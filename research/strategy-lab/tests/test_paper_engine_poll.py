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
from engine.live.untradableVts import UNTRADABLE_VTS

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
    # 주문 원장도 비운다 - 안 그러면 테스트끼리 원장이 누적돼 다음 테스트가
    # 앞 테스트의 주문번호를 자기 것으로 본다.
    ledger = positionStore._orders_path(REPO_ROOT, STRATEGY_ID)
    if ledger.exists():
        ledger.unlink()


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
    # 주문일 당일이어야 "아직 대기중"이다 - 날이 바뀌면 그 주문은 만료다(아래 두 테스트)
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        now=datetime(2026, 8, 21, 10, 0, tzinfo=KST))
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



class NoStopRule:
    """가격 기반 stop/target이 없는 순수 시간청산 전략 - risk에 stopPct/targetPct
    키가 아예 없다(factor_earnings_yield_v1/policy.json 그대로의 모양)."""
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "testUniverse": ["TEST1"],
        "risk": {"note": "No price-based stop/target - pure time exit", "maxHoldingSessions": 3},
        "position": {"notionalPerPosition": 1000000, "maxPositions": 1},
    }


def test_no_stop_pct_policy_opens_position_instead_of_crashing():
    """★ 2026-09-09 회귀. 옛 _open_from_fills는 risk["stopPct"]를 필수로 읽어
    이 정책에서 KeyError로 poll_once 전체를 죽였다 - 상태가 저장되지 않아
    factor_earnings_yield_v1 61종목이 전량 체결됐는데도 ENTRY_SUBMITTED로
    5거래일 묶였다. stop/target이 없으면 None이지 예외가 아니다."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 100.0, "pending": False},
    ])
    events = poll_once(REPO_ROOT, NoStopRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("체결이 FILL_ENTRY로 보고된다", [e["type"] for e in events] == ["FILL_ENTRY"], events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("ENTRY_SUBMITTED -> OPEN 전이", state["TEST1"]["status"] == "OPEN", state)
    ok("stop_price는 None (0이나 sentinel이 아니다)", state["TEST1"]["stop_price"] is None, state)
    ok("target_price는 None", state["TEST1"]["target_price"] is None, state)
    _reset()


def test_no_stop_pct_open_position_still_time_exits():
    """stop/target이 None이어도 OPEN 분기가 터지지 않고 시간청산은 그대로 걸린다."""
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 100.0,
                      "entry_date": "2026-08-21", "stop_price": None, "target_price": None,
                      "max_holding_sessions": 3, "sessions_held": 3, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=100.0)
    events = poll_once(REPO_ROOT, NoStopRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("None stop/target에도 TIME_EXIT이 난다",
       [(e["type"], e.get("reason")) for e in events] == [("EXIT_SUBMITTED", "TIME_EXIT")], events)
    _reset()


def test_no_stop_pct_open_position_does_not_exit_early():
    """가격이 아무리 움직여도 STOP/TARGET으로는 안 나간다 - None은 '없음'이다."""
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 100.0,
                      "entry_date": "2026-08-21", "stop_price": None, "target_price": None,
                      "max_holding_sessions": 3, "sessions_held": 1, "lastCountedDate": "2026-08-20"}})
    broker = FakeBroker(price=0.01)   # 폭락해도 stop이 없으므로 청산 없음
    events = poll_once(REPO_ROOT, NoStopRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("stop_price None이면 STOP 청산 없음", events == [], events)
    ok("매도 제출 없음", broker.sell_calls == 0, broker.sell_calls)
    _reset()



def test_untradable_pending_entry_is_dropped_without_touching_broker():
    """목록에 오르기 전에 쌓인 PENDING_ENTRY 정리. 제출이 전부 거부됐으므로
    KIS에 취소할 주문이 없다 - 상태에서 지우는 것으로 끝난다."""
    _reset()
    sym = sorted(UNTRADABLE_VTS)[0]
    _seed({sym: {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-08-03"}})
    broker = FakeBroker()
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    ok("DROP_UNTRADABLE 이벤트", [e["type"] for e in events] == ["DROP_UNTRADABLE"], events)
    ok("상태에서 제거", sorted(positionStore.load(REPO_ROOT, STRATEGY_ID)) == [], positionStore.load(REPO_ROOT, STRATEGY_ID))
    ok("브로커를 건드리지 않는다", broker.buy_calls == 0 and broker.check_fill_calls == 0,
       (broker.buy_calls, broker.check_fill_calls))
    _reset()



def test_topup_fill_averages_entry_price_and_keeps_position_history():
    """탑업이 체결되면 옛 체결과 새 체결의 가중평균 단가로 OPEN 이 복원돼야
    한다. 그리고 보유일수·topup_as_of 가 리셋되면 (a) 시간청산 시계가 되감기고
    (b) 다음 날 가격이 내렸을 때 또 사들인다(눌림목 매수 드리프트)."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 10, "target_quantity": 10,
                      "filled_quantity": 4, "entry_cost": 4 * 100.0,   # 기존 4주 @100
                      "entry_slices": 1, "order_no": "ORD1", "order_date": "20260821",
                      "order_quantity": 6, "first_fill_date": "2026-07-01",
                      "sessions_held": 10, "lastCountedDate": "2026-08-01",
                      "topup_as_of": "2026-08-03"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 6, "avgPrice": 200.0, "pending": False},
    ])
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("OPEN 으로 복원", st["status"] == "OPEN" and st["quantity"] == 10, st)
    # (4*100 + 6*200) / 10 = 160
    ok("가중평균 단가", st["entry_price"] == 160.0, st["entry_price"])
    ok("보유일 기산일 유지", st["entry_date"] == "2026-07-01", st)
    ok("보유일수 리셋 안 됨", st["sessions_held"] == 10, st)
    ok("topup_as_of 유지(재탑업 방지)", st["topup_as_of"] == "2026-08-03", st)
    _reset()


def test_fresh_entry_still_starts_its_clock_at_zero():
    """위 이어받기가 신규 진입까지 바꾸면 안 된다 - 없는 키는 그대로 없다."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 100.0, "pending": False},
    ])
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("신규 진입은 0 에서 시작", st["sessions_held"] == 0 and st["lastCountedDate"] is None, st)
    ok("신규 진입에 topup_as_of 없음", "topup_as_of" not in st, st)
    _reset()



def test_fill_uses_signal_hold_sessions_over_policy_default():
    """FakeRule.PARAMS 의 risk.maxHoldingSessions 는 3 이지만, 신호가 실은
    hold_sessions=23 이 이긴다. 정책 고정값은 신호가 없을 때의 기본값이다."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821", "hold_sessions": 23}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 100.0, "pending": False},
    ])
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("신호의 보유일수가 정책 기본값을 이긴다", st["max_holding_sessions"] == 23, st)
    ok("hold_sessions 도 남는다(다음 체결에서 또 쓴다)", st["hold_sessions"] == 23, st)
    _reset()


def test_fill_without_signal_hold_sessions_uses_policy_default():
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": True, "rejected": False, "filledQty": 5, "avgPrice": 100.0, "pending": False},
    ])
    poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("없으면 정책 기본값 3", st["max_holding_sessions"] == 3, st)
    _reset()


def test_submit_records_order_ledger_for_strategy_attribution():
    """★ 2026-09-11. 전략 귀속은 주문을 내는 순간에만 존재했다 - order_no 는
    체결 확인과 동시에 state 에서 지워지고 매도가 체결되면 포지션 자체가
    삭제된다. 그래서 "어느 전략이 언제 얼마 샀나"를 나중에 물으면 답할 데가
    없었다(교훈75). 제출 시점에 원장을 남긴다.

    이 테스트가 깨지는 방식: record_order 호출을 빼면 원장이 비고, UI 의
    전략별 매매 내역이 통째로 '미귀속'으로 떨어진다(조용히 - 계좌 합계는
    그대로 맞으므로 화면만 보면 모른다)."""
    _reset()
    _seed({"TEST1": {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-08-20"}})
    now = datetime(2026, 8, 21, 9, 5, tzinfo=KST)
    poll_once(REPO_ROOT, FakeRule(), FakeBroker(), log=lambda *a: None,
              enable_live_orders=True, now=now)
    ledger = positionStore.load_orders(REPO_ROOT, STRATEGY_ID)
    ok("매수 주문번호가 원장에", "ORD1" in ledger, ledger)
    ok("원장에 날짜·종목·side·수량",
       ledger.get("ORD1") == {"date": "2026-08-21", "symbol": "TEST1",
                               "side": "BUY", "quantity": 5, "reason": "ENTRY"}, ledger)

    # 매도도 같은 자리에 남는다 - 체결되면 포지션이 삭제되므로 더 급하다.
    _reset()
    _seed({"TEST1": {"status": "OPEN", "quantity": 5, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 190.0, "target_price": 220.0,
                      "max_holding_sessions": 3, "sessions_held": 0,
                      "lastCountedDate": "2026-08-20"}})
    poll_once(REPO_ROOT, FakeRule(), FakeBroker(price=185.0), log=lambda *a: None,
              enable_live_orders=True, now=now)
    ledger = positionStore.load_orders(REPO_ROOT, STRATEGY_ID)
    sells = [v for v in ledger.values() if v["side"] == "SELL"]
    ok("매도도 원장에 남는다", len(sells) == 1, ledger)
    ok("매도 사유까지", sells and sells[0]["reason"] == "STOP", sells)
    # 진입가를 같이 남긴다 - 체결되면 포지션이 삭제돼 그 뒤로는 알 데가 없고,
    # 이게 없으면 전략별 실현손익을 영영 못 낸다. 손익 자체는 안 적는다
    # (청산가는 KIS 가 준다 - 유도값을 저장하면 원본과 갈린다).
    ok("매도 원장에 진입가", sells and sells[0]["entryPrice"] == 200.0, sells)
    ok("매도 원장에 진입일", sells and sells[0]["entryDate"] == "2026-08-20", sells)
    ok("손익은 원장에 안 적는다", sells and "pnl" not in sells[0], sells)
    _reset()


def test_order_ledger_write_failure_does_not_break_trading():
    """원장은 편의다. 쓰기가 실패해도 주문은 나가고 상태는 저장돼야 한다 -
    기록하려던 편의가 매매를 깨면 안 된다.

    실패를 진짜로 만든다(함수를 통째로 바꿔치기하면 record_order 안의 방어를
    건너뛰어 '있지도 않은 실패'를 시험하게 된다, 교훈72): 원장 경로의 부모가
    파일이면 mkdir 이 실제로 터진다."""
    _reset()
    _seed({"TEST1": {"status": "PENDING_ENTRY", "quantity": 5, "intent_date": "2026-08-20"}})
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        blocker = Path(tmp) / "notadir"
        blocker.write_text("", encoding="utf-8")      # 디렉터리 자리에 파일
        orig = positionStore._orders_path
        positionStore._orders_path = lambda repo_root, sid: blocker / f"{sid}_orders.json"
        try:
            ok("원장 쓰기 실패는 예외가 아니라 False",
               positionStore.record_order(REPO_ROOT, STRATEGY_ID, "X",
                                           {"date": "2026-08-21", "symbol": "T", "side": "BUY",
                                            "quantity": 1, "reason": "ENTRY"}) is False)
            broker = FakeBroker()
            events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None,
                                enable_live_orders=True,
                                now=datetime(2026, 8, 21, 9, 5, tzinfo=KST))
            ok("원장이 못 써져도 주문은 나갔다", broker.buy_calls == 1, broker.buy_calls)
            ok("원장이 못 써져도 상태는 저장됐다",
               positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]["status"] == "ENTRY_SUBMITTED",
               positionStore.load(REPO_ROOT, STRATEGY_ID))
            ok("이벤트도 그대로", [e["type"] for e in events] == ["ENTRY_SUBMITTED"], events)
        finally:
            positionStore._orders_path = orig
    _reset()


def test_expired_entry_order_settles_partial_fill_and_retries_remainder():
    """부분체결로 끝난 매수 주문 - 장 마감에 잔여가 취소되면 fullyFilled 가
    영영 안 온다. 주문일이 지나면 체결분만 확정하고 남은 수량을 다시 낸다
    (실측 2026-09-09: 호가 얇은 소형주 5건이 ENTRY_SUBMITTED 에 갇혔다)."""
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 10, "target_quantity": 10,
                      "intent_date": "2026-08-20", "order_no": "ORD1",
                      "order_date": "20260821", "order_quantity": 10}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": False, "filledQty": 4, "avgPrice": 200.0, "pending": True},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        now=datetime(2026, 8, 24, 10, 0, tzinfo=KST))
    ok("체결된 4주만 FILL_ENTRY", [(e["type"], e["qty"]) for e in events] == [("FILL_ENTRY", 4)], events)
    pos = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("PENDING_ENTRY 로 풀려 재주문 가능", pos["status"] == "PENDING_ENTRY", pos)
    ok("주문 흔적이 지워졌다", "order_no" not in pos and "order_date" not in pos, pos)
    ok("체결분 누적 4주 · 원가 800", pos["filled_quantity"] == 4 and pos["entry_cost"] == 800.0, pos)
    ok("보유일수 시계는 주문일부터", pos["first_fill_date"] == "2026-08-21", pos)
    _reset()


def test_expired_entry_order_with_zero_fill_retries_whole_quantity():
    _reset()
    _seed({"TEST1": {"status": "ENTRY_SUBMITTED", "quantity": 5, "intent_date": "2026-08-20",
                      "order_no": "ORD1", "order_date": "20260821"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": False, "filledQty": 0, "avgPrice": None, "pending": True},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        now=datetime(2026, 8, 24, 10, 0, tzinfo=KST))
    ok("미체결 만료는 체결 이벤트를 안 만든다", events == [], events)
    pos = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("PENDING_ENTRY · 체결 0", pos["status"] == "PENDING_ENTRY" and pos.get("filled_quantity", 0) == 0, pos)
    ok("첫 체결일을 지어내지 않는다", "first_fill_date" not in pos, pos)
    _reset()


def test_expired_exit_order_returns_unsold_quantity_to_open():
    """매도 만료가 더 나쁘다 - 안 풀면 포지션이 영영 안 팔린다."""
    _reset()
    _seed({"TEST1": {"status": "EXIT_SUBMITTED", "quantity": 10, "entry_price": 200.0,
                      "entry_date": "2026-08-20", "stop_price": 190.0, "target_price": 220.0,
                      "max_holding_sessions": 3, "sessions_held": 5,
                      "order_no": "ORD1", "order_date": "20260821", "exitReason": "TIME_EXIT"}})
    broker = FakeBroker(fill_script=[
        {"fullyFilled": False, "rejected": False, "filledQty": 3, "avgPrice": 210.0, "pending": True},
    ])
    events = poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None, enable_live_orders=True,
                        now=datetime(2026, 8, 24, 10, 0, tzinfo=KST))
    ok("체결된 3주만 손익에 잡힌다",
       any(e["type"] == "FILL_EXIT_TIME_EXIT" and e["qty"] == 3
           and e["pnl"] == round((210.0 - 200.0) * 3, 2) for e in events), events)
    pos = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    ok("남은 7주가 OPEN 으로 복귀", pos["status"] == "OPEN" and pos["quantity"] == 7, pos)
    ok("청산 사유가 지워져 다음 poll 이 다시 판정", "exitReason" not in pos, pos)
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
    test_no_stop_pct_policy_opens_position_instead_of_crashing()
    test_no_stop_pct_open_position_still_time_exits()
    test_no_stop_pct_open_position_does_not_exit_early()
    test_untradable_pending_entry_is_dropped_without_touching_broker()
    test_topup_fill_averages_entry_price_and_keeps_position_history()
    test_fresh_entry_still_starts_its_clock_at_zero()
    test_fill_uses_signal_hold_sessions_over_policy_default()
    test_fill_without_signal_hold_sessions_uses_policy_default()
    test_submit_records_order_ledger_for_strategy_attribution()
    test_order_ledger_write_failure_does_not_break_trading()
    test_expired_entry_order_settles_partial_fill_and_retries_remainder()
    test_expired_entry_order_with_zero_fill_retries_whole_quantity()
    test_expired_exit_order_returns_unsold_quantity_to_open()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'='*40}\npassed {passed} · failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
