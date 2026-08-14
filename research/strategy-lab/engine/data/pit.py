"""Point-In-Time access control (PIT CONTRACT).

Strategy code never receives a raw DataFrame - it receives a PITBars proxy that
structurally cannot return rows after `as_of`. This is deliberately a small,
closed interface (not a full pandas-API passthrough): the wider the surface, the
easier it is for a leak to sneak in through a method nobody thought to guard.

Execution code (executor.py) receives the raw DataFrame directly and is exempt -
by the time a signal has fired, resolving its outcome legitimately requires
future bars.

Dates are normalized to pandas.Timestamp for comparison so callers can pass
either a 'YYYY-MM-DD' string (how Signal.signal_date is stored) or a Timestamp
(how the DataFrame is indexed) interchangeably.
"""
import pandas as pd


class PITViolation(Exception):
    pass


class PITBars:
    def __init__(self, df, as_of):
        self._df = df
        self.as_of = pd.Timestamp(as_of)

    def upto_now(self):
        """A real DataFrame containing only rows with date <= as_of."""
        return self._df.loc[:self.as_of]

    def at(self, date):
        ts = pd.Timestamp(date)
        if ts > self.as_of:
            raise PITViolation(f"PIT violation: as_of={self.as_of}, requested {ts}")
        if ts not in self._df.index:
            return None
        return self._df.loc[ts]

    def latest(self):
        view = self.upto_now()
        return None if view.empty else view.iloc[-1]
