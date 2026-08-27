"""dd252_v1_cohort - DD252(skip-1m) Arm A, 6-cohort 격리 회계용 신호 조회.

이 파일 자체는 신호 생성만 한다 - "어느 cohort 소속인가"는 selection.json에
같이 저장돼 있지만 engine의 Signal/Order 계약에는 그 필드가 없어(base.py
계약 - cohort 개념 자체가 engine에 없음) 여기서는 안 쓴다. cohort별 회계
분리는 run_dd252_cohort_smoke.py가 run_smoke()의 resolved 결과를 받은
뒤, (symbol, signal_date) 조합으로 selection.json을 다시 찾아 cohort를
사후에 복원해서 한다 - engine을 전혀 안 건드리는 이유이기도 하다.

나머지 구조는 strategies/lowmom60_v1/rule.py·pbr_value_v1/rule.py와 완전히
동일한 조회형 패턴.
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_HOLD_COL = "dd252HoldSessions"

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
# ticker -> {date: holdSessions} (cohort는 여기서 버림 - run_dd252_cohort_smoke.py가
# 같은 selection.json을 별도로 다시 읽어 cohort 복원용으로 쓴다)
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
