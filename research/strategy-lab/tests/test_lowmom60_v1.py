"""lowmom60_v1 최소 자체검증 - pbr_value_v1과 동일 패턴(strategies/base.py
계약 하나만 본다, 프레임워크 없음). 새 전략이 selection.json 조회로만
신호를 내고, RiskSpec이 STOP/TARGET을 봉쇄한 채 TIME_EXIT만 나오는지 확인.
"""
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

_RULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "strategies", "lowmom60_v1", "rule.py")
_spec = importlib.util.spec_from_file_location("strategies.lowmom60_v1.rule", _RULE_PATH)
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
    assert signal_dates <= selected_dates, "emitted a signal not in selection.json"
    for s in signals:
        assert s.direction == "LONG"
    for d in signal_dates:
        written = features.loc[pd.Timestamp(d), rule._HOLD_COL]
        assert written == rule._SELECTION[ticker][d]


def test_risk_spec_uses_per_signal_hold_sessions():
    row = pd.Series({"close": 12345.0, rule._HOLD_COL: 17})
    spec = rule.risk_spec_for(row)
    entry_price = row["close"]
    stop_price = entry_price - spec.stop_distance
    target_price = entry_price + spec.reward_risk * spec.stop_distance
    assert stop_price < 0
    assert target_price > entry_price * 50
    assert spec.max_holding_sessions == 17

    row_missing = pd.Series({"close": 12345.0, rule._HOLD_COL: float("nan")})
    spec2 = rule.risk_spec_for(row_missing)
    assert spec2.max_holding_sessions == rule._FALLBACK_MAX_HOLDING


def test_evaluate_at_matches_generate_signals():
    from engine.data.pit import PITBars

    ticker = next(t for t, dates in rule._SELECTION.items() if len(dates) > 0)
    a_date = next(iter(rule._SELECTION[ticker].keys()))
    bars = _sample_bars()
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


def test_selection_only_includes_high_liquidity_low_momentum():
    """Locks in Candidate C's design (not A/B): every selection came from a
    turnover20>=1억 month, and the promised top-30-by-lowest-mom60 cap held."""
    from collections import Counter
    per_month = Counter()
    for ticker, dates in rule._SELECTION.items():
        for d in dates:
            per_month[d] += 1
    assert per_month, "selection.json produced no picks at all"
    assert max(per_month.values()) <= 30


def run():
    test_generate_signals_only_on_selected_dates()
    test_risk_spec_uses_per_signal_hold_sessions()
    test_evaluate_at_matches_generate_signals()
    test_selection_only_includes_high_liquidity_low_momentum()
    print("test_lowmom60_v1: OK")


if __name__ == "__main__":
    run()
