"""5DC-v1A-P - the single, frozen (2026-08-14) implementation of the
5DC-v1A-Daily-Pullback Primary signal/risk rule. Nothing here beyond the
contract: no liquidity filter, no extra confirmation, no threshold not present
in policy.json.
"""
import json
import os

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.bollinger import bollinger_bands
from engine.indicators.cci import cci as cci_indicator
from engine.signals.schema import RiskSpec, Signal

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]

_BB_PERIOD = PARAMS["indicators"]["bollinger"]["period"]
_BB_STDDEV = PARAMS["indicators"]["bollinger"]["stddev"]
_CCI_PERIOD = PARAMS["indicators"]["cci"]["period"]
_CCI_THRESHOLD = PARAMS["indicators"]["cci"]["threshold"]
_ATR_PERIOD = PARAMS["indicators"]["atr"]["period"]
_ATR_MULTIPLE = 2.0  # "stop_distance = 2 * ATR[t]" - contract constant, per policy.json's risk.stopDistanceFormula
_RR = PARAMS["risk"]["rewardRisk"]
_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: [open, high, low, close, volume] indexed by date. Returns a copy
    with bb_mid, cci, atr columns added - all backward-only by construction
    (Phase 2's causality tests cover bollinger/cci/atr themselves)."""
    features = bars.copy()
    bb = bollinger_bands(features["close"], period=_BB_PERIOD, stddev=_BB_STDDEV)
    features["bb_mid"] = bb["bb_mid"]
    features["cci"] = cci_indicator(features["high"], features["low"], features["close"], period=_CCI_PERIOD)
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=_ATR_PERIOD)
    return features


def _raw_signal_series(features: pd.DataFrame) -> pd.Series:
    """Close[t] > BB_mid[t] AND CCI[t-1] <= threshold AND CCI[t] > threshold.
    Warm-up rows are NaN in bb_mid/cci, and NaN comparisons evaluate to False in
    pandas - so "insufficient warmup" produces no signals with no separate
    filter needed."""
    close_above_mid = features["close"] > features["bb_mid"]
    cci_prev = features["cci"].shift(1)
    recovered = (cci_prev <= _CCI_THRESHOLD) & (features["cci"] > _CCI_THRESHOLD)
    return close_above_mid & recovered


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """Bulk path used by the smoke run - vectorized, mathematically identical to
    evaluate_at() below (both apply the exact same boolean formula to the same
    causal feature columns)."""
    raw = _raw_signal_series(features).fillna(False)
    return [Signal(symbol=symbol, signal_date=_fmt(d), direction="LONG") for d in features.index[raw]]


def risk_spec_for(features_row) -> RiskSpec:
    """features_row: a row of compute_features() output, at the signal date.
    stop_distance is fixed here from ATR[t] only - the executor never
    recomputes it (ATR TIMING CONTRACT)."""
    atr_t = float(features_row["atr"])
    return RiskSpec(stop_distance=_ATR_MULTIPLE * atr_t, reward_risk=_RR, max_holding_sessions=_MAX_HOLDING)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """PIT-guarded path - identical boolean formula to generate_signals(), but
    evaluated one date at a time through a PITBars wrapper. `pit_features.at()`
    raises PITViolation if `date` is beyond the wrapper's as_of. This is what
    the PIT-violation unit test exercises directly; the smoke run uses
    generate_signals() for speed, not this function."""
    row = pit_features.at(date)
    prev_row = pit_features.at(prev_date) if prev_date else None
    if row is None or prev_row is None:
        return None
    if pd.isna(row["bb_mid"]) or pd.isna(row["cci"]) or pd.isna(prev_row["cci"]):
        return None
    if row["close"] > row["bb_mid"] and prev_row["cci"] <= _CCI_THRESHOLD and row["cci"] > _CCI_THRESHOLD:
        return Signal(symbol=symbol, signal_date=_fmt(date), direction="LONG")
    return None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
