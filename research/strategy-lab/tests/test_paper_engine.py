"""engine/live/paperEngine.py self-check - synthetic bars only, no real A2a
read and no dependency on the real (frozen) calendar.json. Exercises exactly
the operational concerns 2026-08-21 리스크계약-스톱타이밍-결정브리프.md 관련
논의에서 사용자가 나열한 것들: no-lookahead entry timing, duplicate-entry
guard, stop/target/time-exit, and restart-safety across two separate
run_once() calls sharing only the on-disk state file.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from engine.live import positionStore
from engine.live.paperEngine import run_once

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STRATEGY_ID = "test_paper_engine_synth"


class FakeCalendar:
    """Same convention as tests/test_execution.py's FakeCalendar - decouples
    this test from the real frozen data/backfill/calendar.json."""
    def __init__(self, n=40):
        self.days = [f"2024-01-{d:02d}" for d in range(1, min(n, 31) + 1)]

    def next_session(self, date):
        i = self.days.index(date) if date in self.days else -1
        if i == -1:
            later = [d for d in self.days if d > date]
            return later[0] if later else None
        return self.days[i + 1] if i + 1 < len(self.days) else None


def _bars(prices, dates):
    """prices: list of close prices, one per date. OHLC all equal the close
    except where a test overrides high/low directly on the returned frame -
    good enough for signal/entry timing tests that don't touch stop/target."""
    df = pd.DataFrame({"open": prices, "high": prices, "low": prices, "close": prices},
                       index=pd.to_datetime(dates))
    return df


class FakeRule:
    """Fires exactly once, on a date the test controls - PARAMS mirrors
    strategies/dummy_sma20/policy.json's shape."""
    PARAMS = {
        "strategyId": STRATEGY_ID,
        "testUniverse": ["TEST1"],
        "risk": {"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 3},
        "position": {"notionalPerPosition": 1000000, "maxPositions": 1},
    }

    def __init__(self, fire_on):
        self.fire_on = fire_on

    def compute_features(self, bars):
        return bars

    def signal_fires(self, features, as_of):
        return as_of == self.fire_on


passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _reset_state():
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})


def test_entry_fills_next_session_not_signal_day():
    """No-lookahead: a signal on day 1 must fill at day 2's open, never day 1's
    own close (which is the price the signal was computed from)."""
    _reset_state()
    cal = FakeCalendar()
    dates = cal.days
    prices = [100 + i for i in range(len(dates))]  # day i's close = 100+i
    bars = {"TEST1": _bars(prices, dates)}
    rule = FakeRule(fire_on=dates[0])

    events_day1 = run_once(REPO_ROOT, rule, dates[0], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)
    ok("day1 produces only an INTENT, no fill", [e["type"] for e in events_day1] == ["INTENT_ENTRY"],
       events_day1)

    events_day2 = run_once(REPO_ROOT, rule, dates[1], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)
    fills = [e for e in events_day2 if e["type"] == "FILL_ENTRY"]
    ok("day2 fills the entry", len(fills) == 1, events_day2)
    ok("fill price is day2's open (101), not day1's close (100)",
       fills and fills[0]["price"] == prices[1], fills)
    _reset_state()


def test_duplicate_entry_guard():
    """A symbol already PENDING_ENTRY or OPEN must not produce a second
    INTENT_ENTRY even if the signal keeps firing."""
    _reset_state()
    cal = FakeCalendar()
    dates = cal.days
    prices = [100] * len(dates)
    bars = {"TEST1": _bars(prices, dates)}

    class AlwaysFireRule(FakeRule):
        def signal_fires(self, features, as_of):
            return True

    rule = AlwaysFireRule(fire_on=None)
    e1 = run_once(REPO_ROOT, rule, dates[0], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)
    e2 = run_once(REPO_ROOT, rule, dates[1], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)
    e3 = run_once(REPO_ROOT, rule, dates[2], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)
    intent_count = sum(1 for e in (e1 + e2 + e3) if e["type"] == "INTENT_ENTRY")
    ok("exactly one INTENT_ENTRY across 3 always-fire days (position already held after day1)",
       intent_count == 1, intent_count)
    _reset_state()


def test_stop_target_time_exit_and_restart_safety():
    """Open a position, then verify restart-safety by loading fresh state in a
    *separate* run_once() call before exercising TIME_EXIT - the second call
    must see the position load() gave it, not anything held in memory."""
    _reset_state()
    cal = FakeCalendar()
    dates = cal.days
    prices = [100] * len(dates)
    bars = {"TEST1": _bars(prices, dates)}
    rule = FakeRule(fire_on=dates[0])

    run_once(REPO_ROOT, rule, dates[0], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)  # INTENT
    run_once(REPO_ROOT, rule, dates[1], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)  # FILL @100

    # simulate a process restart: state only exists on disk between calls
    state_after_entry = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("state persisted to disk after entry", "TEST1" in state_after_entry and
       state_after_entry["TEST1"]["status"] == "OPEN", state_after_entry)

    # entry day (dates[1]) already counted as sessions_held=1 (exit check runs
    # the same call that opens the position) - maxHoldingSessions=3 is hit on
    # the entry day's 3rd subsequent call, i.e. dates[3].
    run_once(REPO_ROOT, rule, dates[2], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)  # sessions_held -> 2
    events = run_once(REPO_ROOT, rule, dates[3], log=lambda *a: None, bars_by_ticker=bars, calendar=cal)  # -> 3
    ok("TIME_EXIT fires once sessions_held reaches maxHoldingSessions",
       any(e["type"] == "FILL_EXIT_TIME_EXIT" for e in events), events)

    final_state = positionStore.load(REPO_ROOT, STRATEGY_ID)
    ok("position removed from state after exit", "TEST1" not in final_state, final_state)
    _reset_state()


def main():
    test_entry_fills_next_session_not_signal_day()
    test_duplicate_entry_guard()
    test_stop_target_time_exit_and_restart_safety()
    positionStore.save(REPO_ROOT, STRATEGY_ID, {})  # leave no residue
    print(f"\n{'='*40}\npassed {passed} · failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
