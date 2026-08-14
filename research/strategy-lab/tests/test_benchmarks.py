import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from benchmarks import b0_buy_hold, b1_bb_only, b2_cci_only  # noqa: E402


def _bars(n=40):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "open": [100] * n, "high": [101] * n, "low": [99] * n,
        "close": [100] * n, "volume": [1000] * n,
    }, index=dates)


def test_b1_fires_only_on_the_crossing_day_not_every_day_above():
    dates = pd.date_range("2024-01-01", periods=25, freq="D")
    closes = [100] * 20 + [90, 92, 95, 110, 111]  # dips then rises and stays above bb_mid for 2 days
    bars = pd.DataFrame({
        "open": closes, "high": [c + 1 for c in closes], "low": [c - 1 for c in closes],
        "close": closes, "volume": [1000] * 25,
    }, index=dates)
    features = b1_bb_only.compute_features(bars)
    signals = b1_bb_only.generate_signals("X", features)
    signal_dates = {s.signal_date for s in signals}
    # close[23]=110 crosses above bb_mid (falling series pulled bb_mid down); close[24]=111
    # stays above but is NOT a new crossing - must not both fire
    assert len(signal_dates) <= 1, f"edge-trigger must not repeat on consecutive above-days: {signal_dates}"


def test_b2_matches_core_cci_condition_only():
    bars = _bars(40)
    bars.loc[bars.index[20], "close"] = 70  # engineer a dip/recovery-ish wiggle
    bars.loc[bars.index[21], "close"] = 130
    features = b2_cci_only.compute_features(bars)
    signals = b2_cci_only.generate_signals("X", features)
    # every returned signal date must independently satisfy the CCI-only condition
    for s in signals:
        ts = pd.Timestamp(s.signal_date)
        row = features.loc[ts]
        idx = features.index.get_loc(ts)
        prev = features.iloc[idx - 1]
        assert prev["cci"] <= -100 and row["cci"] > -100


def test_b0_trades_and_costs():
    bars_by_ticker = {
        "000001": pd.DataFrame({"close": [100.0, 110.0, 120.0]},
                                index=pd.date_range("2024-01-01", periods=3, freq="D")),
        "000002": pd.DataFrame({"close": [50.0, 55.0]},
                                index=pd.date_range("2024-01-02", periods=2, freq="D")),
    }
    trades, alloc = b0_buy_hold.compute_trades(bars_by_ticker, initial_capital=1_000_000,
                                                entry_cost_bps=15, exit_cost_bps=15)
    assert len(trades) == 2
    assert alloc == 500_000
    t1 = next(t for t in trades if t["symbol"] == "000001")
    assert t1["entry_price"] == 100.0 and t1["exit_price"] == 120.0
    expected_shares = int(500_000 // (100.0 * 1.0015))
    assert t1["shares"] == expected_shares
    expected_cost_basis = 100.0 * expected_shares * 1.0015
    assert abs(t1["cost_basis"] - expected_cost_basis) < 1e-6


def run():
    test_b1_fires_only_on_the_crossing_day_not_every_day_above()
    test_b2_matches_core_cci_condition_only()
    test_b0_trades_and_costs()
    print("test_benchmarks: OK")


if __name__ == "__main__":
    run()
