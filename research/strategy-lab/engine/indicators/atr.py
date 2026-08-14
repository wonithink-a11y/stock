"""ATR (Average True Range), Wilder's original smoothing (not a plain SMA of True
Range). The spec only says "period=14"; both smoothings are called "ATR" in
practice, so the choice is made explicit here rather than left implicit - Wilder's
method is what most platforms default to when they say "ATR" unqualified.
"""
import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    result = pd.Series(float("nan"), index=tr.index)
    if len(tr) < period:
        return result

    first = tr.iloc[:period].mean()
    result.iloc[period - 1] = first
    prev = first
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr.iloc[i]) / period
        result.iloc[i] = prev
    return result
