import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.execution.contracts import Order
from engine.execution.executor import CostModel, build_order, simulate_trade
from engine.signals.schema import RiskSpec, Signal


class FakeCalendar:
    """Consecutive synthetic trading days - decouples execution unit tests from
    the real (frozen) data/backfill/calendar.json."""
    def __init__(self, n=80):
        self.days = [f"2024-01-{d:02d}" if d <= 31 else f"2024-02-{d-31:02d}" for d in range(1, n + 1)]

    def next_session(self, date):
        i = self.days.index(date) if date in self.days else -1
        if i == -1:
            # date not itself a session (e.g. before the calendar) - first day after
            later = [d for d in self.days if d > date]
            return later[0] if later else None
        return self.days[i + 1] if i + 1 < len(self.days) else None

    def sessions_between(self, start, end):
        return [d for d in self.days if start <= d <= end]

    def next_n_sessions(self, start, n):
        return [d for d in self.days if d >= start][:n]


def _bars(rows):
    """rows: [(date, open, high, low, close)]"""
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close"]).set_index("date")
    return df


def test_next_session_entry():
    cal = FakeCalendar()
    signal = Signal(symbol="005930", signal_date=cal.days[0], direction="LONG")
    risk = RiskSpec(stop_distance=10.0, reward_risk=3.0, max_holding_sessions=60)
    order = build_order(signal, risk, cal)
    assert order.order_date == cal.days[1], "entry must be the NEXT session, not the signal day"


def test_target_hit():
    cal = FakeCalendar()
    order = Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60))
    rows = [(cal.days[1], 100, 101, 99, 100)] + [(d, 100, 100, 99, 99.5) for d in cal.days[2:5]] \
        + [(cal.days[5], 100, 132, 99, 130)]  # entry=100, stop=90, target=130
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert entry.fill_price == 100
    assert exit_.fill_type == "TARGET"
    assert exit_.fill_price == 130


def test_same_bar_stop_first():
    cal = FakeCalendar()
    order = Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60))
    # day after entry touches BOTH stop(90) and target(130) in one bar
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 100, 135, 85, 100)]
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "STOP", "same-bar rule must resolve to STOP, not TARGET"
    assert exit_.fill_price == 90


def test_gap_through_stop_fills_at_open():
    cal = FakeCalendar()
    order = Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60))
    # stop=90, but next day gaps open at 80 - already through the stop
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 80, 82, 78, 81)]
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "STOP"
    assert exit_.fill_price == 80, "gap-through-stop must fill at the actual open, not the nominal stop price"


def test_time_exit_at_60th_session_close():
    cal = FakeCalendar(n=80)
    order = Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60))
    # 60 sessions from order_date, never touching stop(90) or target(130)
    window = cal.sessions_between(cal.days[1], cal.days[-1])[:60]
    rows = [(d, 100, 105, 95, 100) for d in window]
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type == "TIME_EXIT"
    assert exit_.fill_date == window[-1]
    assert exit_.fill_price == 100


def test_atr_timing_stop_distance_is_fixed_at_signal_time():
    """Even if bars after order_date show wildly different volatility, stop_price
    must not move - because stop_distance was already resolved (from ATR[t]) and
    passed in as a fixed number, never recomputed by the executor."""
    cal = FakeCalendar()
    risk = RiskSpec(stop_distance=10.0, reward_risk=3.0, max_holding_sessions=60)  # as if ATR[t]=5, 2xATR=10
    order = Order("X", cal.days[0], cal.days[1], "LONG", risk)
    # huge range days after entry (as if volatility exploded) - stop must still be entry-10
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 100, 200, 92, 150)]
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel())
    assert exit_.fill_type != "STOP", "low=92 is above stop=90, must not have stopped out"
    assert exit_.fill_type == "TARGET"
    assert exit_.fill_price == 130  # entry(100) + 3*10, unaffected by the day's wide range


def test_transaction_cost_recorded_on_gap_stop_exit():
    cal = FakeCalendar()
    order = Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(10.0, 3.0, 60))
    rows = [(cal.days[1], 100, 101, 99, 100), (cal.days[2], 80, 82, 78, 81)]
    bars = _bars(rows)
    entry, exit_ = simulate_trade(order, bars, cal, CostModel(entry_cost_bps=15, exit_cost_bps=15))
    assert exit_.cost_bps == 15, "exit transaction cost must apply even on a gap-through-stop exit"


def _gap_order(cal):
    return Order("X", cal.days[0], cal.days[1], "LONG", RiskSpec(1e9, 1.0, 5))  # 도달 불가 stop/target, 5세션 시간청산


def test_delisted_mid_hold_exits_at_last_bar():
    cal = FakeCalendar()
    bars = _bars([(cal.days[1], 100, 100, 100, 100), (cal.days[2], 40, 40, 10, 12)])  # 이틀 뒤 폐지
    assert simulate_trade(_gap_order(cal), bars, cal, CostModel()) is None, "data_end 없이는 예전 동작(버림) 유지"
    _, exit_ = simulate_trade(_gap_order(cal), bars, cal, CostModel(), data_end=cal.days[-1])
    assert (exit_.fill_type, exit_.fill_date, exit_.fill_price) == ("LAST_BAR_EXIT", cal.days[2], 12),         "폐지 손실이 사라지면 안 된다 - 마지막 거래일 종가에 판다"


def test_halt_over_exit_day_exits_at_resume():
    cal = FakeCalendar()
    bars = _bars([(cal.days[1], 100, 100, 100, 100), (cal.days[9], 30, 30, 30, 31)])  # 청산일(5세션째) 정지, 9일째 재개
    _, exit_ = simulate_trade(_gap_order(cal), bars, cal, CostModel(), data_end=cal.days[-1])
    assert (exit_.fill_type, exit_.fill_date, exit_.fill_price) == ("RESUME_EXIT", cal.days[9], 31)


def test_window_past_data_end_stays_unresolved():
    cal = FakeCalendar()
    bars = _bars([(cal.days[1], 100, 100, 100, 100), (cal.days[2], 100, 100, 100, 100)])
    assert simulate_trade(_gap_order(cal), bars, cal, CostModel(), data_end=cal.days[3]) is None,         "데이터가 끝나서 모르는 결과를 마지막 가격으로 지어내면 안 된다"
    short = FakeCalendar(n=4)  # 달력 끝에 잘린 창
    assert simulate_trade(_gap_order(short), bars, short, CostModel(), data_end=short.days[-1]) is None


def test_normal_time_exit_unchanged_by_data_end():
    cal = FakeCalendar()
    bars = _bars([(d, 100, 100, 100, 100 + i) for i, d in enumerate(cal.days[1:8])])
    a = simulate_trade(_gap_order(cal), bars, cal, CostModel())
    b = simulate_trade(_gap_order(cal), bars, cal, CostModel(), data_end=cal.days[-1])
    assert a[1].fill_type == b[1].fill_type == "TIME_EXIT" and a[1].fill_price == b[1].fill_price


def run():
    test_next_session_entry()
    test_target_hit()
    test_same_bar_stop_first()
    test_gap_through_stop_fills_at_open()
    test_time_exit_at_60th_session_close()
    test_atr_timing_stop_distance_is_fixed_at_signal_time()
    test_transaction_cost_recorded_on_gap_stop_exit()
    test_delisted_mid_hold_exits_at_last_bar()
    test_halt_over_exit_day_exits_at_resume()
    test_window_past_data_end_stays_unresolved()
    test_normal_time_exit_unchanged_by_data_end()
    print("test_execution: OK")


if __name__ == "__main__":
    run()
