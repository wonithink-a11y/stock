"""lowmom60_v1 - 60D 저모멘텀 팩터, 월별 리밸런싱, 절대 유동성 임계값 적용.

전체 구조는 strategies/pbr_value_v1/rule.py와 동일 - 그 파일의 상세 설명을
그대로 참고. 다른 점은 "신호"의 출처뿐이다: PBR은 외부 valuation 패널
(A5 resolve() 산출물)을 읽지만, LOWMOM60은 가격 데이터 자체(close.shift(60))
에서 계산한다. 두 경우 다 횡단면 랭킹은 build_selection.py가 오프라인으로
미리 계산해 selection.json에 굽고, 이 파일은 순수 조회만 한다 - engine의
Strategy 계약(compute_features(bars)/generate_signals(symbol, features)이
종목 하나씩만 본다는 제약, strategies/base.py)을 우회하는 같은 이유다.
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]  # 마지막 달(다음 리밸런싱일 없음)에만 사용
_STOP_MULTIPLE = 100.0  # entry_price * 100 - policy.json risk.stopDistanceFormula
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_HOLD_COL = "lowmom60HoldSessions"

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
# ticker -> {date: holdSessions}
_SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
              for t, entries in _SELECTION_FILE["selection"].items()}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """기술적 지표 없음 - 신호는 selection.json에 이미 구워져 있다. bars를
    복사하고 _HOLD_COL을 NaN으로 초기화만 해 둔다(generate_signals가 이 종목의
    선택일에만 실제 값을 채운다)."""
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """선택일마다 정확한 holdSessions를 features에 직접 써 넣는다 - runner.py가
    compute_features()의 반환값을 features_by_ticker[symbol]에 저장한 뒤 이
    함수를 호출하므로(같은 객체 참조), 여기서 하는 in-place 수정이 나중에
    risk_spec_for(row)가 읽는 값에 그대로 반영된다."""
    dates = _SELECTION.get(symbol, {})
    out = []
    for d, hold_sessions in dates.items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    """price 기반 stop/target을 도달 불가능하게 만들어 TIME_EXIT만 발생하도록
    한다(policy.json risk 블록 참고). max_holding_sessions는 generate_signals가
    채운 _HOLD_COL에서 읽는다(결측이면 마지막 달 근사)."""
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=max_holding)


def selected_symbols(as_of: str) -> list:
    """engine/live/paperEngine.py의 scan_rebalance_signals()가 쓴다 - pbr_value_v1/rule.py와 동일 패턴."""
    return [t for t, dates in _SELECTION.items() if as_of in dates]


def still_selected(symbol: str, as_of: str) -> bool:
    """engine/live/paperEngine.py의 poll_once(is_still_selected=...)가 쓴다 - pbr_value_v1/rule.py와 동일 패턴."""
    return as_of in _SELECTION.get(symbol, {})


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """generate_signals와 동일한 조회 로직, PIT 래퍼를 거쳐서. selection.json
    자체가 이미 PIT 안전하다 - build_selection.py는 그 리밸런싱일까지의 가격
    (mom60·turnover20 계산에 close.shift(60)/rolling(20) 사용, 전부 과거창)과
    그 리밸런싱일 이후 캘린더(다음 리밸런싱일)만 참조해 미래 데이터를 안 쓴다."""
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
