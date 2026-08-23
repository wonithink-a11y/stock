"""성과지표 convention 회귀 테스트 (2026-08-22 convention 감사 산출).

엔진 metric 함수(engine/metrics/metrics.py)의 현재 동작은 변경하지 않고,
그 의미(semantics)를 실제 baseline에서 관측된 수치로 고정한다.

감사로 확정된 사실:
  - total_return(curve)는 항상 curve[-1]/curve[0]-1이다. 호출자가 초기자본
    앵커 없는 event curve를 넘기면 결과는 initial-capital 기준과 달라진다
    (5DC-v1A-P post-fix: -71.349% vs -71.529%, Δ≈-18bp).
  - cagr(curve)는 첫/끝 관측일 span만 쓴다. 백테스트 시작일이 아니므로
    첫 체결이 늦은 전략일수록 연율화가 강해진다
    (5DC post-fix: 첫 exit 앵커 4424일 -9.805% vs 시작일 앵커 4465일 -9.766%).
  - MDD는 (시작일, 초기자본) 앵커 추가에 불변이지만 Sharpe는 민감하다.

frozen 참조값 출처:
  reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_samebar_rerun.json
  resultTable(totalReturn/cagr) · allTrades[0](첫 거래 pnl) — 파일 의존 없이
  상수로 고정한다(reports/*는 gitignore 대상이라 CI에서 파일이 없을 수 있음).
"""
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.metrics.metrics import cagr, max_drawdown, sharpe, total_return

INITIAL_CAPITAL = 100_000_000.0
BT_START, BT_END = "2014-05-13", "2026-08-03"

# --- frozen 5DC-v1A-P post-fix baseline reference (rerun json 기록값) ---
FIRST_EXIT_DATE = "2014-06-23"
FIRST_TRADE_PNL = -628_288.3536515813          # allTrades[0].pnl (STOP, 114630)
FINAL_EQUITY = 28_471_028.93155632             # resultTable.finalEquity
RECORDED_TOTAL_RETURN = -0.7134895992042365    # resultTable.totalReturn (curve식)
RECORDED_CAGR = -0.09805313945578853           # resultTable.cagr (첫 exit 앵커)


def _ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return date(y, m, d).toordinal()


def _baseline_event_curve():
    """runner 패턴(run_5dc_v1a_p_samebar.realized_pnl_metrics)과 동일한
    무앵커 event curve를 frozen 참조값으로 축약 재현: 첫 점이 초기자본이 아니라
    '초기자본 + 첫 거래 pnl'이다."""
    first_point_equity = INITIAL_CAPITAL + FIRST_TRADE_PNL
    return [
        (FIRST_EXIT_DATE, first_point_equity),
        (BT_END, FINAL_EQUITY),
    ]


def _anchored_baseline_curve():
    """권고 표준: (백테스트 시작일, 초기자본)을 첫 점으로 prepend."""
    return [(BT_START, INITIAL_CAPITAL)] + _baseline_event_curve()


PEAK_DATE = "2015-05-22"
PEAK_EQUITY = 113_884_876.0                     # 감사 기록 peak (2015-05-22)


def _baseline_event_curve_with_peak():
    """MDD/Sharpe 검증용: 실제 곡선의 최고점을 중간에 포함한 축약 재현.
    TR/CAGR은 끝점만 보므로 이 곡선에서도 동일하게 작동한다."""
    return [
        (FIRST_EXIT_DATE, INITIAL_CAPITAL + FIRST_TRADE_PNL),
        (PEAK_DATE, PEAK_EQUITY),
        (BT_END, FINAL_EQUITY),
    ]


# ---------------------------------------------------------------------------
# Total Return 두 convention
# ---------------------------------------------------------------------------

def test_initial_capital_total_return_formula():
    """initial-capital TR = final_equity / initial_capital - 1 (회계 동일식)."""
    expected = FINAL_EQUITY / INITIAL_CAPITAL - 1
    assert abs(expected - (-0.7152897106844368)) < 1e-15


def test_engine_total_return_is_purely_curve_based():
    """engine.metrics.total_return은 초기자본 개념이 없다 - curve 비율만 본다."""
    curve = _baseline_event_curve()
    assert total_return(curve) == curve[-1][1] / curve[0][1] - 1


def test_unanchored_curve_reproduces_recorded_postfix_total_return():
    """무앵커 event curve로 정본 resultTable.totalReturn이 비트 단위 재현된다."""
    curve = _baseline_event_curve()
    assert total_return(curve) == RECORDED_TOTAL_RETURN


def test_two_total_return_conventions_diverge_on_unanchored_curve():
    """같은 baseline에서 두 convention의 차이(≈-18.0bp)를 명시적으로 고정."""
    curve_based = total_return(_baseline_event_curve())
    initial_based = FINAL_EQUITY / INITIAL_CAPITAL - 1
    delta = curve_based - initial_based
    # 첫 거래 손실로 분모(curve[0])가 줄어 curve식이 유리하게 보인다
    assert delta > 0
    assert abs(delta - 0.0018001114802003) < 1e-12  # ≈ +18.0bp
    # 그리고 curve식이 정본 기록값과 일치함을 재확인
    assert curve_based == RECORDED_TOTAL_RETURN
    assert initial_based != RECORDED_TOTAL_RETURN


# ---------------------------------------------------------------------------
# CAGR 기간 convention
# ---------------------------------------------------------------------------

def test_cagr_period_is_curve_endpoint_span_not_backtest_window():
    """cagr은 첫~끝 관측일 span(4424일)으로 연율화한다 - 시작일 창(4465일)이 아님."""
    curve = _baseline_event_curve()
    years_span = (_ordinal(BT_END) - _ordinal(FIRST_EXIT_DATE)) / 365.25
    expected = (curve[-1][1] / curve[0][1]) ** (1 / years_span) - 1
    assert cagr(curve) == expected
    assert cagr(curve) == RECORDED_CAGR
    # 같은 equity 비율을 시작일 창으로 연율화하면 다른 값이 나온다
    years_window = (_ordinal(BT_END) - _ordinal(BT_START)) / 365.25
    start_anchored = (FINAL_EQUITY / INITIAL_CAPITAL) ** (1 / years_window) - 1
    assert cagr(curve) != start_anchored


def test_first_observation_after_backtest_start_changes_cagr_sign_of_error():
    """첫 관측(첫 exit)이 시작일보다 늦으면 span이 짧아져 연율화가 강해진다.

    실측: 첫 exit 앵커 -9.805% vs 시작일 앵커 -9.766% (Δ≈+3.9bp, 손실 전략에서
    무앵커 쪽이 더 나빠 보임). 방향과 크기를 고정한다.
    """
    unanchored = cagr(_baseline_event_curve())
    anchored = cagr(_anchored_baseline_curve())
    # span 단축(4424 < 4465) -> 0 미만 비율의 연율화 강화(더 깊은 음수)
    assert unanchored < anchored
    delta = anchored - unanchored
    assert abs(delta - 0.00038977453112643) < 1e-12  # ≈ +3.9bp
    assert abs(unanchored - RECORDED_CAGR) < 1e-15


# ---------------------------------------------------------------------------
# 권고 표준: (백테스트 시작일, 초기자본) 앵커 - production 변경 없이 검증
# ---------------------------------------------------------------------------

def test_anchor_prepend_makes_both_total_return_conventions_agree():
    """앵커 prepend 시 curve식 TR == initial-capital식 TR (비트 단위)."""
    anchored = _anchored_baseline_curve()
    assert total_return(anchored) == FINAL_EQUITY / INITIAL_CAPITAL - 1


def test_anchor_prepend_aligns_cagr_with_full_evaluation_window():
    """앵커 prepend 시 cagr이 백테스트 창(4465일) 연율화와 일치."""
    anchored = _anchored_baseline_curve()
    years_window = (_ordinal(BT_END) - _ordinal(BT_START)) / 365.25
    expected = (FINAL_EQUITY / INITIAL_CAPITAL) ** (1 / years_window) - 1
    assert cagr(anchored) == expected


def test_mdd_is_invariant_under_anchoring():
    """MDD는 앵커 추가에 불변 - anchor 값(초기자본)이 실제 peak보다 낮아
    running max/trough가 바뀌지 않기 때문이다."""
    unanchored = max_drawdown(_baseline_event_curve_with_peak())
    anchored = max_drawdown([(BT_START, INITIAL_CAPITAL)] + _baseline_event_curve_with_peak())
    assert unanchored == anchored
    assert abs(unanchored - (-0.7500016684083142)) < 1e-9  # 정본 mdd


def test_sharpe_is_not_invariant_under_anchoring_documented():
    """Sharpe는 앵커에 민감 - convention 변경 시 위험조정지표 재계산이
    필요하다는 사실 자체를 고정한다."""
    unanchored = sharpe(_baseline_event_curve_with_peak())
    anchored = sharpe([(BT_START, INITIAL_CAPITAL)] + _baseline_event_curve_with_peak())
    assert unanchored is not None and anchored is not None
    assert unanchored != anchored
    assert not math.isclose(unanchored, anchored, rel_tol=1e-6)
