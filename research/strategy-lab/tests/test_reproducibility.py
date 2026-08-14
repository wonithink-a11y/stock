"""Same inputs -> byte-identical outputs, across the whole Signal->Fill->Portfolio
->Metrics chain. No RNG anywhere in this engine (5DC-v1A itself is deterministic),
so this should hold trivially - the test exists to catch accidental
non-determinism (e.g. dict/set iteration order leaking into output ordering).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.execution.contracts import Order
from engine.execution.executor import CostModel, simulate_trade
from engine.metrics.metrics import trade_stats
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.signals.schema import RiskSpec


class FakeCalendar:
    def __init__(self, n=80):
        self.days = [f"2024-01-{d:02d}" if d <= 31 else f"2024-02-{d - 31:02d}" for d in range(1, n + 1)]

    def sessions_between(self, start, end):
        return [d for d in self.days if start <= d <= end]

    def next_n_sessions(self, start, n):
        return [d for d in self.days if d >= start][:n]


def _run_once():
    cal = FakeCalendar()
    tickers = [f"{i:06d}" for i in range(15)]
    orders = [Order(t, cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60)) for t in tickers]
    bars_by_ticker = {
        t: pd.DataFrame(
            {"open": [100, 100, 100], "high": [101, 132, 100], "low": [99, 99, 99], "close": [100, 130, 100]},
            index=[cal.days[1], cal.days[2], cal.days[3]],
        )
        for t in orders_symbols(orders)
    }
    fills = {}
    for order in orders:
        result = simulate_trade(order, bars_by_ticker[order.symbol], cal, CostModel())
        if result:
            fills[order.symbol] = result

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    pf = Portfolio(cfg)
    candidates = [(o, fills[o.symbol][0]) for o in orders if o.symbol in fills]
    pf.process_day(cal.days[1], [], candidates)

    exits = [(sym, fills[sym][1], pos["shares"]) for sym, pos in list(pf.open_positions.items())]
    pf.process_day(cal.days[2], exits, [])

    trades = [{"pnl": t["pnl"], "holding_sessions": 1} for t in pf.closed_positions]
    stats = trade_stats(trades)
    return {
        "finalCash": pf.cash,
        "closedCount": len(pf.closed_positions),
        "tradeStats": stats,
        "orderSymbolsAdmitted": sorted(pf.closed_positions and [p["symbol"] for p in pf.closed_positions] or []),
    }


def orders_symbols(orders):
    return [o.symbol for o in orders]


def test_two_runs_produce_identical_results():
    result1 = _run_once()
    result2 = _run_once()
    assert result1 == result2, "identical inputs must produce identical outputs"


def run():
    test_two_runs_produce_identical_results()
    print("test_reproducibility: OK")


if __name__ == "__main__":
    run()
