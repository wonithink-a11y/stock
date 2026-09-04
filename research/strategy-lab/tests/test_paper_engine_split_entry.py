"""분할 매수(entry_slices) self-check - 진짜 assert 를 쓴다.

목표수량을 여러 거래일에 나눠 사는 경로만 본다. 기본값(entry_slices=1)이
기존 동작과 완전히 같은지도 여기서 못 박는다 - 그게 이 변경의 안전장치다.

배경: 시장충격은 '하루' 참여율의 함수라 큰 자금에서는 하루에 다 사면 안 된다
(findings/sizing-position-count-capacity-2026-09.md 정정 절 - pbr 5억이면
최악 종목 하루 참여율이 15.6%, 5일에 나누면 3.1%).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

from engine.live import positionStore
from engine.live.paperEngine import poll_once

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STRATEGY_ID = "test_split_entry_synth"
KST = timezone(timedelta(hours=9))


class FakeRule:
    PARAMS = {"strategyId": STRATEGY_ID, "testUniverse": ["TEST1"],
              "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 3}}


class FakeBroker:
    def __init__(self, fills=None):
        self.buys = []          # (symbol, quantity)
        self._fills = list(fills or [])
        self._seq = 0

    def submit_buy(self, symbol, quantity):
        self.buys.append((symbol, quantity))
        self._seq += 1
        return f"ORD{self._seq}"

    def check_fill(self, order_no, order_date, requested_qty):
        if self._fills:
            return self._fills.pop(0)
        return {"fullyFilled": False, "rejected": False, "filledQty": 0, "avgPrice": None}

    def current_price(self, symbol):
        return 100.0


def _day(d):
    return datetime(2026, 9, d, 10, 0, tzinfo=KST)


def _run(broker, day):
    return poll_once(REPO_ROOT, FakeRule(), broker, log=lambda *a: None,
                     enable_live_orders=True, now=_day(day))


def _seed(**kw):
    st = {"status": "PENDING_ENTRY", "quantity": 30, "intent_date": "2026-09-01"}
    st.update(kw)
    positionStore.save(REPO_ROOT, STRATEGY_ID, {"TEST1": st})


def test_default_is_unchanged_single_shot():
    """entry_slices 를 안 주면 예전처럼 전량 한 번에 나간다."""
    _seed()
    b = FakeBroker()
    _run(b, 1)
    assert b.buys == [("TEST1", 30)], b.buys
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_slices_split_quantity_and_one_per_day():
    _seed(target_quantity=30, entry_slices=3)
    b = FakeBroker(fills=[{"fullyFilled": True, "rejected": False, "filledQty": 10, "avgPrice": 100.0}])
    _run(b, 1)                                   # 1조각 제출
    assert b.buys == [("TEST1", 10)], b.buys
    _run(b, 1)                                   # 같은 날 체결확인 -> PENDING 복귀
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    assert st["status"] == "PENDING_ENTRY" and st["filled_quantity"] == 10, st
    _run(b, 1)                                   # ★ 같은 날 두 번째 조각은 안 나간다
    assert b.buys == [("TEST1", 10)], b.buys
    _run(b, 2)                                   # 다음 날 두 번째 조각
    assert b.buys == [("TEST1", 10), ("TEST1", 10)], b.buys
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_completed_slices_open_with_weighted_average_price():
    _seed(target_quantity=30, entry_slices=3)
    prices = [100.0, 110.0, 120.0]
    b = FakeBroker(fills=[{"fullyFilled": True, "rejected": False, "filledQty": 10, "avgPrice": p}
                          for p in prices])
    for day in (1, 2, 3):
        _run(b, day)      # 제출
        _run(b, day)      # 체결확인
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    assert st["status"] == "OPEN", st
    assert st["quantity"] == 30, st
    assert abs(st["entry_price"] - 110.0) < 1e-6, st          # (1000+1100+1200)/30
    assert st["entry_date"] == "2026-09-01", st               # 첫 조각 체결일부터 센다
    assert abs(st["stop_price"] - round(110.0 * 0.95, 2)) < 1e-9, st
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_last_slice_is_remainder_not_full_slice():
    """목표 10 을 3분할하면 4,4,2 - 초과 매수하지 않는다."""
    _seed(quantity=10, target_quantity=10, entry_slices=3)
    b = FakeBroker(fills=[{"fullyFilled": True, "rejected": False, "filledQty": q, "avgPrice": 100.0}
                          for q in (4, 4, 2)])
    for day in (1, 2, 3):
        _run(b, day); _run(b, day)
    assert [q for _, q in b.buys] == [4, 4, 2], b.buys
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    assert st["status"] == "OPEN" and st["quantity"] == 10, st
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_rejected_slice_retries_same_day():
    """거부는 체결이 아니다 - 하루 한도를 소모하지 않는다."""
    _seed(target_quantity=30, entry_slices=3)
    b = FakeBroker(fills=[{"fullyFilled": False, "rejected": True, "filledQty": 0, "avgPrice": None}])
    _run(b, 1); _run(b, 1)
    st = positionStore.load(REPO_ROOT, STRATEGY_ID)["TEST1"]
    assert st["status"] == "PENDING_ENTRY" and "last_slice_date" not in st, st
    _run(b, 1)
    assert len(b.buys) == 2, b.buys        # 같은 날 재시도됐다
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def main():
    for fn in (test_default_is_unchanged_single_shot,
               test_slices_split_quantity_and_one_per_day,
               test_completed_slices_open_with_weighted_average_price,
               test_last_slice_is_remainder_not_full_slice,
               test_rejected_slice_retries_same_day):
        fn()
        print(f"  ok  {fn.__name__}")
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})
    print("split entry self-check ok (5건)")


if __name__ == "__main__":
    main()
