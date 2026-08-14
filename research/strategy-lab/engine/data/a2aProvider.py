"""A2a price adapter - reads data/backfill/price/a2a/*.jsonl.gz read-only.

Performance contract: for a given (ticker set, date range), the 14 source gzip
files are streamed exactly once per run - never once per ticker. Results are
optionally cached to a local parquet file under research/strategy-lab/.cache/,
keyed by cacheKey.build_cache_key(); a cache hit still round-trips through an
explicit metadata comparison before being trusted (CACHE CONTRACT).

Never writes to data/backfill/ - that tree is Actions-only (CLAUDE.md rule 4).
"""
import gzip
import json
from pathlib import Path

import pandas as pd

from .cacheKey import build_cache_key
from .priceProvider import PriceProvider

A2A_DIR = "data/backfill/price/a2a"
A2A_MANIFEST = "data/backfill/manifest/A2a.json"
CACHE_DIR = "research/strategy-lab/.cache/a2a"

_SCHEMA_FIELDS = ("ticker", "date", "open", "high", "low", "close", "volume")


class A2aProvider(PriceProvider):
    def __init__(self, repo_root=".", use_cache=True):
        self.repo_root = Path(repo_root)
        self.use_cache = use_cache
        with open(self.repo_root / A2A_MANIFEST, encoding="utf-8") as f:
            self._manifest = json.load(f)
        self._bars = {}

    @property
    def manifest_hash(self):
        return self._manifest["hash"]

    def coverage(self, ticker):
        df = self._bars.get(ticker)
        if df is None or df.empty:
            return None
        return (df.index[0].strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d"))

    def load(self, tickers, start, end, universe_hash="none"):
        tickers = set(tickers)
        cache_key, cache_meta = build_cache_key(self.manifest_hash, universe_hash, tickers, start, end)
        cache_path = self.repo_root / CACHE_DIR / f"{cache_key}.parquet"

        if self.use_cache and self._cache_metadata_matches(cache_path, cache_meta):
            df_all = pd.read_parquet(cache_path)
            self._bars = {
                t: g.drop(columns=["ticker"]).set_index("date").sort_index()
                for t, g in df_all.groupby("ticker")
            }
            return self._bars

        self._bars = self._scan(tickers, start, end)
        if self.use_cache and self._bars:
            self._write_cache(cache_path, cache_meta)
        return self._bars

    def _scan(self, tickers, start, end):
        """Single sequential pass over the 14 year-files. O(rows in range), not
        O(tickers * rows) - this is the requirement 1 fix from Phase 2 review."""
        buffers = {t: [] for t in tickers}
        a2a_dir = self.repo_root / A2A_DIR
        for path in sorted(a2a_dir.glob("*.jsonl.gz")):
            if not path.name[:4].isdigit():
                continue  # skips price-quality-excluded.jsonl.gz (not a year file)
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    ticker = row["ticker"]
                    if ticker not in buffers:
                        continue
                    date = row["date"]
                    if date < start or date > end:
                        continue
                    missing = [k for k in _SCHEMA_FIELDS if k not in row]
                    if missing:
                        raise ValueError(f"A2a schema violation: missing {missing} ({ticker} {date})")
                    buffers[ticker].append(row)

        result = {}
        for t, rows in buffers.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype("float32")
            df["volume"] = df["volume"].astype("int64")
            result[t] = df[["open", "high", "low", "close", "volume"]]
        return result

    def _write_cache(self, cache_path, cache_meta):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        frames = []
        for t, df in self._bars.items():
            g = df.reset_index()
            g["ticker"] = t
            frames.append(g)
        pd.concat(frames, ignore_index=True).to_parquet(cache_path)
        with open(cache_path.with_suffix(".meta.json"), "w", encoding="utf-8") as f:
            json.dump(cache_meta, f)

    def _cache_metadata_matches(self, cache_path, expected_meta):
        meta_path = cache_path.with_suffix(".meta.json")
        if not (self.use_cache and cache_path.exists() and meta_path.exists()):
            return False
        with open(meta_path, encoding="utf-8") as f:
            stored = json.load(f)
        return stored == expected_meta
