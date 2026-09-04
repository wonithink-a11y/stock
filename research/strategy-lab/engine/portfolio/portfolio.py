"""The one implementation of the PORTFOLIO ACCOUNTING CONTRACT. Knows nothing
about any strategy's rule - only a tie-break name and a handful of numbers.

Same-day cash reuse ban: proceeds from a position closed today are held in a
local `pending_cash` total and only merged into `self.cash` at the end of
process_day(), after this day's new entries have already been sized and paid
for. So today's exits cannot fund today's entries - only tomorrow's.

Equal-weight sizing: the per-slot target allocation is computed once per day
from cash available *before* today's entries are placed (self.cash / max_positions),
then reused unchanged for every entry accepted that day. Recomputing it after each
purchase would make later entries in the same day get a smaller slice than earlier
ones - order-dependent, and not actually equal weight. Transaction cost is sized
INTO that allocation (shares = floor(target_alloc / (price * (1+cost_bps)))),
not added on top of it - otherwise N equal slices of exactly cash/N collectively
overshoot cash once costs are layered on, and the last slot(s) silently starve.
"""
from dataclasses import dataclass

from .tieBreak import get_tie_break


@dataclass
class PortfolioConfig:
    initial_capital: float = 100_000_000.0
    max_positions: int = 10
    equal_weight: bool = True
    fractional_shares: bool = False
    tie_break: str = "ticker_ascending"


class Portfolio:
    def __init__(self, config: PortfolioConfig):
        self.config = config
        self.cash = config.initial_capital
        self.open_positions = {}  # symbol -> {shares, entry_fill, cost_basis, entry_date}
        self.closed_positions = []

    def process_day(self, date, exits_today, candidate_orders_today, weights=None):
        """exits_today: [(symbol, exit_fill, shares)].
        candidate_orders_today: [(order, entry_fill)] - unordered, this function
        applies the configured tie-break.
        weights: optional {symbol: float}, opt-in relative sizing among today's
        admitted entries only (e.g. inverse-volatility). None (default) keeps
        the existing equal_weight/full-cash behavior byte-for-byte. When given,
        the SAME total pool equal_weight would have deployed today (len(selected)
        slices of cash/max_positions) is redistributed proportionally to weight,
        rather than split evenly - existing positions and exits are untouched."""
        pending_cash = 0.0
        for symbol, exit_fill, shares in exits_today:
            proceeds = exit_fill.fill_price * shares
            cost = proceeds * (exit_fill.cost_bps / 10000)
            pending_cash += proceeds - cost
            pos = self.open_positions[symbol]
            held = pos["shares"]
            # 부분 청산: shares < 보유수량이면 원가를 안분하고 나머지를 남긴다.
            # shares == held 이면 아래는 기존 경로와 수치가 완전히 같다(basis_sold
            # = cost_basis, 남는 수량 0 -> pop).
            basis_sold = pos["cost_basis"] * (shares / held) if held else 0.0
            pnl = (proceeds - cost) - basis_sold
            partial = shares < held
            if partial:
                pos["shares"] = held - shares
                pos["cost_basis"] = pos["cost_basis"] - basis_sold
            else:
                self.open_positions.pop(symbol)
            self.closed_positions.append({
                "symbol": symbol, "entry": pos["entry_fill"], "exit": exit_fill,
                "shares": shares, "pnl": pnl, "partial": partial,
                "entry_date": pos["entry_date"], "exit_date": exit_fill.fill_date,
            })

        available_slots = self.config.max_positions - len(self.open_positions)
        ordered = get_tie_break(self.config.tie_break)(candidate_orders_today)
        # a symbol already holding an open position is never admitted a second
        # time - two simultaneous positions under one symbol key would silently
        # overwrite each other's cost basis below (교훈 18: 동일 종목 중복 포지션)
        ordered = [pair for pair in ordered if pair[0].symbol not in self.open_positions]
        selected = ordered[:max(available_slots, 0)]

        base_alloc = (self.cash / self.config.max_positions) if self.config.equal_weight else self.cash
        if weights is None:
            alloc_for = {order.symbol: base_alloc for order, _ in selected}
        else:
            total_w = sum(weights.get(order.symbol, 0.0) for order, _ in selected) or 1.0
            pool_today = base_alloc * len(selected)
            alloc_for = {order.symbol: pool_today * (weights.get(order.symbol, 0.0) / total_w)
                         for order, _ in selected}
        for order, entry_fill in selected:
            # cost is sized INTO the target allocation (not added on top of it) -
            # otherwise N equal slices of exactly cash/N collectively overshoot
            # cash once entry costs are layered on, and the last slot(s) starve.
            target_alloc = alloc_for[order.symbol]
            all_in_price = entry_fill.fill_price * (1 + entry_fill.cost_bps / 10000)
            shares = int(target_alloc // all_in_price)
            if shares <= 0:
                continue
            cost_basis = entry_fill.fill_price * shares
            total_cost = cost_basis + cost_basis * (entry_fill.cost_bps / 10000)
            if total_cost > self.cash:
                continue  # cannot afford it - never goes cash-negative
            self.cash -= total_cost
            self.open_positions[order.symbol] = {
                "shares": shares, "entry_fill": entry_fill,
                "cost_basis": total_cost, "entry_date": date,
            }

        self.cash += pending_cash  # today's exits become spendable starting tomorrow

    def equity(self, closes_today):
        """closes_today: {symbol: close_price} for currently open positions."""
        market_value = sum(
            closes_today.get(sym, pos["entry_fill"].fill_price) * pos["shares"]
            for sym, pos in self.open_positions.items()
        )
        return self.cash + market_value
