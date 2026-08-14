"""Regression proof for the FastBars performance optimization (2026-08-14):
simulate_trade() must produce value-identical Fill results whether given the
original pandas DataFrame or the FastBars wrapper built from it, across every
execution-contract scenario (target, same-bar stop-first, gap-through-stop,
time-exit). executor.py itself was not changed for this - only the calendar
list-slice - so this test also covers that.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.data.fastBars import FastBars
from engine.execution.contracts import Order
from engine.execution.executor import CostModel, simulate_trade
from engine.signals.schema import RiskSpec


_ALL_DATES = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-01-01", periods=100, freq="D")]


class FakeCalendar:
    def __init__(self, n=100):
        self.days = _ALL_DATES[:n]

    def sessions_between(self, start, end):
        return [d for d in self.days if start <= d <= end]

    def next_n_sessions(self, start, n):
        return [d for d in self.days if d >= start][:n]


def _df(rows):
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


SCENARIOS = {
    "target_hit": [
        (_ALL_DATES[1], 100, 101, 99, 100), (_ALL_DATES[2], 100, 100, 99, 99.5),
        (_ALL_DATES[3], 100, 100, 99, 99.5), (_ALL_DATES[4], 100, 100, 99, 99.5),
        (_ALL_DATES[5], 100, 132, 99, 130),
    ],
    "same_bar_stop_first": [
        (_ALL_DATES[1], 100, 101, 99, 100), (_ALL_DATES[2], 100, 135, 85, 100),
    ],
    "gap_through_stop": [
        (_ALL_DATES[1], 100, 101, 99, 100), (_ALL_DATES[2], 80, 82, 78, 81),
    ],
    "time_exit": [(_ALL_DATES[i], 100, 105, 95, 100) for i in range(1, 61)],
}


def test_fast_bars_matches_dataframe_across_all_scenarios():
    cal = FakeCalendar(n=100)
    risk = RiskSpec(stop_distance=10.0, reward_risk=3.0, max_holding_sessions=60)
    cost = CostModel(entry_cost_bps=15, exit_cost_bps=15, slippage_bps=0)

    for name, rows in SCENARIOS.items():
        order = Order("X", cal.days[0], rows[0][0], "LONG", risk)
        df = _df(rows)
        fast = FastBars(df)

        result_df = simulate_trade(order, df, cal, cost)
        result_fast = simulate_trade(order, fast, cal, cost)

        assert (result_df is None) == (result_fast is None), name
        if result_df is None:
            continue
        entry_df, exit_df = result_df
        entry_fast, exit_fast = result_fast

        assert entry_df.fill_date == entry_fast.fill_date, name
        assert entry_df.fill_price == entry_fast.fill_price, name
        assert entry_df.fill_type == entry_fast.fill_type, name
        assert exit_df.fill_date == exit_fast.fill_date, name
        assert exit_df.fill_price == exit_fast.fill_price, name
        assert exit_df.fill_type == exit_fast.fill_type, (name, exit_df.fill_type, exit_fast.fill_type)
        assert exit_df.cost_bps == exit_fast.cost_bps, name


def test_fast_bars_index_and_loc_match_dataframe_semantics():
    df = _df([("2024-01-02", 100, 101, 99, 100), ("2024-01-03", 105, 106, 104, 105)])
    fast = FastBars(df)
    assert ("2024-01-02" in fast.index) == (pd.Timestamp("2024-01-02") in df.index)
    assert ("2024-01-09" in fast.index) == (pd.Timestamp("2024-01-09") in df.index)
    assert fast.loc["2024-01-02", "open"] == df.loc[pd.Timestamp("2024-01-02"), "open"]
    row_fast = fast.loc["2024-01-03"]
    row_df = df.loc[pd.Timestamp("2024-01-03")]
    for col in ("open", "high", "low", "close"):
        assert row_fast[col] == row_df[col]


def run():
    test_fast_bars_matches_dataframe_across_all_scenarios()
    test_fast_bars_index_and_loc_match_dataframe_semantics()
    print("test_fast_bars_equivalence: OK")


if __name__ == "__main__":
    run()
