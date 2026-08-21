"""OrderIntent/PaperFill - the live/paper-trading pipeline stages between a
strategy's Signal and a broker. Mirrors engine/execution/contracts.py's
Order/Fill split, but for the live path: no full historical bar series is
available ahead of time, so a Broker implementation (PaperBroker today,
KISBrokerAdapter later) decides fills one day at a time instead of a backtest
loop resolving an entire trade in one pass.

A strategy or the paper engine never talks to a broker API directly - it only
produces an OrderIntent. Swapping PaperBroker for a real broker later should
not require touching engine/live/paperEngine.py's orchestration logic, only
the fill-execution call site.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str              # "BUY" | "SELL"
    quantity: int
    reason: str             # "ENTRY_SIGNAL" | "STOP" | "TARGET" | "TIME_EXIT"
    intent_date: str        # KST date this intent was generated, engine/execution's
                             # next-tradable-session rule still applies for BUY fills
    strategy_id: str
    stop_price: Optional[float] = None
    target_price: Optional[float] = None


@dataclass(frozen=True)
class PaperFill:
    intent: OrderIntent
    fill_date: str
    fill_price: float
    fill_type: str          # "ENTRY" | "STOP" | "TARGET" | "TIME_EXIT"
