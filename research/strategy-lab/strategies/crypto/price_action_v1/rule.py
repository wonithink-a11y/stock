"""Quantified Price Action / Range Expansion (Strategy 6).

Quantifies the chartist pattern "strong body candle + breakout + volume surge".

Features:
  body_ratio     = abs(close - open) / (high - low)            >= 0.6
  close_location = (close - low) / (high - low)                >= 0.8
  range_expansion= (high - low) / ATR(20)                      >= 1.5
  previous 20-bar high breakout: close > max(high[t-20..t-1])  (single shift)
  volume_ratio   = volume / SMA(volume, 20)                    >= 1.5

Entry: all conditions simultaneously -> next bar OPEN (engine next_session).
Exit: existing lab ATR risk management reused (2x ATR(20) at signal stop,
3.0 RR, 60-bar time exit) - the spec defines entry only, so the lab's default
risk management is applied and recorded; no exit optimization.

This is a fixed baseline for mimicking the pattern. Condition add/remove tuning
to maximize TEST performance is forbidden. Feature occurrence frequency is
reported as analysis in the workbook, not used to change the signal.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class PriceActionParams:
    body_ratio_min: float = 0.6
    close_location_min: float = 0.8
    range_expansion_min: float = 1.5
    vol_ratio_min: float = 1.5
    breakout_bars: int = 20
    atr_period: int = 20
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return PriceActionParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: PriceActionParams) -> pd.DataFrame:
    features = bars.copy()

    rng = (features["high"] - features["low"]).replace(0.0, float("nan"))
    features["body"] = features["close"] - features["open"]
    features["body_ratio"] = features["body"].abs() / rng
    features["close_location"] = (features["close"] - features["low"]) / rng

    features["atr"] = atr_indicator(features["high"], features["low"], features["close"],
                                    period=params.atr_period)
    features["range_expansion"] = (features["high"] - features["low"]) / features["atr"]

    # previous 20-bar high (t itself excluded -> single shift before rolling max)
    features["prev_high"] = features["high"].shift(1).rolling(params.breakout_bars).max()
    features["new_high"] = features["close"] > features["prev_high"]

    features["vol_sma20"] = features["volume"].rolling(20).mean()
    features["volume_ratio"] = features["volume"] / features["vol_sma20"]

    # condition flags (kept as columns so occurrence frequency can be reported)
    features["f_body"] = features["body_ratio"] >= params.body_ratio_min
    features["f_loc"] = features["close_location"] >= params.close_location_min
    features["f_range"] = features["range_expansion"] >= params.range_expansion_min
    features["f_high"] = features["new_high"]
    features["f_vol"] = features["volume_ratio"] >= params.vol_ratio_min

    features["entry_cond"] = (features["f_body"] & features["f_loc"] & features["f_range"]
                              & features["f_high"] & features["f_vol"])
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: PriceActionParams) -> list:
    warmup = (features["body_ratio"].notna()
              & features["atr"].notna()
              & features["prev_high"].notna()
              & features["vol_sma20"].notna())
    entry_signal = features["entry_cond"] & warmup

    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d %H:%M:%S"),
            direction="LONG",
        ))
    return signals


def risk_spec_for(row, params: PriceActionParams) -> RiskSpec:
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