"""Covers engine/runner.py's _merge_continuous_same_symbol_holds() - the opt-in
(PARAMS["scheduling"]["continuousHoldOnRenewal"]) step that collapses a same-
symbol renewal chain into one continuously-held trade, added 2026-08-21 while
fixing pbr_value_v1's cash-timing throttle (see the function's own docstring).
Separate from test_runner_scheduling.py (_schedule_portfolio()'s own same-bar
contract, unaffected - this merge runs strictly before scheduling).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution.contracts import Fill, Order
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.runner import _merge_continuous_same_symbol_holds, _schedule_portfolio
from engine.signals.schema import RiskSpec


def _make_trade(symbol, order_date, entry_price, exit_date, exit_price, exit_type):
    risk_spec = RiskSpec(stop_distance=10.0, reward_risk=3.0, max_holding_sessions=60)
    order = Order(symbol=symbol, signal_date=order_date, order_date=order_date,
                  direction="LONG", risk_spec=risk_spec)
    entry_fill = Fill(order, order_date, entry_price, "OPEN", 15.0, 0.0)
    exit_fill = Fill(order, exit_date, exit_price, exit_type, 15.0, 0.0)
    return (None, order, entry_fill, exit_fill, risk_spec, 5.0)


def test_renewal_chain_merges_into_one_continuous_hold():
    """Two consecutive TIME_EXIT trades on the same symbol where trade A's exit
    date exactly equals trade B's order_date (a monthly renewal - the symbol
    stayed selected) must merge into ONE trade: A's entry, B's exit, no interim
    event."""
    trade_a = _make_trade("000001", "2024-01-02", 100.0, "2024-02-02", 110.0, "TIME_EXIT")
    trade_b = _make_trade("000001", "2024-02-02", 110.0, "2024-03-04", 120.0, "TIME_EXIT")
    merged, merge_count = _merge_continuous_same_symbol_holds([trade_a, trade_b])

    assert merge_count == 1
    assert len(merged) == 1
    _, order, entry_fill, exit_fill, _, _ = merged[0]
    assert order.symbol == "000001"
    assert entry_fill.fill_price == 100.0, "must keep the ORIGINAL entry, not trade B's"
    assert exit_fill.fill_price == 120.0, "must extend to the FINAL exit"
    assert exit_fill.fill_date == "2024-03-04"

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    _schedule_portfolio(merged, portfolio, cfg)
    assert len(portfolio.closed_positions) == 1, "no interim exit/reentry cash event should reach the portfolio"


def test_stop_exit_is_never_merged():
    """A STOP exit followed (by coincidence) by a same-day, unrelated new signal
    for the same symbol must NOT be merged - a real stop-loss must never be
    silently welded into a fabricated continuous hold."""
    trade_a = _make_trade("000002", "2024-01-02", 100.0, "2024-01-15", 90.0, "STOP")
    trade_b = _make_trade("000002", "2024-01-15", 90.0, "2024-02-15", 95.0, "TIME_EXIT")
    merged, merge_count = _merge_continuous_same_symbol_holds([trade_a, trade_b])

    assert merge_count == 0
    assert len(merged) == 2, "STOP-then-new-signal must stay as two distinct trades"


def test_default_path_unaffected_when_merge_step_not_invoked():
    """The same renewal chain as the first test, scheduled WITHOUT calling the
    merge step (the current default for every strategy lacking the opt-in
    policy field) - must resolve exactly as before this feature existed: two
    separate closed positions, unchanged from test_runner_scheduling.py's
    baseline behavior."""
    trade_a = _make_trade("000003", "2024-01-02", 100.0, "2024-02-02", 110.0, "TIME_EXIT")
    trade_b = _make_trade("000003", "2024-02-02", 110.0, "2024-03-04", 120.0, "TIME_EXIT")
    resolved = [trade_a, trade_b]  # merge step deliberately skipped

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    _schedule_portfolio(resolved, portfolio, cfg)
    assert len(portfolio.closed_positions) == 2, "unmerged chain must still resolve as two trades"


def run():
    test_renewal_chain_merges_into_one_continuous_hold()
    test_stop_exit_is_never_merged()
    test_default_path_unaffected_when_merge_step_not_invoked()
    print("test_continuous_hold_merge: OK")


if __name__ == "__main__":
    run()
