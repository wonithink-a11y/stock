"""run_5dc_v1a_p_samebar.realized_pnl_metrics의 convention 표준 회귀 테스트.

표준 (2026-08-22 convention 감사 확정):
  - equity curve의 첫 점 = (백테스트 evaluation 시작일, 초기자본)
  - totalReturn == final_equity / initial_capital - 1
  - cagr이 전체 evaluation window(시작일 -> 마지막 exit)로 연율화
  - MDD는 앵커 추가에 불변
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_5dc_v1a_p_samebar import realized_pnl_metrics  # noqa: E402

INITIAL = 100_000_000.0
START, END = "2014-05-13", "2026-08-03"


class _Cfg:
    initial_capital = INITIAL


class _FakePortfolio:
    def __init__(self, positions):
        self.config = _Cfg()
        self.closed_positions = positions


def _ordinal(ds):
    y, m, d = map(int, ds.split("-"))
    return date(y, m, d).toordinal()


def _positions():
    # peak가 초기자본 위에 있는 3거래 축약 (MDD 불변성 검증 가능한 형태)
    return [
        {"exit_date": "2014-06-23", "pnl": -500_000.0},
        {"exit_date": "2015-05-22", "pnl": +20_000_000.0},
        {"exit_date": "2026-08-03", "pnl": -80_000_000.0},
    ]


def test_empty_positions_returns_none():
    assert realized_pnl_metrics(_FakePortfolio([]), None, START, END) is None


def test_total_return_is_initial_capital_based():
    r = realized_pnl_metrics(_FakePortfolio(_positions()), None, START, END)
    final = INITIAL + sum(p["pnl"] for p in _positions())
    assert r["finalEquity"] == final
    assert r["totalReturn"] == final / INITIAL - 1


def test_cagr_spans_full_evaluation_window_from_start_anchor():
    r = realized_pnl_metrics(_FakePortfolio(_positions()), None, START, END)
    final = INITIAL + sum(p["pnl"] for p in _positions())
    years = (_ordinal(END) - _ordinal(START)) / 365.25
    assert r["cagr"] == (final / INITIAL) ** (1 / years) - 1


def test_mdd_matches_unanchored_computation():
    """앵커는 MDD를 바꾸지 않는다 - 무앵커 수동 계산과 정확히 일치."""
    r = realized_pnl_metrics(_FakePortfolio(_positions()), None, START, END)
    eq, manual = INITIAL, []
    for p in sorted(_positions(), key=lambda p: p["exit_date"]):
        eq += p["pnl"]
        manual.append((p["exit_date"], eq))
    peak, mdd = manual[0][1], 0.0
    for _, v in manual:
        peak = max(peak, v)
        mdd = min(mdd, (v - peak) / peak)
    assert r["mdd"] == mdd


def test_final_equity_and_trade_layer_untouched_by_convention():
    """convention 변경은 equity/trade 층을 건드리지 않는다."""
    r = realized_pnl_metrics(_FakePortfolio(_positions()), None, START, END)
    assert r["initialCapital"] == INITIAL
    assert r["finalEquity"] == INITIAL + (-500_000.0 + 20_000_000.0 - 80_000_000.0)
