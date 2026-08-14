"""Covers the suspension-row handling in engine/runner.py. Narrowed after
verification against the full A2a universe showed a blanket volume==0 filter
over-removed real (flat-but-genuine) quotes - see _drop_suspension_rows'
docstring for the full rationale and the real-ticker ATR-distortion evidence."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.runner import _drop_suspension_rows


def test_drops_only_open_high_low_all_zero_rows():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    bars = pd.DataFrame({
        "open": [100, 0, 102, 50, 104],
        "high": [101, 0, 103, 50, 105],
        "low": [99, 0, 101, 50, 103],
        "close": [100, 100, 102, 50, 104],  # halt row carries a reference close, not 0
        "volume": [1000, 0, 1500, 0, 1200],
    }, index=dates)
    cleaned = _drop_suspension_rows(bars)
    assert len(cleaned) == 4  # only the true open=high=low=0 row is dropped
    assert not ((cleaned["open"] == 0) & (cleaned["high"] == 0) & (cleaned["low"] == 0)).any()


def test_flat_but_nonzero_volume_zero_quote_is_kept():
    """A day with no trade but a genuine flat quote (open=high=low=close, all
    nonzero, volume=0) must NOT be dropped - this is exactly the case the prior
    (rejected) volume>0 predicate over-removed."""
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    bars = pd.DataFrame({
        "open": [100, 100], "high": [100, 100], "low": [100, 100],
        "close": [100, 100], "volume": [1000, 0],
    }, index=dates)
    cleaned = _drop_suspension_rows(bars)
    assert len(cleaned) == 2


def run():
    test_drops_only_open_high_low_all_zero_rows()
    test_flat_but_nonzero_volume_zero_quote_is_kept()
    print("test_runner_data_quality: OK")


if __name__ == "__main__":
    run()
