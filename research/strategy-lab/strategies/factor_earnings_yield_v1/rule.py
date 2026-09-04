"""Single-factor backtest for earnings_yield (high decile).
Monthly rebalance, top/bottom decile, equal-weight, time-exit only.
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

_HOLD_COL = "holdSessions"
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
# ticker -> {date: holdSessions}
_SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
              for t, entries in _SELECTION_FILE["selection"].items()}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    dates = _SELECTION.get(symbol, {})
    out = []
    for d, hold_sessions in dates.items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=max_holding)


def selected_symbols(as_of: str) -> list:
    """engine/live/paperEngine.py의 scan_rebalance_signals()가 쓴다 - 이번
    리밸런싱일에 선택된 전체 종목 목록. 백테스트 경로(generate_signals 등)와
    무관한 라이브 전용 진입점."""
    return [t for t, dates in _SELECTION.items() if as_of in dates]


def still_selected(symbol: str, as_of: str) -> bool:
    """engine/live/paperEngine.py의 poll_once(is_still_selected=...)가 쓴다 -
    OPEN 포지션이 이번 리밸런싱에도 선택 목록에 남아있는지."""
    return as_of in _SELECTION.get(symbol, {})


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
