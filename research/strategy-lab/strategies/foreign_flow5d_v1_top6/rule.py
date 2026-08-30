"""foreign_flow5d_v1 - 외국인수급5D 팩터, 일별 리밸런싱, 5세션 고정 보유.

전체 구조는 strategies/lowmom60_v1/rule.py와 동일 - 그 파일의 상세 설명을
참고. 다른 점: holdSessions가 매 신호마다 고정 5(일별 리밸런싱이라 "다음
리밸런싱일까지" 가변 계산이 필요 없다 - lowmom60_v1의 _FALLBACK_MAX_HOLDING
복잡성이 여기선 불필요).
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_HOLD_SESSIONS = PARAMS["risk"]["maxHoldingSessions"]
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
_SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
              for t, entries in _SELECTION_FILE["selection"].items()}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """기술적 지표 없음 - 신호는 selection.json에 이미 구워져 있다."""
    return bars.copy()


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    dates = _SELECTION.get(symbol, {})
    out = []
    for d in dates:
        ts = pd.Timestamp(d)
        if ts in features.index:
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    """모든 신호가 고정 5세션 - price 기반 stop/target을 도달 불가능하게 만들어
    TIME_EXIT만 발생하도록 한다(lowmom60_v1과 동일 패턴)."""
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=_HOLD_SESSIONS)


def selected_symbols(as_of: str) -> list:
    return [t for t, dates in _SELECTION.items() if as_of in dates]


def still_selected(symbol: str, as_of: str) -> bool:
    return as_of in _SELECTION.get(symbol, {})


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
