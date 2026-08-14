"""PIT CONTRACT tests.

Two different kinds of leak are covered, because a wrapper that blocks reads only
catches one of them:
  1. Access-level leak: strategy code tries to read a future row through PITBars.
  2. Causality leak: an indicator FORMULA itself looks forward (e.g. a bug uses
     .shift(-1) instead of .shift(1)). No access wrapper catches this - it has to
     be tested by comparing the indicator computed on a truncated series against
     the same indicator computed on the full series, at the truncation point.
     This is what actually detects "ATR[t+1] used" / "CCI[t+1] used".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.data.pit import PITBars, PITViolation
from engine.indicators.atr import atr
from engine.indicators.bollinger import bollinger_bands
from engine.indicators.cci import cci


def _sample_df():
    dates = pd.date_range("2020-01-01", periods=30, freq="D")
    df = pd.DataFrame({
        "open": range(100, 130), "high": range(101, 131),
        "low": range(99, 129), "close": range(100, 130), "volume": [1000] * 30,
    }, index=dates)
    return df


def test_pit_bars_blocks_future_access():
    df = _sample_df()
    as_of = df.index[10]
    bars = PITBars(df, as_of)
    future_date = df.index[15]
    try:
        bars.at(future_date)
        raise AssertionError("expected PITViolation, none raised")
    except PITViolation:
        pass


def test_pit_bars_upto_now_excludes_future():
    df = _sample_df()
    as_of = df.index[10]
    bars = PITBars(df, as_of)
    view = bars.upto_now()
    assert (view.index <= as_of).all()
    assert len(view) == 11


def test_pit_bars_latest_matches_as_of():
    df = _sample_df()
    as_of = df.index[10]
    bars = PITBars(df, as_of)
    assert bars.latest()["close"] == df.loc[as_of, "close"]


def _causality_check(indicator_fn, full_df, truncate_at_idx):
    """Recompute the indicator on a series truncated right after truncate_at_idx
    and compare against the full-series computation, at that same index. If they
    differ, the indicator used data beyond truncate_at_idx to produce that value -
    a future leak."""
    truncated = full_df.iloc[: truncate_at_idx + 1]
    full_value = indicator_fn(full_df).iloc[truncate_at_idx]
    truncated_value = indicator_fn(truncated).iloc[truncate_at_idx]
    if pd.isna(full_value) and pd.isna(truncated_value):
        return True
    return abs(full_value - truncated_value) < 1e-9


def test_bollinger_is_causal():
    df = _sample_df()
    fn = lambda d: bollinger_bands(d["close"], period=20)["bb_mid"]
    for idx in (19, 20, 25, 29):
        assert _causality_check(fn, df, idx), f"bb_mid leaked future data at idx {idx}"


def test_cci_is_causal():
    df = _sample_df()
    fn = lambda d: cci(d["high"], d["low"], d["close"], period=20)
    for idx in (19, 20, 25, 29):
        assert _causality_check(fn, df, idx), f"CCI[t] used data beyond t at idx {idx}"


def test_atr_is_causal():
    df = _sample_df()
    fn = lambda d: atr(d["high"], d["low"], d["close"], period=14)
    for idx in (13, 14, 20, 29):
        assert _causality_check(fn, df, idx), f"ATR[t] used data beyond t at idx {idx}"


def test_leaking_indicator_is_caught_by_causality_check():
    """Negative control: a deliberately broken 'indicator' that looks one bar
    ahead must FAIL the causality check - proving the check has teeth."""
    df = _sample_df()
    leaking_fn = lambda d: d["close"].shift(-1)  # reads tomorrow's close
    assert not _causality_check(leaking_fn, df, 10), (
        "causality check failed to catch a deliberately future-leaking indicator"
    )


def run():
    test_pit_bars_blocks_future_access()
    test_pit_bars_upto_now_excludes_future()
    test_pit_bars_latest_matches_as_of()
    test_bollinger_is_causal()
    test_cci_is_causal()
    test_atr_is_causal()
    test_leaking_indicator_is_caught_by_causality_check()
    print("test_pit_contract: OK")


if __name__ == "__main__":
    run()
