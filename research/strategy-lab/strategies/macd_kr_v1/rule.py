"""MACD-KR-V1 baseline (STEP 2).

MACD(12,26,9) crossover, Long only, no pyramiding/short/leverage.

Signals:
  - Entry (bullish cross): hist[t] > 0 AND hist[t-1] <= 0   (MACD crosses above Signal)
  - Exit  (bearish cross): hist[t] < 0 AND hist[t-1] >= 0   (MACD crosses below Signal)

Execution (handled by run_macd_kr_v1_smoke.py, NOT engine.executor):
  - Signal decided at t CLOSE.
  - Fill at next_session(t) OPEN. No same-bar execution.
  - Hold state per ticker: flat -> bullish -> LONG(entry next open); long -> bearish -> FLAT(exit next open).

Indicator convention: EMA via pandas ewm(span=..., adjust=False), identical to the
repository's established MACD reference (macd_from_close_series in
macd_information_content_study.py), so TEST 1 comparison is exact.
"""
import json
import os

import numpy as np
import pandas as pd

with open(os.path.join(os.path.dirname(__file__), "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

_FAST = PARAMS["indicators"]["macd"]["fast"]
_SLOW = PARAMS["indicators"]["macd"]["slow"]
_SIGNAL = PARAMS["indicators"]["macd"]["signal"]


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def macd_from_close(close: pd.Series, fast: int = _FAST, slow: int = _SLOW,
                    signal_span: int = _SIGNAL) -> pd.DataFrame:
    """Return DataFrame[macd, signal, hist]. Matches repo reference convention."""
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd = fast_ema - slow_ema
    signal = ema(macd, signal_span)
    hist = macd - signal
    return pd.DataFrame({"macd": macd, "signal": signal, "hist": hist}, index=close.index)


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    """bars: [open, high, low, close, volume] indexed by date. Adds macd, signal,
    hist (all causal / backward-only)."""
    features = bars.copy()
    m = macd_from_close(features["close"])
    features["macd"] = m["macd"]
    features["macd_signal"] = m["signal"]
    features["macd_hist"] = m["hist"]
    return features


def cross_series(hist: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (bullish_bool, bearish_bool) aligned to hist.index.

    bullish[t] = hist[t] > 0 AND hist[t-1] <= 0 (short-only comparison, no double
    count of a zero floor it over bar t-1). bearish[t] = hist[t] < 0 AND hist[t-1] >= 0.
    NaN hist rows -> False (warmup not a signal)."""
    hist = hist.fillna(value=np.nan)
    prev = hist.shift(1)
    bullish = (hist > 0) & (prev <= 0)
    bearish = (hist < 0) & (prev >= 0)
    return bullish.fillna(False), bearish.fillna(False)


def _fmt(d):
    return d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    """Crossover signals only (used by unit tests / any engine-driven run)."""
    from engine.signals.schema import Signal  # local import keeps rule standalone for tests
    bull, _ = cross_series(features["macd_hist"])
    return [Signal(symbol=symbol, signal_date=_fmt(d), direction="LONG")
            for d in features.index[bull]]


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    """PIT-guarded per-date entry-signal evaluator (matches engine evaluate_at contract)."""
    row = pit_features.at(date)
    if row is None:
        return None
    hist_t = row.get("macd_hist")
    if hist_t is None or pd.isna(hist_t):
        return None
    if prev_date is None:
        return None
    prev_row = pit_features.at(prev_date)
    if prev_row is None:
        return None
    hist_prev = prev_row.get("macd_hist")
    if hist_prev is None or pd.isna(hist_prev):
        return None
    if float(hist_t) > 0 and float(hist_prev) <= 0:
        from engine.signals.schema import Signal
        return Signal(symbol=symbol, signal_date=_fmt(date), direction="LONG")
    return None
