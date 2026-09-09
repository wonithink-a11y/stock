"""engine/live/paperEngine.py의 scan_rebalance_signals() self-check. 월별
교체매매(pbr_value_v1·lowmom60_v1) 전용 스캔 - rule.selected_symbols(as_of)로
이번 리밸런싱일의 전체 선택 목록을 한 번에 받는다(scan_signals()의 종목별
predicate 루프와 다른 경로). 합성 bars_by_ticker만 쓴다 - A2a 실데이터도
KIS도 안 건드린다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.live import positionStore
from engine.live.paperEngine import scan_rebalance_signals
from engine.live.untradableVts import UNTRADABLE_VTS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STRATEGY_ID = "test_rebalance_scan_synth"
AS_OF = "2026-08-03"


class FakeRule:
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "portfolio": {"maxPositions": 3},
    }

    @staticmethod
    def selected_symbols(as_of):
        return ["CHEAP", "EXPENSIVE", "MISSING_PRICE"] if as_of == AS_OF else []


def _bars(price):
    return pd.DataFrame({"close": [price]}, index=[pd.Timestamp(AS_OF)])


BARS = {"CHEAP": _bars(10_000.0), "EXPENSIVE": _bars(999_999.0)}  # MISSING_PRICE 의도적으로 없음

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


def test_affordable_symbol_gets_pending_entry_within_slot_budget():
    _reset()
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    # slot budget = 300,000 // 3 = 100,000. CHEAP(10,000)만 사고, EXPENSIVE는 예산초과라 스킵,
    # MISSING_PRICE는 가격이 없어 스킵.
    ok("only CHEAP entered", [e["symbol"] for e in events] == ["CHEAP"], events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("CHEAP qty = budget // price = 10", state["CHEAP"]["quantity"] == 10, state)
    ok("EXPENSIVE skipped (over slot budget)", "EXPENSIVE" not in state, state)
    ok("MISSING_PRICE skipped (no bar)", "MISSING_PRICE" not in state, state)
    _reset()


def _open_pos(qty, **kw):
    base = {"status": "OPEN", "quantity": qty, "entry_price": 9_000.0,
            "entry_date": "2026-07-01", "stop_price": 1.0, "target_price": 999_999.0,
            "max_holding_sessions": 999, "sessions_held": 10, "lastCountedDate": "2026-08-01"}
    base.update(kw)
    return base


def test_already_held_symbol_at_budget_is_not_rebought():
    """continuousHoldOnRenewal - 이미 보유중(OPEN)인 종목이 이번에도 선택됐다고
    새 포지션을 만들면 안 된다(poll_once의 is_still_selected가 계속 들고 간다).
    슬롯예산(100,000 = 300,000//3)을 이미 채운 10주라 탑업도 할 일이 없다."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {"CHEAP": _open_pos(10)})   # 10 x 10,000 = 예산 전액
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("no new intent for already-held CHEAP", all(e["symbol"] != "CHEAP" for e in events), events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("CHEAP position untouched", state["CHEAP"]["status"] == "OPEN" and state["CHEAP"]["quantity"] == 10, state)
    _reset()


def test_underfunded_position_is_topped_up_to_slot_budget():
    """★ 2026-09-09. 배정액을 올려도 기존 포지션에는 반영되지 않아 실측으로
    pbr_value_v1 이 배정의 7.5%, lowmom60_v1 이 3.2%만 투자돼 있었다. 이번
    리밸런싱일의 슬롯예산까지 끌어올린다 - 새 상태를 만들지 않고 분할매수와
    같은 모양의 PENDING_ENTRY 로 되돌린다."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {"CHEAP": _open_pos(2)})    # 예산 100,000 중 20,000만
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("탑업 이벤트가 난다",
       {"type": "INTENT_TOPUP", "symbol": "CHEAP", "date": AS_OF,
        "quantity": 8, "targetQuantity": 10} in events, events)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    ok("분할매수와 같은 모양으로 되돌린다", st["status"] == "PENDING_ENTRY"
       and st["target_quantity"] == 10 and st["filled_quantity"] == 2, st)
    ok("이미 산 것의 원가를 이어받는다", st["entry_cost"] == 2 * 9_000.0, st)
    ok("보유일 기산일은 원래 진입일", st["first_fill_date"] == "2026-07-01", st)
    _reset()


def test_topup_runs_once_per_rebalance_date():
    """매 폴링마다 '예산 대비 부족한가'를 다시 물으면 가격이 내릴 때마다 더 사게
    된다 - 그건 배정액 반영이 아니라 전략 변경이다. 리밸런싱일당 한 번만."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {"CHEAP": _open_pos(2)})
    scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                            log=lambda *a: None, bars_by_ticker=BARS)
    # 탑업이 체결돼 OPEN 으로 돌아온 뒤(topup_as_of 는 _open_from_fills 가 이어받는다)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    positionStore.save(REPO_ROOT, STRATEGY_ID,
                        {"CHEAP": _open_pos(10, topup_as_of=st["topup_as_of"])})
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=900_000,  # 예산 3배
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("같은 리밸런싱일에는 두 번 안 한다", all(e["symbol"] != "CHEAP" for e in events), events)
    _reset()


def test_topup_never_shrinks_a_position():
    """예산보다 많이 들고 있어도 팔지 않는다 - 탑업은 한 방향이다."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {"CHEAP": _open_pos(50)})   # 예산의 5배
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("줄이지 않는다", all(e["symbol"] != "CHEAP" for e in events), events)
    ok("수량 그대로", positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]["quantity"] == 50)
    _reset()


def test_topup_skips_positions_that_are_mid_entry():
    """PENDING_ENTRY/ENTRY_SUBMITTED 는 target_quantity 가 이미 현재 예산이다 -
    거기에 탑업을 겹치면 목표가 두 번 잡힌다."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {
        "CHEAP": {"status": "ENTRY_SUBMITTED", "quantity": 2, "target_quantity": 2,
                  "order_no": "ORD1", "order_date": "20260803", "intent_date": AS_OF},
    })
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    ok("진입 중인 포지션은 안 건드린다",
       all(e["symbol"] != "CHEAP" for e in events) and st["status"] == "ENTRY_SUBMITTED", (events, st))
    _reset()


def test_slot_budget_expands_when_book_exceeds_max_positions():
    """★ factor_earnings_yield_v1 실사례 - maxPositions 30 인데 장부가 61종목이다
    (maxPositions 가 200 으로 드리프트했던 09-04 에 진입). capital//30 으로 탑업하면
    목표 합이 배정액의 2배가 된다. 장부가 더 크면 실제 보유 수로 나눈다."""
    _reset()
    book = {f"X{i}": _open_pos(1) for i in range(6)}      # maxPositions=3 인데 6종목
    book["CHEAP"] = _open_pos(1)
    positionStore.save(REPO_ROOT, STRATEGY_ID, book)
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=700_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    # slots = max(3, 7) = 7 -> 슬롯예산 100,000 -> CHEAP(10,000) 목표 10주
    topups = [e for e in events if e["type"] == "INTENT_TOPUP"]
    ok("장부 크기로 나눈 예산을 쓴다", [e["targetQuantity"] for e in topups] == [10], topups)
    ok("목표 합이 배정액을 안 넘는다", 7 * 100_000 <= 700_000)
    _reset()


def test_max_positions_cap_stops_new_entries():
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {
        "X1": {"status": "OPEN", "quantity": 1}, "X2": {"status": "OPEN", "quantity": 1},
        "X3": {"status": "OPEN", "quantity": 1},  # maxPositions=3 이미 꽉 참
    })
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("no new entries once at cap", events == [], events)
    _reset()


UNTRADABLE_ONE = sorted(UNTRADABLE_VTS)[0]   # 실제 목록에서 하나 - 목록이 비면 이 테스트가 먼저 깨진다


class UntradableRule:
    PARAMS = {"strategyId": STRATEGY_ID, "portfolio": {"maxPositions": 3}}

    @staticmethod
    def selected_symbols(as_of):
        return [UNTRADABLE_ONE, "CHEAP"] if as_of == AS_OF else []


def test_untradable_symbol_never_becomes_pending_entry():
    """★ 2026-09-09. 모의계좌가 못 사는 종목에 진입 의도를 만들면 체결되지 않는
    PENDING_ENTRY로 남아 폴링(10분)마다 영원히 재시도한다 - 실측으로 12종목이
    08-03 이후 91~93회 전부 거부됐다. 선택 목록에는 그대로 두고(백테스트와
    표본을 안 가른다) 진입 단계에서만 거른다."""
    _reset()
    bars = dict(BARS)
    bars[UNTRADABLE_ONE] = _bars(10_000.0)     # 가격은 멀쩡하다 - 스킵 사유가 가격이 아님을 못박는다
    events = scan_rebalance_signals(REPO_ROOT, UntradableRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=bars)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("매매불가 종목은 상태에 안 들어간다", UNTRADABLE_ONE not in state, state)
    ok("스킵이 이벤트로 보인다(조용히 사라지지 않는다)",
       {"type": "SKIP_UNTRADABLE", "symbol": UNTRADABLE_ONE, "date": AS_OF} in events, events)
    ok("같은 스캔의 정상 종목은 그대로 진입", state.get("CHEAP", {}).get("status") == "PENDING_ENTRY", state)
    _reset()



class HoldRule:
    """rule.hold_sessions()를 제공하는 전략 - 라이브 4전략과 같은 모양."""
    PARAMS = {"strategyId": STRATEGY_ID, "portfolio": {"maxPositions": 3}}
    HOLD = {"CHEAP": 23}

    @staticmethod
    def selected_symbols(as_of):
        return ["CHEAP"] if as_of == AS_OF else []

    @classmethod
    def hold_sessions(cls, symbol, as_of):
        return cls.HOLD.get(symbol) if as_of == AS_OF else None


def test_new_entry_records_signal_hold_sessions():
    """★ 2026-09-09. 백테스트는 리밸런싱일마다 정확한 보유일수(18~23)를 쓰는데
    페이퍼는 정책 고정값 21 을 썼다. 2026년 리밸런싱일 9개 중 5개가 22~23 이라,
    고정 21 이면 다음 리밸런싱 1~2세션 전에 팔고 곧바로 다시 산다."""
    _reset()
    scan_rebalance_signals(REPO_ROOT, HoldRule(), AS_OF, capital_krw=300_000,
                            log=lambda *a: None, bars_by_ticker=BARS)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    ok("신호의 보유일수를 상태에 싣는다", st.get("hold_sessions") == 23, st)
    _reset()


def test_existing_open_position_is_corrected_not_only_new_entries():
    """지금 굳어 있는 책도 고쳐야 한다 - '다음 진입부터'만 듣는 수정은 탑업에서
    이미 한 번 겪은 실패 모양이다."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID,
                        {"CHEAP": _open_pos(10, max_holding_sessions=21)})
    events = scan_rebalance_signals(REPO_ROOT, HoldRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    ok("기존 OPEN 도 보정", st["max_holding_sessions"] == 23, st)
    ok("보정이 이벤트로 보인다",
       {"type": "HOLD_SESSIONS_SYNCED", "symbol": "CHEAP", "holdSessions": 23} in events, events)
    _reset()


def test_rule_without_hold_sessions_falls_back_silently():
    """옛 전략(dummy_sma20 등)은 hold_sessions 를 안 준다 - 죽지 않고 정책
    기본값 경로로 떨어져야 한다."""
    _reset()
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["CHEAP"]
    ok("hold_sessions 키 자체가 없다", "hold_sessions" not in st, st)
    ok("진입은 정상", st["status"] == "PENDING_ENTRY", st)
    _reset()


def main():
    test_affordable_symbol_gets_pending_entry_within_slot_budget()
    test_already_held_symbol_at_budget_is_not_rebought()
    test_underfunded_position_is_topped_up_to_slot_budget()
    test_topup_runs_once_per_rebalance_date()
    test_topup_never_shrinks_a_position()
    test_topup_skips_positions_that_are_mid_entry()
    test_slot_budget_expands_when_book_exceeds_max_positions()
    test_new_entry_records_signal_hold_sessions()
    test_existing_open_position_is_corrected_not_only_new_entries()
    test_rule_without_hold_sessions_falls_back_silently()
    test_max_positions_cap_stops_new_entries()
    test_untradable_symbol_never_becomes_pending_entry()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'='*40}\npassed {passed} \xb7 failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
