"""V3 Bollinger+RSI - video candidate wired into the shared engine contract.
Reuses 5DC-v1A-P/trend-breakout-v1's RiskSpec/executor/portfolio/cost contract
verbatim; only the indicators (Bollinger lower band + RSI) and signal differ.

[OBSERVED] entry: Low[t] < LowerBand(20,2)[t] AND RSI(14)[t] <= 30 -> buy
[OBSERVED] exit:  High[t] >= UpperBand[t] -> sell. This dynamic band exit is NOT
expressible in the static stop/target/time executor contract shared by all
strategies here; risk constants below are [ASSUMPTION]s reused verbatim from the
existing frozen contracts (2*ATR stop, RR 3.0, 60-session max hold) - see
policy.json risk.assumptions. Deviation is analyzed in findings/v3-engine-smoke.

RSI is computed with the exact same formula as v3_bb_rsi_signal_study.py (Wilder
ewm alpha=1/n, min_periods=n, adjust=False) so engine signals are comparable to
the signal study. NOTE: engine bollinger_bands uses ddof=0 while the study used
pandas rolling .std() default ddof=1 - this known difference is quantified in
the smoke findings, not silently reconciled.
"""
import json
import os

import numpy as np
import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.bollinger import bollinger_bands
from engine.signals.schema import RiskSpec, Signal

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

_BB_PERIOD = PARAMS["indicators"]["bollinger"]["period"]
_BB_STDDEV = PARAMS["indicators"]["bollinger"]["stddev"]
_RSI_PERIOD = PARAMS["indicators"]["rsi"]["period"]
_ATR_PERIOD = PARAMS["indicators"]["atr"]["period"]
_ATR_MULTIPLE = 2.0  # contract constant per policy.json risk.stopDistanceFormula ([ASSUMPTION], reused)
_RR = PARAMS["risk"]["rewardRisk"]
_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]


def rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    """Same formula as v3_bb_rsi_signal_study.py (Wilder smoothing)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: [open, high, low, close, volume] indexed by date. Adds bb_mid,
    bb_lower, bb_upper (engine bollinger, ddof=0), rsi, atr - all backward-only."""
    features = bars.copy()
    bb = bollinger_bands(features["close"], period=_BB_PERIOD, stddev=_BB_STDDEV)
    features["bb_mid"] = bb["bb_mid"]
    features["bb_upper"] = bb["bb_upper"]
    features["bb_lower"] = bb["bb_lower"]
    features["rsi"] = rsi_wilder(features["close"], _RSI_PERIOD)
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=_ATR_PERIOD)
    return features


def _raw_signal_series(features: pd.DataFrame) -> pd.Series:
    """[OBSERVED] level trigger: Low[t] < bb_lower[t] AND RSI[t] <= 30. NaN warmup
    rows compare False in pandas - no separate warmup filter needed."""
    below_band = features["low"] < features["bb_lower"]
    oversold = features["rsi"] <= 30
    return below_band & oversold


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    raw = _raw_signal_series(features).fillna(False)
    return [Signal(symbol=symbol, signal_date=_fmt(d), direction="LONG") for d in features.index[raw]]


def risk_spec_for(features_row) -> RiskSpec:
    """stop_distance fixed from ATR[t] only (ATR TIMING CONTRACT). All constants
    are [ASSUMPTION]s reused from the existing frozen contracts - see policy.json."""
    atr_t = float(features_row["atr"])
    return RiskSpec(stop_distance=_ATR_MULTIPLE * atr_t, reward_risk=_RR, max_holding_sessions=_MAX_HOLDING)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    row = pit_features.at(date)
    if row is None:
        return None
    if pd.isna(row["bb_lower"]) or pd.isna(row["rsi"]):
        return None
    if row["low"] < row["bb_lower"] and row["rsi"] <= 30:
        return Signal(symbol=symbol, signal_date=_fmt(date), direction="LONG")
    return None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)
