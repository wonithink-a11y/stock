"""전략 인터페이스와 로더 — 사용자가 갈아끼우는 자리.

전략은 파일 하나(`autotrader/strategies/<이름>.py`)다. 그 파일에 `STRATEGY` 라는 이름으로 `Strategy` 서브클래스
(또는 인스턴스)를 두면 설정의 `"strategy": "<이름>"` 으로 불려진다. 새 전략은 `_template.py` 를 복사해서 시작한다.

전략이 하는 일은 `decide(ctx)` 에서 **주문 목록(Intent)을 돌려주는 것뿐**이다. 브로커를 직접 부르지 않는다 —
주문은 엔진이 위험 검사(risk.py)를 거쳐 낸다.
"""
from __future__ import annotations

import importlib
import re
from datetime import datetime
from typing import Dict, List, Optional

from .broker import Broker
from .models import Intent, Position


class Strategy:
    name = "unnamed"
    markets = ["KR"]          # 이 전략이 다루는 시장. 설정의 markets 와 교집합만 실행된다.

    def decide(self, ctx: "Context") -> List[Intent]:
        raise NotImplementedError


class Context:
    """전략에 주는 읽기 전용 시야. 조회는 실행 안에서 캐시된다(같은 값을 두 번 묻지 않는다)."""

    def __init__(self, broker: Broker, now: datetime, params: dict, state: dict):
        self._broker = broker
        self.now = now                      # KST
        self.params = params                # 설정의 params
        self.state = state                  # 실행 사이에 유지되는 dict — 전략이 자유롭게 쓴다
        self._pos: Dict[str, Dict[str, Position]] = {}
        self._quote: Dict[tuple, float] = {}
        self._cash: Dict[tuple, float] = {}

    def positions(self, market: str) -> Dict[str, Position]:
        if market not in self._pos:
            self._pos[market] = {p.symbol: p for p in self._broker.positions(market)}
        return self._pos[market]

    def cash(self, market: str, ref_symbol: Optional[str] = None) -> float:
        key = (market, ref_symbol)
        if key not in self._cash:
            self._cash[key] = self._broker.cash(market, ref_symbol)
        return self._cash[key]

    def quote(self, symbol: str, market: str) -> float:
        key = (symbol, market)
        if key not in self._quote:
            self._quote[key] = self._broker.quote(symbol, market)
        return self._quote[key]


_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def load_strategy(name: str) -> Strategy:
    """`autotrader.strategies.<name>` 의 STRATEGY 를 불러온다. 이름은 소문자·숫자·밑줄만(경로 조작 방지)."""
    if not _NAME.match(name or ""):
        raise ValueError(f"전략 이름은 소문자로 시작하는 [a-z0-9_] 만 가능: {name!r}")
    mod = importlib.import_module(f"autotrader.strategies.{name}")
    s = getattr(mod, "STRATEGY", None)
    if s is None:
        raise ValueError(f"autotrader/strategies/{name}.py 에 STRATEGY 가 없다")
    s = s() if isinstance(s, type) else s
    if not isinstance(s, Strategy):
        raise ValueError(f"STRATEGY 가 Strategy 서브클래스가 아니다: {name}")
    return s
