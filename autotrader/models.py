"""데이터 모델 — 전략이 돌려주는 주문 의도(Intent)와 브로커가 돌려주는 상태."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

MARKETS = ("KR", "US")
SIDES = ("BUY", "SELL")
ORDER_TYPES = ("limit", "market", "loc")


@dataclass(frozen=True)
class Intent:
    """전략이 엔진에 요청하는 주문. 전략은 브로커를 직접 부르지 않는다 — 주문은 엔진만 낸다."""
    symbol: str
    side: str                        # BUY | SELL
    qty: int
    market: str = "KR"               # KR(국내) | US(해외 나스닥)
    order_type: str = "limit"        # limit | market(KR 만) | loc(US 실전 만)
    limit_price: Optional[float] = None
    reason: str = ""

    def validate(self) -> Optional[str]:
        """문제가 있으면 사유 문자열, 없으면 None."""
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            return "종목코드가 비었다"
        if self.side not in SIDES:
            return f"side 는 BUY|SELL: {self.side!r}"
        if self.market not in MARKETS:
            return f"market 은 KR|US: {self.market!r}"
        if self.order_type not in ORDER_TYPES:
            return f"order_type 은 limit|market|loc: {self.order_type!r}"
        if isinstance(self.qty, bool) or not isinstance(self.qty, int) or self.qty <= 0:
            return f"수량은 양의 정수여야 한다: {self.qty!r}"
        if self.order_type == "market" and self.market != "KR":
            return "시장가는 국내(KR)만 지원한다"
        if self.order_type == "loc" and self.market != "US":
            return "loc 는 해외(US)만 지원한다"
        if self.order_type in ("limit", "loc"):
            p = self.limit_price
            if p is None or isinstance(p, bool) or not isinstance(p, (int, float)) \
                    or not math.isfinite(p) or p <= 0:
                return f"지정가가 필요하다(양수): {p!r}"
        return None


@dataclass(frozen=True)
class Position:
    symbol: str
    market: str
    qty: int
    avg_price: float
    price: float = 0.0              # 현재가(브로커 잔고 응답). 0 = 모름 — 손익 계산에서 빠진다
    name: str = ""                  # 종목명(브로커 잔고 응답). 없으면 화면이 유니버스에서 찾는다


@dataclass(frozen=True)
class OpenOrder:
    order_no: str
    symbol: str
    market: str
    side: str
    qty: int
    filled_qty: int
    price: float

    @property
    def remaining(self) -> int:
        return self.qty - self.filled_qty
