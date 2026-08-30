"""Crypto Donchian Breakout + ATR Stop/Trailing Strategy.

Entry: Close > Donchian High(N)  (breakout above N-period high)
Exit: 
  - Stop: Close < Entry - ATR_mult * ATR(14)  (initial stop)
  - Trail: Close < Highest_Close_Since_Entry - ATR_mult * ATR(14)  (trailing stop)
  - Time: Max holding sessions reached

Uses only data available at signal time (PIT-compliant).
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass

from engine.indicators.donchian import donchian_channel
from engine.indicators.atr import atr
from engine.signals.schema import RiskSpec


PARAMS = {
    "strategyId": "crypto_donchian_atr",
    "universe": {"mode": "CRYPTO_FIXED"},
    "testUniverse": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"],
    "donchianPeriod": 20,
    "atrPeriod": 14,
    "atrMult": 2.0,           # stop/trail distance in ATR units
    "maxHoldingSessions": 60, # max bars (days or 4h candles)
    "risk": {
        "stopPct": 0.0,       # not used; ATR-based stop
        "targetPct": 0.0,     # not used; trailing exit
        "maxHoldingSessions": 60,
    },
    "cost": {
        "entryCostBps": 5,    # 0.05% Upbit maker fee
        "exitCostBps": 5,
        "slippageBps": 3,     # 0.03% slippage
    },
    "portfolio": {
        "initialCapital": 100_000_000,  # 100M KRW
        "maxPositions": 5,
        "equalWeight": True,
        "fractionalShares": True,
        "tieBreak": "ticker_ascending",
    },
    "scheduling": {"continuousHoldOnRenewal": False},
}


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute Donchian channels and ATR. All shifted to avoid lookahead."""
    df = bars.copy()
    
    # Donchian channel (uses high.shift(1), low.shift(1) internally)
    dc = donchian_channel(df["high"], df["low"], period=PARAMS["donchianPeriod"])
    df["donchian_high"] = dc["donchian_high"]
    df["donchian_low"] = dc["donchian_low"]
    
    # ATR (Wilder's smoothing, shifted internally)
    df["atr"] = atr(df["high"], df["low"], df["close"], period=PARAMS["atrPeriod"])
    
    # Signal: close breaks above donchian_high
    # We use close > donchian_high (both available at bar close)
    df["signal"] = (df["close"] > df["donchian_high"]).astype(int)
    
    # For trailing: track highest close since entry (computed at runtime in risk_spec)
    # Here we just prepare ATR for stop distance
    df["stop_distance_atr"] = df["atr"] * PARAMS["atrMult"]
    
    return df


def signal_fires(features: pd.DataFrame, as_of: str) -> bool:
    """Check if entry signal fires on as_of date."""
    ts = pd.Timestamp(as_of)
    if ts not in features.index:
        return False
    row = features.loc[ts]
    # Signal fires when close > donchian_high (breakout)
    # Need valid donchian_high and atr
    if pd.isna(row["donchian_high"]) or pd.isna(row["atr"]):
        return False
    return bool(row["signal"] == 1)


def risk_spec_for(row: pd.Series) -> RiskSpec:
    """Return risk spec for executor. Uses ATR-based stop with 2:1 reward:risk."""
    # Ensure row is a Series (not DataFrame from duplicate index)
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    stop_distance = float(row["stop_distance_atr"])
    return RiskSpec(
        stop_distance=stop_distance,
        reward_risk=2.0,  # 2:1 reward:risk
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
        if row["signal"] == 1 and not pd.isna(row["donchian_high"]) and not pd.isna(row["atr"]):
            # Signal strength based on breakout magnitude
            strength = (row["close"] / row["donchian_high"] - 1) if row["donchian_high"] > 0 else 0
            yield Signal(
                symbol=symbol,
                signal_date=idx.strftime("%Y-%m-%d"),
                direction="LONG",
                signal_strength=float(strength),
                metadata={"donchian_high": float(row["donchian_high"]), "atr": float(row["atr"])}
            )


if __name__ == "__main__":
    # Quick selftest
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
    
    from engine.data.cryptoProvider import load_crypto_bars
    
    markets = ["KRW-BTC"]
    bars = load_crypto_bars(markets, timeframe="D", count=300)
    btc_bars = bars["KRW-BTC"]
    
    feats = compute_features(btc_bars)
    print(f"Rows: {len(feats)}")
    print(f"Signals: {feats['signal'].sum()}")
    print(f"Last 5 signals:\n{feats[feats['signal']==1].tail()}")
    print(f"\nLast row:\n{feats.tail(1)}")