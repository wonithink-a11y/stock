"""소수 수량(크립토) self-check - 진짜 assert 를 쓴다.

배경(실측 2026-09-20): poll_once 의 PENDING_ENTRY 분기가 `remaining < 1` 로
"이미 다 샀다"를 판정했다. 정수 주식에서는 `<= 0` 과 같지만 0.0001 BTC 에서는
매수를 **한 번도 안 내고** _open_from_fills(filled=0) 으로 넘어간다. 그러면
entry_price 가 0 이 되고 target_price 도 0 이라 다음 poll 이 즉시 TARGET 청산하며
체결가 전액을 이익으로 기록한다 - 장부가 통째로 거짓이 되는 조용한 실패다.

scan_signals/run_once 의 `int(notional // price)` 도 같은 정수 가정이다.
notional 1만원짜리 의도가 1 BTC(약 1억) 주문이 된다.

이 파일이 못 박는 것은 둘이다.
  (1) 소수 수량이 실제로 주문으로 나간다
  (2) 정수 수량의 동작은 **하나도 안 바뀐다** - 그게 이 변경의 안전장치다
      (실주문 KIS 경로가 이 코드를 공유한다)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from engine.live import positionStore
from engine.live.paperEngine import _entry_quantity, poll_once

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STRATEGY_ID = "test_fractional_synth"
KST = timezone(timedelta(hours=9))
SYM = "KRW-BTC"


class FakeRule:
    PARAMS = {"strategyId": STRATEGY_ID, "testUniverse": [SYM],
              "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 1}}


class FakeBroker:
    def __init__(self):
        self.buys = []
        self.sells = []

    def submit_buy(self, symbol, quantity):
        self.buys.append((symbol, quantity))
        return "ORD1"

    def submit_sell(self, symbol, quantity):
        self.sells.append((symbol, quantity))
        return "ORD2"

    def check_fill(self, order_no, order_date, requested_qty):
        return {"fullyFilled": True, "rejected": False, "filledQty": requested_qty,
                "avgPrice": 1.0e8, "pending": False}

    def current_price(self, symbol):
        return 1.0e8


def _run(broker, day):
    return poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None,
                     enable_live_orders=True, now=datetime(2026, 9, day, 10, 0, tzinfo=KST))


def _seed(qty):
    positionStore.save(REPO_ROOT, STRATEGY_ID,
                       {SYM: {"status": "PENDING_ENTRY", "quantity": qty,
                              "intent_date": "2026-09-01"}})


def _pos():
    return positionStore.load(REPO_ROOT, STRATEGY_ID).get(SYM)


def test_fractional_quantity_actually_submits_a_buy():
    """0.0001 BTC 가 주문으로 나간다 - 이게 고치기 전엔 빈 리스트였다."""
    _seed(0.0001)
    b = FakeBroker()
    _run(b, 1)
    assert b.buys == [(SYM, 0.0001)], b.buys
    assert _pos()["status"] == "ENTRY_SUBMITTED", _pos()


def test_fractional_entry_price_is_the_real_fill_not_zero():
    """체결 확인 후 entry_price 가 실제 체결가여야 한다.

    고치기 전에는 매수 없이 OPEN 이 되면서 entry_price=0 · target_price=0 이라
    다음 poll 이 즉시 TARGET 청산하고 체결가 전액을 이익으로 적었다.
    """
    _seed(0.0001)
    b = FakeBroker()
    _run(b, 1)          # PENDING_ENTRY -> ENTRY_SUBMITTED
    _run(b, 1)          # -> OPEN
    pos = _pos()
    assert pos["status"] == "OPEN", pos
    assert pos["entry_price"] == 1.0e8, pos["entry_price"]
    assert pos["target_price"] > 0, pos["target_price"]
    assert abs(pos["quantity"] - 0.0001) < 1e-12, pos["quantity"]


def test_fractional_position_exits_for_its_full_quantity():
    """시간청산이 소수 수량 전량을 팔고 포지션을 지운다(잔량이 남지 않는다)."""
    _seed(0.0001)
    b = FakeBroker()
    _run(b, 1)
    _run(b, 1)          # OPEN, sessions_held=1 >= maxHoldingSessions=1
    _run(b, 2)          # TIME_EXIT -> EXIT_SUBMITTED
    assert b.sells == [(SYM, 0.0001)], b.sells
    _run(b, 2)          # 체결 확인 -> 삭제
    assert _pos() is None, _pos()


def test_integer_quantity_path_is_byte_for_byte_unchanged():
    """정수 수량은 예전과 똑같이 동작한다 - 실주문 KIS 경로의 안전장치."""
    _seed(30)
    b = FakeBroker()
    _run(b, 1)
    assert b.buys == [(SYM, 30)], b.buys
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_entry_quantity_opt_in_only():
    """fractionalQuantity 를 안 주면 기존 정수 반올림 그대로."""
    price = 1.0e8
    assert _entry_quantity({"notionalPerPosition": 10000}, price) == 1
    assert _entry_quantity({"notionalPerPosition": 10000, "fractionalQuantity": False}, price) == 1
    assert _entry_quantity({"notionalPerPosition": 250000}, 1000.0) == 250
    # 옵트인하면 나눗셈 그대로 - 1억짜리 코인에 1만원이면 0.0001
    assert _entry_quantity({"notionalPerPosition": 10000, "fractionalQuantity": True}, price) == 0.0001


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print(f"\n{'FAILED' if failed else 'PASSED'} - {failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
