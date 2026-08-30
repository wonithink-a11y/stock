"""Crypto Donchian Breakout + ATR Stop/Trailing + Volatility/Market Regime Filter.

Entry: Same as crypto_donchian_atr but ONLY when regime is favorable.
Regime: 
  - Volatility regime: ATR(14) / Close < vol_threshold (low volatility = favorable for breakouts)
  - OR: BTC as market leader - only trade alts when BTC is in uptrend (close > SMA(50))
  - Configurable: can use either or both filters

Exit: Same ATR-based trailing stop as base strategy.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass

from engine.indicators.donchian import donchian_channel
from engine.indicators.atr import atr
from engine.signals.schema import RiskSpec


PARAMS = {
    "strategyId": "crypto_regime_filtered",
    "universe": {"mode": "CRYPTO_FIXED"},
    "testUniverse": ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"],
    "donchianPeriod": 20,
    "atrPeriod": 14,
    "atrMult": 2.0,
    "maxHoldingSessions": 60,
    # Regime filters
    "useVolRegimeFilter": True,
    "volThreshold": 0.03,      # ATR/Close < 3% = low vol regime (favorable)
    "useBtcTrendFilter": True, # Only trade alts when BTC > SMA(50)
    "btcTrendPeriod": 50,
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

# Cache for BTC trend (computed once per backtest)
_btc_trend_cache = {}


def compute_features(bars: pd.DataFrame, symbol: str = "", all_bars: dict | None = None) -> pd.DataFrame:
    """Compute Donchian, ATR, and regime indicators. All shifted for PIT."""
    df = bars.copy()
    
    # Donchian channel
    dc = donchian_channel(df["high"], df["low"], period=PARAMS["donchianPeriod"])
    df["donchian_high"] = dc["donchian_high"]
    df["donchian_low"] = dc["donchian_low"]
    
    # ATR
    df["atr"] = atr(df["high"], df["low"], df["close"], period=PARAMS["atrPeriod"])
    
    # Base signal: close breaks above donchian_high
    df["base_signal"] = (df["close"] > df["donchian_high"]).astype(int)
    
    # Volatility regime: ATR/Close (normalized volatility)
    df["vol_ratio"] = (df["atr"] / df["close"]).shift(1)  # shifted for PIT
    df["vol_regime_favorable"] = (df["vol_ratio"] < PARAMS["volThreshold"]).astype(int)
    
    # BTC trend regime (for alts only)
    if PARAMS["useBtcTrendFilter"] and symbol != "KRW-BTC" and all_bars is not None:
        btc_key = "KRW-BTC"
        if btc_key in all_bars:
            btc_bars = all_bars[btc_key]
            # Compute BTC SMA if not cached
            cache_key = f"btc_sma_{PARAMS['btcTrendPeriod']}"
            if cache_key not in _btc_trend_cache:
                btc_sma = btc_bars["close"].rolling(PARAMS["btcTrendPeriod"]).mean().shift(1)
                _btc_trend_cache[cache_key] = btc_sma
            else:
                btc_sma = _btc_trend_cache[cache_key]
            
            # Align to this symbol's index
            btc_trend = (btc_bars["close"] > btc_sma).astype(int)
            btc_trend = btc_trend.reindex(df.index, method="ffill")
            df["btc_trend_favorable"] = btc_trend
        else:
            df["btc_trend_favorable"] = 1  # no BTC data, allow
    else:
        df["btc_trend_favorable"] = 1  # BTC itself or filter disabled
    
    # Combined regime filter
    vol_ok = df["vol_regime_favorable"] if PARAMS["useVolRegimeFilter"] else 1
    btc_ok = df["btc_trend_favorable"] if PARAMS["useBtcTrendFilter"] else 1
    df["regime_favorable"] = (vol_ok & btc_ok).astype(int)
    
    # Final signal: base_signal AND regime_favorable
    df["signal"] = (df["base_signal"] & df["regime_favorable"]).astype(int)
    
    # Stop distance
    df["stop_distance_atr"] = df["atr"] * PARAMS["atrMult"]
    
    return df


def signal_fires(features: pd.DataFrame, as_of: str) -> bool:
    """Check if entry signal fires on as_of date."""
    ts = pd.Timestamp(as_of)
    if ts not in features.index:
        return False
    row = features.loc[ts]
    if pd.isna(row["donchian_high"]) or pd.isna(row["atr"]):
        return False
    return bool(row["signal"] == 1)


def risk_spec_for(row: pd.Series) -> RiskSpec:
    """Return risk spec for executor."""
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
                metadata={"donchian_high": float(row["donchian_high"]), "atr": float(row["atr"]),
                          "regime_favorable": int(row["regime_favorable"])}
            )


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
    
    from engine.data.cryptoProvider import load_crypto_bars
    
    markets = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
    bars = load_crypto_bars(markets, timeframe="D", count=500)
    
    for symbol in markets:
        feats = compute_features(bars[symbol], symbol=symbol, all_bars=bars)
        print(f"\n{symbol}: Rows={len(feats)}, Signals={feats['signal'].sum()}, Regime OK={feats['regime_favorable'].sum()}")
        if feats['signal'].sum() > 0:
            print(f"  Last signals:\n{feats[feats['signal']==1].tail(3)[['close','donchian_high','atr','vol_ratio','regime_favorable']]}")