"""Crypto Trend Following + Multi-timeframe Momentum Strategy.

Entry: 
  - Trend: Close > SMA(long_period)  (long-term trend filter)
  - Momentum: ROC(short_period) > 0 AND ROC(medium_period) > 0  (multi-timeframe momentum)
  - Both conditions must be true

Exit:
  - Trend reversal: Close < SMA(long_period)
  - Momentum loss: ROC(short_period) < 0
  - Time: Max holding sessions

PIT-compliant: all indicators use shifted data.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass

from engine.signals.schema import RiskSpec


PARAMS = {
    "strategyId": "crypto_trend_momentum",
    "universe": {"mode": "CRYPTO_FIXED"},
    "testUniverse": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"],
    "trendPeriod": 200,      # long-term trend (SMA)
    "momShortPeriod": 20,    # short-term momentum (ROC)
    "momMediumPeriod": 60,   # medium-term momentum (ROC)
    "maxHoldingSessions": 60,
    "risk": {
        "stopPct": 0.0,
        "targetPct": 0.0,
        "maxHoldingSessions": 60,
    },
    "cost": {
        "entryCostBps": 5,
        "exitCostBps": 5,
        "slippageBps": 3,
    },
    "portfolio": {
        "initialCapital": 100_000_000,
        "maxPositions": 5,
        "equalWeight": True,
        "fractionalShares": True,
        "tieBreak": "ticker_ascending",
    },
    "scheduling": {"continuousHoldOnRenewal": False},
}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute trend and momentum indicators. All shifted for PIT."""
    df = bars.copy()
    
    # Long-term trend: SMA(200) of close, shifted by 1
    df["sma_long"] = df["close"].rolling(PARAMS["trendPeriod"]).mean().shift(1)
    
    # Short-term momentum: ROC(20) = close / close.shift(20) - 1, shifted by 1
    df["roc_short"] = (df["close"] / df["close"].shift(PARAMS["momShortPeriod"]) - 1).shift(1)
    
    # Medium-term momentum: ROC(60), shifted by 1
    df["roc_medium"] = (df["close"] / df["close"].shift(PARAMS["momMediumPeriod"]) - 1).shift(1)
    
    # Trend filter: close > sma_long
    df["trend_up"] = (df["close"] > df["sma_long"]).astype(int)
    
    # Momentum: both ROC positive
    df["mom_positive"] = ((df["roc_short"] > 0) & (df["roc_medium"] > 0)).astype(int)
    
    # Combined signal
    df["signal"] = (df["trend_up"] & df["mom_positive"]).astype(int)
    
    # For exits
    df["trend_down"] = (df["close"] < df["sma_long"]).astype(int)
    df["mom_negative"] = (df["roc_short"] < 0).astype(int)
    
    return df


def signal_fires(features: pd.DataFrame, as_of: str) -> bool:
    """Check if entry signal fires on as_of date."""
    ts = pd.Timestamp(as_of)
    if ts not in features.index:
        return False
    row = features.loc[ts]
    if pd.isna(row["sma_long"]) or pd.isna(row["roc_short"]) or pd.isna(row["roc_medium"]):
        return False
    return bool(row["signal"] == 1)


def risk_spec_for(row: pd.Series) -> RiskSpec:
    """Return risk spec. Use 2:1 reward:risk with ATR-based stop."""
    # Ensure row is a Series (not DataFrame from duplicate index)
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    # Use ATR-like stop (5% of price as proxy since we don't have ATR in this strategy)
    # The executor will use this stop_distance
    close_val = row["close"]
    if isinstance(close_val, pd.Series):
        close_val = close_val.iloc[0]
    return RiskSpec(
        stop_distance=0.05 * close_val if not pd.isna(close_val) else 0.0,
        reward_risk=2.0,
        max_holding_sessions=PARAMS["maxHoldingSessions"],
    )


@dataclass
class Signal:
    symbol: str
    signal_date: str
    direction: str = "LONG"
    signal_strength: float | None = None
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def generate_signals(symbol: str, features: pd.DataFrame):
    """Yield Signal objects for each entry signal in features."""
    for idx, row in features.iterrows():
        if row["signal"] == 1 and not pd.isna(row["sma_long"]) and not pd.isna(row["roc_short"]):
            # Signal strength based on momentum magnitude
            strength = float(row["roc_short"]) if not pd.isna(row["roc_short"]) else 0
            yield Signal(
                symbol=symbol,
                signal_date=idx.strftime("%Y-%m-%d"),
                direction="LONG",
                signal_strength=strength,
                metadata={"sma_long": float(row["sma_long"]) if not pd.isna(row["sma_long"]) else None, 
                          "roc_short": float(row["roc_short"]) if not pd.isna(row["roc_short"]) else None}
            )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
    
    from engine.data.cryptoProvider import load_crypto_bars
    
    markets = ["KRW-BTC"]
    bars = load_crypto_bars(markets, timeframe="D", count=500)
    btc_bars = bars["KRW-BTC"]
    
    feats = compute_features(btc_bars)
    print(f"Rows: {len(feats)}")
    print(f"Signals: {feats['signal'].sum()}")
    print(f"Last 5 signals:\n{feats[feats['signal']==1].tail()}")
    print(f"\nLast row:\n{feats.tail(1)}")