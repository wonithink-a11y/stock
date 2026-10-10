"""Signal -> Order -> Fill(entry) -> Fill(exit) simulation.

Owns, generically for any strategy that declares a RiskSpec:
  - next-tradable-session entry (EXECUTION CONTRACT)
  - same-bar stop-first when both stop and target are touched in one day
  - gap-through-stop: if next day's open is already past the stop, fill at that
    open, not at the nominal stop price
  - time exit at the close of the max_holding_sessions'th session

A strategy never reimplements any of this - it only supplies a RiskSpec (already
resolved using signal-date-only data, per the ATR TIMING CONTRACT).
"""
from dataclasses import dataclass

from .contracts import Fill, Order


@dataclass(frozen=True)
class CostModel:
    entry_cost_bps: float = 15.0
    exit_cost_bps: float = 15.0
    slippage_bps: float = 0.0  # Primary = 0. Kept as its own field so cost and
    # slippage sensitivity can be varied independently later.


def build_order(signal, risk_spec, calendar):
    order_date = calendar.next_session(signal.signal_date)
    if order_date is None:
        return None  # past the end of the calendar - no fabricated date
    return Order(
        symbol=signal.symbol,
        signal_date=signal.signal_date,
        order_date=order_date,
        direction=signal.direction,
        risk_spec=risk_spec,
    )


def simulate_trade(order: Order, bars, calendar, cost_model: CostModel, data_end=None):
    """bars: the ticker's full DataFrame (future included - this layer is allowed
    to see it). Returns (entry_fill, exit_fill), or None if order_date has no bar
    (e.g. ran past available data).

    data_end (2026-10-10): the last date the caller loaded prices for. Without it
    (default) a trade whose exit day has no bar is dropped - which silently erased
    delisting losses and exits on halt days (EW benchmark lost 1,247 trades,
    findings/pbr-combined-merged-rerun-results-2026-10.md). With it, such a trade is
    still dropped only when the holding window runs past data_end or past the
    calendar (genuinely unresolved); otherwise it exits at the close of the first
    bar after the window (RESUME_EXIT - halted, then resumed) or, if there is none,
    the last bar the ticker traded (LAST_BAR_EXIT - delisted)."""
    if order.order_date not in bars.index:
        return None

    entry_price = _apply_slippage(float(bars.loc[order.order_date, "open"]), "BUY", cost_model.slippage_bps)
    entry_fill = Fill(order, order.order_date, entry_price, "OPEN",
                       cost_model.entry_cost_bps, cost_model.slippage_bps)

    stop_price = entry_price - order.risk_spec.stop_distance
    target_price = entry_price + order.risk_spec.reward_risk * order.risk_spec.stop_distance

    # equivalent to sessions_between(order_date, calendar.days[-1])[:n], but
    # without materializing the full (up to ~3000-day) remainder of the
    # calendar just to slice n off the front of it (profiled 2026-08-14)
    holding_window = calendar.next_n_sessions(order.order_date, order.risk_spec.max_holding_sessions)

    exit_fill = None
    for day in holding_window:
        if day not in bars.index:
            continue
        row = bars.loc[day]
        hit_stop = row["low"] <= stop_price
        hit_target = row["high"] >= target_price
        if hit_stop:
            # same-bar rule: STOP FIRST, whether or not target was also touched
            exit_fill = _fill_stop(order, day, row, stop_price, cost_model)
        elif hit_target:
            price = _apply_slippage(target_price, "SELL", cost_model.slippage_bps)
            exit_fill = Fill(order, day, price, "TARGET", cost_model.exit_cost_bps, cost_model.slippage_bps)
        if exit_fill:
            break

    if exit_fill is None and holding_window:
        last_day = holding_window[-1]
        if last_day in bars.index:
            price = _apply_slippage(float(bars.loc[last_day, "close"]), "SELL", cost_model.slippage_bps)
            exit_fill = Fill(order, last_day, price, "TIME_EXIT", cost_model.exit_cost_bps, cost_model.slippage_bps)

    if exit_fill is None and data_end is not None:
        exit_fill = _exit_after_gap(order, bars, holding_window, data_end, cost_model)

    if exit_fill is None:
        return None  # unresolved (data ends before the exit) - not fabricated

    return entry_fill, exit_fill


def _exit_after_gap(order, bars, holding_window, data_end, cost_model):
    """Exit for a trade whose scheduled exit day has no bar. None when the window is
    cut by the calendar or by data_end - the outcome is not knowable yet."""
    if len(holding_window) < order.risk_spec.max_holding_sessions or holding_window[-1] > data_end:
        return None
    days = sorted(str(d)[:10] for d in bars.index)
    after = [d for d in days if holding_window[-1] < d <= data_end]
    if after:
        day, kind = after[0], "RESUME_EXIT"
    else:
        held = [d for d in days if order.order_date <= d <= holding_window[-1]]
        day, kind = held[-1], "LAST_BAR_EXIT"  # order_date itself has a bar, so held is non-empty
    price = _apply_slippage(float(bars.loc[day, "close"]), "SELL", cost_model.slippage_bps)
    return Fill(order, day, price, kind, cost_model.exit_cost_bps, cost_model.slippage_bps)


def _fill_stop(order, day, row, stop_price, cost_model):
    gapped_through = row["open"] <= stop_price
    price = float(row["open"]) if gapped_through else stop_price
    price = _apply_slippage(price, "SELL", cost_model.slippage_bps)
    return Fill(order, day, price, "STOP", cost_model.exit_cost_bps, cost_model.slippage_bps)


def _apply_slippage(price, side, slippage_bps):
    if slippage_bps == 0:
        return price
    adj = price * (slippage_bps / 10000)
    return price + adj if side == "BUY" else price - adj
