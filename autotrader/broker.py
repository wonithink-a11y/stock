"""브로커 인터페이스와 테스트용 FakeBroker.

엔진은 이 인터페이스만 안다. 브로커마다(KIS 등) 이걸 구현한다. 조회는 부작용이 없고, 주문/취소는
`dry_run` 을 받는다 — 엔진은 `--execute` 가 아니면 항상 dry_run=True 로 부른다.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import Intent, OpenOrder, Position


class Broker:
    name = "base"
    mode = "paper"

    def positions(self, market: str) -> List[Position]:
        raise NotImplementedError

    def cash(self, market: str, ref_symbol: Optional[str] = None) -> float:
        """주문가능 현금(시장 통화). 해외는 KIS 가 종목·가격을 넣어야 계산하므로 ref_symbol 이 필요하다."""
        raise NotImplementedError

    def open_orders(self, market: str) -> List[OpenOrder]:
        raise NotImplementedError

    def quote(self, symbol: str, market: str) -> float:
        raise NotImplementedError

    def place(self, intent: Intent, dry_run: bool = True) -> dict:
        raise NotImplementedError

    def cancel(self, order: OpenOrder, dry_run: bool = True) -> dict:
        raise NotImplementedError


class FakeBroker(Broker):
    """메모리 브로커 — 회귀 테스트용. 호출을 전부 기록한다."""
    name = "fake"

    def __init__(self, positions: Optional[Dict[str, List[Position]]] = None,
                 cash: Optional[Dict[str, float]] = None,
                 quotes: Optional[Dict[str, float]] = None,
                 open_orders: Optional[List[OpenOrder]] = None,
                 cancel_removes: bool = True, place_fails: bool = False):
        self._pos = positions or {}
        self._cash = cash or {}
        self._quotes = quotes or {}
        self._open = list(open_orders or [])
        self.cancel_removes = cancel_removes
        self.place_fails = place_fails
        self.placed: List[dict] = []
        self.cancelled: List[dict] = []
        self._seq = 1000

    def positions(self, market):
        return list(self._pos.get(market, []))

    def cash(self, market, ref_symbol=None):
        return float(self._cash.get(market, 0.0))

    def open_orders(self, market):
        return [o for o in self._open if o.market == market]

    def quote(self, symbol, market):
        if symbol not in self._quotes:
            raise KeyError(f"시세 없음: {symbol}")
        return float(self._quotes[symbol])

    def place(self, intent, dry_run=True):
        if dry_run:
            return {"dryRun": True, "symbol": intent.symbol, "side": intent.side, "qty": intent.qty}
        if self.place_fails:
            raise RuntimeError("주문 실패(가짜)")
        self._seq += 1
        rec = {"dryRun": False, "orderNo": str(self._seq), "symbol": intent.symbol,
               "side": intent.side, "qty": intent.qty, "price": intent.limit_price,
               "market": intent.market}
        self.placed.append(rec)
        return rec

    def cancel(self, order, dry_run=True):
        if dry_run:
            return {"dryRun": True, "orderNo": order.order_no}
        self.cancelled.append({"orderNo": order.order_no, "symbol": order.symbol})
        if self.cancel_removes:
            self._open = [o for o in self._open if o.order_no != order.order_no]
        return {"dryRun": False, "orderNo": order.order_no}
