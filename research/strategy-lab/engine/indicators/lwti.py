"""LWTI (Larry Williams Large Trade Index).

★ 이 지표에는 정본이 없다. Loxx의 TradingView Pine 구현이 사실상의 참조
구현이고, 거기서 널리 인용되는 형태는

    diff[t] = close[t] - close[t-n]
    lwti[t] = diff[t] / ATR(n)[t] * 50 + 50

이다. 이 파일은 그 식을 그대로 옮긴다. Loxx 원본이 제공하는 스무딩 선택
(SMA/EMA/... 를 diff 나 결과에 적용)은 구현하지 않았다 - 검증하지 않은
자유도를 늘리지 않기 위해서다. 그 변형은 미검증으로 남아 있다.

★★ 색상 규칙은 공개 정의에 수치로 적혀 있지 않다. "빨강 -> 녹색"이 무엇을
뜻하는지는 구현마다 갈리고, 둘 다 실제로 쓰인다:

    slope    lwti[t] > lwti[t-1]     (지표선이 돌아섰다)
    midline  lwti[t] > 50            (기준선을 넘었다)

지어내지 않는다(교훈50: 잴 수 없는 계약은 계약이 아니다). 둘 다 구현해 두고
어느 쪽을 썼는지 정책에 적고 결과를 둘 다 보고한다.

ATR 은 engine.indicators.atr(Wilder)를 쓴다 - 저장소 안에서 ATR 이 한 뜻만
갖게 한다.
"""
import pandas as pd

from .atr import atr as atr_indicator

COLOR_RULES = ("slope", "midline")


def lwti(high: pd.Series, low: pd.Series, close: pd.Series,
         period: int = 25) -> pd.Series:
    """LWTI 값. 50 이 중립, 위가 매수 우위. 전부 후방참조만 한다(t 포함, t+1 없음)."""
    diff = close - close.shift(period)
    a = atr_indicator(high, low, close, period=period)
    return diff / a.where(a > 0) * 50 + 50


def lwti_green(values: pd.Series, color_rule: str = "slope") -> pd.Series:
    """그날 지표가 '녹색'인가. 워밍업(NaN)은 녹색이 아니다 - 모르는 것은
    참이 아니다(교훈57)."""
    if color_rule not in COLOR_RULES:
        raise ValueError("color_rule은 %s 중 하나여야 한다: %r"
                         % (list(COLOR_RULES), color_rule))
    if color_rule == "midline":
        green = values > 50
    else:
        green = values > values.shift(1)
    return (green & values.notna()).fillna(False)


def lwti_turned_green(values: pd.Series, color_rule: str = "slope") -> pd.Series:
    """빨강 -> 녹색 전환일. 전환은 '어제 녹색이 아니었고 오늘 녹색'이다.
    첫 유효일은 어제가 NaN 이라 전환으로 세지 않는다."""
    green = lwti_green(values, color_rule)
    prev = green.shift(1, fill_value=False)
    return green & ~prev & values.shift(1).notna()
