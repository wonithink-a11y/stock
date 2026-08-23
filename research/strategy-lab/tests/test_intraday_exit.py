"""Covers engine/execution/intraday_exit.py — CAND1의 09:35 청산 확장.

기존 engine/execution/executor.py(STOP/TARGET/TIME_EXIT)는 이 파일이
건드리지 않는다 — intraday_exit.py는 그 경로를 호출하지 않는 완전히
분리된 모듈이라 여기서도 별도로 테스트한다.

두 계층으로 나눈다:
  1) 합성 데이터로 PIT/결측/공식 성질을 검증(네트워크·원본 데이터 불요)
  2) 실제 MinuteProvider로 timestamp/tz/09:35 존재 여부의 실제 semantics만
     가볍게 확인(한 종목·하루, 무거운 스캔 아님)
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.execution.executor import CostModel  # noqa: E402
from engine.execution.intraday_exit import (  # noqa: E402
    resolve_intraday_price, simulate_intraday_exit_trade, trade_return,
)


def _minute_df(rows):
    """rows: [(hhmm, close), ...] -> tz-aware ts 인덱스 DataFrame(2026-01-05 기준)."""
    idx = pd.to_datetime(["2026-01-05 %s:00+09:00" % h for h, _ in rows])
    return pd.DataFrame({
        "open": [c for _, c in rows], "high": [c for _, c in rows],
        "low": [c for _, c in rows], "close": [c for _, c in rows],
        "volume": [100] * len(rows),
    }, index=idx)


# ---------------- 1) 합성 데이터 ----------------

def test_resolve_exact_minute_match():
    df = _minute_df([("09:33", 100.0), ("09:34", 101.0), ("09:35", 102.0),
                      ("09:36", 103.0)])
    assert resolve_intraday_price(df, "09:35") == 102.0


def test_resolve_missing_tick_returns_none_not_fabricated():
    """09:35 틱이 아예 없으면 앞뒤 값으로 보간하지 않고 None."""
    df = _minute_df([("09:33", 100.0), ("09:34", 101.0), ("09:36", 103.0)])
    assert resolve_intraday_price(df, "09:35") is None


def test_resolve_empty_frame_returns_none():
    assert resolve_intraday_price(pd.DataFrame(), "09:35") is None
    assert resolve_intraday_price(None, "09:35") is None


def test_pit_result_unaffected_by_removing_later_bars():
    """PIT 핵심 성질: 09:35 이후 봉이 있든 없든 09:35 조회 결과는 같아야
    한다 — resolve_intraday_price가 그 이후 봉을 읽거나 필요로 하지
    않는다는 걸 직접 증명한다."""
    with_future = _minute_df([("09:35", 102.0), ("09:36", 103.0),
                              ("09:40", 110.0), ("15:30", 120.0)])
    without_future = _minute_df([("09:35", 102.0)])
    a = resolve_intraday_price(with_future, "09:35")
    b = resolve_intraday_price(without_future, "09:35")
    assert a == b == 102.0


def test_simulate_trade_builds_expected_fills():
    df = _minute_df([("09:35", 102.0)])
    cost = CostModel(entry_cost_bps=10.0, exit_cost_bps=10.0, slippage_bps=0.0)
    result = simulate_intraday_exit_trade(
        symbol="005930", signal_date="2026-01-04", entry_date="2026-01-05",
        entry_price=100.0, minute_bars_on_entry_date=df, cost_model=cost)
    assert result is not None
    entry_fill, exit_fill = result
    assert entry_fill.fill_price == 100.0
    assert entry_fill.fill_type == "OPEN"
    assert exit_fill.fill_price == 102.0
    assert exit_fill.fill_type == "INTRADAY_TIME_EXIT"
    # 기존 STOP/TARGET/TIME_EXIT 문자열과 겹치지 않는 새 값임을 확인
    assert exit_fill.fill_type not in ("STOP", "TARGET", "TIME_EXIT")


def test_simulate_trade_returns_none_when_exit_missing():
    df = _minute_df([("09:34", 101.0)])  # 09:35 없음
    cost = CostModel(entry_cost_bps=10.0, exit_cost_bps=10.0)
    result = simulate_intraday_exit_trade(
        "005930", "2026-01-04", "2026-01-05", 100.0, df, cost)
    assert result is None


def test_trade_return_matches_cand1_single_cost_formula():
    """entry_cost_bps+exit_cost_bps 합이 CAND1의 단일 cost_bps(20)와 같으면
    net 공식이 기존 검증 공식(gross - cost_bps/1e4)과 정확히 같아야 한다."""
    df = _minute_df([("09:35", 103.0)])
    cost = CostModel(entry_cost_bps=10.0, exit_cost_bps=10.0)  # 합 20bp
    entry_fill, exit_fill = simulate_intraday_exit_trade(
        "005930", "2026-01-04", "2026-01-05", 100.0, df, cost)
    gross, net = trade_return(entry_fill, exit_fill)
    expected_gross = 103.0 / 100.0 - 1.0
    expected_net = expected_gross - 20.0 / 1e4
    assert gross == pytest.approx(expected_gross)
    assert net == pytest.approx(expected_net)


def test_independent_trades_do_not_interfere():
    """겹침방지/공유 상태 없음을 증명 — 같은 종목의 서로 다른 날짜 두
    트레이드를 어떤 순서로 계산해도(셔플해도) 각자 독립적으로 같은 결과.
    PBR이 겪은 '공유 스케줄링 루프의 겹침방지 로직이 갱신 신호를 버리는'
    문제(CLAUDE.md 완료기록)는 애초에 공유 루프가 없어야 발생하지 않는다
    — 이 모듈은 _schedule_portfolio()를 호출하지 않는다(가장 강한 보장은
    "안 씀"이고, 이 테스트는 그래도 결과가 순서 무관·독립적임을 재확인한다)."""
    cost = CostModel(entry_cost_bps=10.0, exit_cost_bps=10.0)
    df1 = _minute_df([("09:35", 105.0)])
    df2 = _minute_df([("09:35", 95.0)])

    def run(order):
        results = []
        for entry_price, df in order:
            r = simulate_intraday_exit_trade(
                "005930", "2026-01-04", "2026-01-05", entry_price, df, cost)
            results.append(trade_return(*r))
        return results

    forward = run([(100.0, df1), (100.0, df2)])
    reversed_ = run([(100.0, df2), (100.0, df1)])
    assert forward == [reversed_[1], reversed_[0]]


# ---------------- 2) 실제 MinuteProvider (가벼운 스모크) ----------------

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_MINUTE_CACHE = os.path.join(_REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")


@pytest.mark.skipif(not os.path.isdir(_MINUTE_CACHE), reason="분봉 캐시 없음(로컬 전용 데이터)")
def test_minute_provider_real_timestamp_semantics():
    from engine.data.minuteProvider import MinuteProvider
    mp = MinuteProvider(repo_root=_REPO_ROOT)
    d = mp._dates[0]
    bars = mp.load(["005930"], d, d)
    assert "005930" in bars
    df = bars["005930"]
    assert str(df.index.tz) == "UTC+09:00"  # KST, docstring이 주장하는 그대로
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    price = resolve_intraday_price(df, "09:35")
    # 이 특정 종목·날짜에 09:35 틱이 없을 수도 있다(전사 결측률 21% 실측,
    # 2026-08-23) — 있으면 값이, 없으면 None이 나오는 것 자체가 정상.
    assert price is None or isinstance(price, float)


@pytest.mark.skipif(not os.path.isdir(_MINUTE_CACHE), reason="분봉 캐시 없음(로컬 전용 데이터)")
def test_minute_provider_missing_ticker_is_silently_absent():
    from engine.data.minuteProvider import MinuteProvider
    mp = MinuteProvider(repo_root=_REPO_ROOT)
    d = mp._dates[0]
    bars = mp.load(["005930", "999999NOPE"], d, d)
    assert "999999NOPE" not in bars  # 존재하지 않는 티커는 조용히 빠진다(오류 아님)
