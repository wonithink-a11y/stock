"""dummy_sma20 - Paper Trading Engine 배관 검증용. 실제 매매 후보 아님(policy.json
참고). SMA20 상향 돌파 하나뿐인 신호로, engine/live/paperEngine.py가 PENDING_ENTRY
-> OPEN -> exit 상태 전이를 실제로 겪게 만드는 것이 유일한 목적이다.
"""
import json
import os

import pandas as pd

from engine.indicators.bollinger import bollinger_bands

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    features["sma20"] = bollinger_bands(features["close"], period=20, stddev=2.0)["bb_mid"]
    return features


def signal_fires(features: pd.DataFrame, as_of: str) -> bool:
    ts = pd.Timestamp(as_of)
    if ts not in features.index:
        return False
    idx = features.index.get_loc(ts)
    if idx == 0:
        return False
    row, prev = features.iloc[idx], features.iloc[idx - 1]
    if pd.isna(row["sma20"]) or pd.isna(prev["sma20"]):
        return False
    return bool(prev["close"] <= prev["sma20"] and row["close"] > row["sma20"])
