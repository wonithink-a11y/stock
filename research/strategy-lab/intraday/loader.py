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

# MN-1.1 이 tradingValue 를 더했다. 옛 파티션에는 없으므로 _present() 가 걸러낸다 -
# 기본 목록에 넣어 두어야 있는 날엔 자동으로 딸려 온다.
_SCHEMA_FIELDS = ("ticker", "ts", "open", "high", "low", "close", "volume", "tradingValue")


def _present(part, wanted):
    """그 parquet 에 실제로 있는 열만. 스키마(메타데이터)만 읽어 비용이 없다."""
    try:
        import pyarrow.parquet as pq
        have = set(pq.ParquetFile(part).schema_arrow.names)
    except Exception:                                          # noqa: BLE001
        return list(wanted)
    return [c for c in wanted if c in have]


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
    # 파티션마다 schemaVersion 이 다르다(MN-1.0 6열 / MN-1.1 tradingValue 추가).
    # 없는 열을 요청하면 옛 파티션에서 깨지므로 파일에 있는 것만 읽는다.
    frames = [pd.read_parquet(p, columns=_present(p, columns)) for p in parts]
    out = pd.concat(frames, ignore_index=True)
    if "ts" not in out.columns:
        return out
    ts = out["ts"].astype(str)
    out["hhmm"] = (ts.str.slice(11, 13) + ts.str.slice(14, 16)).astype(np.int32)
    return out


def read_days(dates, columns=_SCHEMA_FIELDS, base=None):
    for d in dates:
        yield d, read_day(d, columns=columns, base=base)
