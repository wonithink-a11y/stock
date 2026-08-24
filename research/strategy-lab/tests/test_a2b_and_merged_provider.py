"""A2bProvider mirrors A2aProvider's tests (same contract, different source
directory). MergedPriceProvider tests confirm the routing itself: A1a tickers
resolve through A2a, A1b tickers resolve through A2b, and a ticker present in
neither returns no bars (not an error) - same "missing is absent, not a
crash" behavior the two underlying providers already have.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data.a2aProvider import A2aProvider
from engine.data.a2bProvider import A2bProvider
from engine.data.mergedPriceProvider import MergedPriceProvider

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 000060 (메리츠화재해상보험) is the A1b/A2b sample already verified real by
# lib/a5/priceSource.js's own regression (scripts/test-price-source.js) -
# reusing a ticker this project already knows has genuine A2b rows.
_A1B_TICKER_WITH_DATA = "000060"
_A1A_TICKER = "005930"


def test_a2b_provider_reads_real_delisted_ticker():
    provider = A2bProvider(repo_root=REPO_ROOT, use_cache=False)
    bars = provider.load({_A1B_TICKER_WITH_DATA}, "2016-01-01", "2016-12-31")
    assert _A1B_TICKER_WITH_DATA in bars
    assert len(bars[_A1B_TICKER_WITH_DATA]) > 0
    assert set(bars[_A1B_TICKER_WITH_DATA].columns) == {"open", "high", "low", "close", "volume"}


def test_a2b_provider_skips_non_year_files():
    # If delisted-exit.jsonl.gz or price-quality-excluded.jsonl.gz were scanned
    # as if they were year files, this would raise a schema violation instead
    # of just returning no rows for an unrelated ticker.
    provider = A2bProvider(repo_root=REPO_ROOT, use_cache=False)
    provider.load({_A1B_TICKER_WITH_DATA}, "2016-01-01", "2016-01-31")  # must not raise


def test_merged_provider_routes_a1a_ticker_through_a2a():
    merged = MergedPriceProvider(
        A2aProvider(repo_root=REPO_ROOT, use_cache=False),
        A2bProvider(repo_root=REPO_ROOT, use_cache=False),
    )
    bars = merged.load({_A1A_TICKER}, "2024-01-01", "2024-01-31")
    assert _A1A_TICKER in bars
    assert len(bars[_A1A_TICKER]) > 0


def test_merged_provider_routes_a1b_ticker_through_a2b():
    merged = MergedPriceProvider(
        A2aProvider(repo_root=REPO_ROOT, use_cache=False),
        A2bProvider(repo_root=REPO_ROOT, use_cache=False),
    )
    bars = merged.load({_A1B_TICKER_WITH_DATA}, "2016-01-01", "2016-12-31")
    assert _A1B_TICKER_WITH_DATA in bars
    assert len(bars[_A1B_TICKER_WITH_DATA]) > 0


def test_merged_provider_missing_ticker_is_absent_not_an_error():
    merged = MergedPriceProvider(
        A2aProvider(repo_root=REPO_ROOT, use_cache=False),
        A2bProvider(repo_root=REPO_ROOT, use_cache=False),
    )
    bars = merged.load({"999999"}, "2024-01-01", "2024-01-31")  # not a real ticker
    assert "999999" not in bars


def test_merged_provider_manifest_hash_combines_both():
    merged = MergedPriceProvider(
        A2aProvider(repo_root=REPO_ROOT, use_cache=False),
        A2bProvider(repo_root=REPO_ROOT, use_cache=False),
    )
    h = merged.manifest_hash
    assert set(h.keys()) == {"a2a", "a2b"}
    assert h["a2a"] and h["a2b"]


def run():
    test_a2b_provider_reads_real_delisted_ticker()
    test_a2b_provider_skips_non_year_files()
    test_merged_provider_routes_a1a_ticker_through_a2a()
    test_merged_provider_routes_a1b_ticker_through_a2b()
    test_merged_provider_missing_ticker_is_absent_not_an_error()
    test_merged_provider_manifest_hash_combines_both()
    print("test_a2b_and_merged_provider: OK")


if __name__ == "__main__":
    run()
