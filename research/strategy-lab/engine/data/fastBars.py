"""Performance-only optimization, no contract change: a drop-in replacement for
a per-ticker OHLC DataFrame that engine/execution/executor.py can use through
the exact same `bars.index` / `bars.loc[...]` calls it already makes -
executor.py is unmodified.

Why this exists (profiled, 2026-08-14): order.order_date and the `day` values
walked in simulate_trade's holding-window loop are always plain 'YYYY-MM-DD'
strings (from TradingCalendar, never Timestamps). Every `date in bars.index` or
`bars.loc[date]` against a real pandas DatetimeIndex re-parses that string into
a Timestamp before it can even do the lookup - cProfile showed this dominating
simulate_trade's cost (~75%: pandas indexing + regex date parsing) once the
number of signals got large. A ticker's bars are reused across many trades (one
per signal on that ticker), so paying the parsing cost once per ticker instead
of once per (trade x lookup) is a straightforward, non-behavioral fix.
"""


class FastBars:
    def __init__(self, df):
        self._rows = {}
        for ts, o, h, l, c in zip(df.index, df["open"], df["high"], df["low"], df["close"]):
            self._rows[ts.strftime("%Y-%m-%d")] = {"open": o, "high": h, "low": l, "close": c}
        self.index = self._rows  # plain dict supports `date in bars.index` via dict.__contains__

    @property
    def loc(self):
        return self

    def __getitem__(self, key):
        if isinstance(key, tuple):
            date, col = key
            return self._rows[date][col]
        return self._rows[key]
