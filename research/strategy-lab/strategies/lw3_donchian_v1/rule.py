"""LW3 - '래리 윌리엄스 3박자' 재현 (연구 전용).

  STEP 1  종가가 돈치안20 상단을 돌파       (사건, edge-trigger)
  STEP 2  LWTI 가 녹색                      (확인, 상태)
  STEP 3  거래량이 20일 이동평균 위          (확인, 상태)
  청산    손절 = 돈치안 중간선 · 익절 = 손절폭 x 2

ablation 을 위해 STEP 2·3 은 PARAMS["filters"] 로 꺼진다. 끄고 켜는 것이
전부라 A~E 변형이 같은 코드·같은 엔진·같은 비용을 지난다.

계약상 주의 두 가지는 policy.json 의 stopNote·intrabarNote 에 적었다:
손절 '거리'는 신호일 종가 기준이고, 진입은 T+1 시가다.
"""
import json
import os

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.donchian import donchian_channel
from engine.indicators.lwti import lwti, lwti_green, lwti_turned_green
from engine.signals.schema import RiskSpec, Signal

STRATEGY_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(STRATEGY_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: [open, high, low, close, volume] indexed by date. 전부 후방참조."""
    ind = PARAMS["indicators"]
    f = bars.copy()

    dc = donchian_channel(f["high"], f["low"], period=ind["donchian"]["period"])
    f["donchian_high"] = dc["donchian_high"]
    f["donchian_low"] = dc["donchian_low"]
    f["donchian_mid"] = (f["donchian_high"] + f["donchian_low"]) / 2

    f["volume_ma"] = f["volume"].rolling(ind["volumeMa"]["period"]).mean()

    lw = lwti(f["high"], f["low"], f["close"], period=ind["lwti"]["period"])
    rule = ind["lwti"]["colorRule"]
    f["lwti"] = lw
    f["lwti_green"] = lwti_green(lw, rule)
    f["lwti_turned_green"] = lwti_turned_green(lw, rule)

    # 엔진이 신호행의 'atr' 결측으로 워밍업을 거른다(runner.py). 이 전략은
    # ATR 로 사이징하지 않지만 그 게이트를 그대로 쓴다.
    f["atr"] = atr_indicator(f["high"], f["low"], f["close"],
                             period=ind["atr"]["period"])

    f["stop_distance"] = f["close"] - f["donchian_mid"]
    return f


def signal_mask(f: pd.DataFrame) -> pd.Series:
    """세 조건의 불리언 결합. generate_signals 와 evaluate_at 이 같은 식을 쓴다."""
    above = f["close"] > f["donchian_high"]
    mask = above & ~above.shift(1, fill_value=False)          # STEP 1 (edge)

    if PARAMS["filters"]["volume"]:                            # STEP 3
        mask = mask & (f["volume"] > f["volume_ma"])
    if PARAMS["filters"]["lwti"]:                              # STEP 2
        col = ("lwti_turned_green"
               if PARAMS["signal"]["lwtiMode"] == "transition" else "lwti_green")
        mask = mask & f[col]

    # 어제의 상단을 모르면 '어제는 위가 아니었다'를 단정할 수 없다(교훈57).
    # evaluate_at 도 같은 조건을 걸어야 두 경로가 갈리지 않는다.
    warm = (f["donchian_high"].notna() & f["donchian_high"].shift(1).notna()
            & f["volume_ma"].notna() & f["lwti"].notna() & f["atr"].notna())
    # 손절폭이 0 이하면 진입 자체가 성립하지 않는다. 돌파 정의상
    # close > upper >= mid 라 실제로는 걸릴 일이 없고, tests 가 그것을 고정한다.
    return (mask & warm & (f["stop_distance"] > 0)).fillna(False)


def _fmt(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    return [Signal(symbol=symbol, signal_date=_fmt(d), direction="LONG")
            for d in features.index[signal_mask(features)]]


def risk_spec_for(row) -> RiskSpec:
    return RiskSpec(
        stop_distance=float(row["stop_distance"]),
        reward_risk=float(PARAMS["risk"]["rewardRisk"]),
        max_holding_sessions=int(PARAMS["risk"]["maxHoldingSessions"]),
    )


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """PIT 가드 경로. signal_mask() 와 정확히 같은 불리언 식을 행 단위로 편다
    (tests/test_lw3_donchian_v1.py 가 두 경로의 동치를 고정한다).
    pit_features.at() 은 as_of 를 넘는 날짜에 PITViolation 을 던진다."""
    row = pit_features.at(date)
    prev_row = pit_features.at(prev_date) if prev_date else None
    if row is None or prev_row is None:
        return None

    for col in ("donchian_high", "volume_ma", "lwti", "atr", "stop_distance"):
        if pd.isna(row[col]):
            return None
    if pd.isna(prev_row["donchian_high"]):
        # 어제 상단을 모르면 '어제는 위가 아니었다'를 단정할 수 없다(교훈57).
        return None

    if not (row["close"] > row["donchian_high"]):
        return None
    if prev_row["close"] > prev_row["donchian_high"]:      # edge-trigger
        return None
    if row["stop_distance"] <= 0:
        return None
    if PARAMS["filters"]["volume"] and not (row["volume"] > row["volume_ma"]):
        return None
    if PARAMS["filters"]["lwti"]:
        col = ("lwti_turned_green"
               if PARAMS["signal"]["lwtiMode"] == "transition" else "lwti_green")
        if not bool(row[col]):
            return None
    return Signal(symbol=symbol, signal_date=_fmt(date), direction="LONG")
