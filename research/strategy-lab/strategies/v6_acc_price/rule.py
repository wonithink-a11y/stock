"""v6_acc_price - 외국인+기관 동시 순매수 + 매집가 +5% (video candidate).

strategies/pbr_value_v1 패턴을 그대로 따른다: 이 전략의 조건(nb_5d·매집단가)은
종목 하나의 OHLCV bars만 보는 compute_features 계약 안에서 계산할 수 없으므로,
build_selection.py가 오프라인으로 (ticker, date) 선별을 selection.json에 굽고 이
파일은 조회만 한다. engine/runner.py·portfolio.py·executor.py는 건드리지 않는다.

pbr_value_v1과 동일하게 가격 기반 stop/target이 없는 순수 시간 청산 전략이라,
RiskSpec의 stop_distance/reward_risk를 도달 불가 값으로 채워 TIME_EXIT만
발생시킨다. holdSessions는 고정 20세션([ASSUMPTION] - study T+20 비교 정렬용)이지만
PBR과 같은 in-place 주입 경로(features 컬럼 -> risk_spec_for)를 그대로 유지한다.

policy.json의 scheduling.continuousHoldOnRenewal=true 필수 - 레벨 스크린이라
연속 보유 중 갱신 신호가 자주 나오며, 이 opt-in이 없으면 overlap-avoidance가
갱신을 버려 실제 보유가 신호 의도와 어긋난다(PBR에서 뒤늦게 발견된 항목).
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]  # selection에 없는 경우 폴백
_STOP_MULTIPLE = 100.0  # entry_price * 100 - policy.json risk.stopDistanceFormula (도달 불가)
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_HOLD_COL = "v6HoldSessions"

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION_FILE = json.load(_f)
_SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
              for t, entries in _SELECTION_FILE["selection"].items()}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """기술적 지표 없음 - 신호는 selection.json에 구워져 있다."""
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """선택일마다 holdSessions를 features에 in-place로 써 넣는다(pbr_value_v1과
    동일 - runner가 features_by_ticker에 같은 객체 참조를 저장한 뒤 호출하므로
    risk_spec_for(row)가 나중에 읽을 수 있다)."""
    dates = _SELECTION.get(symbol, {})
    out = []
    for d, hold_sessions in dates.items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    """stop/target 도달 불가 -> TIME_EXIT만 발생(pbr_value_v1과 동일).
    max_holding_sessions는 generate_signals가 채운 _HOLD_COL에서 읽는다."""
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                    max_holding_sessions=max_holding)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """generate_signals와 동일 조회, PIT 래퍼 경유. selection.json은 t 종가 시점
    데이터(nb_5d·close·매집단가)만으로 만들어졌으므로 PIT 안전하다."""
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
