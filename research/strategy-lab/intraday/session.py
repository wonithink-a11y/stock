"""KRX regular-session definitions for the minute-bar research.

Session contract (findings/minute-data-quality-2026-08.md):
  - Regular session 09:00~15:30 KST = 381 one-minute slots.
  - A stray '15:32' slot exists (114 rows) and is EXCLUDED everywhere here.
  - Missing bars = no trades in that minute (raw-only design), so any
    price lookup must be AS-OF: last bar with ts <= target.

OPEN30 definition (directive step 4):
  - Observation window = the first 30 minutes of trading = bars stamped
    09:00..09:29 (exactly 30 slots).
  - price_at_30m = as-of close at the 09:30 mark.
"""
from __future__ import annotations

import numpy as np

SESSION_START = "0900"
SESSION_END = "1530"

# All 381 regular-session slot labels "HHMM" as ints, ascending.
SESSION_SLOTS = np.array([h * 100 + m for h in range(9, 16) for m in range(60)
                          if (h * 100 + m) >= 900 and (h * 100 + m) <= 1530],
                         dtype=np.int32)

# OPEN30 formation window [09:00, 09:29]; decision point at 09:30.
OPEN30_LO = 900
OPEN30_HI = 929          # inclusive; last formation bar
OPEN30_MARK = 930        # price_at_30m = as-of close at this mark

# Forward-return horizons measured from an event mark (minutes after event).
HORIZON_MINUTES = (5, 10, 30, 60, 120)


def hhmm_to_min(hhmm_int):
    """'HHMM' int -> minutes since midnight (e.g. 930 -> 570)."""
    return (hhmm_int // 100) * 60 + hhmm_int % 100


# 5-minute grid marks from 09:05 to 15:30 inclusive (78 marks).
# Built from minutes-since-midnight so hour boundaries stay chronological
# (an HHMM-unit arange would fabricate stamps like 0960).
_GRID_MINUTES = np.arange(545, 931, 5, dtype=np.int64)          # 09:05..15:30
GRID_MARKS = (_GRID_MINUTES // 60 * 100 + _GRID_MINUTES % 60).astype(np.int32)
assert len(GRID_MARKS) == 78
# Bucket index for a bar timestamp: bucket j covers (mark_{j-1}, mark_j].
def grid_bucket_index(hhmm_arr):
    """Vectorized bucket index into GRID_MARKS for each bar timestamp.

    Bars at exactly 09:00 belong to bucket 0; bars in (09:00, 09:05] -> 0;
    ...; bars in (15:25, 15:30] -> 77. Anything beyond clips to 77.
    """
    mins = (hhmm_arr // 100) * 60 + (hhmm_arr % 100)
    j = ((mins - 541) // 5).astype(np.int64)
    j = np.where(mins <= 540, 0, j)
    return np.clip(j, 0, len(GRID_MARKS) - 1)


# Directive step 9 observation windows: (label, start_hhmm, end_hhmm).
TIME_WINDOWS = (
    ("w0900_0930", 900, 930),
    ("w0930_1030", 930, 1030),
    ("w1030_1130", 1030, 1130),
    ("w1130_1300", 1130, 1300),
    ("w1300_1400", 1300, 1400),
    ("w1400_1500", 1400, 1500),
    ("w1500_1530", 1500, 1530),
)

# Afternoon-crash windows (step 11): return from mark S to day close.
AFTERNOON_MARKS = {"r1400_close": 1400, "r1500_close": 1500}
