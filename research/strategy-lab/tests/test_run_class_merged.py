"""Integration test for engine/runner.py's A1A_A1B_MERGED path (2026-08-24
Strategy Lab PRIMARY promotion). Uses a small ticker_subset + short window so
it runs in seconds instead of the ~14-minute full-universe backtest.

PRIMARY does not require 100% price coverage (see runner.py's run_class
comment) - it only requires the merged universe was actually used. This test
locks that decision in: a merged run over a subset that includes a ticker
with zero A2a/A2b data must still classify PRIMARY, with the gap visible in
diag["universeCoverage"] rather than silently downgrading the run.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.runner import load_strategy, run_smoke  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_A1A_TICKER = "005930"        # active, A2a
_A1B_TICKER_WITH_DATA = "000060"  # delisted, A2b (verified real in test_a2b_and_merged_provider.py)
_TICKER_WITH_NO_DATA = "999999"   # not a real ticker anywhere


class _MergedParamsModule:
    """Wraps strategies/5dc_v1a_p/rule.py, overriding only PARAMS.universe.mode
    to A1A_A1B_MERGED - avoids depending on whichever mode 5dc_v1a_p/policy.json
    happens to ship with when this test runs."""

    def __init__(self, base):
        self._base = base
        self.PARAMS = copy.deepcopy(base.PARAMS)
        self.PARAMS["universe"]["mode"] = "A1A_A1B_MERGED"

    def __getattr__(self, name):
        return getattr(self._base, name)


def test_merged_run_with_missing_ticker_still_classifies_primary():
    base = load_strategy("5dc_v1a_p", REPO_ROOT)
    merged_rule = _MergedParamsModule(base)

    result = run_smoke(
        strategy_id="5dc_v1a_p",
        start="2016-01-01", end="2016-03-31",
        repo_root=REPO_ROOT,
        ticker_subset={_A1A_TICKER, _A1B_TICKER_WITH_DATA, _TICKER_WITH_NO_DATA},
        trace_limit=0,
        rule_module=merged_rule,
    )
    diag = result["diag"]
    assert diag["universeMode"] == "A1A_A1B_MERGED"
    assert diag["runClass"] == "PRIMARY"
    assert diag["universeCoverage"]["fullyCovered"] is False  # the gap is real, not hidden
    assert diag["universeCoverage"]["missingPriceTickers"] >= 1


def test_a1a_only_run_stays_smoke():
    result = run_smoke(
        strategy_id="5dc_v1a_p",
        start="2016-01-01", end="2016-03-31",
        repo_root=REPO_ROOT,
        ticker_subset={_A1A_TICKER},
        trace_limit=0,
        rule_module=load_strategy("5dc_v1a_p", REPO_ROOT),  # unmodified: whatever mode is committed
    )
    # A1A_ONLY is the only mode this checks; if 5dc_v1a_p ships as MERGED by
    # default, this exercises the currently-committed mode instead - still a
    # meaningful check (SMOKE iff not merged).
    diag = result["diag"]
    expected = "PRIMARY" if diag["universeMode"] == "A1A_A1B_MERGED" else "SMOKE"
    assert diag["runClass"] == expected


def run():
    test_merged_run_with_missing_ticker_still_classifies_primary()
    test_a1a_only_run_stays_smoke()
    print("test_run_class_merged: OK")


if __name__ == "__main__":
    run()
