"""B1 - Bollinger-only benchmark. Reuses 5DC-v1A-P's indicators/risk formula/cost
/portfolio verbatim (compute_features, risk_spec_for, PARAMS, TIE_BREAK) from
strategies/5dc_v1a_p/rule.py - the only thing this file adds is a different
generate_signals().

Signal definition (edge-triggered, confirmed 2026-08-14): the bare level
condition "Close > BB_mid" is not itself a discrete tradeable event, so it is
read as the day the condition first becomes true:

    Close[t-1] <= BB_mid[t-1]  AND  Close[t] > BB_mid[t]

No new parameters. No CCI condition.
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


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    above = features["close"] > features["bb_mid"]
    prev_above = above.shift(1, fill_value=False)
    edge = above & ~prev_above
    return [Signal(symbol=symbol, signal_date=_core._fmt(d), direction="LONG") for d in features.index[edge.fillna(False)]]
