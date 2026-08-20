#!/usr/bin/env python
"""SL-2: build the competing equity-curve CANDIDATES from the same 2,154 admitted
trades and score each against one objective anchor.

ANCHOR (definition-free): the engine itself ended with cash 20,232,068.029 and
ZERO open positions (slim_diag.json). 100,000,000 + sum(pnl over 2,154 closed
positions) = 20,232,068.029 to float precision. Any daily equity curve over this
run must therefore terminate at that number. This is bookkeeping, not a choice
of convention - it does not decide how OPEN positions should be valued
mid-flight, which is the part that is genuinely a definition.

Candidates:
  A  realized-only        open positions carried at cost basis (= cash + cost).
                          Reproduces analyze_long_term_drawdown.py ("Ultra").
  B  as-published v1.json reproduces compute_annual_2154.py /
                          compute_annual_from_pickle.py ("Lightning"): daily
                          close MTM, but 5bps hardcoded costs and an
                          affordability re-check applied on top of decisions the
                          engine already made.
  C  faithful MTM         daily close MTM, contract costs (15bps from the Fill
                          objects), engine decisions replayed verbatim (no
                          re-admission logic), same-day cash-reuse ban honoured.
  C2 as C but with the entry-price fallback for missing closes (the 1,400-era
                          convention) instead of last-known-close carry-forward.

Reads only the slim extract. Writes only into this report directory.
"""
import json
import os
import pickle
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "reports", "2026-08-16-sl2-sequential")
INITIAL = 100_000_000.0

trades = json.load(open(os.path.join(OUT, "slim_trades.json")))
sessions = json.load(open(os.path.join(OUT, "sessions.json")))
daily_closes = pickle.load(open(os.path.join(OUT, "daily_closes.pkl"), "rb"))
diag = json.load(open(os.path.join(OUT, "slim_diag.json")))
RUNNER_CASH = diag["portfolio_cash"]

by_entry, by_exit = defaultdict(list), defaultdict(list)
for t in trades:
    by_entry[t["entry_date"]].append(t)
    by_exit[t["exit_date"]].append(t)


def replay(mtm, cost_bps_source, refuse_unaffordable, same_day_cash_ban=True,
           missing_close="carry_forward", same_bar_second_pass=True):
    """mtm: 'cost' | 'close'. cost_bps_source: 'fill' | 'five'.

    same_bar_second_pass mirrors engine/runner.py::_schedule_portfolio: a trade
    whose entry_date == exit_date cannot be closed in the exits-before-entries
    pass (it is not open yet), so it is retried after the entries of the same
    date. Skipping this retry silently strands the position open forever - which
    is exactly what the as-published path does."""
    cash = INITIAL
    open_pos = {}
    last_close = {}
    curve = []
    dropped = 0

    def close_trade(t, pending):
        bps = t["exit"]["cost_bps"] if cost_bps_source == "fill" else 5.0
        proceeds = t["exit"]["price"] * t["shares"]
        got = proceeds - proceeds * (bps / 10000)
        del open_pos[t["symbol"]]
        return pending + got

    for date in sessions:
        closes = daily_closes.get(date, {})
        last_close.update(closes)
        pending = 0.0
        for t in by_exit.get(date, []):
            if same_bar_second_pass and t["entry_date"] == date:
                continue  # same-bar: its own entry has not been admitted yet
            if t["symbol"] in open_pos:
                pending = close_trade(t, pending)
        if not same_day_cash_ban:
            cash += pending
            pending = 0.0
        for t in by_entry.get(date, []):
            sym = t["symbol"]
            bps = t["entry"]["cost_bps"] if cost_bps_source == "fill" else 5.0
            basis = t["entry"]["price"] * t["shares"]
            total = basis + basis * (bps / 10000)
            if refuse_unaffordable and total > cash:
                dropped += 1
                continue
            cash -= total
            open_pos[sym] = {"shares": t["shares"], "entry_price": t["entry"]["price"],
                             "cost": total}
        if same_bar_second_pass:
            for t in by_exit.get(date, []):
                if t["entry_date"] == date and t["symbol"] in open_pos:
                    pending = close_trade(t, pending)
        cash += pending
        if mtm == "cost":
            mv = sum(p["cost"] for p in open_pos.values())
        else:
            mv = 0.0
            for sym, p in open_pos.items():
                if missing_close == "carry_forward":
                    px = closes.get(sym, last_close.get(sym, p["entry_price"]))
                else:
                    px = closes.get(sym, p["entry_price"])
                mv += px * p["shares"]
        curve.append((date, cash + mv))
    return curve, cash, dropped, len(open_pos)


CANDIDATES = {
    "A_realized_only": dict(mtm="cost", cost_bps_source="fill", refuse_unaffordable=False),
    "B_as_published":  dict(mtm="close", cost_bps_source="five", refuse_unaffordable=True,
                            same_day_cash_ban=False, missing_close="entry_price",
                            same_bar_second_pass=False),
    # isolate the three defects of B one at a time, on top of C
    "B1_only_5bps":    dict(mtm="close", cost_bps_source="five", refuse_unaffordable=False),
    "B2_only_readmit": dict(mtm="close", cost_bps_source="fill", refuse_unaffordable=True),
    "B3_only_samebar": dict(mtm="close", cost_bps_source="fill", refuse_unaffordable=False,
                            same_bar_second_pass=False),
    "C_faithful_mtm":  dict(mtm="close", cost_bps_source="fill", refuse_unaffordable=False),
    "C2_entrypx_fallback": dict(mtm="close", cost_bps_source="fill", refuse_unaffordable=False,
                                missing_close="entry_price"),
}

results = {}
curves = {}
for name, kw in CANDIDATES.items():
    curve, cash, dropped, still_open = replay(**kw)
    curves[name] = curve
    yearly = {}
    for d, eq in curve:
        yearly[d[:4]] = eq  # last observation of each year wins
    results[name] = {
        "params": kw,
        "terminalEquity": curve[-1][1],
        "terminalCash": cash,
        "tradesDroppedByReAdmissionCheck": dropped,
        "positionsStillOpenAtEnd": still_open,
        "matchesRunnerCash": abs(cash - RUNNER_CASH) < 1.0,
        "terminalVsAnchorDiff": curve[-1][1] - RUNNER_CASH,
        "yearEndEquity": yearly,
    }

json.dump({
    "anchor": {
        "runnerFinalCash": RUNNER_CASH,
        "runnerOpenPositionsAtEnd": diag["open_at_end"],
        "initialPlusSumPnl": INITIAL + sum(t["pnl"] for t in trades),
        "note": "engine ended flat, so every candidate curve must terminate here",
    },
    "candidates": results,
}, open(os.path.join(OUT, "equity_candidates.json"), "w"), indent=1)

pickle.dump(curves, open(os.path.join(OUT, "equity_curves.pkl"), "wb"))

for name, r in results.items():
    print(f"{name:24s} terminal={r['terminalEquity']:>16,.0f} cash={r['terminalCash']:>16,.0f} "
          f"cashMatch={r['matchesRunnerCash']} dropped={r['tradesDroppedByReAdmissionCheck']} "
          f"openEnd={r['positionsStillOpenAtEnd']}")
print(f"{'ANCHOR':24s} terminal={RUNNER_CASH:>16,.0f}")
print("\n2024 year-end by candidate:")
for name, r in results.items():
    print(f"  {name:24s} {r['yearEndEquity'].get('2024', 0):>16,.0f}")

# ---- self-check: the anchor identity must hold, and C must reproduce it ----
assert abs((INITIAL + sum(t["pnl"] for t in trades)) - RUNNER_CASH) < 1.0, "anchor identity broken"
assert results["C_faithful_mtm"]["matchesRunnerCash"], "faithful replay does not reproduce runner cash"
assert abs(results["C_faithful_mtm"]["terminalEquity"] - RUNNER_CASH) < 1.0
assert abs(results["A_realized_only"]["terminalEquity"] - RUNNER_CASH) < 1.0
print("\nself-check OK")
