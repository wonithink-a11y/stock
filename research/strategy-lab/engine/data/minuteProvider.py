"""MinuteProvider - reads 1-minute bars mirrored from the Oracle VM (~/minute-raw)
into research/strategy-lab/.cache/minute_raw/ (2026-08-22 scp pull, read-only VM
access, VM原본 unchanged).

★ Research-only import, NOT an official backfill. data/backfill/ has no MN-1.0
manifest yet (see docs/MN-1.0-분봉Raw저장계약.md - promotion pipeline VM -> Object
Storage -> Actions -> commit is still unimplemented). This provider exists so
research/strategy-lab can experiment with 1-minute bars using the same interface
as A2a - it is not a substitute for that pipeline and manifest_hash below is not a
reproducibility guarantee the way A2aProvider's is.

Timestamps are KST (+09:00), 1-minute bars, 09:00-15:30 KRX session
(confirmed in findings/minute-vm-inventory-2026-08.md).
"""
import glob
import hashlib
import os

import pandas as pd

from .priceProvider import PriceProvider

MINUTE_DIR = "research/strategy-lab/.cache/minute_raw"
_SCHEMA_FIELDS = ("ticker", "ts", "open", "high", "low", "close", "volume")
# MN-1.1(2026-09-09)이 더한 열. 그 이전 파티션에는 없다 - 있으면 읽고 없으면 만다.
_OPTIONAL_FIELDS = ("tradingValue",)


def _present_columns(part, wanted):
    """그 파일에 실제로 있는 열만 고른다.

    파티션마다 schemaVersion 이 다르다(MN-1.0 6열 / MN-1.1 7열). 없는 열을
    read_parquet(columns=...) 에 넣으면 옛 파티션에서 그대로 깨진다. 스키마는
    파일 메타데이터만 읽으므로 비용이 사실상 없다.
    """
    try:
        import pyarrow.parquet as pq
        have = set(pq.ParquetFile(part).schema_arrow.names)
    except Exception:                                          # noqa: BLE001
        return list(_SCHEMA_FIELDS)
    return [c for c in wanted if c in have]


class MinuteProvider(PriceProvider):
    def __init__(self, repo_root="."):
        self.repo_root = repo_root
        self._bars = {}
        base = os.path.join(repo_root, MINUTE_DIR)
        self._dates = sorted(
            d.split("=", 1)[1] for d in os.listdir(base) if d.startswith("date=")
        )

    @property
    def manifest_hash(self):
        # No official MN-1.0 manifest exists (data/backfill/ has none for minute
        # data). This is a hash of which date partitions were mirrored locally -
        # useful to detect "the local mirror changed", not a promoted guarantee.
        digest = hashlib.sha256(",".join(self._dates).encode()).hexdigest()[:16]
        return f"unofficial-vm-mirror:{digest}"

    def coverage(self, ticker):
        df = self._bars.get(ticker)
        if df is None or df.empty:
            return None
        return (df.index[0].isoformat(), df.index[-1].isoformat())

    def load(self, tickers, start, end, universe_hash="none"):
        """start/end are 'YYYY-MM-DD' strings. Returns {ticker: DataFrame[open,high,
        low,close,volume]} indexed by ts (ascending). Scans only the date
        partitions inside [start, end] - not the full 252-day mirror - mirroring
        A2aProvider's single-pass-per-relevant-file design."""
        tickers = set(tickers)
        buffers = {t: [] for t in tickers}
        for d in self._dates:
            if d < start or d > end:
                continue
            date_dir = os.path.join(self.repo_root, MINUTE_DIR, f"date={d}")
            for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
                cols = _present_columns(part, _SCHEMA_FIELDS + _OPTIONAL_FIELDS)
                df = pd.read_parquet(part, columns=cols)
                df = df[df["ticker"].isin(tickers)]
                if df.empty:
                    continue
                for t, g in df.groupby("ticker"):
                    buffers[t].append(g)

        self._bars = {}
        for t, chunks in buffers.items():
            if not chunks:
                continue
            df = pd.concat(chunks, ignore_index=True)
            df["ts"] = pd.to_datetime(df["ts"])
            df = df.sort_values("ts").set_index("ts")
            self._bars[t] = df[["open", "high", "low", "close", "volume"]]
        return self._bars
