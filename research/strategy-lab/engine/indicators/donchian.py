"""Donchian Channel - rolling N-session High/Low, computed strictly from bars
BEFORE t (t itself excluded). Used as the breakout reference level for
TREND-BREAKOUT-v1.

SINGLE-SHIFT CONTRACT: shift once (High/Low -> "as of t-1"), then take the
rolling window over the shifted series. Do NOT also shift the rolling
result - that would apply a second day of lag (donchian_high[t] would end up
reading High[t-N-1..t-2] instead of High[t-N..t-1]), silently pushing every
breakout signal one session later than the contract states. There is exactly
one shift in this file; tests/test_donchian.py's manual-window and
no-double-shift checks catch a regression that adds a second one.
"""
import pandas as pd


def donchian_channel(high: pd.Series, low: pd.Series, period: int = 20) -> pd.DataFrame:
    prior_high = high.shift(1)
    prior_low = low.shift(1)
    return pd.DataFrame({
        "donchian_high": prior_high.rolling(period).max(),
        "donchian_low": prior_low.rolling(period).min(),
    })
