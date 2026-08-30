"""SUPERTREND-KR-V1 baseline rule module.

Implements SuperTrend (Olivier Seban, 2008) as standardised by TradingView:
- ATR(10) with Wilder EMA (alpha=1/10)
- Source = (High + Low) / 2
- Multiplier = 3.0
- Recursive final upper/lower bands
- Trend: UP when close > final_ub_prev, DOWN when close < final_lb_prev
- Entry: DOWN->UP flip; Exit: UP->DOWN flip
- Signal at t close; execution at next trading day OPEN.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "strategies" / "supertrend_kr_v1" / "policy.json").read_text(encoding="utf-8"))

ATR_PERIOD = POLICY["indicators"]["atr"]["period"]
ATR_ALPHA = POLICY["indicators"]["atr"]["alpha"]
MULT = POLICY["indicators"]["supertrend"]["multiplier"]

def _wilder_ema(series: pd.Series, alpha: float) -> pd.Series:
    """Wilder's EMA: ewm with adjust=False, alpha=1/period."""
    return series.ewm(alpha=alpha, adjust=False).mean()

def _tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev).abs(),
        (low - prev).abs()
    ], axis=1).max(axis=1)
    return tr

def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Add SuperTrend indicators to A2a OHLCV bars."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars = bars.copy()
        bars.index = pd.to_datetime(bars.index)

    feats = bars.copy()
    h = feats["high"]
    l = feats["low"]
    c = feats["close"]

    # ATR with Wilder EMA
    tr = _tr(h, l, c)
    atr = _wilder_ema(tr, ATR_ALPHA)
    feats["atr"] = atr

    # Basic bands
    src = (h + l) / 2.0
    basic_ub = src + MULT * atr
    basic_lb = src - MULT * atr

    # Recursive final bands
    final_ub = pd.Series(index=feats.index, dtype=float)
    final_lb = pd.Series(index=feats.index, dtype=float)
    trend = pd.Series(index=feats.index, dtype=int)  # 1=UP, -1=DOWN

    for i in range(len(feats)):
        if i == 0:
            final_ub.iloc[i] = basic_ub.iloc[i]
            final_lb.iloc[i] = basic_lb.iloc[i]
            trend.iloc[i] = 1 if c.iloc[i] > final_ub.iloc[i] else -1
            continue

        # Final upper band
        if basic_ub.iloc[i] < final_ub.iloc[i-1] or c.iloc[i-1] > final_ub.iloc[i-1]:
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = final_ub.iloc[i-1]

        # Final lower band
        if basic_lb.iloc[i] > final_lb.iloc[i-1] or c.iloc[i-1] < final_lb.iloc[i-1]:
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = final_lb.iloc[i-1]

        # Trend determination
        if c.iloc[i] > final_ub.iloc[i-1]:
            trend.iloc[i] = 1
        elif c.iloc[i] < final_lb.iloc[i-1]:
            trend.iloc[i] = -1
        else:
            trend.iloc[i] = trend.iloc[i-1]

    feats["final_ub"] = final_ub
    feats["final_lb"] = final_lb
    feats["trend"] = trend  # 1=UP, -1=DOWN

    # Entry: DOWN(-1) -> UP(1) flip
    feats["entry_sig"] = (trend.shift(1) == -1) & (trend == 1)
    # Exit: UP(1) -> DOWN(-1) flip
    feats["exit_sig"] = (trend.shift(1) == 1) & (trend == -1)

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
                "signal_type": "SUPERTREND_FLIP_UP",
                "entry_price": None,
            })
    return signals

def _prev_session(date_str: str, cal) -> str | None:
    try:
        idx = cal.sessions.index(date_str)
        if idx > 0:
            return cal.sessions[idx - 1]
    except Exception:
        pass
    return None

def evaluate_at(pit_features, symbol: str, date: str, prev_date: str | None) -> dict | None:
    """PIT entry evaluator. Returns entry signal dict or None."""
    if prev_date is None:
        return None
    try:
        f = pit_features.at(date)
    except Exception:
        return None
    if bool(f.get("entry_sig", False)):
        return {"symbol": symbol, "side": "BUY", "signal_date": date, "signal_type": "SUPERTREND_FLIP_UP"}
    return None