"""Read-only access helpers for the local minute_raw mirror.

Mirrors engine/data/minuteProvider.py conventions but exposes per-day
partition scanning so research passes stream each parquet exactly once.
"""
from __future__ import annotations

import glob
import os

import numpy as np
import pandas as pd

# intraday/loader.py -> stock root is 4 dirnames up
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
MINUTE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")

_SCHEMA_FIELDS = ("ticker", "ts", "open", "high", "low", "close", "volume")


def list_dates(base=None):
    base = base or MINUTE_DIR
    return sorted(d.split("=", 1)[1] for d in os.listdir(base)
                  if d.startswith("date="))


def read_day(date_str, columns=_SCHEMA_FIELDS, base=None):
    """All bars of one date partition with an added int 'hhmm' column.

    hhmm is derived by fixed-offset slicing of the ISO ts string
    ('YYYY-MM-DDTHH:MM+09:00') - no per-row to_datetime.
    """
    base = base or MINUTE_DIR
    parts = sorted(glob.glob(os.path.join(base, f"date={date_str}", "part-*.parquet")))
    if not parts:
        return None
    frames = [pd.read_parquet(p, columns=list(columns)) for p in parts]
    out = pd.concat(frames, ignore_index=True)
    if "ts" not in out.columns:
        return out
    ts = out["ts"].astype(str)
    out["hhmm"] = (ts.str.slice(11, 13) + ts.str.slice(14, 16)).astype(np.int32)
    return out


def read_days(dates, columns=_SCHEMA_FIELDS, base=None):
    for d in dates:
        yield d, read_day(d, columns=columns, base=base)
