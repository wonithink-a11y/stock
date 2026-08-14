"""TREND-BREAKOUT-v1 contract tests. Where a condition (edge-trigger) needs to
be isolated, a synthetic *features* frame is fed directly to the internal
boolean function, same approach as tests/test_5dc_v1a_p.py - the indicator
formula itself (lookahead, double-shift) is already covered by
tests/test_donchian.py. Where the test is about wiring (entry timing,
stop/target), real OHLC + the real engine pieces are used together.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.data.pit import PITBars, PITViolation
from engine.execution.contracts import Order
from engine.execution.executor import CostModel, build_order, simulate_trade
from engine.portfolio.portfolio import Portfolio, PortfolioConfig

import importlib.util

_RULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "strategies", "trend_breakout_v1", "rule.py")
_spec = importlib.util.spec_from_file_location("strategies.trend_breakout_v1.rule", _RULE_PATH)
rule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rule)


def _features(rows):
    """rows: [(date, close, donchian_high)]"""
    df = pd.DataFrame(rows, columns=["date", "close", "donchian_high"]).set_index("date")
    df["open"] = df["close"]
    df["high"] = df["close"]
    df["low"] = df["close"]
    df["atr"] = 5.0
    return df


class FakeCalendar:
    def __init__(self, n=80):
        self.days = [f"2024-01-{d:02d}" if d <= 31 else f"2024-02-{d - 31:02d}" for d in range(1, n + 1)]

    def next_session(self, date):
        i = self.days.index(date) if date in self.days else -1
        return self.days[i + 1] if 0 <= i < len(self.days) - 1 else None

    def sessions_between(self, start, end):
        return [d for d in self.days if start <= d <= end]

    def next_n_sessions(self, start, n):
        return [d for d in self.days if d >= start][:n]


def test_edge_triggered_breakout_isolated():
    # edge-triggered: only the day the close first crosses above the channel fires
    f = _features([
        ("d1", 100, 105),  # below channel
        ("d2", 100, 105),  # still below -> no signal
        ("d3", 110, 105),  # crosses above -> signal on d3
        ("d4", 110, 105),  # still above -> NOT a new signal (level condition would wrongly re-fire)
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == False  # noqa: E712
    assert raw["d3"] == True  # noqa: E712
    assert raw["d4"] == False  # noqa: E712


def test_boundary_equal_is_not_breakout():
    f = _features([
        ("d1", 100, 105),
        ("d2", 105, 105),  # close == channel -> not a breakout (strict >)
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == False  # noqa: E712


def test_re_breakout_after_pullback_fires_again():
    # falling back below the channel and breaking out again is a new event
    f = _features([
        ("d1", 100, 105), ("d2", 110, 105),  # breakout 1 on d2
        ("d3", 100, 105), ("d4", 110, 105),  # pullback below, breakout 2 on d4
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == True  # noqa: E712
    assert raw["d4"] == True  # noqa: E712


def test_insufficient_warmup_produces_no_signals():
    dates = pd.date_range("2024-01-01", periods=15, freq="D")  # < donchian period(20)+1 warmup
    bars = pd.DataFrame({
        "open": range(100, 115), "high": range(101, 116),
        "low": range(99, 114), "close": range(100, 115), "volume": [1000] * 15,
    }, index=dates)
    features = rule.compute_features(bars)
    signals = rule.generate_signals("000001", features)
    assert signals == []


def test_atr_fixed_stop_distance():
    row = pd.Series({"atr": 7.5})
    risk = rule.risk_spec_for(row)
    assert risk.stop_distance == 15.0  # 2 * ATR[t], contract-fixed multiple
    assert risk.reward_risk == 3.0
    assert risk.max_holding_sessions == 60


def test_long_only():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    bars = pd.DataFrame({
        "open": [100] * 25 + [150] * 15,
        "high": [101] * 25 + [151] * 15,
        "low": [99] * 25 + [149] * 15,
        "close": [100] * 25 + [150] * 15,
        "volume": [1000] * 40,
    }, index=dates)
    features = rule.compute_features(bars)
    signals = rule.generate_signals("000001", features)
    assert len(signals) >= 1
    assert all(s.direction == "LONG" for s in signals)


def test_next_session_entry_and_3r_target_and_stop_via_wiring():
    cal = FakeCalendar()
    atr_row = pd.Series({"atr": 5.0})
    risk = rule.risk_spec_for(atr_row)  # stop_distance = 10
    from engine.signals.schema import Signal
    signal = Signal(symbol="X", signal_date=cal.days[0], direction="LONG")
    order = build_order(signal, risk, cal)
    assert order.order_date == cal.days[1]  # signal t -> entry at next session's open

    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 100, 132, 99, 130)]
    bars = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert entry.fill_price == 100  # entry at next session's Open
    assert exit_.fill_type == "TARGET"
    assert exit_.fill_price == 100 + 3 * 10  # entry + 3 * stop_distance, RR=3.0


def test_deterministic_tie_break():
    assert rule.TIE_BREAK == "ticker_ascending"
    cfg = PortfolioConfig(initial_capital=100_000_000, max_positions=10, tie_break=rule.TIE_BREAK)
    pf = Portfolio(cfg)
    from engine.execution.contracts import Fill
    candidates = []
    for i in range(15):
        o = Order(f"{i:06d}", "2024-01-01", "2024-01-02", "LONG", rule.risk_spec_for(pd.Series({"atr": 5.0})))
        candidates.append((o, Fill(o, "2024-01-02", 10_000, "OPEN", 15.0, 0.0)))
    pf.process_day("2024-01-02", [], candidates)
    assert set(pf.open_positions.keys()) == {f"{i:06d}" for i in range(10)}


def test_pit_violation_on_evaluate_at():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    bars = pd.DataFrame({
        "open": range(100, 130), "high": range(101, 131),
        "low": range(99, 129), "close": range(100, 130), "volume": [1000] * 30,
    }, index=dates)
    features = rule.compute_features(bars)
    as_of = features.index[20]
    pit_features = PITBars(features, as_of)
    future_date = features.index[25].strftime("%Y-%m-%d")
    prev_date = features.index[24].strftime("%Y-%m-%d")
    try:
        rule.evaluate_at(pit_features, "000001", future_date, prev_date)
        raise AssertionError("expected PITViolation")
    except PITViolation:
        pass


def test_evaluate_at_agrees_with_generate_signals():
    """The PIT-guarded path and the bulk path implement the identical formula -
    cross-check them against each other on the same (legitimate, non-future) data."""
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    bars = pd.DataFrame({
        "open": [100] * 25 + [150] * 15,
        "high": [101] * 25 + [151] * 15,
        "low": [99] * 25 + [149] * 15,
        "close": [100] * 25 + [150] * 15,
        "volume": [1000] * 40,
    }, index=dates)
    features = rule.compute_features(bars)
    bulk_signals = {s.signal_date for s in rule.generate_signals("000001", features)}

    as_of = features.index[-1]
    pit_features = PITBars(features, as_of)
    pit_signals = set()
    for i in range(1, len(features)):
        d, prev_d = features.index[i].strftime("%Y-%m-%d"), features.index[i - 1].strftime("%Y-%m-%d")
        sig = rule.evaluate_at(pit_features, "000001", d, prev_d)
        if sig:
            pit_signals.add(sig.signal_date)
    assert bulk_signals == pit_signals


def run():
    test_edge_triggered_breakout_isolated()
    test_boundary_equal_is_not_breakout()
    test_re_breakout_after_pullback_fires_again()
    test_insufficient_warmup_produces_no_signals()
    test_atr_fixed_stop_distance()
    test_long_only()
    test_next_session_entry_and_3r_target_and_stop_via_wiring()
    test_deterministic_tie_break()
    test_pit_violation_on_evaluate_at()
    test_evaluate_at_agrees_with_generate_signals()
    print("test_trend_breakout_v1: OK")


if __name__ == "__main__":
    run()
