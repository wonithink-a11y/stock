"""KisVtsBroker - engine/live/paperEngine.py의 poll_once()가 실제 주문을 낼 때
쓰는 유일한 통로. KisVtsClient를 감싸기만 한다 - 주문/체결 판단 로직은 여기
없다(그건 paperEngine.py의 상태기계 몫).

PaperBroker(로컬 시뮬레이션, 동기)와 인터페이스가 다르다 - 실제 주문은
"제출"과 "체결 확인"이 분리된 별개 호출이라 동기적으로 합칠 수 없다.
paperEngine.py가 이 비동기성을 ENTRY_SUBMITTED/EXIT_SUBMITTED 상태로
다룬다.
"""
from .kisVtsClient import KisVtsClient, KisVtsError

__all__ = ["KisVtsBroker", "KisVtsError"]


class KisVtsBroker:
    def __init__(self, client=None):
        self.client = client or KisVtsClient()

    def submit_buy(self, symbol, quantity):
        """반환: 주문번호(str)."""
        resp = self.client.order_cash("BUY", symbol, quantity)
        return resp["output"]["ODNO"]

    def submit_sell(self, symbol, quantity):
        resp = self.client.order_cash("SELL", symbol, quantity)
        return resp["output"]["ODNO"]

    def check_fill(self, order_no, order_date_yyyymmdd, requested_qty):
        """{"fullyFilled", "rejected", "filledQty", "avgPrice", "pending"} 그대로
        반환 - 상태 해석은 paperEngine.py가 한다."""
        return self.client.get_order_status(order_no, order_date_yyyymmdd, requested_qty)

    def current_price(self, symbol):
        return self.client.get_current_price(symbol)
