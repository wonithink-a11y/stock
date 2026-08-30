"""WVF-KR-V1 baseline rule module.

Implements Williams Vix Fix (Larry Williams, Active Trader Dec 2007):
- WVF = (Highest(Close, 22) - Low) / Highest(Close, 22) * 100
- Bollinger Bands on WVF: SMA(WVF, 20) ± 2.0 * StdDev(WVF, 20)
- Entry: WVF crosses above BB upper band
- Exit: WVF crosses below BB midline (20 SMA)
- Signal at t close; execution at next trading day OPEN.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "strategies" / "wvf_kr_v1" / "policy.json").read_text(encoding="utf-8"))

WVF_LOOKBACK = POLICY["indicators"]["wvf"]["lookback"]
BB_LEN = POLICY["indicators"]["bollinger"]["length"]
BB_MULT = POLICY["indicators"]["bollinger"]["mult"]

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _std(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).std(ddof=0)

def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Add WVF and Bollinger Bands on WVF to A2a OHLCV bars."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars = bars.copy()
        bars.index = pd.to_datetime(bars.index)

    feats = bars.copy()
    c = feats["close"]
    l = feats["low"]

    # WVF = (Highest(Close, 22) - Low) / Highest(Close, 22) * 100
    highest_close = c.rolling(WVF_LOOKBACK).max()
    feats["wvf"] = (highest_close - l) / highest_close * 100.0

    # Bollinger Bands on WVF
    wvf_sma = _sma(feats["wvf"], BB_LEN)
    wvf_std = _std(feats["wvf"], BB_LEN)
    feats["bb_mid"] = wvf_sma
    feats["bb_upper"] = wvf_sma + BB_MULT * wvf_std
    feats["bb_lower"] = wvf_sma - BB_MULT * wvf_std

    # Entry: WVF crosses above BB upper band
    feats["entry_sig"] = (feats["wvf"] >= feats["bb_upper"]) & (feats["wvf"].shift(1) < feats["bb_upper"].shift(1))
    # Exit: WVF crosses below BB midline
    feats["exit_sig"] = (feats["wvf"] < feats["bb_mid"]) & (feats["wvf"].shift(1) >= feats["bb_mid"].shift(1))

    return feats

def generate_signals(symbol: str, features: pd.DataFrame) -> list[dict]:
    """Entry signals for engine compatibility (PIT evaluator will filter by date)."""
    signals = []
    for d, row in features.iterrows():
        if row.get("entry_sig", False):
            signals.append({
                "symbol": symbol,
                "side": "BUY",
                "signal_date": d.strftime("%Y-%m-%d"),
                "signal_type": "WVF_BB_UPPER_CROSS",
                "entry_price": None,
            })
    return signals

def evaluate_at(pit_features, symbol: str, date: str, prev_date: str | None) -> dict | None:
    """PIT entry evaluator. Returns entry signal dict or None."""
    if prev_date is None:
        return None
    try:
        f = pit_features.at(date)
    except Exception:
        return None
    if bool(f.get("entry_sig", False)):
        return {"symbol": symbol, "side": "BUY", "signal_date": date, "signal_type": "WVF_BB_UPPER_CROSS"}
    return None