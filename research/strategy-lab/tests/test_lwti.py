"""LWTI 계약 테스트.

이 지표는 공개 정본이 없어 '무엇이 옳은가'를 잴 수 없다. 그래서 재는 것은
구현이 스스로 선언한 것을 지키는가다 - 식이 문서와 같은가(독립 재계산),
후방참조만 하는가(미래 누설 없음), 색상 규칙 둘이 실제로 다른가, 워밍업을
녹색으로 세지 않는가(교훈57).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.lwti import (COLOR_RULES, lwti, lwti_green,
                                    lwti_turned_green)


def _bars(n=80, seed=7):
    rnd = np.random.RandomState(seed)
    close = pd.Series(1000 + rnd.randn(n).cumsum() * 20)
    high = close + rnd.rand(n) * 15 + 1
    low = close - rnd.rand(n) * 15 - 1
    return high, low, close


def test_formula_matches_declared_definition():
    """docstring이 선언한 식 그대로인가 - 독립 재계산으로 대조한다."""
    high, low, close = _bars()
    period = 25
    got = lwti(high, low, close, period=period)
    expect = ((close - close.shift(period))
              / atr_indicator(high, low, close, period=period) * 50 + 50)
    pd.testing.assert_series_equal(got.dropna(), expect.dropna())


def test_no_lookahead():
    """t 이후의 봉을 바꿔도 lwti[t]가 흔들리면 미래를 본 것이다."""
    high, low, close = _bars()
    period = 10
    base = lwti(high, low, close, period=period)
    cut = 50
    h2, l2, c2 = high.copy(), low.copy(), close.copy()
    h2.iloc[cut + 1:] *= 3
    l2.iloc[cut + 1:] *= 3
    c2.iloc[cut + 1:] *= 3
    after = lwti(h2, l2, c2, period=period)
    pd.testing.assert_series_equal(base.iloc[:cut + 1], after.iloc[:cut + 1])


def test_warmup_is_not_green():
    """값이 NaN인 구간은 녹색이 아니다 - 모르는 것은 참이 아니다(교훈57)."""
    high, low, close = _bars(n=40)
    period = 25
    values = lwti(high, low, close, period=period)
    for rule in COLOR_RULES:
        green = lwti_green(values, rule)
        assert not green[values.isna()].any(), rule
        assert green.dtype == bool, rule


def test_two_color_rules_are_actually_different():
    """slope와 midline이 같은 계열을 내면 둘을 나눠 놓은 의미가 없다."""
    high, low, close = _bars(n=200, seed=3)
    values = lwti(high, low, close, period=25)
    slope = lwti_green(values, "slope")
    mid = lwti_green(values, "midline")
    assert (slope != mid).sum() > 0
    assert slope.sum() > 0 and mid.sum() > 0


def test_midline_rule_is_exactly_the_50_line():
    high, low, close = _bars(n=120, seed=11)
    values = lwti(high, low, close, period=25)
    green = lwti_green(values, "midline")
    assert green.equals((values > 50).fillna(False))


def test_transition_is_a_subset_of_green_and_edge_triggered():
    high, low, close = _bars(n=200, seed=5)
    values = lwti(high, low, close, period=25)
    for rule in COLOR_RULES:
        green = lwti_green(values, rule)
        turned = lwti_turned_green(values, rule)
        assert (turned & ~green).sum() == 0, rule          # 전환일은 녹색이다
        assert turned.sum() < green.sum(), rule            # 상태보다 드물다
        # 연속 녹색 구간에서 전환은 첫날 하나뿐
        assert (turned & green.shift(1, fill_value=False)).sum() == 0, rule


def test_unknown_color_rule_raises():
    high, low, close = _bars(n=60)
    values = lwti(high, low, close, period=25)
    try:
        lwti_green(values, "rainbow")
    except ValueError:
        return
    raise AssertionError("알 수 없는 color_rule이 조용히 통과했다")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("  PASS  " + name)
    print("\n  LWTI 계약 테스트 통과")
