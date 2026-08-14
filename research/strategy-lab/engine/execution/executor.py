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


def simulate_trade(order: Order, bars, calendar, cost_model: CostModel):
    """bars: the ticker's full DataFrame (future included - this layer is allowed
    to see it). Returns (entry_fill, exit_fill), or None if order_date has no bar
    (e.g. ran past available data)."""
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

    if exit_fill is None:
        return None  # ran out of bars (e.g. delisted mid-holding) - not fabricated

    return entry_fill, exit_fill


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
