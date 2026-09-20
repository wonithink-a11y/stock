"""crypto_upshock_v1 - 크립토 상승충격 다음날 지속. 모의 관측 전용.

사전등록: findings/crypto-upshock-paper-sleeve-preregistration-2026-09.md
규칙 출처: futures/crypto_upshock_recent.py (두 독립 표본에서 확인된 뒤 동결)

신호는 그 스크립트의 것을 한 글자도 안 바꾸고 옮겼다 - 파라미터를 여기서
다시 고르지 않는다. 원본은 UTC 일 시가(mark_open, hour==0) 계열을 썼고
여기서는 업비트 일봉 종가를 쓴다. 크립토는 24시간 연속이라 일 시가 ≈ 전일
종가이고, 두 계열 모두 "경계 시점에 이미 확정된 직전 24시간 수익률"을
가리킨다 - 경계(UTC 00:00)가 같으므로 같은 신호다.

  r[d]  = close[d-1] / close[d-2] - 1      (as_of=d-1 시점에 확정)
  sd[d] = r 의 30일 rolling std, shift(1), min_periods=20
  신호   = r[d] > 2 * sd[d]

★ shift(1) 이 PIT 장치다. 빼면 오늘 수익률이 자기 임계값 계산에 들어가
  (충격이 클수록 sd 도 커져) 신호가 조용히 약해진다.
"""
import json
import os

import pandas as pd

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

_SIG = PARAMS["signal"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    ret = features["close"].pct_change()
    features["ret"] = ret
    features["sigma"] = ret.shift(1).rolling(
        _SIG["stdWindow"], min_periods=_SIG["stdMinPeriods"]).std()
    features["threshold"] = _SIG["sigmaMultiple"] * features["sigma"]
    return features


def signal_fires(features: pd.DataFrame, as_of: str) -> bool:
    ts = pd.Timestamp(as_of)
    if ts not in features.index:
        return False
    row = features.loc[ts]
    if pd.isna(row["ret"]) or pd.isna(row["threshold"]):
        return False
    return bool(row["ret"] > row["threshold"])
