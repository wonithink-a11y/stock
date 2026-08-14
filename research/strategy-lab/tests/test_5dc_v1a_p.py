"""5DC-v1A-P contract tests. Where a condition (BB, CCI) needs to be isolated
from the other, a synthetic *features* frame is fed directly to the internal
boolean function rather than hand-crafting OHLC that happens to produce exact
indicator values - the indicator formulas themselves are already covered by
Phase 2's causality tests. Where the test is about wiring (entry timing,
stop/target, tie-break), real OHLC + the real engine pieces are used together,
matching how the smoke run actually exercises the strategy.
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
                           "strategies", "5dc_v1a_p", "rule.py")
_spec = importlib.util.spec_from_file_location("strategies.5dc_v1a_p.rule", _RULE_PATH)
rule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rule)


def _features(rows):
    """rows: [(date, close, bb_mid, cci)]"""
    df = pd.DataFrame(rows, columns=["date", "close", "bb_mid", "cci"]).set_index("date")
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


def test_bb_trend_condition_isolated():
    # CCI condition held true throughout; only close-vs-bb_mid varies
    f = _features([
        ("d1", 100, 105, -101), ("d2", 100, 105, -50),   # close < bb_mid -> no signal even though CCI recovered
        ("d3", 110, 105, -101), ("d4", 110, 105, -50),   # close > bb_mid -> signal on d4
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == False  # noqa: E712
    assert raw["d4"] == True  # noqa: E712


def test_cci_minus_100_recovery_condition_isolated():
    # BB condition held true throughout; only the CCI crossing varies
    f = _features([
        ("d1", 110, 100, -60), ("d2", 110, 100, -30),    # never <= -100 -> no recovery
        ("d3", 110, 100, -101), ("d4", 110, 100, -99),   # -101 <= -100 then -99 > -100 -> recovery
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == False  # noqa: E712
    assert raw["d4"] == True  # noqa: E712


def test_false_signal_rejection():
    f = _features([
        ("d1", 110, 100, -101),
        ("d2", 110, 100, -100),   # -100 > -100 is False - boundary must NOT fire
        ("d3", 90, 100, -50),     # close < bb_mid, even with a real CCI recovery on this row alone
    ])
    raw = rule._raw_signal_series(f)
    assert raw["d2"] == False  # noqa: E712
    assert raw["d3"] == False  # noqa: E712


def test_insufficient_warmup_produces_no_signals():
    dates = pd.date_range("2024-01-01", periods=15, freq="D")  # < 20-bar BB/CCI warmup
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
        "open": [100] * 25 + [90] * 10 + [100] * 5,
        "high": [101] * 25 + [92] * 10 + [102] * 5,
        "low": [99] * 25 + [80] * 10 + [99] * 5,
        "close": [100] * 25 + [85] * 10 + [110] * 5,
        "volume": [1000] * 40,
    }, index=dates)
    features = rule.compute_features(bars)
    signals = rule.generate_signals("000001", features)
    assert all(s.direction == "LONG" for s in signals)


def test_next_session_entry_and_3r_target_and_stop_via_5dc_wiring():
    cal = FakeCalendar()
    atr_row = pd.Series({"atr": 5.0})
    risk = rule.risk_spec_for(atr_row)  # stop_distance = 10
    from engine.signals.schema import Signal
    signal = Signal(symbol="X", signal_date=cal.days[0], direction="LONG")
    order = build_order(signal, risk, cal)
    assert order.order_date == cal.days[1]

    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 100, 132, 99, 130)]
    bars = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert entry.fill_price == 100
    assert exit_.fill_type == "TARGET"
    assert exit_.fill_price == 100 + 3 * 10  # entry + 3 * stop_distance, RR=3.0


def test_same_bar_stop_first_via_5dc_wiring():
    cal = FakeCalendar()
    risk = rule.risk_spec_for(pd.Series({"atr": 5.0}))  # stop_distance=10
    order = Order("X", cal.days[0], cal.days[1], "LONG", risk)
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 100, 135, 85, 100)]
    bars = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    _, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "STOP"


def test_gap_through_stop_via_5dc_wiring():
    cal = FakeCalendar()
    risk = rule.risk_spec_for(pd.Series({"atr": 5.0}))  # stop_distance=10, stop=90
    order = Order("X", cal.days[0], cal.days[1], "LONG", risk)
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 80, 82, 78, 81)]
    bars = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    _, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "STOP"
    assert exit_.fill_price == 80


def test_60th_session_time_exit_via_5dc_wiring():
    cal = FakeCalendar(n=80)
    risk = rule.risk_spec_for(pd.Series({"atr": 5.0}))  # max_holding_sessions=60
    assert risk.max_holding_sessions == 60
    order = Order("X", cal.days[0], cal.days[1], "LONG", risk)
    window = cal.sessions_between(cal.days[1], cal.days[-1])[:60]
    rows = [(d, 100, 105, 95, 100) for d in window]  # never touches stop(90) or target(130)
    bars = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    _, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "TIME_EXIT"
    assert exit_.fill_date == window[-1]


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
        "open": [100] * 25 + [90] * 10 + [100] * 5,
        "high": [101] * 25 + [92] * 10 + [102] * 5,
        "low": [99] * 25 + [80] * 10 + [99] * 5,
        "close": [100] * 25 + [85] * 10 + [110] * 5,
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
    test_bb_trend_condition_isolated()
    test_cci_minus_100_recovery_condition_isolated()
    test_false_signal_rejection()
    test_insufficient_warmup_produces_no_signals()
    test_atr_fixed_stop_distance()
    test_long_only()
    test_next_session_entry_and_3r_target_and_stop_via_5dc_wiring()
    test_same_bar_stop_first_via_5dc_wiring()
    test_gap_through_stop_via_5dc_wiring()
    test_60th_session_time_exit_via_5dc_wiring()
    test_deterministic_tie_break()
    test_pit_violation_on_evaluate_at()
    test_evaluate_at_agrees_with_generate_signals()
    print("test_5dc_v1a_p: OK")


if __name__ == "__main__":
    run()
