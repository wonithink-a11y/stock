"""pbr_value_v1 최소 자체검증 - 새 전략이 selection.json 조회로만 신호를
내고, RiskSpec이 STOP/TARGET을 봉쇄한 채 TIME_EXIT만 나오는지 확인한다.
프레임워크 없음, 이 전략 하나의 계약만 본다.
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

_RULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "strategies", "pbr_value_v1", "rule.py")
_spec = importlib.util.spec_from_file_location("strategies.pbr_value_v1.rule", _RULE_PATH)
rule = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rule)


def _sample_bars():
    dates = pd.date_range("2016-01-04", periods=40, freq="B")
    return pd.DataFrame({
        "open": [10000.0] * 40, "high": [10100.0] * 40,
        "low": [9900.0] * 40, "close": [10000.0] * 40, "volume": [100000] * 40,
    }, index=dates)


def test_generate_signals_only_on_selected_dates():
    ticker = next(iter(rule._SELECTION.keys()))
    selected_dates = set(rule._SELECTION[ticker].keys())
    bars = _sample_bars()
    features = rule.compute_features(bars)
    assert rule._HOLD_COL in features.columns
    signals = rule.generate_signals(ticker, features)
    signal_dates = {s.signal_date for s in signals}
    # bars covers only 40 business days from 2016-01-04 - only selected dates
    # inside that window should produce a signal, and every signal date must
    # be one of the ticker's precomputed selected dates.
    assert signal_dates <= selected_dates, "emitted a signal not in selection.json"
    for s in signals:
        assert s.direction == "LONG"
    # generate_signals must have written the exact holdSessions into features
    # in place, at each signal date (this is what risk_spec_for reads later).
    for d in signal_dates:
        written = features.loc[pd.Timestamp(d), rule._HOLD_COL]
        assert written == rule._SELECTION[ticker][d]


def test_risk_spec_uses_per_signal_hold_sessions():
    row = pd.Series({"close": 12345.0, rule._HOLD_COL: 17})
    spec = rule.risk_spec_for(row)
    entry_price = row["close"]
    stop_price = entry_price - spec.stop_distance
    target_price = entry_price + spec.reward_risk * spec.stop_distance
    # a stop this far negative, and a target this far above, must be
    # unreachable by any realistic daily low/high - proves TIME_EXIT is the
    # only possible outcome, matching policy.json's risk.note.
    assert stop_price < 0
    assert target_price > entry_price * 50
    assert spec.max_holding_sessions == 17  # read from the row, not the fallback

    row_missing = pd.Series({"close": 12345.0, rule._HOLD_COL: float("nan")})
    spec2 = rule.risk_spec_for(row_missing)
    assert spec2.max_holding_sessions == rule._FALLBACK_MAX_HOLDING


def test_evaluate_at_matches_generate_signals():
    from engine.data.pit import PITBars

    ticker = next(t for t, dates in rule._SELECTION.items() if len(dates) > 0)
    a_date = next(iter(rule._SELECTION[ticker].keys()))
    bars = _sample_bars()
    # reindex bars to include the actual selected date so PITBars.at() can find it
    bars = pd.concat([bars, pd.DataFrame(
        {"open": [10000.0], "high": [10100.0], "low": [9900.0], "close": [10000.0], "volume": [100000]},
        index=[pd.Timestamp(a_date)],
    )]).sort_index()
    pit = PITBars(bars, pd.Timestamp(a_date))
    sig = rule.evaluate_at(pit, ticker, a_date, None)
    assert sig is not None
    assert sig.symbol == ticker and sig.signal_date == a_date

    non_selected_date = "1999-01-01"
    sig2 = rule.evaluate_at(pit, ticker, non_selected_date, None)
    assert sig2 is None


def run():
    test_generate_signals_only_on_selected_dates()
    test_risk_spec_uses_per_signal_hold_sessions()
    test_evaluate_at_matches_generate_signals()
    print("test_pbr_value_v1: OK")


if __name__ == "__main__":
    run()
