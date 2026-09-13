"""BithumbBroker - engine/live/paperEngine.py의 poll_once()가 실제 주문을 낼 때
쓰는 통로가 될 클래스. BithumbClient를 감싸기만 한다 - 주문/체결 판단 로직은
여기 없다(upbitBroker.py·kisVtsBroker.py와 동일 원칙).

**이 클래스를 실제로 생성해서 poll_once(enable_live_orders=True)에 넘기는
드라이버 스크립트는 이 저장소에 없다.** upbitBroker.py와 동일한 이유로
dormant다 - 코드는 완성돼 있지만 실행은 모의매매 검증 이후 별도 승인
대상이다. BITHUMB_ACCESS_KEY/BITHUMB_SECRET_KEY가 .env에 있어야만 이
클래스의 메서드가 동작한다(BithumbClient._require_keys()).

submit_buy(quantity)는 '코인 수량'을 받지만 주문 시점 시세로 notional을
역산해 지정가(order_type=limit)로 낸다 - bithumbClient.py의
place_order(order_type='price'/'market')로 시장가를 내는 방식은
**미검증**(공식 예제가 limit만 보여줬다)이라 여기서는 안전하게 지정가만
쓴다. 체결 안 될 수 있다는 게 대가지만, 미검증 주문타입으로 예상 밖
동작을 내는 것보다 낫다.
"""
from .bithumbClient import BithumbClient, BithumbError

__all__ = ["BithumbBroker", "BithumbError"]


class BithumbBroker:
    def __init__(self, client=None):
        self.client = client or BithumbClient()

    def submit_buy(self, symbol, quantity):
        """반환: 주문 order_id(str). 현재가의 100.5%를 지정가로 넣어 즉시
        체결을 노린다(시장가 미검증 - 위 docstring)."""
        price = self.client.get_ticker(symbol)
        limit_price = round(price * 1.005)
        resp = self.client.place_order(symbol, side="bid", order_type="limit",
                                        volume=quantity, price=limit_price)
        return resp["order_id"]

    def submit_sell(self, symbol, quantity):
        price = self.client.get_ticker(symbol)
        limit_price = round(price * 0.995)
        resp = self.client.place_order(symbol, side="ask", order_type="limit",
                                        volume=quantity, price=limit_price)
        return resp["order_id"]

    def check_fill(self, order_no, order_date_yyyymmdd, requested_qty):
        """{"fullyFilled", "rejected", "filledQty", "avgPrice", "pending"} -
        상태 해석은 paperEngine.py가 한다(upbitBroker.py와 동일 계약).
        ★ get_order()가 미검증 엔드포인트를 쓴다(bithumbClient.py 참고)."""
        resp = self.client.get_order(order_no)
        state = resp.get("state")
        executed = float(resp.get("executed_volume") or 0)
        trades = resp.get("trades") or []
        avg_price = None
        if trades:
            total_cost = sum(float(t["price"]) * float(t["volume"]) for t in trades)
            total_vol = sum(float(t["volume"]) for t in trades)
            avg_price = total_cost / total_vol if total_vol else None
        fully_filled = state == "done" and executed >= float(requested_qty) * 0.999
        rejected = state == "cancel" and executed == 0
        return {"fullyFilled": fully_filled, "rejected": rejected,
                "filledQty": executed, "avgPrice": avg_price,
                "pending": not fully_filled and not rejected}

    def current_price(self, symbol):
        return self.client.get_ticker(symbol)
