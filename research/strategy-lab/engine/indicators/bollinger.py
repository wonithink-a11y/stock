"""Bollinger Bands. 5DC-v1A only uses bb_mid, but upper/lower are generic and
cheap so they're provided for any future strategy.

Standard deviation uses ddof=0 (population) - a documented choice, not the
default of pandas' own .std() (which is ddof=1). Only bb_mid feeds into 5DC-v1A's
signal, so this choice does not affect that strategy's results either way; it is
recorded here so a future strategy that does use the bands knows the convention.
"""
import pandas as pd


def bollinger_bands(close: pd.Series, period: int = 20, stddev: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return pd.DataFrame({
        "bb_mid": mid,
        "bb_upper": mid + stddev * std,
        "bb_lower": mid - stddev * std,
    })
