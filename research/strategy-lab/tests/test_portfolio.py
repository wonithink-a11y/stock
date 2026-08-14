import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution.contracts import Fill, Order
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.signals.schema import RiskSpec


def _order_fill(symbol, price, cost_bps=15.0):
    order = Order(symbol, "2024-01-01", "2024-01-02", "LONG", RiskSpec(10.0, 3.0, 60))
    fill = Fill(order, "2024-01-02", price, "OPEN", cost_bps, 0.0)
    return order, fill


def _expected_shares(target_alloc, price, cost_bps):
    """Cost is sized INTO the allocation, not added on top - otherwise N equal
    slices of exactly cash/N collectively overshoot cash once costs are added."""
    all_in_price = price * (1 + cost_bps / 10000)
    return int(target_alloc // all_in_price)


def test_equal_weight_sizing_across_10_candidates():
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10)
    pf = Portfolio(cfg)
    candidates = [_order_fill(f"{i:06d}", 10_000) for i in range(10)]
    pf.process_day("2024-01-02", [], candidates)
    assert len(pf.open_positions) == 10, "all 10 equal-weight slots must be affordable out of 100M capital"
    expected = _expected_shares(100_000_000 / 10, 10_000, 15.0)
    total_spent = 0.0
    for sym, pos in pf.open_positions.items():
        assert pos["shares"] == expected
        total_spent += pos["cost_basis"]
    assert total_spent <= cfg.initial_capital, "sizing must never overshoot total capital once costs are included"


def test_fractional_shares_false_truncates():
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, fractional_shares=False)
    pf = Portfolio(cfg)
    order, fill = _order_fill("000001", 7_777)
    pf.process_day("2024-01-02", [], [(order, fill)])
    shares = pf.open_positions["000001"]["shares"]
    assert shares == int(shares)
    assert shares == _expected_shares(100_000_000 / 10, 7_777, 15.0)


def test_same_day_exit_cash_not_reused_same_day():
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=1)  # 1 slot forces the conflict
    pf = Portfolio(cfg)
    order1, fill1 = _order_fill("000001", 10_000_000)  # eats ~all capital into 1 position
    pf.process_day("2024-01-02", [], [(order1, fill1)])
    assert len(pf.open_positions) == 1
    cash_before_exit_day = pf.cash

    exit_order = order1
    exit_fill = Fill(exit_order, "2024-01-03", 12_000_000, "TARGET", 15.0, 0.0)  # big profit, frees a lot of cash
    order2, fill2 = _order_fill("000002", 5_000_000)
    pf.process_day("2024-01-03", [("000001", exit_fill, 9)], [(order2, fill2)])

    # position 2 could only have been sized from cash available BEFORE today's
    # exit proceeds were credited - i.e. from cash_before_exit_day, not from the
    # freshly-freed larger amount.
    assert "000002" in pf.open_positions
    shares2 = pf.open_positions["000002"]["shares"]
    expected_alloc = cash_before_exit_day / cfg.max_positions
    assert shares2 == _expected_shares(expected_alloc, 5_000_000, 15.0)


def test_never_goes_cash_negative():
    cfg = PortfolioConfig(initial_capital=1_000, max_positions=1)
    pf = Portfolio(cfg)
    order, fill = _order_fill("000001", 999_999_999)  # unaffordable at any share count > 0
    pf.process_day("2024-01-02", [], [(order, fill)])
    assert "000001" not in pf.open_positions
    assert pf.cash == 1_000


def test_tie_break_ticker_ascending_selects_top_10_of_more():
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break="ticker_ascending")
    pf = Portfolio(cfg)
    candidates = [_order_fill(f"{i:06d}", 10_000) for i in range(15)]
    pf.process_day("2024-01-02", [], candidates)
    assert set(pf.open_positions.keys()) == {f"{i:06d}" for i in range(10)}, (
        "must admit the 10 lowest tickers (ascending), not an arbitrary subset"
    )


def test_duplicate_symbol_never_double_opened():
    """A symbol already holding an open position must not be admitted again -
    two simultaneous positions under one symbol key would silently overwrite
    the first one's cost basis, corrupting accounting."""
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10)
    pf = Portfolio(cfg)
    order1, fill1 = _order_fill("000001", 10_000)
    pf.process_day("2024-01-02", [], [(order1, fill1)])
    original_cost_basis = pf.open_positions["000001"]["cost_basis"]

    order1b, fill1b = _order_fill("000001", 50_000)  # a second signal for the same ticker, still open
    pf.process_day("2024-01-03", [], [(order1b, fill1b)])

    assert len(pf.open_positions) == 1
    assert pf.open_positions["000001"]["cost_basis"] == original_cost_basis, (
        "the second candidate for an already-open symbol must be rejected, not overwrite the first"
    )


def run():
    test_equal_weight_sizing_across_10_candidates()
    test_fractional_shares_false_truncates()
    test_same_day_exit_cash_not_reused_same_day()
    test_never_goes_cash_negative()
    test_tie_break_ticker_ascending_selects_top_10_of_more()
    test_duplicate_symbol_never_double_opened()
    print("test_portfolio: OK")


if __name__ == "__main__":
    run()
