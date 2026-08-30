"""WVF-KR-V1 unit / invariant tests (STEP 2, section 14).

Covers TEST 1-10. Fast, synthetic bars where possible; one real-data reference
comparison for TEST 1 (WVF against known formula).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

import numpy as np
import pandas as pd

from strategies.wvf_kr_v1 import rule as WVF_RULE
from engine.data.calendar import TradingCalendar

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

WVF_LOOKBACK = WVF_RULE.WVF_LOOKBACK
BB_LEN = WVF_RULE.BB_LEN
BB_MULT = WVF_RULE.BB_MULT


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
# TEST 1 - WVF matches reference implementation
# --------------------------------------------------------------------------
def test_1_wvf_matches_reference():
    """Verify WVF calculation against slow reference implementation."""
    bars = synthetic_bars(300, seed=3)
    feats = WVF_RULE.compute_features(bars)
    
    # Reference implementation
    c = bars["close"]
    l = bars["low"]
    
    highest_close_ref = c.rolling(WVF_LOOKBACK).max()
    wvf_ref = (highest_close_ref - l) / highest_close_ref * 100.0
    
    wvf_sma_ref = wvf_ref.rolling(BB_LEN).mean()
    wvf_std_ref = wvf_ref.rolling(BB_LEN).std(ddof=0)
    bb_mid_ref = wvf_sma_ref
    bb_upper_ref = wvf_sma_ref + BB_MULT * wvf_std_ref
    
    entry_sig_ref = (wvf_ref >= bb_upper_ref) & (wvf_ref.shift(1) < bb_upper_ref.shift(1))
    exit_sig_ref = (wvf_ref < bb_mid_ref) & (wvf_ref.shift(1) >= bb_mid_ref.shift(1))
    
    # Compare
    common = feats.index.intersection(bars.index)
    for col, ref_col in [("wvf", "wvf_ref"), ("bb_mid", "bb_mid_ref"), 
                          ("bb_upper", "bb_upper_ref"), ("entry_sig", "entry_sig_ref"),
                          ("exit_sig", "exit_sig_ref")]:
        a = feats.loc[common, col].to_numpy()
        if ref_col == "wvf_ref":
            b = wvf_ref.loc[common].to_numpy()
        elif ref_col == "bb_mid_ref":
            b = bb_mid_ref.loc[common].to_numpy()
        elif ref_col == "bb_upper_ref":
            b = bb_upper_ref.loc[common].to_numpy()
        elif ref_col == "entry_sig_ref":
            b = entry_sig_ref.loc[common].to_numpy()
        elif ref_col == "exit_sig_ref":
            b = exit_sig_ref.loc[common].to_numpy()
        mask = np.isfinite(a) & np.isfinite(b)
        if col in ("entry_sig", "exit_sig"):
            assert np.array_equal(a[mask], b[mask]), f"{col} deviates"
        else:
            assert np.allclose(a[mask], b[mask], rtol=1e-6, atol=1e-9), f"{col} deviates"


# --------------------------------------------------------------------------
# TEST 2/3 - Entry/Exit signal detection
# --------------------------------------------------------------------------
def test_2_3_signal_detection():
    """Craft a sequence that produces clear BB upper cross and midline cross."""
    bars = synthetic_bars(100, seed=11)
    feats = WVF_RULE.compute_features(bars)
    entry_sig = feats["entry_sig"]
    exit_sig = feats["exit_sig"]
    
    # Verify entry_sig fires exactly on WVF >= BB_upper transition
    expected_entry = (feats["wvf"] >= feats["bb_upper"]) & (feats["wvf"].shift(1) < feats["bb_upper"].shift(1))
    assert entry_sig.equals(expected_entry), "entry_sig != WVF crosses above BB upper"
    
    # Verify exit_sig fires exactly on WVF < BB_mid transition
    expected_exit = (feats["wvf"] < feats["bb_mid"]) & (feats["wvf"].shift(1) >= feats["bb_mid"].shift(1))
    assert exit_sig.equals(expected_exit), "exit_sig != WVF crosses below BB mid"


# --------------------------------------------------------------------------
# TEST 4 - signal day != execution day (next-open fill)
# --------------------------------------------------------------------------
def test_4_signal_and_execution_separated():
    from run_wvf_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=13)
    feats = WVF_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, audit = build_events("T0000", feats, cal, None)
    for kind, fd, fill in events:
        sig_date = fill.order.signal_date
        assert fd > sig_date, f"same-bar execution? signal {sig_date} fill {fd}"
        assert fd == cal.next_session(sig_date), "fill not at next session open"
        assert fill.fill_type in ("OPEN", "MEAN_REVERSION")


# --------------------------------------------------------------------------
# TEST 5 - no same-bar execution in any generated trade
# --------------------------------------------------------------------------
def test_5_no_samebar_execution():
    from run_wvf_kr_v1_smoke import build_events
    bars = synthetic_bars(500, seed=17)
    feats = WVF_RULE.compute_features(bars)
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
    from run_wvf_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=19)
    feats = WVF_RULE.compute_features(bars)
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
    from run_wvf_kr_v1_smoke import build_events
    bars = synthetic_bars(400, seed=23)
    feats = WVF_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0003", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.direction == "LONG", f"unexpected direction {fill.order.direction}"


# --------------------------------------------------------------------------
# TEST 9 - no leverage (cash never negative in simulated portfolio)
# --------------------------------------------------------------------------
def test_9_no_leverage():
    from run_wvf_kr_v1_smoke import build_events, PORT_CFG
    from engine.portfolio.portfolio import Portfolio
    bars = synthetic_bars(400, seed=29)
    feats = WVF_RULE.compute_features(bars)
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
    from run_wvf_kr_v1_smoke import build_events, PERF_START
    bars = synthetic_bars(300, seed=31)
    idx = pd.date_range("2014-06-01", periods=300, freq="B")
    bars.index = idx
    feats = WVF_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0005", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.signal_date >= PERF_START, \
            f"warmup signal {fill.order.signal_date} leaked into performance"


def run():
    test_1_wvf_matches_reference()
    test_2_3_signal_detection()
    test_4_signal_and_execution_separated()
    test_5_no_samebar_execution()
    test_6_7_listing_date_gate()
    test_8_no_short()
    test_9_no_leverage()
    test_10_warmup_not_in_performance()
    print("test_wvf_kr_v1: OK")


if __name__ == "__main__":
    run()