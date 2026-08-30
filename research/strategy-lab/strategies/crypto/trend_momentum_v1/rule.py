"""Trend Following + Momentum Strategy for Crypto (Daily/4H).

Source inspiration:
- Dual Moving Average Crossover (classic trend following)
- Momentum filter (12-1 or 6-1 month momentum) - Jegadeesh/Titman (1993)
- Crypto adaptations: freqtrade "MACD+RSI", "EMA Crossover" strategies
- GitHub: freqtrade/freqtrade-strategies (trend following strategies)
- GitHub: mementum/backtrader (samples: SMA crossover, momentum)
- Academic: "Time Series Momentum" (Moskowitz/Ooi/Pedersen, 2012)

Core Rules (reproduced from public descriptions):
1. Trend Filter: Fast MA > Slow MA (uptrend) AND price > Slow MA
2. Momentum Filter: N-period return > 0 (positive momentum)
3. Entry: Both filters true on bar close
4. Exit: Trend filter fails (fast MA crosses below slow MA) OR momentum turns negative
5. Stop: ATR-based trailing stop (optional)
6. Position sizing: Equal weight, max concurrent positions

Parameters (from public strategy defaults):
- Fast MA: 20 (daily) / 50 (4h)
- Slow MA: 50 (daily) / 200 (4h)
- Momentum period: 60 (daily) / 120 (4h) - approx 3 months / 20 days
- ATR stop: 2.0 * ATR(14) (optional)
- Max holding: None (trend following holds until trend breaks)
"""
import json
import os
from dataclasses import dataclass

import pandas as pd
import numpy as np

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class TrendMomentumParams:
    fast_ma: int = 20
    slow_ma: int = 50
    momentum_period: int = 60
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 0  # 0 = no time exit (trend following)
    use_atr_stop: bool = True


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return TrendMomentumParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: TrendMomentumParams) -> pd.DataFrame:
    """Compute MAs, momentum, and ATR. All backward-only."""
    features = bars.copy()
    
    # Moving averages (shifted by 1 for PIT compliance)
    features["fast_ma"] = features["close"].shift(1).rolling(params.fast_ma).mean()
    features["slow_ma"] = features["close"].shift(1).rolling(params.slow_ma).mean()
    
    # Momentum: N-period return (shifted by 1)
    features["momentum"] = features["close"].shift(1) / features["close"].shift(1 + params.momentum_period) - 1
    
    # ATR for optional stop
    if params.use_atr_stop:
        features["atr"] = atr_indicator(features["high"], features["low"], features["close"], period=params.atr_period)
    
    # Trend filter: fast > slow AND price > slow
    features["trend_up"] = (features["fast_ma"] > features["slow_ma"]) & (features["close"] > features["slow_ma"])
    
    # Momentum filter: positive momentum
    features["mom_up"] = features["momentum"] > 0
    
    # Combined entry condition
    features["entry_cond"] = features["trend_up"] & features["mom_up"]
    
    # Exit condition: trend breaks (fast crosses below slow)
    features["exit_cond"] = features["fast_ma"] < features["slow_ma"]
    
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: TrendMomentumParams) -> list:
    """Vectorized signal generation: enter on entry_cond edge, exit on exit_cond."""
    # Edge-triggered entry: entry_cond[t-1] == False AND entry_cond[t] == True
    entry_signal = features["entry_cond"] & ~features["entry_cond"].shift(1, fill_value=False)
    
    # Exit signal (for reference, actual exit handled by risk_spec/time_exit)
    # In trend following, we rely on trend break or ATR stop
    
    # Warmup: require valid MAs and momentum
    warmup_mask = (
        features["fast_ma"].notna() & 
        features["slow_ma"].notna() & 
        features["momentum"].notna()
    )
    if params.use_atr_stop:
        warmup_mask = warmup_mask & features["atr"].notna()
    
    entry_signal = entry_signal & warmup_mask
    
    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date),
            direction="LONG"
        ))
    return signals


def risk_spec_for(row, params: TrendMomentumParams) -> RiskSpec:
    """Risk spec: ATR stop if enabled, else very wide stop (rely on trend exit)."""
    if params.use_atr_stop:
        atr_t = float(row["atr"])
        stop_distance = params.atr_mult * atr_t
    else:
        # Wide stop - effectively no stop, rely on trend exit
        stop_distance = float(row["close"]) * 0.5  # 50% stop as fallback
    
    max_holding = params.max_holding if params.max_holding > 0 else 10000
    
    return RiskSpec(
        stop_distance=stop_distance,
        reward_risk=params.reward_risk,
        max_holding_sessions=max_holding
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