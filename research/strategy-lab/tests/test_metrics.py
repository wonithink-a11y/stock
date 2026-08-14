import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.metrics.metrics import (cagr, calmar, max_drawdown, sharpe, sortino,
                                     total_return, trade_stats)


def test_total_return_exact():
    curve = [("2020-01-01", 1_000_000), ("2021-01-01", 1_210_000)]
    assert abs(total_return(curve) - 0.21) < 1e-9


def test_max_drawdown_exact():
    curve = [("2020-01-01", 100), ("2020-01-02", 120), ("2020-01-03", 90), ("2020-01-04", 110)]
    assert abs(max_drawdown(curve) - (-0.25)) < 1e-9


def test_cagr_roughly_doubling_over_a_year():
    curve = [("2020-01-01", 1_000_000), ("2020-12-31", 2_000_000)]  # ~365 days
    c = cagr(curve)
    assert c is not None
    assert abs(c - 1.0) < 0.01  # ~100% CAGR for ~doubling in ~1 year


def test_sharpe_none_when_flat():
    curve = [("2020-01-0" + str(i), 1_000_000) for i in range(1, 6)]
    assert sharpe(curve) is None  # zero variance -> undefined, not fabricated as 0


def test_sortino_and_calmar_run_without_error():
    curve = [("2020-01-0" + str(i), 1_000_000 + i * 1000 - (i % 2) * 3000) for i in range(1, 6)]
    assert sortino(curve) is not None
    # a curve with an actual drawdown, so calmar (CAGR / |MDD|) is well-defined
    with_drawdown = [("2020-01-01", 1_000_000), ("2020-06-01", 900_000), ("2021-01-01", 1_100_000)]
    assert calmar(with_drawdown) is not None
    # a monotonically rising curve has MDD=0 -> calmar is undefined, not fabricated as some huge number
    assert calmar([("2020-01-01", 1_000_000), ("2021-01-01", 1_100_000)]) is None


def test_trade_stats_exact():
    trades = [
        {"pnl": 100, "holding_sessions": 5},
        {"pnl": -50, "holding_sessions": 10},
        {"pnl": 200, "holding_sessions": 3},
        {"pnl": -30, "holding_sessions": 7},
    ]
    s = trade_stats(trades)
    assert s["tradeCount"] == 4
    assert abs(s["winRate"] - 0.5) < 1e-9
    assert abs(s["avgWin"] - 150) < 1e-9
    assert abs(s["avgLoss"] - (-40)) < 1e-9
    assert abs(s["winLossRatio"] - 3.75) < 1e-9
    assert abs(s["profitFactor"] - 3.75) < 1e-9
    assert abs(s["expectancy"] - 55) < 1e-9
    assert abs(s["avgHoldingPeriod"] - 6.25) < 1e-9
    assert s["maxConsecutiveWins"] == 1
    assert s["maxConsecutiveLosses"] == 1


def test_trade_stats_empty_is_not_zero():
    s = trade_stats([])
    assert s["tradeCount"] == 0
    assert s["winRate"] is None  # no trades -> N/A, not 0% (LESSON 57)


def run():
    test_total_return_exact()
    test_max_drawdown_exact()
    test_cagr_roughly_doubling_over_a_year()
    test_sharpe_none_when_flat()
    test_sortino_and_calmar_run_without_error()
    test_trade_stats_exact()
    test_trade_stats_empty_is_not_zero()
    print("test_metrics: OK")


if __name__ == "__main__":
    run()
