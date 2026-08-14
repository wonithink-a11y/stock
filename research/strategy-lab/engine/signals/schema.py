"""Signal is the only thing a strategy's rule.py returns. This file defines its
shape - no BB/CCI composition logic lives here, that belongs to strategies/.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Signal:
    symbol: str
    signal_date: str
    direction: str  # "LONG" | "SHORT"
    signal_strength: Optional[float] = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RiskSpec:
    """Stop/target declared as a *distance* from entry, not an absolute price -
    entry price is not known at signal time (it's next session's open).

    ATR TIMING CONTRACT: stop_distance must be computed from data available at
    signal_date (e.g. ATR[t]) and passed in already resolved. The execution layer
    never recomputes it at fill time, so ATR[t+1] cannot leak in structurally.
    """
    stop_distance: float
    reward_risk: float
    max_holding_sessions: int
