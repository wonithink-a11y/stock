"""UpbitBroker - engine/live/paperEngine.py의 poll_once()가 실제 주문을 낼 때
쓰는 통로가 될 클래스. UpbitClient를 감싸기만 한다 - 주문/체결 판단 로직은
여기 없다(그건 paperEngine.py의 상태기계 몫, kisVtsBroker.py와 동일 원칙).

**이 클래스를 실제로 생성해서 poll_once(enable_live_orders=True)에 넘기는
드라이버 스크립트는 이 저장소에 아직 없다.** 업비트-연동-2026-08-27 계획
문서의 "이번에 안 하는 것" 참고 - 코드는 완성돼 있지만 실행은 모의매매
검증 이후 별도 승인 대상이다. UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY가 .env에
있어야만 이 클래스의 메서드가 동작한다(UpbitClient._require_keys()).

submit_buy(quantity)는 '코인 수량'을 받지만 업비트 시장가 매수는 '총
KRW 금액'(ord_type=price)으로 주문한다 - 호출 시점 시세로 notional을
역산해서 보낸다(체결 시점까지의 가격 변동만큼 약간 어긋날 수 있다 - 시장가
주문 특유의 슬리피지와 같은 성격이지, 이 클래스의 결함이 아니다. 상류
paperEngine.scan_rebalance_signals()도 이미 신호 시점 가격으로 quantity를
근사한다). submit_sell(quantity)는 코인 수량 그대로(ord_type=market)
보낸다. 매수/매도가 비대칭인 건 업비트 API 자체의 설계다(문서 확인,
2026-08-27) - KIS처럼 매수/매도가 대칭인 걸 가정하고 짜면 안 된다.
"""
from .upbitClient import UpbitClient, UpbitError

__all__ = ["UpbitBroker", "UpbitError"]


class UpbitBroker:
    def __init__(self, client=None):
        self.client = client or UpbitClient()

    def submit_buy(self, symbol, quantity):
        """반환: 주문 uuid(str)."""
        price = self.client.get_ticker(symbol)
        notional = round(price * quantity)
        resp = self.client.place_order(symbol, side="bid", ord_type="price", price=notional)
        return resp["uuid"]

    def submit_sell(self, symbol, quantity):
        resp = self.client.place_order(symbol, side="ask", ord_type="market", volume=quantity)
        return resp["uuid"]

    def check_fill(self, order_no, order_date_yyyymmdd, requested_qty):
        """{"fullyFilled", "rejected", "filledQty", "avgPrice", "pending"} -
        상태 해석은 paperEngine.py가 한다(kisVtsBroker.py와 동일 계약)."""
        resp = self.client.get_order(order_no)
        state = resp.get("state")
        executed = float(resp.get("executed_volume") or 0)
        trades = resp.get("trades") or []
        avg_price = None
        if trades:
            total_cost = sum(float(t["price"]) * float(t["volume"]) for t in trades)
            total_vol = sum(float(t["volume"]) for t in trades)
            avg_price = total_cost / total_vol if total_vol else None
        # 0.999 여유 - 코인 수량은 float라 부동소수점 오차로 정확히 같지
        # 않을 수 있다(KIS는 정수 주식수라 이 문제가 없었다).
        fully_filled = state == "done" and executed >= float(requested_qty) * 0.999
        rejected = state == "cancel" and executed == 0
        return {"fullyFilled": fully_filled, "rejected": rejected,
                "filledQty": executed, "avgPrice": avg_price,
                "pending": not fully_filled and not rejected}

    def current_price(self, symbol):
        return self.client.get_ticker(symbol)
