#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""MN-1.1 하위호환 회귀 — 6열(MN-1.0)과 7열(MN-1.1) 파티션을 같이 읽는가.

MN-1.1(2026-09-09)이 `tradingValue` 를 더했지만 **기존 파티션은 6열 그대로다**.
소급 재수집을 하지 않기로 했으므로 이 혼재는 영구적이다 - 그래서 계약이 아니라
**리더가** 이것을 감당해야 한다(MN-1.0 §4).

이 검사가 없으면 실패가 조용하다: 옛 파티션 하나만 범위에 들어와도 read_parquet
가 KeyError 로 죽는데, 그게 백테스트 중간에 터지면 원인을 찾는 데 시간이 든다.

  python scripts/test-minute-schema-compat.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "research", "strategy-lab"))

OLD = ["ticker", "ts", "open", "high", "low", "close", "volume"]          # MN-1.0
NEW = OLD + ["tradingValue"]                                             # MN-1.1

_fails = []


def check(msg, cond, extra=None):
    print(("  PASS  " if cond else "  FAIL  ") + msg + ("" if cond else "  %r" % (extra,)))
    if not cond:
        _fails.append(msg)


def write_partition(base, date, cols):
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = os.path.join(base, "date=" + date)
    os.makedirs(d)
    n = 3
    t = {"ticker": ["005930"] * n,
         "ts": ["%sT09:0%d+09:00" % (date, i) for i in range(n)],
         "open": [100] * n, "high": [110] * n, "low": [90] * n, "close": [105] * n,
         "volume": [10, 20, 30], "tradingValue": [1000, 2000, 3000]}
    pq.write_table(pa.table({k: t[k] for k in cols}),
                   os.path.join(d, "part-000.parquet"))


def main():
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        print("pyarrow 없음 - 건너뛴다(로컬 전용 검사)")
        return 0

    base = tempfile.mkdtemp(prefix="mn11-compat-")
    try:
        write_partition(base, "2025-08-08", OLD)      # MN-1.0 파티션
        write_partition(base, "2026-09-09", NEW)      # MN-1.1 파티션

        from intraday import loader
        old = loader.read_day("2025-08-08", base=base)
        new = loader.read_day("2026-09-09", base=base)
        check("loader: 옛 6열 파티션을 읽는다", old is not None and len(old) == 3, old)
        check("loader: 없는 열을 요청하지 않는다",
              old is not None and "tradingValue" not in old.columns,
              None if old is None else list(old.columns))
        check("loader: 새 파티션에서는 tradingValue 가 딸려 온다",
              new is not None and list(new["tradingValue"]) == [1000, 2000, 3000], new)
        check("loader: 파생 hhmm 은 두 스키마 모두에서 생긴다",
              old is not None and new is not None
              and "hhmm" in old.columns and "hhmm" in new.columns)

        from engine.data import minuteProvider as MP
        old_part = os.path.join(base, "date=2025-08-08", "part-000.parquet")
        new_part = os.path.join(base, "date=2026-09-09", "part-000.parquet")
        wanted = MP._SCHEMA_FIELDS + MP._OPTIONAL_FIELDS
        check("provider: 파티션별로 있는 열만 고른다",
              MP._present_columns(old_part, wanted) == OLD
              and MP._present_columns(new_part, wanted) == NEW)

        prev_dir = MP.MINUTE_DIR
        MP.MINUTE_DIR = "."
        try:
            mp = MP.MinuteProvider.__new__(MP.MinuteProvider)
            mp.repo_root, mp._bars = base, {}
            mp._dates = ["2025-08-08", "2026-09-09"]
            bars = mp.load({"005930"}, "2025-01-01", "2026-12-31")
            check("provider: 두 스키마 파티션을 한 번에 읽는다",
                  "005930" in bars and len(bars["005930"]) == 6,
                  None if "005930" not in bars else len(bars["005930"]))
        finally:
            MP.MINUTE_DIR = prev_dir

        # 수집기 쪽 계약이 문서와 어긋나지 않는지 (열 이름·버전은 한 곳에서 온다)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cmk", os.path.join(ROOT, "scripts", "collect-minute-kis.py"))
        cmk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cmk)
        check("수집기 SCHEMA 가 MN-1.1 7열이다", cmk.SCHEMA == NEW, cmk.SCHEMA)
        check("수집기 SCHEMA_VERSION 이 MN-1.1", cmk.SCHEMA_VERSION == "MN-1.1",
              cmk.SCHEMA_VERSION)
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n  통과 %d · 실패 %d" % (8 - len(_fails), len(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
