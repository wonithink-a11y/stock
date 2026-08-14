"""PriceProvider - the one abstract interface the engine depends on for price data.

A2a/A2b concrete providers only need to implement this. execution/portfolio/metrics
never know which concrete provider is wired in - that is how A2b can be added later
without touching engine code (Phase 1 design item E)."""
from abc import ABC, abstractmethod


class PriceProvider(ABC):
    @abstractmethod
    def load(self, tickers, start, end, universe_hash="none"):
        """Return {ticker: pandas.DataFrame[open,high,low,close,volume]} indexed by
        date (ascending). Rows outside [start, end] are not included."""
        raise NotImplementedError

    @abstractmethod
    def coverage(self, ticker):
        """(first_date, last_date) as 'YYYY-MM-DD' strings, or None if no data."""
        raise NotImplementedError

    @property
    @abstractmethod
    def manifest_hash(self):
        """Hash of the upstream manifest this provider reads from. Used in the
        cache key and in run manifests for reproducibility."""
        raise NotImplementedError
