"""B2 - CCI-only benchmark. Reuses 5DC-v1A-P's indicators/risk formula/cost
/portfolio verbatim from strategies/5dc_v1a_p/rule.py - only generate_signals()
differs (no BB condition).

Signal: CCI[t-1] <= -100 AND CCI[t] > -100 (same threshold as the contract, no
new parameters, no Close/BB_mid condition).
"""
import importlib.util
import os

import pandas as pd

from engine.signals.schema import Signal

_CORE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "strategies", "5dc_v1a_p", "rule.py")
_spec = importlib.util.spec_from_file_location("strategies.5dc_v1a_p.rule", _CORE_PATH)
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

PARAMS = _core.PARAMS
TIE_BREAK = _core.TIE_BREAK
compute_features = _core.compute_features
risk_spec_for = _core.risk_spec_for

_CCI_THRESHOLD = PARAMS["indicators"]["cci"]["threshold"]


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    cci_prev = features["cci"].shift(1)
    recovered = (cci_prev <= _CCI_THRESHOLD) & (features["cci"] > _CCI_THRESHOLD)
    return [Signal(symbol=symbol, signal_date=_core._fmt(d), direction="LONG") for d in features.index[recovered.fillna(False)]]
