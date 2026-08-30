"""Volatility Breakout + Trend Persistence (Strategy Lab Step 9).

Research question:
  "변동성이 확장되면서 일정 방향으로 돌파한 경우, 단순 breakout보다
   이후 추세가 지속되는가?" (= does breakout AND volatile expansion
   lead to higher trend persistence than a plain breakout?)

Definition (baseline params only - no optimization):
  1. Volatility baseline : ATR(14) (Wilder)
  2. Price breakout      : Close crosses the prior 20-bar HIGH (t-1..t-20,
                           current bar excluded). Edge-triggered.
  3. Volatility expansion: current ATR(14)[t] > mean(ATR(14), t-1..t-20)
                           (prior-20-bar average of ATR, current excluded)
  4. Direction           : upper breakout -> LONG only. The Strategly Lab
                           Portfolio engine is LONG-only (no short/direction
                           handling), so lower-breakout SHORT is computed in
                           features but NOT signaled - no custom short engine.
  5. Entry               : next session OPEN (next_bar_open) via build_order -
                           no look-ahead.
  6. Exit                : standard lab exit reused as-is: RiskSpec(2*ATR[t]
                           stop, reward_risk 3.0, max_holding 60 bars). Same
                           standard exit used by all S1..S6 / existing lab
                           strategies. No new exit experiments.

Information difference vs existing strategies:
  - donchian_atr_v1/vol_regime_v1 use Donchian breakout with NO vol-expansion
    filter (vol_regime trades LOW volatility percentile, the opposite
    hypothesis). This strategy's entry filter is ATR vs its own 20-bar mean.
"""
import json
import os
from dataclasses import dataclass

import pandas as pd

from engine.indicators.atr import atr as atr_indicator
from engine.signals.schema import RiskSpec, Signal


@dataclass
class VolBreakPersistParams:
    atr_period: int = 14          # Wilder ATR input period
    breakout_period: int = 20     # prior-bar high/low lookback (t excluded)
    vol_ref_period: int = 20      # trailing mean window for ATR reference
    atr_mult: float = 2.0         # standard lab stop distance = 2*ATR[t]
    reward_risk: float = 3.0      # standard lab target = entry + 3*stop
    max_holding: int = 60         # standard lab time exit


def load_params(strategy_dir):
    policy_path = os.path.join(strategy_dir, "policy.json")
    with open(policy_path, encoding="utf-8") as f:
        policy = json.load(f)
    return VolBreakPersistParams(**policy.get("params", {}))


def compute_features(bars: pd.DataFrame, params: VolBreakPersistParams) -> pd.DataFrame:
    """Backward-only features. All references exclude the current bar."""
    features = bars.copy()

    features["atr"] = atr_indicator(
        features["high"], features["low"], features["close"],
        period=params.atr_period)

    # prior-20-bar rolling max(hig) / min(low), EXCLUDING today
    features["hh20_prior"] = features["high"].shift(1).rolling(params.breakout_period).max()
    features["ll20_prior"] = features["low"].shift(1).rolling(params.breakout_period).min()

    # prior-20-bar mean of ATR, EXCLUDING today
    features["atr_mean20"] = features["atr"].shift(1).rolling(params.vol_ref_period).mean()
    features["vol_expand"] = features["atr"] > features["atr_mean20"]

    features["up_break"] = features["close"] > features["hh20_prior"]
    features["dn_break"] = features["close"] < features["ll20_prior"]

    return features


def generate_signals(symbol: str, features: pd.DataFrame, params: VolBreakPersistParams) -> list:
    """Edge-triggered: fresh close break of prior 20-bar high, gated by
    volatility expansion (ATR > prior-20 mean). LONG only."""
    up = features["up_break"]
    prev_up = up.shift(1, fill_value=False)
    raw = up & ~prev_up & features["vol_expand"]

    warmup = (features["hh20_prior"].notna()
              & features["atr"].notna()
              & features["atr_mean20"].notna())
    entry_signal = raw & warmup

    signals = []
    for date in features.index[entry_signal]:
        signals.append(Signal(
            symbol=symbol,
            signal_date=date.strftime("%Y-%m-%d %H:%M:%S"),
            direction="LONG",  # engine is LONG-only; SHORT intentionally unused
        ))
    return signals


def risk_spec_for(row, params: VolBreakPersistParams) -> RiskSpec:
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