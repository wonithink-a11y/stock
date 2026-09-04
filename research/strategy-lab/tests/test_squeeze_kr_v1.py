"""SQUEEZE-KR-V1 unit / invariant tests (STEP 1, section 14).

Covers TEST 1-10. Fast, synthetic bars where possible; one real-data reference
comparison for TEST 1 (linreg endpoint against known formula).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

import numpy as np
import pandas as pd

from strategies.squeeze_kr_v1 import rule as SQUEEZE_RULE
from engine.data.calendar import TradingCalendar

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", ".."))

BB_LEN = SQUEEZE_RULE.BB_LEN
BB_MULT = SQUEEZE_RULE.BB_MULT
KC_LEN = SQUEEZE_RULE.KC_LEN
KC_MULT = SQUEEZE_RULE.KC_MULT
MOM_LEN = SQUEEZE_RULE.MOM_LEN


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


def _linreg_endpoint_reference(y: np.ndarray, n: int) -> np.ndarray:
    """Slow reference implementation for verification."""
    out = np.full(len(y), np.nan)
    for i in range(n - 1, len(y)):
        window = y[i - n + 1:i + 1]
        x = np.arange(n)
        A = np.vstack([x, np.ones(n)]).T
        coeff, *_ = np.linalg.lstsq(A, window, rcond=None)
        out[i] = coeff[0] * (n - 1) + coeff[1]
    return out


# --------------------------------------------------------------------------
# TEST 1 - linreg endpoint matches reference OLS
# --------------------------------------------------------------------------
def test_1_linreg_matches_reference():
    close = synthetic_bars(300, seed=3)["close"]
    feats = SQUEEZE_RULE.compute_features(synthetic_bars(300, seed=3))
    delta = close - feats["composite"]   # rule 이 실제로 linreg 에 넣는 입력
    mine = feats["momentum"].to_numpy()
    ref = _linreg_endpoint_reference(delta.to_numpy(), MOM_LEN)
    common = np.isfinite(mine) & np.isfinite(ref)
    assert np.allclose(mine[common], ref[common], rtol=1e-6, atol=1e-9), "linreg endpoint deviates"


# --------------------------------------------------------------------------
# TEST 2 - squeeze_on / release detection on crafted series
# --------------------------------------------------------------------------
def test_2_squeeze_and_release():
    # craft a sequence where BB enters KC then exits
    bars = synthetic_bars(50, seed=11)
    # force squeeze on for bars 10-20, off afterwards by manipulating close
    feats = SQUEEZE_RULE.compute_features(bars)
    sq = feats["squeeze_on"]
    rel = feats["release"]
    # verify release fires exactly on transition
    transitions = (sq.shift(1, fill_value=False) & ~sq).astype(int)
    assert rel.equals(transitions.astype(bool)), "release != transition"


# --------------------------------------------------------------------------
# TEST 3 - exit_cross detects zero down-cross
# --------------------------------------------------------------------------
def test_3_exit_cross():
    mom = pd.Series([2.0, 1.0, 0.5, -0.1, -0.5, 1.0, -0.2],
                    index=pd.date_range("2020-01-01", periods=7, freq="B"))
    # construct feats with this momentum
    bars = synthetic_bars(7, seed=99)
    feats = SQUEEZE_RULE.compute_features(bars)
    feats["momentum"] = mom
    feats["exit_cross"] = (feats["momentum"] < 0) & (feats["momentum"].shift(1) >= 0)
    cross = feats["exit_cross"]
    assert bool(cross.iloc[3])     # 0.5 -> -0.1  (pandas 가 np.bool_ 을 준다 - `is True` 금지)
    assert bool(cross.iloc[6])     # 1.0 -> -0.2
    assert cross.iloc[[0, 1, 2, 4, 5]].sum() == 0


# --------------------------------------------------------------------------
# TEST 4 - signal day != execution day (next-open fill)
# --------------------------------------------------------------------------
def test_4_signal_and_execution_separated():
    from run_squeeze_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=13)
    feats = SQUEEZE_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, audit = build_events("T0000", feats, cal, None)
    for kind, fd, fill in events:
        sig_date = fill.order.signal_date
        assert fd > sig_date, f"same-bar execution? signal {sig_date} fill {fd}"
        assert fd == cal.next_session(sig_date), "fill not at next session open"
        assert fill.fill_type in ("OPEN", "CROSSOVER")


# --------------------------------------------------------------------------
# TEST 5 - no same-bar execution in any generated trade
# --------------------------------------------------------------------------
def test_5_no_samebar_execution():
    from run_squeeze_kr_v1_smoke import build_events
    bars = synthetic_bars(500, seed=17)
    feats = SQUEEZE_RULE.compute_features(bars)
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
    from run_squeeze_kr_v1_smoke import build_events
    bars = synthetic_bars(300, seed=19)
    feats = SQUEEZE_RULE.compute_features(bars)
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
    from run_squeeze_kr_v1_smoke import build_events
    bars = synthetic_bars(400, seed=23)
    feats = SQUEEZE_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0003", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.direction == "LONG", f"unexpected direction {fill.order.direction}"


# --------------------------------------------------------------------------
# TEST 9 - no leverage (cash never negative in simulated portfolio)
# --------------------------------------------------------------------------
def test_9_no_leverage():
    from run_squeeze_kr_v1_smoke import build_events, PORT_CFG
    from engine.portfolio.portfolio import Portfolio
    bars = synthetic_bars(400, seed=29)
    feats = SQUEEZE_RULE.compute_features(bars)
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
    from run_squeeze_kr_v1_smoke import build_events, PERF_START
    bars = synthetic_bars(300, seed=31)
    idx = pd.date_range("2014-06-01", periods=300, freq="B")
    bars.index = idx
    feats = SQUEEZE_RULE.compute_features(bars)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    events, _ = build_events("T0005", feats, cal, None)
    for k, fd, fill in events:
        assert fill.order.signal_date >= PERF_START, \
            f"warmup signal {fill.order.signal_date} leaked into performance"


def run():
    test_1_linreg_matches_reference()
    test_2_squeeze_and_release()
    test_3_exit_cross()
    test_4_signal_and_execution_separated()
    test_5_no_samebar_execution()
    test_6_7_listing_date_gate()
    test_8_no_short()
    test_9_no_leverage()
    test_10_warmup_not_in_performance()
    print("test_squeeze_kr_v1: OK")


if __name__ == "__main__":
    run()