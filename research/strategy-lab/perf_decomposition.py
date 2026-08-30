#!/usr/bin/env python
"""5DC-v1A-P performance-decomposition analysis (RESEARCH, read-only).

Decomposes the A1A_ONLY SMOKE baseline (1,592 trades, CAGR -9.8%, MDD -75%)
statistically, EXCLUDING survivorship and corporate-action causes (per user).
Market regime is defined by an A2a equal-weighted index proxy (user-approved;
decision 2 re-opened for this analysis only, proxy method documented).

Writes only under research/strategy-lab/reports/2026-08-17-perf-decomposition/.
No production code/policy/params touched.
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from engine.data.a2aProvider import A2aProvider  # noqa: E402


REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
BASELINE = os.path.join(REPO, "research", "strategy-lab", "reports",
                        "2026-08-17-survivorship-bias-measurement", "run_a1a_only.json")
OUT_DIR = os.path.join(REPO, "research", "strategy-lab", "reports",
                       "2026-08-17-perf-decomposition")
START, END = "2014-05-13", "2026-08-03"


def _o(s):
    y, m, d = map(int, s.split("-"))
    return _date(y, m, d).toordinal()


def _fmt_date(ordinal):
    return _date.fromordinal(ordinal).isoformat()


def load_trades():
    r = json.load(open(BASELINE, encoding="utf-8"))
    return r["allTrades"]


def build_ew_index(use_cache=True):
    """A2a equal-weighted index: mean of per-symbol daily returns across the
    A1A universe, compounded to a level series. Survivor-based proxy - the
    universe is A1A-current symbols (delisted excluded). Documented caveat."""
    a2a = A2aProvider(repo_root=REPO, use_cache=use_cache)
    universe_tickers = set()
    with open(os.path.join(REPO, "data", "backfill", "universe", "a1a", "current.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            universe_tickers.add(json.loads(line)["ticker"])
    bars = a2a.load(universe_tickers, START, END, universe_hash="perf-decomp")
    rets = {}
    for t, df in bars.items():
        s = df["close"]
        s = s[~((df["open"] == 0) & (df["high"] == 0) & (df["low"] == 0))]
        r = s.pct_change()
        rets[t] = r
    panel = pd.DataFrame(rets)
    ew = panel.mean(axis=1, skipna=True).dropna()
    return ew


def classify_regime(ew, window=20, up_th=0.03, down_th=-0.03):
    """Regime per date: trailing `window` cumulative return of the EW index.
    UP >= up_th, DOWN <= down_th, else FLAT."""
    trailing = (1 + ew).rolling(window).apply(np.prod, raw=True) - 1
    regime = pd.Series("FLAT", index=trailing.index, dtype=object)
    regime[trailing >= up_th] = "UP"
    regime[trailing <= down_th] = "DOWN"
    return regime


def regime_at(trades, regime_series):
    """Attach regime at entry and at exit to each trade."""
    for t in trades:
        e = pd.Timestamp(t["entry_date"])
        x = pd.Timestamp(t["exit_date"])
        t["regime_entry"] = regime_series.get(e, "NA")
        t["regime_exit"] = regime_series.get(x, "NA")
        t["regime_entry_date"] = t["entry_date"]
    return trades


def yearly(trades):
    years = defaultdict(lambda: {"count": 0, "win": 0, "loss": 0, "grossWin": 0.0,
                                 "grossLoss": 0.0, "net": 0.0, "startEq": None, "endEq": None})
    for t in trades:
        y = t["exit_date"][:4]
        b = years[y]
        b["count"] += 1
        if t["pnl"] >= 0:
            b["win"] += 1
            b["grossWin"] += t["pnl"]
        else:
            b["loss"] += 1
            b["grossLoss"] += t["pnl"]
        b["net"] += t["pnl"]

    # equity stepping at exit events for per-year return
    events = sorted((t["exit_date"], t["pnl"]) for t in trades)
    eq = 100_000_000.0
    curve = {}
    year_start_eq = {str(y): None for y in range(2014, 2027)}
    year_start_eq["2014"] = 100_000_000.0
    last = {}
    for d, pnl in events:
        eq += pnl
        y = d[:4]
        if y not in curve:
            curve[y] = (eq, d)
        last[y] = eq
    for y in years:
        end_eq = last.get(y, eq if y == "2026" else None)
        start_eq = year_start_eq.get(y) or curve.get(str(int(y) - 1), (None, None))[0]
        # start of year = equity at last exit event before Jan 1 of that year
    # more robust: compute equity right before each year
    # equity as of last event strictly before year start
    all_events = [(d, pnl) for d, pnl in events]
    eq_before_year = {}
    eq_accum = 100_000_000.0
    events_by_date = defaultdict(list)
    for d, pnl in all_events:
        events_by_date[d].append(pnl)
    for year in range(2014, 2027):
        eq_before_year[str(year)] = eq_accum
        for d, pnls in sorted(events_by_date.items()):
            if d[:4] == str(year):
                eq_accum += sum(pnls)
    for y, b in years.items():
        b["startEq"] = eq_before_year[y]
        b["endEq"] = eq_before_year[str(int(y) + 1)] if int(y) < 2026 else eq
        b["yearReturn"] = (b["endEq"] / b["startEq"] - 1) if b["startEq"] else None
        b["winRate"] = round(b["win"] / b["count"], 4) if b["count"] else None
        b["pf"] = round(b["grossWin"] / abs(b["grossLoss"]), 4) if b["grossLoss"] else None
    return {y: years[y] for y in sorted(years)}


def by_exit_type(trades):
    out = {}
    for et in ["STOP", "TARGET", "TIME_EXIT"]:
        sub = [t for t in trades if t["exit_type"] == et]
        w = sum(1 for t in sub if t["pnl"] >= 0)
        grossW = sum(t["pnl"] for t in sub if t["pnl"] >= 0)
        grossL = sum(t["pnl"] for t in sub if t["pnl"] < 0)
        out[et] = {
            "count": len(sub),
            "winRate": round(w / len(sub), 4) if sub else None,
            "grossWin": round(grossW, 2),
            "grossLoss": round(grossL, 2),
            "net": round(sum(t["pnl"] for t in sub), 2),
            "pf": round(grossW / abs(grossL), 4) if grossL else None,
            "avgPnl": round(sum(t["pnl"] for t in sub) / len(sub), 2) if sub else None,
            "avgHold": round(sum(t["holding_sessions"] for t in sub) / len(sub), 1) if sub else None,
            "shareOfLoss": round(grossL / abs(sum(t["pnl"] for t in trades if t["pnl"] < 0)), 4),
        }
    return out


def by_holding(trades, bins):
    out = []
    for lo, hi, label in bins:
        sub = [t for t in trades if lo <= t["holding_sessions"] <= hi]
        if not sub:
            continue
        w = sum(1 for t in sub if t["pnl"] >= 0)
        grossW = sum(t["pnl"] for t in sub if t["pnl"] >= 0)
        grossL = sum(t["pnl"] for t in sub if t["pnl"] < 0)
        out.append({
            "label": label,
            "count": len(sub),
            "winRate": round(w / len(sub), 4),
            "net": round(sum(t["pnl"] for t in sub), 2),
            "grossWin": round(grossW, 2),
            "grossLoss": round(grossL, 2),
            "pf": round(grossW / abs(grossL), 4) if grossL else None,
            "avgPnl": round(sum(t["pnl"] for t in sub) / len(sub), 2),
        })
    return out


def monthly_net(trades):
    by_month = defaultdict(lambda: {"net": 0.0, "win": 0, "loss": 0, "count": 0})
    for t in trades:
        m = t["exit_date"][:7]
        b = by_month[m]
        b["net"] += t["pnl"]
        b["count"] += 1
        if t["pnl"] >= 0:
            b["win"] += 1
        else:
            b["loss"] += 1
    return {m: {"net": round(v["net"], 2), "count": v["count"],
                "winRate": round(v["win"] / v["count"], 4) if v["count"] else None}
            for m, v in sorted(by_month.items())}


def by_regime(trades, key):
    groups = defaultdict(list)
    for t in trades:
        groups[t[key]].append(t)
    out = {}
    for reg in ["UP", "FLAT", "DOWN", "NA"]:
        sub = groups.get(reg, [])
        if not sub:
            continue
        w = sum(1 for t in sub if t["pnl"] >= 0)
        grossW = sum(t["pnl"] for t in sub if t["pnl"] >= 0)
        grossL = sum(t["pnl"] for t in sub if t["pnl"] < 0)
        out[reg] = {
            "count": len(sub),
            "winRate": round(w / len(sub), 4),
            "grossWin": round(grossW, 2),
            "grossLoss": round(grossL, 2),
            "net": round(sum(t["pnl"] for t in sub), 2),
            "pf": round(grossW / abs(grossL), 4) if grossL else None,
            "avgPnl": round(sum(t["pnl"] for t in sub) / len(sub), 2),
        }
    return out


def samebar_exclusion(trades):
    same = [t for t in trades if t["entry_date"] == t["exit_date"]]
    rest = [t for t in trades if t["entry_date"] != t["exit_date"]]
    w = sum(1 for t in rest if t["pnl"] >= 0)
    grossW = sum(t["pnl"] for t in rest if t["pnl"] >= 0)
    grossL = sum(t["pnl"] for t in rest if t["pnl"] < 0)
    return {
        "sameBarCount": len(same),
        "sameBarNet": round(sum(t["pnl"] for t in same), 2),
        "sameBarByType": dict(Counter(t["exit_type"] for t in same)),
        "sameBarWinRate": round(sum(1 for t in same if t["pnl"] >= 0) / len(same), 4),
        "withoutSameBar": {
            "count": len(rest),
            "winRate": round(w / len(rest), 4),
            "net": round(sum(t["pnl"] for t in rest), 2),
            "finalEquity": 100_000_000 + round(sum(t["pnl"] for t in rest), 2),
            "grossWin": round(grossW, 2),
            "grossLoss": round(grossL, 2),
            "pf": round(grossW / abs(grossL), 4) if grossL else None,
        },
    }


def loss_concentration(trades):
    losses = [t for t in trades if t["pnl"] < 0]
    total_loss = abs(sum(t["pnl"] for t in losses))
    # by year
    by_year = defaultdict(float)
    for t in losses:
        by_year[t["exit_date"][:4]] += t["pnl"]
    # by exit type
    by_et = defaultdict(float)
    for t in losses:
        by_et[t["exit_type"]] += t["pnl"]
    # by regime (exit)
    by_reg = defaultdict(float)
    for t in losses:
        by_reg[t.get("regime_exit", "NA")] += t["pnl"]
    # top loss symbols
    by_sym = defaultdict(float)
    for t in trades:
        by_sym[t["symbol"]] += t["pnl"]
    top_sym_loss = sorted(by_sym.items(), key=lambda kv: kv[1])[:10]
    # monthly worst
    by_month = defaultdict(float)
    for t in losses:
        by_month[t["exit_date"][:7]] += t["pnl"]
    worst_months = sorted(by_month.items(), key=lambda kv: kv[1])[:12]
    return {
        "totalLoss": round(total_loss, 2),
        "lossCount": len(losses),
        "lossShareOfTrades": round(len(losses) / len(trades), 4),
        "byYear": {y: round(v, 2) for y, v in sorted(by_year.items())},
        "byExitType": {k: round(v, 2) for k, v in by_et.items()},
        "byRegimeExit": {k: round(v, 2) for k, v in by_reg.items() if v},
        "topLossSymbols": [(s, round(v, 2)) for s, v in top_sym_loss],
        "worstMonths": [(m, round(v, 2)) for m, v in worst_months],
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    trades = load_trades()

    print("building A2a equal-weighted index ...")
    ew = build_ew_index(use_cache=True)
    regime = classify_regime(ew)
    trades = regime_at(trades, regime)

    report = {
        "analysis_date": "2026-08-17",
        "model_name": "deepseek",
        "purpose": "strategy-internal performance decomposition (excl. survivorship & corporate action)",
        "baseline": "A1A_ONLY SMOKE 1,592 trades / CAGR -9.81% / MDD -75.00%",
        "dataSource": BASELINE,
        "regimeMethod": "A2a equal-weighted index proxy (mean of A1A-universe per-symbol daily returns), "
                        "trailing 20d cumulative return >=+3% UP, <=-3% DOWN, else FLAT. Survivor-based proxy; "
                        "decision-2 proxy ban re-opened by user for this analysis only.",
        "yearly": yearly(trades),
        "byExitType": by_exit_type(trades),
        "byHolding": by_holding(trades, [
            (0, 0, "same-bar(0)"), (1, 2, "1-2"), (3, 5, "3-5"), (6, 10, "6-10"),
            (11, 20, "11-20"), (21, 40, "21-40"), (41, 60, "41-60"), (61, 999, "61+"),
        ]),
        "byRegimeEntry": by_regime(trades, "regime_entry"),
        "byRegimeExit": by_regime(trades, "regime_exit"),
        "monthlyNet": monthly_net(trades),
        "samebarExclusion": samebar_exclusion(trades),
        "lossConcentration": loss_concentration(trades),
    }

    out_path = os.path.join(OUT_DIR, "decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print("saved:", out_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()