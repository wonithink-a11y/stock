"""engine/live/upbitPaperBroker.py 구조 테스트 - 네트워크 없음(FakeClient로
UpbitClient.get_ticker를 대체). 상태 없는 설계(order_no가 심볼을 그대로
담아 재시작에도 안전한지)와 poll_once()가 기대하는 반환 모양을 확인한다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.live.upbitPaperBroker import UpbitPaperBroker

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


class FakeClient:
    def __init__(self, price):
        self.price = price
        self.calls = 0

    def get_ticker(self, market):
        self.calls += 1
        return self.price


def test_submit_and_check_fill_round_trip():
    broker = UpbitPaperBroker(client=FakeClient(50000000.0))
    order_no = broker.submit_buy("KRW-BTC", 0.001)
    result = broker.check_fill(order_no, "20260827", 0.001)
    ok("fullyFilled immediately (no async latency to simulate)", result["fullyFilled"] is True, result)
    ok("filledQty echoes requested_qty", result["filledQty"] == 0.001, result)
    ok("avgPrice comes from current ticker", result["avgPrice"] == 50000000.0, result)
    ok("not rejected, not pending", result["rejected"] is False and result["pending"] is False, result)


def test_stateless_across_broker_instances():
    """order_no must encode enough that a *different* broker instance
    (simulating a process restart between submit and check_fill) can still
    resolve the fill - the risk this guards is losing an in-memory order
    dict on restart."""
    client = FakeClient(123.0)
    order_no = UpbitPaperBroker(client=client).submit_sell("KRW-ETH", 2.0)
    fresh_broker = UpbitPaperBroker(client=client)  # 새 인스턴스 = 재시작 흉내
    result = fresh_broker.check_fill(order_no, "20260827", 2.0)
    ok("check_fill works from a fresh broker instance (restart-safe)",
       result["fullyFilled"] is True, result)


def test_current_price_delegates_to_client():
    broker = UpbitPaperBroker(client=FakeClient(999.0))
    ok("current_price returns client's ticker", broker.current_price("KRW-BTC") == 999.0)


def main():
    test_submit_and_check_fill_round_trip()
    test_stateless_across_broker_instances()
    test_current_price_delegates_to_client()
    print(f"\n{'='*40}\npassed {passed} . failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
