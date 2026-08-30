"""Bollinger Squeeze + Volume Confirmation (Strategy 2).

Identical to Strategy 1 (bb_squeeze_v1) plus exactly ONE added condition:
current volume > SMA(volume, 20) * 1.5. Objective is only to measure whether
volume confirmation improves the squeeze-breakout signal's quality (comparison
A = S1, B = S2) - NOT to stack further conditions on top of B.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class BBSqueezeVolParams:
    bb_period: int = 20
    bb_std: float = 2.0
    squeeze_lookback: int = 100
    squeeze_pct: float = 0.20
    vol_sma_period: int = 20
    vol_ratio_min: float = 1.5
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return BBSqueezeVolParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: BBSqueezeVolParams) -> pd.DataFrame:
    features = bars.copy()

    mid = features["close"].rolling(params.bb_period).mean()
    std = features["close"].rolling(params.bb_period).std(ddof=0)
    upper = mid + params.bb_std * std
    lower = mid - params.bb_std * std
    bbwidth = (upper - lower) / mid

    features["bb_mid"] = mid
    features["bb_upper"] = upper
    features["bb_lower"] = lower
    features["bb_width"] = bbwidth
    features["bb_width_pctile"] = bbwidth.rolling(params.squeeze_lookback).rank(pct=True)
    features["squeeze"] = features["bb_width_pctile"] <= params.squeeze_pct

    above = features["close"] > upper
    prev_above = above.shift(1, fill_value=False)
    features["breakout"] = above & ~prev_above

    # single added condition: volume expansion
    features["vol_sma20"] = features["volume"].rolling(params.vol_sma_period).mean()
    features["vol_ratio"] = features["volume"] / features["vol_sma20"]
    features["vol_ok"] = features["vol_ratio"] > params.vol_ratio_min

    features["atr"] = atr_indicator(features["high"], features["low"], features["close"],
                                    period=params.atr_period)

    features["entry_cond"] = features["squeeze"] & features["breakout"] & features["vol_ok"]
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: BBSqueezeVolParams) -> list:
    warmup = (features["bb_upper"].notna()
              & features["bb_width_pctile"].notna()
              & features["vol_sma20"].notna()
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


def risk_spec_for(row, params: BBSqueezeVolParams) -> RiskSpec:
    atr_t = float(row["atr"])
    return RiskSpec(
        stop_distance=params.atr_mult * atr_t,
        reward_risk=params.reward_risk,
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