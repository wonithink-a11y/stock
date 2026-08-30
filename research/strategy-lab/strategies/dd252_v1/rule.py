"""dd252_v1 - DD252(skip-1m) 팩터, 월별 리밸런싱, 고정 120세션 보유.

전체 구조는 strategies/lowmom60_v1/rule.py와 동일 - 그 파일의 상세 설명을
그대로 참고. 다른 점은:
- 유니버스: A1A_A1B_MERGED (상장폐지 포함)
- 신호: dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1 (내림차순: 0에 가까울수록 상위)
- 보유: 고정 120세션 (staggered cohort 근사 - continuousHoldOnRenewal=false로 매월 신규 120일 클럭)
- 유동성 필터: Arm A baseline은 없음 (Arm C에서 amt20≥1억 적용)

build_selection.py가 횡단면 랭킹을 오프라인으로 계산해 selection.json에 굽고,
이 파일은 순수 조회만 한다.
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
_STOP_MULTIPLE = 100.0  # entry_price * 100 - policy.json risk.stopDistanceFormula
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_HOLD_COL = "dd252HoldSessions"

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
# ticker -> {date: holdSessions}
_SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
              for t, entries in _SELECTION_FILE["selection"].items()}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """기술적 지표 없음 - 신호는 selection.json에 이미 구워져 있다."""
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """선택일마다 정확한 holdSessions를 features에 직접 써 넣는다."""
    dates = _SELECTION.get(symbol, {})
    out = []
    for d, hold_sessions in dates.items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    """가격 기반 stop/target을 도달 불가능하게 만들어 TIME_EXIT만 발생하도록 한다.
    max_holding_sessions는 generate_signals가 채운 _HOLD_COL에서 읽는다."""
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=max_holding)


def selected_symbols(as_of: str) -> list:
    """engine/live/paperEngine.py의 scan_rebalance_signals()가 쓴다."""
    return [t for t, dates in _SELECTION.items() if as_of in dates]


def still_selected(symbol: str, as_of: str) -> bool:
    """engine/live/paperEngine.py의 poll_once(is_still_selected=...)가 쓴다."""
    return as_of in _SELECTION.get(symbol, {})


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """generate_signals와 동일한 조회 로직, PIT 래퍼를 거쳐서."""
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")