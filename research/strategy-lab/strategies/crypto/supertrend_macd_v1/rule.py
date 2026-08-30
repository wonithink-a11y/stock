"""Supertrend + MACD + ATR (Strategy 5).

Objective: test whether a different trend-following structure from the existing
Donchian+ATR survives out-of-sample.

- Supertrend: ATR period = 10, multiplier = 3 (canonical public formula)
- MACD: 12 / 26 / 9
- Entry: supertrend bullish AND MACD line > signal line (edge-triggered on the
  combined condition -> next bar OPEN via engine next_session)
- Exit: reuse the existing lab ATR stop risk management unchanged
  (stop = entry - 2*ATR(14), target = entry + 3*stop, 60-bar time exit) - the
  spec explicitly asks to reuse the engine's ATR stop, no new exit invented.

No Supertrend/MACD parameter optimization.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class SupertrendMACDParams:
    st_atr_period: int = 10
    st_mult: float = 3.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    atr_mult: float = 2.0
    reward_risk: float = 3.0
    max_holding: int = 60


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return SupertrendMACDParams(**policy.get("params", {}))


def _supertrend(high, low, close, period, mult):
    """Canonical Supertrend (as in public Pine Script implementations)."""
    hl2 = (high + low) / 2.0
    atr = atr_indicator(high, low, close, period)
    basic_ub = hl2 + mult * atr
    basic_lb = hl2 - mult * atr

    n = len(close)
    final_ub = pd.Series(float("nan"), index=close.index)
    final_lb = pd.Series(float("nan"), index=close.index)
    supertrend = pd.Series(float("nan"), index=close.index)

    # start the recursion at the first bar with a valid ATR
    start = atr.notna().argmax()
    if atr.isna().all():
        return supertrend

    ub_prev = float(basic_ub.iloc[start])
    lb_prev = float(basic_lb.iloc[start])
    st_prev = ub_prev
    final_ub.iloc[start], final_lb.iloc[start] = ub_prev, lb_prev
    supertrend.iloc[start] = st_prev

    for i in range(start + 1, n):
        c_prev = float(close.iloc[i - 1])
        bu, bl = float(basic_ub.iloc[i]), float(basic_lb.iloc[i])
        fu = bu if (bu < ub_prev or c_prev > ub_prev) else ub_prev
        fl = bl if (bl > lb_prev or c_prev < lb_prev) else lb_prev
        if st_prev == ub_prev:
            st = fu if close.iloc[i] <= fu else fl
        else:
            st = fl if close.iloc[i] >= fl else fu
        final_ub.iloc[i], final_lb.iloc[i] = fu, fl
        supertrend.iloc[i] = st
        ub_prev, lb_prev, st_prev = fu, fl, st

    return supertrend


def compute_features(bars: pd.DataFrame, params: SupertrendMACDParams) -> pd.DataFrame:
    features = bars.copy()

    st = _supertrend(features["high"], features["low"], features["close"],
                     params.st_atr_period, params.st_mult)
    features["supertrend"] = st
    features["st_bullish"] = features["close"] > st

    ema_fast = features["close"].ewm(span=params.macd_fast, adjust=False).mean()
    ema_slow = features["close"].ewm(span=params.macd_slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=params.macd_signal, adjust=False).mean()
    features["macd"] = macd
    features["macd_signal"] = signal
    features["macd_hist"] = macd - signal
    features["macd_bull"] = macd > signal

    features["cond"] = features["st_bullish"] & features["macd_bull"]
    features["entry_cond"] = features["cond"] & ~features["cond"].shift(1, fill_value=False)

    features["atr"] = atr_indicator(features["high"], features["low"], features["close"],
                                    period=params.atr_period)
    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: SupertrendMACDParams) -> list:
    warmup = (features["supertrend"].notna()
              & features["macd"].notna()
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


def risk_spec_for(row, params: SupertrendMACDParams) -> RiskSpec:
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