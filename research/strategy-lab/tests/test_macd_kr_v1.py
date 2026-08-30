"""MACD-KR-V1 unit / invariant tests (STEP 2, section 14).

Covers TEST 1-10. Fast, synthetic bars where possible; one real-data reference
comparison for TEST 1.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

import numpy as np
import pandas as pd

from strategies.macd_kr_v1 import rule as MACD_RULE
from engine.data.calendar import TradingCalendar
from engine.execution.contracts import Order, Fill

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))
FAST, SLOW, SIGNAL = 12, 26, 9


def synthetic_bars(n=260, seed=7):
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


def _close_series_for_dates(dates, vals):
    return pd.Series(vals, index=pd.DatetimeIndex(dates))


# --------------------------------------------------------------------------
# TEST 1 - MACD matches the repository reference implementation
# --------------------------------------------------------------------------
def test_1_macd_matches_reference():
    # reference: macd_information_content_study.macd_from_close_series
    from macd_information_content_study import macd_from_close_series
    close = synthetic_bars(300, seed=3)["close"]
    # build a reference from a Series (same convention, ewm span adjust=False)
    ref = macd_from_close_series(close)
    ref_ser = ref.set_index(pd.to_datetime(ref["date"]))

    mine = MACD_RULE.macd_from_close(close)
    # compare on rows where both are defined (skip first swing for warmup stability)
    common = mine.index.intersection(ref_ser.index)
    for col, ref_col in (("macd", "macd"), ("signal", "signal"), ("hist", "hist")):
        a = mine.loc[common, col].to_numpy()
        b = ref_ser.loc[common, ref_col].to_numpy()
        assert np.allclose(a[5:], b[5:], rtol=1e-6, atol=1e-9), f"{col} deviates"


# --------------------------------------------------------------------------
# TEST 2/3 - crossover detection
# --------------------------------------------------------------------------
def test_2_3_cross_detection():
    # craft hist: ... flat up-then flat ... to produce one clear bullish and
    # one clear bearish cross
    hist = pd.Series([-1.0, -1.0, -0.5, 2.0, 1.0, 0.5, 0.0, -1.0, -1.0, 3.0],
                     index=pd.date_range("2020-01-01", periods=10, freq="B"))
    bull, bear = MACD_RULE.cross_series(hist)
    assert bool(bull.iloc[3]) is True      # -0.5 -> 2.0 : bullish cross
    assert bool(bull.iloc[9]) is True  # -1.0 -> 3.0 : bullish cross
    assert bool(bear.iloc[7]) is True      # 0.0 -> -1.0 : bearish cross
    assert bull.iloc[[0, 1, 2, 4, 5, 6, 7, 8]].sum() == 0
    assert bear.iloc[[0, 1, 2, 3, 4, 5, 6, 8, 9]].sum() == 0


def test_2_no_double_count_floor():
    # a single transition 0 -> + is one bullish signal, not two
    hist = pd.Series([1.0, 1.0, 1.0, -1.0], index=pd.date_range("2020-01-01", periods=4, freq="B"))
    # +1 held for 3 bars: at bar idx0 it's already >0 with prev NaN (False warmup)
    bull, _ = MACD_RULE.cross_series(hist)
    assert not bull.iloc[0]          # warmup (prev NaN) - no signal
    assert not bull.iloc[1]          # still >0, no cross
    assert not bull.iloc[2]


# --------------------------------------------------------------------------
# TEST 4 - signal day != execution day (next-open fill)
# --------------------------------------------------------------------------
def test_4_signal_and_execution_separated():
    from run_macd_kr_v1_smoke import build_events, COST
    bars = synthetic_bars(300, seed=11)
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, audit = build_events("T0000", feats, cal, None)  # no listing gate
    for kind, fd, fill in events:
        sig_date = fill.order.signal_date
        assert fd > sig_date, f"same-bar execution? signal {sig_date} fill {fd}"
        assert fd == cal.next_session(sig_date), "fill not at next session open"
        assert fill.fill_type == "OPEN" if kind == "ENTRY" else fill.fill_type == "CROSSOVER"


# --------------------------------------------------------------------------
# TEST 5 - no same-bar execution in any generated trade
# --------------------------------------------------------------------------
def test_5_no_samebar_execution():
    from run_macd_kr_v1_smoke import build_events
    bars = synthetic_bars(500, seed=13)
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0001", feats, cal, None)
    entries = [(fd, f) for k, fd, f in events if k == "ENTRY"]
    exits = [(fd, f) for k, fd, f in events if k == "EXIT"]
    assert entries and exits, "test needs at least one complete cycle"
    # every exit fill date is strictly after the matching entry fill date
    for (efd, _ef), (xfd, _xf) in zip(entries, exits):
        assert xfd > efd, f"same-bar exit {xfd} <= entry {efd}"


# --------------------------------------------------------------------------
# TEST 6/7 - listing-date PIT gate: no signal / no position before listedAt
# --------------------------------------------------------------------------
def test_6_7_listing_date_gate():
    from run_macd_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=17)
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    mid = feats.index[len(feats) // 2].strftime("%Y-%m-%d")  # lists midway

    # with a listing gate in the future relative to early bars
    events, audit = build_events("T0002", feats, cal, "9999-12-31")
    assert audit["pre_listing_signals"] > 0, "expected early bullish signals to be gated out"
    assert not events, "no entry/exit event should exist when all signals pre-listing"

    # with a gate in the past, signals are allowed
    events2, audit2 = build_events("T0002", feats, cal, "2010-01-01")
    # total bullish cross minus gated (none gated here) should equal entry attempts
    assert audit2["pre_listing_signals"] == 0


# --------------------------------------------------------------------------
# TEST 8 - no short positions
# --------------------------------------------------------------------------
def test_8_no_short():
    from run_macd_kr_v1_smoke import build_events
    bars = synthetic_bars(400, seed=19)
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0003", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.direction == "LONG", f"unexpected direction {fill.order.direction}"


# --------------------------------------------------------------------------
# TEST 9 - no leverage
# --------------------------------------------------------------------------
def test_9_no_leverage():
    from run_macd_kr_v1_smoke import build_events, PORT_CFG
    from engine.portfolio.portfolio import Portfolio
    bars = synthetic_bars(400, seed=23)
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0004", feats, cal, None)
    # drive a portfolio for one ticker max_positions=1 and assert it never goes
    # cash-negative (leverage would imply buying more than cash)
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
# TEST 10 - MACD warm-up not included in performance
# --------------------------------------------------------------------------
def test_10_warmup_not_in_performance():
    from run_macd_kr_v1_smoke import build_events, PERF_START
    bars = synthetic_bars(300, seed=29)
    # shift dates so the series starts BEFORE perf_start (raw data pre-2016)
    idx = pd.date_range("2014-06-01", periods=300, freq="B")
    bars.index = idx
    feats = MACD_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0005", feats, cal, None)
    # all generated signals must be >= perf_start (warmup signals dropped)
    for k, fd, fill in events:
        assert fill.order.signal_date >= PERF_START, \
            f"warmup signal {fill.order.signal_date} leaked into performance"


def run():
    test_1_macd_matches_reference()
    test_2_3_cross_detection()
    test_2_no_double_count_floor()
    test_4_signal_and_execution_separated()
    test_5_no_samebar_execution()
    test_6_7_listing_date_gate()
    test_8_no_short()
    test_9_no_leverage()
    test_10_warmup_not_in_performance()
    print("test_macd_kr_v1: OK")


if __name__ == "__main__":
    run()
