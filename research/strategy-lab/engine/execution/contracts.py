"""Order/Fill - the pipeline stages between Signal and Position. executor.py
fills these in; no strategy-specific code lives here (only RiskSpec, itself
strategy-declared, flows in from the caller).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Order:
    symbol: str
    signal_date: str
    order_date: str        # next tradable session - engine computes this, not the strategy
    direction: str
    risk_spec: object       # engine.signals.schema.RiskSpec (duck-typed to avoid a cross-package import)


@dataclass(frozen=True)
class Fill:
    order: Order
    fill_date: str
    fill_price: float
    fill_type: str          # "OPEN" | "STOP" | "TARGET" | "TIME_EXIT"
    cost_bps: float
    slippage_bps: float
