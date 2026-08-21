"""PaperBroker - the only thing in the live path allowed to decide a fill
price, and the seam a future KISBrokerAdapter (모의투자 or 실전투자) replaces
without touching paperEngine.py's orchestration.

Both methods take an already-finalized daily bar (today's OHLC is only ever
read after the session that produced it has closed - paperEngine.py enforces
that timing, not this class) so neither call is lookahead:
  fill_entry  - the *next* session's open after a signal fired (same rule as
                engine/execution/executor.py's build_order/simulate_trade)
  check_exit  - stop/target/time-exit against a day that has already closed
"""
from .contracts import PaperFill


class PaperBroker:
    def fill_entry(self, intent, bar_row):
        price = float(bar_row["open"])
        return PaperFill(intent=intent, fill_date=intent.intent_date,
                          fill_price=price, fill_type="ENTRY")

    def check_exit(self, intent, bar_row, stop_price, target_price):
        """STOP_FIRST when both are touched same day (same convention as
        engine/execution/executor.py's same-bar rule) - gap-through-stop
        fills at the open, not the nominal stop price."""
        low, high, open_, close = (float(bar_row[k]) for k in ("low", "high", "open", "close"))
        if low <= stop_price:
            price = open_ if open_ <= stop_price else stop_price
            return PaperFill(intent=intent, fill_date=intent.intent_date, fill_price=price, fill_type="STOP")
        if high >= target_price:
            return PaperFill(intent=intent, fill_date=intent.intent_date, fill_price=target_price, fill_type="TARGET")
        return None

    def fill_time_exit(self, intent, bar_row):
        return PaperFill(intent=intent, fill_date=intent.intent_date,
                          fill_price=float(bar_row["close"]), fill_type="TIME_EXIT")
