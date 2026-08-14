"""TREND-BREAKOUT-v1 - exploratory Donchian-channel breakout candidate in
research/strategy-lab. Not production (5DC-v1A-P is unaffected and unmodified).
Reuses 5DC-v1A-P's RiskSpec/executor/portfolio/cost contract verbatim (same
ATR-based stop/target formula, same tie-break, same cost/portfolio numbers) -
only the indicator (Donchian instead of Bollinger+CCI) and signal differ.
"""
import json
import os

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.donchian import donchian_channel
from engine.signals.schema import RiskSpec, Signal

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]

_DONCHIAN_PERIOD = PARAMS["indicators"]["donchian"]["period"]
_ATR_PERIOD = PARAMS["indicators"]["atr"]["period"]
_ATR_MULTIPLE = 2.0  # "stop_distance = 2 * ATR[t]" - contract constant, per policy.json's risk.stopDistanceFormula
_RR = PARAMS["risk"]["rewardRisk"]
_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: [open, high, low, close, volume] indexed by date. Adds
    donchian_high, donchian_low, atr - all backward-only by construction
    (donchian_high[t]/donchian_low[t] use only High/Low[t-N..t-1], t excluded -
    see engine/indicators/donchian.py; causality covered by tests/test_donchian.py)."""
    features = bars.copy()
    donchian = donchian_channel(features["high"], features["low"], period=_DONCHIAN_PERIOD)
    features["donchian_high"] = donchian["donchian_high"]
    features["donchian_low"] = donchian["donchian_low"]
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=_ATR_PERIOD)
    return features


def _raw_signal_series(features: pd.DataFrame) -> pd.Series:
    """Close[t-1] <= donchian_high[t-1] AND Close[t] > donchian_high[t] -
    edge-triggered (the bare level condition "Close > donchian_high" is not a
    discrete tradeable event once the price has broken out and stayed there;
    same reasoning as benchmarks/b1_bb_only.py's edge trigger). NaN warmup
    rows compare to False, same as 5DC - no separate warmup filter needed."""
    above = features["close"] > features["donchian_high"]
    prev_above = above.shift(1, fill_value=False)
    return above & ~prev_above


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """Bulk path used by the smoke run - vectorized, mathematically identical to
    evaluate_at() below (both apply the exact same boolean formula to the same
    causal feature columns)."""
    raw = _raw_signal_series(features).fillna(False)
    return [Signal(symbol=symbol, signal_date=_fmt(d), direction="LONG") for d in features.index[raw]]


def risk_spec_for(features_row) -> RiskSpec:
    """features_row: a row of compute_features() output, at the signal date.
    stop_distance is fixed here from ATR[t] only - the executor never
    recomputes it (ATR TIMING CONTRACT, identical to 5DC-v1A-P)."""
    atr_t = float(features_row["atr"])
    return RiskSpec(stop_distance=_ATR_MULTIPLE * atr_t, reward_risk=_RR, max_holding_sessions=_MAX_HOLDING)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """PIT-guarded path - identical boolean formula to generate_signals(), but
    evaluated one date at a time through a PITBars wrapper. `pit_features.at()`
    raises PITViolation if `date` is beyond the wrapper's as_of."""
    row = pit_features.at(date)
    prev_row = pit_features.at(prev_date) if prev_date else None
    if row is None or prev_row is None:
        return None
    if pd.isna(row["donchian_high"]) or pd.isna(prev_row["donchian_high"]):
        return None
    if row["close"] > row["donchian_high"] and prev_row["close"] <= prev_row["donchian_high"]:
        return Signal(symbol=symbol, signal_date=_fmt(date), direction="LONG")
    return None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
