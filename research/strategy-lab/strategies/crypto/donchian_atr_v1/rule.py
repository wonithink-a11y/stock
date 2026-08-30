"""Donchian Breakout + ATR Strategy for Crypto (Daily/4H).

Source inspiration:
- Classic Donchian Channel breakout (Richard Donchian, 1970s)
- Turtle Trading rules (Dennis/Eckhardt, 1980s) - Donchian 20/55 + ATR stop
- Modern crypto adaptations: freqtrade "Donchian" strategy, Jesse "Donchian" strategy
- GitHub: freqtrade/freqtrade-strategies (Donchian-based strategies)
- GitHub: jesse-ai/jesse (Donchian channel implementation)

Core Rules (reproduced from public descriptions, not copied):
1. Entry: Close breaks above Donchian High (N-period lookback, t-1 excluded)
2. Exit: ATR-based trailing stop (2 * ATR) OR time exit (max holding periods)
3. Position sizing: Equal weight, max concurrent positions
4. Filter: Optional volatility regime filter (ATR percentile)

Parameters (from public strategy defaults, not optimized):
- Donchian period: 20 (classic) / 55 (long-term)
- ATR period: 14 (Wilder)
- Stop multiplier: 2.0
- Reward:Risk: 3.0
- Max holding: 60 bars (daily) / 120 bars (4h)
"""
import json
import os
from dataclasses import dataclass

import pandas as pd
import numpy as np

from engine.indicators.atr import atr as atr_indicator
from engine.indicators.donchian import donchian_channel
from engine.signals.schema import RiskSpec, Signal


@dataclass
class DonchianATRParams:
    donchian_period: int = 20
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60
    volatility_filter: bool = False  # if True, only trade when ATR < 80th percentile
    vol_lookback: int = 100


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return DonchianATRParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: DonchianATRParams) -> pd.DataFrame:
    """Compute Donchian channels and ATR. All backward-only (t excluded)."""
    features = bars.copy()
    
    # Donchian channel (shifted by 1 so donchian_high[t] uses High[t-N..t-1])
    donchian = donchian_channel(features["high"], features["low"], period=params.donchian_period)
    features["donchian_high"] = donchian["donchian_high"]
    features["donchian_low"] = donchian["donchian_low"]
    
    # ATR (Wilder)
    features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=params.atr_period)
    
    # Volatility regime filter (ATR percentile)
    if params.volatility_filter:
        atr_pct = features["atr"].rolling(params.vol_lookback).rank(pct=True)
        features["atr_percentile"] = atr_pct
        features["vol_ok"] = atr_pct < 0.8  # Only trade in lower 80% volatility
    
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: DonchianATRParams) -> list:
    """Vectorized signal generation: edge-triggered Donchian breakout."""
    # Edge trigger: Close[t-1] <= DonchianHigh[t-1] AND Close[t] > DonchianHigh[t]
    above = features["close"] > features["donchian_high"]
    prev_above = above.shift(1, fill_value=False)
    raw_signal = above & ~prev_above
    
    # Volatility filter
    if params.volatility_filter and "vol_ok" in features.columns:
        raw_signal = raw_signal & features["vol_ok"]
    
    # Warmup: require valid Donchian and ATR
    warmup_mask = features["donchian_high"].notna() & features["atr"].notna()
    raw_signal = raw_signal & warmup_mask
    
    signals = []
    for date in features.index[raw_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
            direction="LONG"
        ))
    return signals


def risk_spec_for(row, params: DonchianATRParams) -> RiskSpec:
    """Risk spec at signal date: stop = entry - 2*ATR, target = entry + 3*stop."""
    atr_t = float(row["atr"])
    stop_distance = params.atr_mult * atr_t
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