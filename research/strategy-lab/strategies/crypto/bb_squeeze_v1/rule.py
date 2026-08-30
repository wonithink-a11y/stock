"""Bollinger Squeeze -> Breakout (Strategy 1).

Community/GitHub concept: price compresses inside Bollinger Bands (volatility
collapse) and a breakout above the upper band starts a new trend.

- middle = SMA(20), upper = middle + 2*std(20), lower = middle - 2*std(20)
- BBWidth = (upper - lower) / middle
- Squeeze: current BBWidth <= squeeze_pct-th percentile of the trailing
  squeeze_lookback-bar window (the current value ranked inside its own history)
- Breakout: close[t] > upper[t] AND close[t-1] <= upper[t-1] (fresh cross)
- Entry: next bar OPEN (engine resolves signal_date -> next session)
- Exit: existing Crypto Lab ATR risk management reused unchanged
  (stop = entry - atr_mult*ATR(14), target = entry + reward_risk*stop,
   time exit at max_holding bars) - no re-optimization.

Baseline parameters fixed; not tuned on any data split.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class BBSqueezeParams:
    bb_period: int = 20
    bb_std: float = 2.0
    squeeze_lookback: int = 100
    squeeze_pct: float = 0.20
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return BBSqueezeParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: BBSqueezeParams) -> pd.DataFrame:
    """All feature columns are backward-only (computed through bar t, used after
    bar t's close -> next bar open entry). No lookahead."""
    features = bars.copy()

    # Bollinger Bands (population std, matched to engine/indicators/bollinger.py)
    mid = features["close"].rolling(params.bb_period).mean()
    std = features["close"].rolling(params.bb_period).std(ddof=0)
    upper = mid + params.bb_std * std
    lower = mid - params.bb_std * std
    bbwidth = (upper - lower) / mid

    features["bb_mid"] = mid
    features["bb_upper"] = upper
    features["bb_lower"] = lower
    features["bb_width"] = bbwidth
    # percentile rank of current BBWidth within the trailing window (incl. self);
    # matches the lab's regime-percentile convention (rolling().rank(pct=True))
    features["bb_width_pctile"] = bbwidth.rolling(params.squeeze_lookback).rank(pct=True)

    # Squeeze: current width in the lowest squeeze_pct of the window
    features["squeeze"] = features["bb_width_pctile"] <= params.squeeze_pct

    # Fresh breakout cross above the upper band
    above = features["close"] > upper
    prev_above = above.shift(1, fill_value=False)
    features["breakout"] = above & ~prev_above

    # ATR for the reused risk management
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"],
                                    period=params.atr_period)

    features["entry_cond"] = features["squeeze"] & features["breakout"]
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: BBSqueezeParams) -> list:
    warmup = (features["bb_upper"].notna()
              & features["bb_width_pctile"].notna()
              & features["atr"].notna())
    entry_signal = features["entry_cond"] & warmup

    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d %H:%M:%S"),
            direction="LONG",
        ))
    return signals


def risk_spec_for(row, params: BBSqueezeParams) -> RiskSpec:
    atr_t = float(row["atr"])
    return RiskSpec(
        stop_distance=params.atr_mult * atr_t,
        reward_risk=params.reward_risk,
        max_holding_sessions=params.max_holding,
    )


# For runner.py compatibility
STRATEGY_DIR = os.path.dirname(__file__)
PARAMS = load_params(STRATEGY_DIR)


def compute_features_main(bars: pd.DataFrame) -> pd.DataFrame:
    return compute_features(bars, PARAMS)


def generate_signals_main(symbol: str, features: pd.DataFrame) -> list:
    return generate_signals(symbol, features, PARAMS)


def risk_spec_for_main(row) -> RiskSpec:
    return risk_spec_for(row, PARAMS)