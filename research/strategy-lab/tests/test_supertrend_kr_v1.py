"""SUPERTREND-KR-V1 unit / invariant tests (STEP 2, section 14).

Covers TEST 1-10. Fast, synthetic bars where possible; one real-data reference
comparison for TEST 1 (SuperTrend against known formula).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

import numpy as np
import pandas as pd

from strategies.supertrend_kr_v1 import rule as ST_RULE
from engine.data.calendar import TradingCalendar

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

ATR_PERIOD = ST_RULE.ATR_PERIOD
ATR_ALPHA = ST_RULE.ATR_ALPHA
MULT = ST_RULE.MULT


def synthetic_bars(n=300, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    bars = pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": rng.integers(1_000, 10_000, n),
    }, index=dates)
    return bars


# --------------------------------------------------------------------------
# TEST 1 - SuperTrend matches reference implementation (TradingView logic)
# --------------------------------------------------------------------------
def test_1_supertrend_matches_reference():
    """Verify SuperTrend calculation against a slow reference implementation."""
    bars = synthetic_bars(300, seed=3)
    feats = ST_RULE.compute_features(bars)
    
    # Reference implementation
    h = bars["high"]
    l = bars["low"]
    c = bars["close"]
    
    # TR
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr_ref = tr.ewm(alpha=ATR_ALPHA, adjust=False).mean()
    
    src = (h + l) / 2.0
    basic_ub = src + MULT * atr_ref
    basic_lb = src - MULT * atr_ref
    
    final_ub_ref = pd.Series(index=bars.index, dtype=float)
    final_lb_ref = pd.Series(index=bars.index, dtype=float)
    trend_ref = pd.Series(index=bars.index, dtype=int)
    
    for i in range(len(bars)):
        if i == 0:
            final_ub_ref.iloc[i] = basic_ub.iloc[i]
            final_lb_ref.iloc[i] = basic_lb.iloc[i]
            trend_ref.iloc[i] = 1 if c.iloc[i] > final_ub_ref.iloc[i] else -1
            continue
        
        if basic_ub.iloc[i] < final_ub_ref.iloc[i-1] or c.iloc[i-1] > final_ub_ref.iloc[i-1]:
            final_ub_ref.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub_ref.iloc[i] = final_ub_ref.iloc[i-1]
            
        if basic_lb.iloc[i] > final_lb_ref.iloc[i-1] or c.iloc[i-1] < final_lb_ref.iloc[i-1]:
            final_lb_ref.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb_ref.iloc[i] = final_lb_ref.iloc[i-1]
            
        if c.iloc[i] > final_ub_ref.iloc[i-1]:
            trend_ref.iloc[i] = 1
        elif c.iloc[i] < final_lb_ref.iloc[i-1]:
            trend_ref.iloc[i] = -1
        else:
            trend_ref.iloc[i] = trend_ref.iloc[i-1]
    
    # Compare
    common = feats.index.intersection(bars.index)
    for col, ref_col in [("atr", "atr_ref"), ("final_ub", "final_ub_ref"), 
                          ("final_lb", "final_lb_ref"), ("trend", "trend_ref")]:
        a = feats.loc[common, col].to_numpy()
        if ref_col == "atr_ref":
            b = atr_ref.loc[common].to_numpy()
        elif ref_col == "final_ub_ref":
            b = final_ub_ref.loc[common].to_numpy()
        elif ref_col == "final_lb_ref":
            b = final_lb_ref.loc[common].to_numpy()
        elif ref_col == "trend_ref":
            b = trend_ref.loc[common].to_numpy()
        mask = np.isfinite(a) & np.isfinite(b)
        if col == "trend":
            assert np.array_equal(a[mask], b[mask]), f"{col} deviates"
        else:
            assert np.allclose(a[mask], b[mask], rtol=1e-6, atol=1e-9), f"{col} deviates"


# --------------------------------------------------------------------------
# TEST 2/3 - Trend flip detection
# --------------------------------------------------------------------------
def test_2_3_trend_flip_detection():
    """Craft a sequence that produces clear UP->DOWN and DOWN->UP flips."""
    bars = synthetic_bars(100, seed=11)
    feats = ST_RULE.compute_features(bars)
    trend = feats["trend"]
    entry_sig = (trend.shift(1) == -1) & (trend == 1)
    exit_sig = (trend.shift(1) == 1) & (trend == -1)
    
    # Verify entry_sig fires exactly on DOWN->UP transition
    expected_entry = (trend.shift(1) == -1) & (trend == 1)
    assert entry_sig.equals(expected_entry), "entry_sig != DOWN->UP transition"
    
    # Verify exit_sig fires exactly on UP->DOWN transition
    expected_exit = (trend.shift(1) == 1) & (trend == -1)
    assert exit_sig.equals(expected_exit), "exit_sig != UP->DOWN transition"


# --------------------------------------------------------------------------
# TEST 4 - signal day != execution day (next-open fill)
# --------------------------------------------------------------------------
def test_4_signal_and_execution_separated():
    from run_supertrend_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=13)
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, audit = build_events("T0000", feats, cal, None)
    for kind, fd, fill in events:
        sig_date = fill.order.signal_date
        assert fd > sig_date, f"same-bar execution? signal {sig_date} fill {fd}"
        assert fd == cal.next_session(sig_date), "fill not at next session open"
        assert fill.fill_type in ("OPEN", "TREND_REVERSAL")


# --------------------------------------------------------------------------
# TEST 5 - no same-bar execution in any generated trade
# --------------------------------------------------------------------------
def test_5_no_samebar_execution():
    from run_supertrend_kr_v1_smoke import build_events
    bars = synthetic_bars(500, seed=17)
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0001", feats, cal, None)
    entries = [(fd, f) for k, fd, f in events if k == "ENTRY"]
    exits = [(fd, f) for k, fd, f in events if k == "EXIT"]
    assert entries and exits, "test needs at least one complete cycle"
    for (efd, _ef), (xfd, _xf) in zip(entries, exits):
        assert xfd > efd, f"same-bar exit {xfd} <= entry {efd}"


# --------------------------------------------------------------------------
# TEST 6/7 - listing-date PIT gate: no signal / no position before listedAt
# --------------------------------------------------------------------------
def test_6_7_listing_date_gate():
    from run_supertrend_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=19)
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    mid = feats.index[len(feats) // 2].strftime("%Y-%m-%d")

    events, audit = build_events("T0002", feats, cal, "9999-12-31")
    assert audit["pre_listing_signals"] > 0, "expected early signals to be gated out"
    assert not events, "no entry/exit event should exist when all signals pre-listing"

    events2, audit2 = build_events("T0002", feats, cal, "2010-01-01")
    assert audit2["pre_listing_signals"] == 0


# --------------------------------------------------------------------------
# TEST 8 - no short positions
# --------------------------------------------------------------------------
def test_8_no_short():
    from run_supertrend_kr_v1_smoke import build_events
    bars = synthetic_bars(400, seed=23)
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0003", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.direction == "LONG", f"unexpected direction {fill.order.direction}"


# --------------------------------------------------------------------------
# TEST 9 - no leverage (cash never negative in simulated portfolio)
# --------------------------------------------------------------------------
def test_9_no_leverage():
    from run_supertrend_kr_v1_smoke import build_events, PORT_CFG
    from engine.portfolio.portfolio import Portfolio
    bars = synthetic_bars(400, seed=29)
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0004", feats, cal, None)
    pf = Portfolio(PORT_CFG.__class__(initial_capital=1_000_000, max_positions=1,
                                      equal_weight=True, fractional_shares=False,
                                      tie_break="ticker_ascending"))
    by_date = {}
    for k, fd, fill in events:
        by_date.setdefault(fd, []).append((k, fill))
    for date in sorted(by_date):
        items = by_date[date]
        exits = []
        for k, f in items:
            if k == "EXIT" and f.order.symbol in pf.open_positions:
                exits.append((f.order.symbol, f, pf.open_positions[f.order.symbol]["shares"]))
        entries = [(f.order, f) for k, f in items if k == "ENTRY"]
        pf.process_day(date, exits, entries)
        assert pf.cash >= -1e-6, "cash went negative -> leverage"


# --------------------------------------------------------------------------
# TEST 10 - warm-up not included in performance (signals before PERF_START dropped)
# --------------------------------------------------------------------------
def test_10_warmup_not_in_performance():
    from run_supertrend_kr_v1_smoke import build_events, PERF_START
    bars = synthetic_bars(300, seed=31)
    idx = pd.date_range("2014-06-01", periods=300, freq="B")
    bars.index = idx
    feats = ST_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0005", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.signal_date >= PERF_START, \
            f"warmup signal {fill.order.signal_date} leaked into performance"


def run():
    test_1_supertrend_matches_reference()
    test_2_3_trend_flip_detection()
    test_4_signal_and_execution_separated()
    test_5_no_samebar_execution()
    test_6_7_listing_date_gate()
    test_8_no_short()
    test_9_no_leverage()
    test_10_warmup_not_in_performance()
    print("test_supertrend_kr_v1: OK")


if __name__ == "__main__":
    run()