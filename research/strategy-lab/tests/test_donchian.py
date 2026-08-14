"""Donchian Channel contract tests - the two failure modes explicitly called
out for this indicator: using High[t]/Low[t] in donchian_high[t]/donchian_low[t]
itself (lookahead), and applying rolling+shift twice (double lag).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.indicators.donchian import donchian_channel


def test_donchian_high_matches_manual_prior_n_window():
    """Independent (non-shift/rolling) reference: donchian_high[i] must equal
    max(High[i-period : i]) - exactly `period` bars immediately before i, i
    itself excluded. A single test that catches both lookahead (window
    reaching into i) and a wrong window size (double-shift lag)."""
    high = pd.Series([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9], dtype="float64")
    low = high - 2
    period = 4
    result = donchian_channel(high, low, period=period)
    for i in range(len(high)):
        if i < period:
            assert pd.isna(result["donchian_high"].iloc[i]), f"expected NaN warmup at {i}"
            continue
        window = high.iloc[i - period:i]
        assert result["donchian_high"].iloc[i] == window.max(), f"mismatch at {i}"


def test_donchian_low_matches_manual_prior_n_window():
    high = pd.Series([3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5, 8, 9, 7, 9], dtype="float64")
    low = high - 2
    period = 4
    result = donchian_channel(high, low, period=period)
    for i in range(period, len(low)):
        window = low.iloc[i - period:i]
        assert result["donchian_low"].iloc[i] == window.min(), f"mismatch at {i}"


def test_today_excluded_from_its_own_channel():
    """A single extreme spike at t must NOT appear in donchian_high[t] itself -
    only visible starting t+1 (lookahead check via a concrete, obvious value)."""
    high = pd.Series([10.0] * 10 + [1000.0] + [10.0] * 10)
    low = high - 1
    result = donchian_channel(high, low, period=5)
    spike_idx = 10
    assert result["donchian_high"].iloc[spike_idx] == 10.0  # spike not yet visible to itself
    assert result["donchian_high"].iloc[spike_idx + 1] == 1000.0  # visible starting next bar


def test_no_double_shift_regression():
    """A 'shift the rolling result again' bug pushes the spike's visibility one
    extra bar later than the single-shift contract. This distinguishes correct
    output from that specific regression."""
    high = pd.Series([10.0] * 10 + [1000.0] + [10.0] * 10)
    low = high - 1
    result = donchian_channel(high, low, period=5)
    double_shift_bug = high.shift(1).rolling(5).max().shift(1)  # simulates the extra lag
    spike_visible_idx = 11
    assert result["donchian_high"].iloc[spike_visible_idx] == 1000.0
    assert double_shift_bug.iloc[spike_visible_idx] != 1000.0  # bug would still read 10.0 here


def _causality_check(indicator_fn, full_high, full_low, truncate_at_idx):
    truncated_high = full_high.iloc[: truncate_at_idx + 1]
    truncated_low = full_low.iloc[: truncate_at_idx + 1]
    full_value = indicator_fn(full_high, full_low).iloc[truncate_at_idx]
    truncated_value = indicator_fn(truncated_high, truncated_low).iloc[truncate_at_idx]
    if pd.isna(full_value) and pd.isna(truncated_value):
        return True
    return abs(full_value - truncated_value) < 1e-9


def test_donchian_high_is_causal():
    high = pd.Series(range(1, 31), dtype="float64")
    low = high - 1
    fn = lambda h, l: donchian_channel(h, l, period=5)["donchian_high"]
    for idx in (5, 6, 15, 29):
        assert _causality_check(fn, high, low, idx), f"donchian_high leaked future data at idx {idx}"


def run():
    test_donchian_high_matches_manual_prior_n_window()
    test_donchian_low_matches_manual_prior_n_window()
    test_today_excluded_from_its_own_channel()
    test_no_double_shift_regression()
    test_donchian_high_is_causal()
    print("test_donchian: OK")


if __name__ == "__main__":
    run()
