"""pbr_value_v1 - 저PBR 가치 팩터, 월별 리밸런싱, 절대 유동성 임계값 적용.

다른 전략(5dc_v1a_p 등)과 다른 점: 이 전략의 "신호"는 종목 하나의 기술적
지표가 아니라 그 달 전체 유니버스 안에서의 PBR 상대순위다. engine의 Strategy
계약(strategies/base.py)은 compute_features(bars)/generate_signals(symbol,
features)가 종목 하나씩만 본다 - 횡단면 랭킹은 여기서 계산할 수 없다. 그래서
그 계산은 build_selection.py가 오프라인으로 미리 하고, 그 결과(selection.json,
ticker -> [{date, holdSessions}] 목록)를 이 파일이 로드해서 순수 조회만 한다.
engine/runner.py·portfolio.py·executor.py는 전혀 안 건드린다(단, runner.py의
"row['atr']" 하드코딩은 ATR 없는 전략을 막고 있어 별도로 고쳤다 - 그 변경은
runner.py 자체에 남아 있다).

가격 기반 stop/target이 없는 순수 시간 청산 전략이라, RiskSpec의 stop_distance/
reward_risk를 도달 불가능한 값으로 채워 STOP/TARGET 청산을 봉쇄하고
maxHoldingSessions로만 청산한다 - policy.json의 risk 블록 참고.

holdSessions은 리밸런싱일마다 다르다(다음 리밸런싱일까지의 실제 거래일수,
19~23일로 흔들림) - risk_spec_for(row)는 row 하나만 받고 symbol을 모르므로
(계약, base.py), generate_signals()가 그 종목의 features 프레임에 직접
컬럼을 얹어(같은 객체 참조를 runner.py가 features_by_ticker에 이미 저장해
둔 뒤라 이 변경이 그대로 반영된다) risk_spec_for가 나중에 읽게 한다.
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
_HOLD_COL = "pbrHoldSessions"

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
    risk_spec_for(row)가 읽는 값에 그대로 반영된다. risk_spec_for는 row 하나만
    받고 symbol을 모르니(base.py 계약), 이 방법이 엔진을 안 건드리고 심볼별
    holdSessions를 전달하는 유일한 경로다."""
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
    한다(policy.json risk 블록 참고) - executor.py에 새 청산 타입을 추가하지
    않고 기존 STOP/TARGET/TIME_EXIT 삼분류를 그대로 재사용. max_holding_sessions는
    generate_signals가 채운 _HOLD_COL에서 읽는다(결측이면 마지막 달 근사)."""
    close = float(features_row["close"])
    huge_stop_distance = close * _STOP_MULTIPLE
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=huge_stop_distance, reward_risk=_REWARD_RISK,
                     max_holding_sessions=max_holding)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """generate_signals와 동일한 조회 로직, PIT 래퍼를 거쳐서. selection.json
    자체가 이미 PIT 안전하다 - build_selection.py가 쓴 valuation-panel.jsonl은
    resolve()의 PIT 선택 규칙을 거친 pbr과, 그 리밸런싱일 이전 20거래일만
    쓰는 turnover20으로 만들어졌다(미래 데이터 없음). holdSessions도 그
    리밸런싱일 이후 캘린더(다음 리밸런싱일)만 참조해 미래 가격은 안 쓴다."""
    dates = _SELECTION.get(symbol, {})
    if date not in dates:
        return None
    row = pit_features.at(date)
    if row is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
