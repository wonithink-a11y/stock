"""Volatility / Market Regime Filter Strategy for Crypto (Daily/4H).

Source inspiration:
- Volatility targeting / regime filtering (classic risk management)
- "Volatility Regime Switching" - Hamilton (1989), Ang/Bekaert (2002)
- Crypto adaptations: freqtrade "Volatility Filter" strategies, "ATR Trailing" with regime
- GitHub: freqtrade/freqtrade-strategies (volatility-based strategies)
- Academic: "Managing Risk with Volatility Timing" (Moreira/Muir, 2017)

Core Rules (reproduced from public descriptions):
1. Regime Detection: Classify market state using volatility percentile (ATR or realized vol)
   - Low Vol: ATR percentile < 30% -> aggressive (full position, wider stops)
   - Normal Vol: 30% <= ATR percentile < 70% -> normal
   - High Vol: ATR percentile >= 70% -> defensive (reduce position, tighter stops, or cash)
2. Base Signal: Donchian breakout (20) OR Trend Following (MA crossover)
3. Position Sizing: Scale position by regime (1.0x normal, 0.5x high vol, 1.5x low vol)
4. Stop Adjustment: Wider stops in low vol, tighter in high vol

This strategy combines a base trend signal with volatility regime overlay.
It's designed as a "filter" that can be applied to any base strategy.

Parameters:
- Base strategy: "donchian" or "trend_momentum"
- Vol lookback: 100 bars
- Low vol threshold: 30th percentile
- High vol threshold: 70th percentile
- Position scaling: low=1.5, normal=1.0, high=0.5 (or 0=cash)
- ATR period: 14
"""
import json
import os
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import numpy as np

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.donchian import donchian_channel
from engine.signals.schema import RiskSpec, Signal


class BaseStrategy(Enum):
    DONCHIAN = "donchian"
    TREND_MOMENTUM = "trend_momentum"


@dataclass
class VolRegimeParams:
    base_strategy: str = "donchian"  # "donchian" or "trend_momentum"
    donchian_period: int = 20
    fast_ma: int = 20
    slow_ma: int = 50
    momentum_period: int = 60
    atr_period: int = 14
    vol_lookback: int = 100
    low_vol_pct: float = 0.30
    high_vol_pct: float = 0.70
    low_vol_scale: float = 1.5
    normal_vol_scale: float = 1.0
    high_vol_scale: float = 0.5  # 0.0 = go to cash in high vol
    atr_mult_base: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return VolRegimeParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: VolRegimeParams) -> pd.DataFrame:
    """Compute base strategy signals + volatility regime."""
    features = bars.copy()
    
    # ATR for volatility regime
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=params.atr_period)
    features["atr_pct"] = features["atr"].rolling(params.vol_lookback).rank(pct=True)
    
    # Regime classification
    features["regime"] = "normal"
    features.loc[features["atr_pct"] < params.low_vol_pct, "regime"] = "low_vol"
    features.loc[features["atr_pct"] >= params.high_vol_pct, "regime"] = "high_vol"
    
    # Position scale by regime
    regime_scale = {
        "low_vol": params.low_vol_scale,
        "normal": params.normal_vol_scale,
        "high_vol": params.high_vol_scale
    }
    features["position_scale"] = features["regime"].map(regime_scale).fillna(params.normal_vol_scale)
    
    # Base strategy signals
    if params.base_strategy == "donchian":
        donchian = donchian_channel(features["high"], features["low"], period=params.donchian_period)
        features["donchian_high"] = donchian["donchian_high"]
        features["donchian_low"] = donchian["donchian_low"]
        
        # Edge-triggered Donchian breakout
        above = features["close"] > features["donchian_high"]
        prev_above = above.shift(1, fill_value=False)
        features["base_signal"] = above & ~prev_above
        
    elif params.base_strategy == "trend_momentum":
        features["fast_ma"] = features["close"].shift(1).rolling(params.fast_ma).mean()
        features["slow_ma"] = features["close"].shift(1).rolling(params.slow_ma).mean()
        features["momentum"] = features["close"].shift(1) / features["close"].shift(1 + params.momentum_period) - 1
        
        features["trend_up"] = (features["fast_ma"] > features["slow_ma"]) & (features["close"] > features["slow_ma"])
        features["mom_up"] = features["momentum"] > 0
        features["base_signal"] = features["trend_up"] & features["mom_up"] & ~(
            (features["trend_up"] & features["mom_up"]).shift(1, fill_value=False)
        )
    
    # Combined signal: base signal AND not in high_vol cash mode
    if params.high_vol_scale > 0:
        features["entry_cond"] = features["base_signal"] & (features["regime"] != "high_vol_cash")
    else:
        features["entry_cond"] = features["base_signal"] & (features["regime"] != "high_vol")
    
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: VolRegimeParams) -> list:
    """Generate signals with regime-aware position scaling."""
    warmup_mask = (
        features["atr"].notna() & 
        features["atr_pct"].notna() & 
        features["position_scale"].notna()
    )
    
    if params.base_strategy == "donchian":
        warmup_mask = warmup_mask & features["donchian_high"].notna()
    else:
        warmup_mask = warmup_mask & features["fast_ma"].notna() & features["slow_ma"].notna() & features["momentum"].notna()
    
    entry_signal = features["entry_cond"] & warmup_mask
    
    signals = []
    for date in features.index[entry_signal]:
        row = features.loc[date]
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
            direction="LONG",
            metadata={
                "regime": row["regime"],
                "position_scale": float(row["position_scale"]),
                "atr_percentile": float(row["atr_pct"])
            }
        ))
    return signals


def risk_spec_for(row, params: VolRegimeParams) -> RiskSpec:
    """Regime-adjusted risk spec."""
    atr_t = float(row["atr"])
    position_scale = float(row.get("position_scale", params.normal_vol_scale))
    
    # Adjust stop distance by regime (wider in low vol, tighter in high vol)
    regime = row.get("regime", "normal")
    if regime == "low_vol":
        atr_mult = params.atr_mult_base * 1.5  # wider stop in low vol
    elif regime == "high_vol":
        atr_mult = params.atr_mult_base * 0.7  # tighter stop in high vol
    else:
        atr_mult = params.atr_mult_base
    
    stop_distance = atr_mult * atr_t
    
    return RiskSpec(
        stop_distance=stop_distance,
        reward_risk=params.reward_risk,
        max_holding_sessions=params.max_holding
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