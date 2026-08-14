"""A1a(+A1b) universe adapter. A1b itself is readable today (schema confirmed in
Phase 0) - what's missing is A1b's *price* data (A2b, not yet collected). So this
provider can already merge A1a+A1b; the SMOKE/PRIMARY split is not decided here -
it is decided by cross-referencing this universe against whichever PriceProvider is
actually wired in (price_coverage_report below), matching Phase 1 item I.
"""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

A1A_PATH = "data/backfill/universe/a1a/current.jsonl"
A1B_PATH = "data/backfill/universe/a1b/delisted.jsonl"


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    corp: str
    listedAt: str
    exitAt: Optional[str]
    source: str  # "A1A" | "A1B"


class UniverseProvider:
    def __init__(self, repo_root=".", include_delisted=False):
        self.repo_root = Path(repo_root)
        self.include_delisted = include_delisted
        self._entries = self._load()

    def _load(self):
        entries = []
        with open(self.repo_root / A1A_PATH, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                entries.append(UniverseEntry(r["ticker"], r["corp"], r["listedAt"], None, "A1A"))
        if self.include_delisted:
            with open(self.repo_root / A1B_PATH, encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    entries.append(UniverseEntry(r["ticker"], r["corp"], "", r.get("exitAt"), "A1B"))
        return entries

    @property
    def mode(self):
        return "A1A_A1B_MERGED" if self.include_delisted else "A1A_ONLY"

    @property
    def tickers(self):
        return {e.ticker for e in self._entries}

    @property
    def entries(self):
        return list(self._entries)

    @property
    def universe_hash(self):
        ordered = sorted(self._entries, key=lambda e: (e.source, e.ticker))
        canonical = json.dumps([asdict(e) for e in ordered], sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()

    def price_coverage_report(self, price_provider):
        """How much of this universe the given price provider actually covers.
        Reports facts only - SMOKE/PRIMARY classification happens in runner.py
        (Phase 3), keeping this function's responsibility singular."""
        missing = [e.ticker for e in self._entries if price_provider.coverage(e.ticker) is None]
        return {
            "universeMode": self.mode,
            "totalTickers": len(self._entries),
            "missingPriceTickers": len(missing),
            "fullyCovered": len(missing) == 0,
        }
