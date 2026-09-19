"""위험 검사 — 모든 주문이 거치는 유일한 관문. 순수 함수(네트워크·파일 없음)라서 회귀로 전부 핀할 수 있다.

전략은 브로커를 직접 부르지 않는다. 주문은 엔진만 내고, 엔진은 주문마다 `check_intent` 를 통과시킨다.
금액은 시장 통화 기준(KR=원, US=달러). 거부 사유는 문자열로 돌려주고(None=통과) 엔진이 리포트에 남긴다.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional

from .models import Intent


def order_value(intent: Intent, last_price: float) -> float:
    """주문 금액 추정: 지정가가 있으면 지정가, 시장가는 직전 시세."""
    price = intent.limit_price if intent.order_type in ("limit", "loc") else last_price
    return float(intent.qty) * float(price)


def check_intent(intent: Intent, *, risk: Dict, allowlist: Iterable[str],
                 last_price: Optional[float], sellable_qty: int, cash: float,
                 held_value: float, spent_today: float, spent_run: float,
                 orders_run: int) -> Optional[str]:
    """None 이면 통과. 문자열이면 거부 사유.

    sellable_qty: 이번 실행에서 이미 잡힌 매도를 뺀 매도 가능 수량(공매도 금지)
    cash: 이번 실행에서 이미 잡힌 매수를 뺀 남은 주문가능 현금
    held_value: 그 종목의 현재 보유 평가금액
    spent_today: 오늘 이미 실행된 주문 금액(원장), spent_run: 이번 실행에서 앞서 잡힌 금액
    """
    bad = intent.validate()
    if bad:
        return bad
    if intent.symbol not in set(allowlist):
        return f"허용목록에 없는 종목: {intent.symbol}"
    if last_price is None or not isinstance(last_price, (int, float)) or not math.isfinite(last_price) \
            or last_price <= 0:
        return "직전 시세를 알 수 없다(시세 없이는 주문하지 않는다)"
    if orders_run >= risk["max_orders_per_run"]:
        return f"1회 실행당 주문 수 한도({risk['max_orders_per_run']}) 초과"
    if intent.order_type in ("limit", "loc"):
        dev = abs(intent.limit_price / last_price - 1.0) * 100
        if dev > risk["price_band_pct"]:
            return f"지정가가 직전 시세에서 {dev:.1f}% 벗어남(허용 ±{risk['price_band_pct']}%)"
    value = order_value(intent, last_price)
    if value > risk["max_order_value"]:
        return f"주문 금액 {value:,.0f} 이 주문당 한도 {risk['max_order_value']:,} 초과"
    if spent_today + spent_run + value > risk["max_daily_value"]:
        return (f"일일 한도 초과: 오늘 {spent_today:,.0f} + 이번 실행 {spent_run:,.0f} + 이 주문 {value:,.0f}"
                f" > {risk['max_daily_value']:,}")
    if intent.side == "SELL":
        if not risk["allow_sell"]:
            return "설정에서 매도가 막혀 있다(allow_sell=false)"
        if intent.qty > sellable_qty:
            return f"매도 가능 수량 {sellable_qty} 보다 많다(공매도 금지)"
    else:
        if value > cash:
            return f"주문가능 현금 {cash:,.0f} 보다 큰 매수 {value:,.0f}"
        if held_value + value > risk["max_position_value"]:
            return (f"종목당 최대 보유금액 {risk['max_position_value']:,} 초과"
                    f"(보유 {held_value:,.0f} + 이 주문 {value:,.0f})")
    return None
