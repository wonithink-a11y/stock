"""A1A_A1B_MERGED price adapter - routes A1a tickers to A2a and A1b tickers to
A2b, exposing one PriceProvider so execution/portfolio/metrics never need to
know a merge happened (same "one interface" principle as priceProvider.py).

No ticker can be in both A1a and A1b at once (BF-1.1 universe contract - a
ticker is either currently listed or delisted, never both), so a plain dict
union of the two providers' results cannot collide. A2aProvider.load() and
A2bProvider.load() already return only tickers they actually found rows for
(missing tickers are simply absent, not an error) - calling both with the full
combined ticker set is safe even though most of it belongs to the other side.
"""
from .priceProvider import PriceProvider


class MergedPriceProvider(PriceProvider):
    def __init__(self, a2a_provider, a2b_provider):
        self._a2a = a2a_provider
        self._a2b = a2b_provider
        self._bars = {}

    @property
    def manifest_hash(self):
        return {"a2a": self._a2a.manifest_hash, "a2b": self._a2b.manifest_hash}

    def coverage(self, ticker):
        return self._bars_source(ticker).coverage(ticker)

    def _bars_source(self, ticker):
        return self._a2a if ticker in self._a2a._bars else self._a2b

    def load(self, tickers, start, end, universe_hash="none"):
        tickers = set(tickers)
        bars_a2a = self._a2a.load(tickers, start, end, universe_hash=universe_hash)
        bars_a2b = self._a2b.load(tickers, start, end, universe_hash=universe_hash)
        overlap = set(bars_a2a) & set(bars_a2b)
        if overlap:
            raise ValueError(f"ticker present in both A2a and A2b: {sorted(overlap)[:5]} - universe contract violated")
        self._bars = {**bars_a2a, **bars_a2b}
        return self._bars
