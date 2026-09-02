"""업종중립 PBR + 성장가속. 선택은 selection.json 에 이미 구워져 있다.

build_sector_neutral_selection.py 가 생성한다 - 직접 고치지 말 것.
pbr_value_v1/rule.py 와 같은 구조(오프라인 선택 + 정확한 holdSessions 전달).
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
                  for t, entries in json.load(_f)["selection"].items()}

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_HOLD_COL = "holdSessions"
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    out = []
    for d, hold_sessions in _SELECTION.get(symbol, {}).items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    close = float(features_row["close"])
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=close * _STOP_MULTIPLE, reward_risk=_REWARD_RISK,
                    max_holding_sessions=max_holding)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    if date not in _SELECTION.get(symbol, {}):
        return None
    if pit_features.at(date) is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
