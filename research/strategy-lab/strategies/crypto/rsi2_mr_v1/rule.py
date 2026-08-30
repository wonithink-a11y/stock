"""Trend-filtered RSI(2) Mean Reversion (Strategy 4).

Objective: check whether a short-term mean-reversion return source exists,
opposite to the breakout/trend-following family.

- Higher timeframe trend: Daily close > Daily SMA(200)  (runner-injected d_trend_up)
- Entry timeframe: 4H
- Entry: daily trend bullish AND RSI(2) <= 10, entered at the NEXT 4H bar OPEN
  (the engine's next_session resolution)
- Exit: RSI(2) >= 70 (bar-close rule, executed by a dynamic exit simulator in
  the runner, since the engine's static STOP/TARGET model cannot express an
  indicator-based exit) OR time exit at max_holding bars.

RSI uses Wilder's smoothing (standard RSI(2) as referenced by community
freqtrade/backtrader implementations). Baseline thresholds fixed: entry RSI=10,
exit RSI=70, max_holding=60. NO threshold sweep (5/10/15/20) is performed.
"""
import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

from engine.signals.schema import RiskSpec, Signal


@dataclass
class RSI2MRParams:
    rsi_period: int = 2
    entry_rsi_max: float = 10.0
    exit_rsi_min: float = 70.0
    max_holding: int = 60
    sma_trend: int = 200


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return RSI2MRParams(**policy.get("params", {}))


def _rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing: seed = SMA of first `period` deltas, then recursive.

    The leading delta is NaN (diff() has no prior bar), so the seed mean is
    taken over the first `period` VALID deltas (positions 1..period), aligned
    to output position `period`. Without skipping the NaN the seed would be NaN
    and the recursion would stay NaN forever.
    """
    arr = series.to_numpy()
    n = len(arr)
    out = pd.Series(float("nan"), index=series.index)
    if n < period:
        return out
    seed_win = arr[1:period + 1]
    if np.isnan(seed_win).any():
        return out
    first = float(np.mean(seed_win))
    if np.isnan(first):
        return out
    out.iloc[period] = first
    prev = first
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + arr[i]) / period
        out.iloc[i] = prev
    return out


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _rma(gain, period)
    avg_loss = _rma(loss, period)
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi = rsi.where(avg_loss != 0.0, 100.0)  # no losses -> extreme overbought
    return rsi


def compute_features(bars: pd.DataFrame, params: RSI2MRParams) -> pd.DataFrame:
    features = bars.copy()

    features["rsi"] = _rsi(features["close"], params.rsi_period)
    features["oversold"] = features["rsi"] <= params.entry_rsi_max

    if "d_trend_up" in features.columns:
        features["trend_up"] = features["d_trend_up"].fillna(False)
        features["trend_known"] = features["d_trend_up"].notna()
    else:
        sma = features["close"].shift(1).rolling(params.sma_trend).mean()
        features["sma_trend"] = sma
        features["trend_up"] = features["close"] > sma
        features["trend_known"] = sma.notna()

    features["entry_cond"] = features["oversold"] & features["trend_up"] & features["trend_known"]
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: RSI2MRParams) -> list:
    entry_signal = features["entry_cond"] & features["rsi"].notna()
    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d %H:%M:%S"),
            direction="LONG",
            metadata={
                "exit_rule": "rsi2_ge70",
                "exit_rsi_min": params.exit_rsi_min,
            },
        ))
    return signals


def risk_spec_for(row, params: RSI2MRParams) -> RiskSpec:
    # No static stop/target (mean reversion exit is RSI-based, handled by the
    # runner's dynamic simulator). Only the time exit is expressed here.
    return RiskSpec(
        stop_distance=0.0,
        reward_risk=1.0,
        max_holding_sessions=params.max_holding,
    )


STRATEGY_DIR = os.path.dirname(__file__)
PARAMS = load_params(STRATEGY_DIR)


def compute_features_main(bars: pd.DataFrame) -> pd.DataFrame:
    return compute_features(bars, PARAMS)


def generate_signals_main(symbol: str, features: pd.DataFrame) -> list:
    return generate_signals(symbol, features, PARAMS)


def risk_spec_for_main(row) -> RiskSpec:
    return risk_spec_for(row, PARAMS)