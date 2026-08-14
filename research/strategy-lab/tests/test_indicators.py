import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.indicators.atr import atr
from engine.indicators.bollinger import bollinger_bands
from engine.indicators.cci import cci


def test_bollinger_mid_is_sma():
    close = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
                        20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], dtype="float64")
    bb = bollinger_bands(close, period=20, stddev=2.0)
    expected_mid_last = close.iloc[-20:].mean()
    assert abs(bb["bb_mid"].iloc[-1] - expected_mid_last) < 1e-9
    assert bb["bb_upper"].iloc[-1] > bb["bb_mid"].iloc[-1] > bb["bb_lower"].iloc[-1]
    assert pd.isna(bb["bb_mid"].iloc[0])  # warm-up


def test_cci_known_value():
    # 20 flat bars followed by one spike - CCI should read strongly positive there
    n = 20
    high = pd.Series([100.0] * n + [110.0])
    low = pd.Series([99.0] * n + [109.0])
    close = pd.Series([99.5] * n + [109.5])
    result = cci(high, low, close, period=20)
    assert pd.isna(result.iloc[0])
    assert result.iloc[-1] > 50  # spike above a flat baseline reads clearly positive


def test_atr_wilder_recursion():
    high = pd.Series([10, 11, 12, 11, 10, 12, 13, 12, 11, 10,
                       12, 13, 14, 13, 12, 13], dtype="float64")
    low = high - 1
    close = high - 0.5
    result = atr(high, low, close, period=14)
    assert pd.isna(result.iloc[12])
    assert not pd.isna(result.iloc[13])
    # manual Wilder step for index 14 given the seed at index 13
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    seed = tr.iloc[:14].mean()
    assert abs(result.iloc[13] - seed) < 1e-9
    expected_14 = (seed * 13 + tr.iloc[14]) / 14
    assert abs(result.iloc[14] - expected_14) < 1e-9


def run():
    test_bollinger_mid_is_sma()
    test_cci_known_value()
    test_atr_wilder_recursion()
    print("test_indicators: OK")


if __name__ == "__main__":
    run()
