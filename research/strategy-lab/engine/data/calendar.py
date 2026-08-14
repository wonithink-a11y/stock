"""Read-only wrapper around data/backfill/calendar.json.

That file is a frozen asset for T1 minute-bar reconnaissance (CLAUDE.md section
6.1 - "동결은 커밋 금지"). This module only ever opens it for reading; nothing
here writes to it.
"""
import bisect
import json
from pathlib import Path

CALENDAR_PATH = "data/backfill/calendar.json"


class TradingCalendar:
    def __init__(self, repo_root="."):
        with open(Path(repo_root) / CALENDAR_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        self.days = raw["tradingDays"]  # ascending 'YYYY-MM-DD' strings

    def next_session(self, date):
        """First trading day strictly after `date`. None past the end of the
        calendar - not fabricated (LESSON 57: unknown is not zero)."""
        i = bisect.bisect_right(self.days, date)
        return self.days[i] if i < len(self.days) else None

    def sessions_between(self, start, end):
        """Trading days in [start, end], inclusive of both ends."""
        lo = bisect.bisect_left(self.days, start)
        hi = bisect.bisect_right(self.days, end)
        return self.days[lo:hi]

    def next_n_sessions(self, start, n):
        """The first n trading days >= start (inclusive), same list a caller
        would get from sessions_between(start, self.days[-1])[:n] - but without
        first materializing the (potentially thousands of days) full remainder
        of the calendar just to slice n off the front of it. Performance-only
        addition (profiled 2026-08-14); sessions_between is unchanged."""
        lo = bisect.bisect_left(self.days, start)
        return self.days[lo:lo + n]
