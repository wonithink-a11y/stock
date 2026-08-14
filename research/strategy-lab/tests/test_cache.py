"""CACHE CONTRACT tests. The integration tests touch real committed A2a data
(read-only) and write only under research/strategy-lab/.cache/ (gitignored) -
this does not violate CLAUDE.md rule 4, which is about data/backfill/ itself.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.data.a2aProvider import CACHE_DIR, A2aProvider
from engine.data.cacheKey import build_cache_key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_cache_key_changes_with_each_component():
    base = build_cache_key("hashA", "uniA", {"005930", "000660"}, "2016-01-01", "2020-12-31")[0]
    variants = [
        build_cache_key("hashB", "uniA", {"005930", "000660"}, "2016-01-01", "2020-12-31")[0],
        build_cache_key("hashA", "uniB", {"005930", "000660"}, "2016-01-01", "2020-12-31")[0],
        build_cache_key("hashA", "uniA", {"005930"}, "2016-01-01", "2020-12-31")[0],
        build_cache_key("hashA", "uniA", {"005930", "000660"}, "2017-01-01", "2020-12-31")[0],
        build_cache_key("hashA", "uniA", {"005930", "000660"}, "2016-01-01", "2021-12-31")[0],
    ]
    assert len(set(variants + [base])) == 6, "each changed component must produce a distinct key"


def test_cache_key_stable_for_identical_inputs():
    k1 = build_cache_key("hashA", "uniA", {"005930", "000660"}, "2016-01-01", "2020-12-31")[0]
    k2 = build_cache_key("hashA", "uniA", {"000660", "005930"}, "2016-01-01", "2020-12-31")[0]  # set order differs
    assert k1 == k2, "ticker set order must not affect the key"


def test_a2a_provider_cache_round_trip():
    cache_root = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a")
    shutil.rmtree(cache_root, ignore_errors=True)

    provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    tickers = {"005930", "000660"}
    bars1 = provider.load(tickers, "2020-01-01", "2020-03-31", universe_hash="test-universe")
    assert "005930" in bars1
    assert len(list((provider.repo_root / CACHE_DIR).glob("*.parquet"))) == 1

    provider2 = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars2 = provider2.load(tickers, "2020-01-01", "2020-03-31", universe_hash="test-universe")
    assert bars1["005930"].equals(bars2["005930"]), "cached load must match the original scan"

    shutil.rmtree(cache_root, ignore_errors=True)


def test_a2a_provider_cache_invalidated_by_different_range():
    cache_root = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a")
    shutil.rmtree(cache_root, ignore_errors=True)

    provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    provider.load({"005930"}, "2020-01-01", "2020-03-31", universe_hash="u1")
    files_after_first = list((provider.repo_root / CACHE_DIR).glob("*.parquet"))
    assert len(files_after_first) == 1

    provider.load({"005930"}, "2021-01-01", "2021-03-31", universe_hash="u1")  # different range
    files_after_second = list((provider.repo_root / CACHE_DIR).glob("*.parquet"))
    assert len(files_after_second) == 2, "a different date range must not reuse the first cache entry"

    shutil.rmtree(cache_root, ignore_errors=True)


def run():
    test_cache_key_changes_with_each_component()
    test_cache_key_stable_for_identical_inputs()
    test_a2a_provider_cache_round_trip()
    test_a2a_provider_cache_invalidated_by_different_range()
    print("test_cache: OK")


if __name__ == "__main__":
    run()
