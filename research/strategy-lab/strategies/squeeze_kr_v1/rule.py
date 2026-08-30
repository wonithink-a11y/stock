"""SQUEEZE-KR-V1 baseline rule module.

Implements TTM Squeeze (John Carter, Mastering the Trade ch.11) as standardised
by LazyBear Squeeze Momentum / StockCharts:
- Bollinger Band: SMA(20) +/- 2.0 * pop_std(close, 20, ddof=0)
- Keltner Channel: SMA(20) +/- 1.5 * SMA(TR, 20)
- TR = max(H-L, |H-prevClose|, |L-prevClose|)
- Squeeze ON: BB upper < KC upper AND BB lower > KC lower
- RELEASE: squeeze_on[t-1] & ~squeeze_on[t]
- Composite = ((Highest(H,20) + Lowest(L,20)) / 2 + SMA(C,20)) / 2
- Momentum: 20-period linear regression endpoint of (Close - Composite)
- Entry: RELEASE & Momentum > 0
- Exit: Momentum crosses zero from above (Momentum[t] < 0 & Momentum[t-1] >= 0)
- Signal evaluated at t close; execution at next trading day OPEN.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "strategies" / "squeeze_kr_v1" / "policy.json").read_text(encoding="utf-8"))

BB_LEN = POLICY["indicators"]["bollinger"]["length"]
BB_MULT = POLICY["indicators"]["bollinger"]["mult"]
KC_LEN = POLICY["indicators"]["keltner"]["length"]
KC_MULT = POLICY["indicators"]["keltner"]["rangeMult"]
MOM_LEN = POLICY["indicators"]["momentum"]["lookback"]

LINREG_DENOM = MOM_LEN * sum(k * k for k in range(MOM_LEN)) - sum(range(MOM_LEN)) ** 2
LINREG_SX = sum(range(MOM_LEN))

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _std(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).std(ddof=0)

def _tr(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev).abs(),
        (low - prev).abs()
    ], axis=1).max(axis=1)
    return tr

def _linreg_endpoint(y: pd.Series, n: int = MOM_LEN) -> pd.Series:
    """Vectorised 20-period linear regression endpoint (OLS on 0..n-1, evaluated at n-1)."""
    gy = (y * pd.Series(np.arange(len(y)), index=y.index))
    sy = y.rolling(n).sum()
    sgy = gy.rolling(n).sum()
    g_cur = pd.Series(np.arange(len(y)), index=y.index)
    sxy = sgy - (g_cur - n + 1) * sy
    b1 = (n * sxy - LINREG_SX * sy) / LINREG_DENOM
    val = sy / n + b1 * (n - 1) / 2
    return val

def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Add squeeze indicators to A2a OHLCV bars."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        bars = bars.copy()
        bars.index = pd.to_datetime(bars.index)

    feats = bars.copy()
    c = feats["close"]
    h = feats["high"]
    l = feats["low"]

    sma20 = _sma(c, BB_LEN)
    std20 = _std(c, BB_LEN)
    feats["bb_upper"] = sma20 + BB_MULT * std20
    feats["bb_lower"] = sma20 - BB_MULT * std20

    tr = _tr(h, l, c)
    atr = _sma(tr, KC_LEN)
    feats["kc_upper"] = sma20 + KC_MULT * atr
    feats["kc_lower"] = sma20 - KC_MULT * atr

    feats["squeeze_on"] = (feats["bb_upper"] < feats["kc_upper"]) & (feats["bb_lower"] > feats["kc_lower"])

    highest_h = h.rolling(MOM_LEN).max()
    lowest_l = l.rolling(MOM_LEN).min()
    donchian_mid = (highest_h + lowest_l) / 2
    composite = (donchian_mid + sma20) / 2
    feats["composite"] = composite

    delta = c - composite
    feats["momentum"] = _linreg_endpoint(delta, MOM_LEN)

    feats["release"] = feats["squeeze_on"].shift(1, fill_value=False) & ~feats["squeeze_on"]
    feats["exit_cross"] = (feats["momentum"] < 0) & (feats["momentum"].shift(1) >= 0)

    return feats

def generate_signals(symbol: str, features: pd.DataFrame) -> list[dict]:
    """Entry signals for engine compatibility (PIT evaluator will filter by date)."""
    signals = []
    for d, row in features.iterrows():
        if row.get("release", False) and row.get("momentum", 0) > 0:
            signals.append({
                "symbol": symbol,
                "side": "BUY",
                "signal_date": d.strftime("%Y-%m-%d"),
                "signal_type": "SQUEEZE_RELEASE",
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
    rel = bool(f.get("release", False))
    mom = float(f.get("momentum", 0))
    if rel and mom > 0:
        return {"symbol": symbol, "side": "BUY", "signal_date": date, "signal_type": "SQUEEZE_RELEASE"}
    return None