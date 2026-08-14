"""Covers engine/runner.py's _schedule_portfolio() - the day-by-day driver
that calls Portfolio.process_day() over a resolved trade list. Separate from
test_runner_data_quality.py (suspension-row filtering, a different concern).

Regression for the SAME-BAR SCHEDULING BUG (found 2026-08-15 auditing
trend_breakout_v1's SMOKE baseline): a trade whose order_date == exit
fill_date (stop/target hit on the very first session) was invisible to the
"order.symbol in portfolio.open_positions" check at the top of that date's
iteration, because its own entry hadn't been admitted yet at that point
(entries are processed after exits inside process_day()). The exit was
silently dropped, leaving the symbol "open" until a LATER, unrelated trade
for the same symbol closed it - fusing two different trades' entry and exit
into one fabricated closed position. See _schedule_portfolio's docstring for
the fix (same-bar exits are retried in a second process_day() call for the
same date, after admission).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution.contracts import Fill, Order
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.runner import _schedule_portfolio
from engine.signals.schema import RiskSpec


def _make_trade(symbol, order_date, entry_price, exit_date, exit_price, exit_type):
    risk_spec = RiskSpec(stop_distance=10.0, reward_risk=3.0, max_holding_sessions=60)
    order = Order(symbol=symbol, signal_date=order_date, order_date=order_date,
                  direction="LONG", risk_spec=risk_spec)
    entry_fill = Fill(order, order_date, entry_price, "OPEN", 15.0, 0.0)
    exit_fill = Fill(order, exit_date, exit_price, exit_type, 15.0, 0.0)
    return (None, order, entry_fill, exit_fill, risk_spec, 5.0)


def test_same_bar_exit_does_not_fuse_with_a_later_trade():
    """Trade A: same-day entry+exit (order_date == exit fill_date), a real
    loss on its own. Trade B: a later, unrelated trade on the SAME symbol.
    Before the fix, A's exit vanished and B's exit closed A's entry instead -
    one fabricated position (entry=100, exit=95, a fake GAIN) instead of two
    real ones (A: 100->90 loss, B: 110->95 loss)."""
    trade_a = _make_trade("000001", "2024-01-02", 100.0, "2024-01-02", 90.0, "STOP")
    trade_b = _make_trade("000001", "2024-01-05", 110.0, "2024-01-10", 95.0, "STOP")
    resolved = [trade_a, trade_b]

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    _schedule_portfolio(resolved, portfolio, cfg)

    assert len(portfolio.closed_positions) == 2, (
        f"expected 2 separate closed trades, got {len(portfolio.closed_positions)} - "
        "same-bar exit likely fused with the later trade again"
    )
    by_entry_price = {round(p["entry"].fill_price): p for p in portfolio.closed_positions}
    assert 100 in by_entry_price, "trade A's own entry (100) missing from closed positions"
    assert 110 in by_entry_price, "trade B's own entry (110) missing from closed positions"
    assert by_entry_price[100]["exit"].fill_price == 90.0, "trade A closed with the wrong exit price"
    assert by_entry_price[110]["exit"].fill_price == 95.0, "trade B closed with the wrong exit price"
    assert by_entry_price[100]["pnl"] < 0, "trade A was a real loss - must not show as a gain"
    assert by_entry_price[110]["pnl"] < 0, "trade B was a real loss - must not show as a gain"


def test_same_bar_exit_with_no_later_trade_still_closes_correctly():
    """A same-bar trade with no subsequent same-symbol trade must still close
    on its own, correctly, the same day - it must not depend on a later
    trade's exit event coincidentally existing to ever get resolved."""
    trade_a = _make_trade("000002", "2024-01-02", 100.0, "2024-01-02", 90.0, "STOP")
    resolved = [trade_a]

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    _schedule_portfolio(resolved, portfolio, cfg)

    assert len(portfolio.closed_positions) == 1
    assert "000002" not in portfolio.open_positions
    pos = portfolio.closed_positions[0]
    assert pos["entry"].fill_price == 100.0
    assert pos["exit"].fill_price == 90.0
    assert pos["exit"].fill_type == "STOP"
    assert pos["pnl"] < 0


def test_non_same_bar_trades_unaffected():
    """Two ordinary (multi-day) trades on the same symbol must still resolve
    cleanly - the fix must not change normal scheduling."""
    trade_a = _make_trade("000003", "2024-01-02", 100.0, "2024-01-08", 130.0, "TARGET")
    trade_b = _make_trade("000003", "2024-01-10", 105.0, "2024-01-15", 95.0, "STOP")
    resolved = [trade_a, trade_b]

    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    portfolio = Portfolio(cfg)
    _schedule_portfolio(resolved, portfolio, cfg)

    assert len(portfolio.closed_positions) == 2
    by_entry_price = {round(p["entry"].fill_price): p for p in portfolio.closed_positions}
    assert by_entry_price[100]["exit"].fill_price == 130.0
    assert by_entry_price[105]["exit"].fill_price == 95.0


def run():
    test_same_bar_exit_does_not_fuse_with_a_later_trade()
    test_same_bar_exit_with_no_later_trade_still_closes_correctly()
    test_non_same_bar_trades_unaffected()
    print("test_runner_scheduling: OK")


if __name__ == "__main__":
    run()
