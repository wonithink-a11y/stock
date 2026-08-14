"""CCI (Commodity Channel Index) on Typical Price = (H+L+C)/3, using the standard
mean-absolute-deviation denominator with the 0.015 constant."""
import numpy as np
import pandas as pd


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    tp = (high + low + close) / 3
    sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad)
