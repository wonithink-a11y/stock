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


def test_already_held_symbol_is_not_rebought():
    """continuousHoldOnRenewal - 이미 보유중(OPEN)인 종목이 이번에도 선택됐다고
    다시 PENDING_ENTRY를 만들면 안 된다(poll_once의 is_still_selected가
    계속 들고 간다)."""
    _reset()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {
        "CHEAP": {"status": "OPEN", "quantity": 5, "entry_price": 9_000.0,
                  "entry_date": "2026-07-01", "stop_price": 1.0, "target_price": 999_999.0,
                  "max_holding_sessions": 999, "sessions_held": 10, "lastCountedDate": "2026-08-01"},
    })
    events = scan_rebalance_signals(REPO_ROOT, FakeRule(), AS_OF, capital_krw=300_000,
                                     log=lambda *a: None, bars_by_ticker=BARS)
    ok("no new intent for already-held CHEAP", all(e["symbol"] != "CHEAP" for e in events), events)
    state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("CHEAP position untouched", state["CHEAP"]["status"] == "OPEN" and state["CHEAP"]["quantity"] == 5, state)
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


def main():
    test_affordable_symbol_gets_pending_entry_within_slot_budget()
    test_already_held_symbol_is_not_rebought()
    test_max_positions_cap_stops_new_entries()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'='*40}\npassed {passed} \xb7 failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
