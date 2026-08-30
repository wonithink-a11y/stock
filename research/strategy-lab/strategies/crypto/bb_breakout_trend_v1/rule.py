"""Bollinger Breakout + Daily Trend Confirmation (Strategy 3, multi-timeframe).

Tests the multi-timeframe structure: a Bollinger Band breakout on the LOW
timeframe (default 4H: close > upper BB(20)) is only traded when the HIGHER
timeframe (Daily) is bullish (Daily close > Daily SMA(200)).

- ARM A (use_daily_trend=False): lower-TF Bollinger breakout alone.
- ARM B (use_daily_trend=True):  lower-TF breakout + Daily trend filter.

Lookahead guard: the module NEVER computes the daily trend itself from a
lower-TF frame. The runner injects the confirmed daily values (d_close,
d_sma200, d_trend_up) aligned so that a daily candle is only usable AFTER that
daily candle has fully closed (see runner.inject_daily_trend). In the
single-frame daily approximation the trend is computed on the daily bars
themselves (self), which carries no leakage either.

Baseline params fixed; no optimization.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class BBBreakoutTrendParams:
    bb_period: int = 20
    bb_std: float = 2.0
    sma_trend: int = 200
    use_daily_trend: bool = True
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return BBBreakoutTrendParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: BBBreakoutTrendParams) -> pd.DataFrame:
    features = bars.copy()

    mid = features["close"].rolling(params.bb_period).mean()
    std = features["close"].rolling(params.bb_period).std(ddof=0)
    upper = mid + params.bb_std * std

    features["bb_mid"] = mid
    features["bb_upper"] = upper

    above = features["close"] > upper
    prev_above = above.shift(1, fill_value=False)
    features["breakout"] = above & ~prev_above

    if "d_trend_up" in features.columns:
        # runner-injected confirmed higher-TF trend (no leakage by construction)
        features["trend_up"] = features["d_trend_up"].fillna(False)
        features["trend_known"] = features["d_trend_up"].notna()
    elif params.use_daily_trend:
        # single-frame (daily) approximation: trend from the bars themselves
        sma = features["close"].shift(1).rolling(params.sma_trend).mean()
        features["sma_trend"] = sma
        features["trend_up"] = features["close"] > sma
        features["trend_known"] = sma.notna()
    else:
        features["trend_up"] = True
        features["trend_known"] = True

    features["atr"] = atr_indicator(features["high"], features["low"], features["close"],
                                    period=params.atr_period)

    features["entry_cond"] = features["breakout"] & features["trend_up"] & features["trend_known"]
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: BBBreakoutTrendParams) -> list:
    warmup = (features["bb_upper"].notna() & features["atr"].notna())
    entry_signal = features["entry_cond"] & warmup

    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d %H:%M:%S"),
            direction="LONG",
        ))
    return signals


def risk_spec_for(row, params: BBBreakoutTrendParams) -> RiskSpec:
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