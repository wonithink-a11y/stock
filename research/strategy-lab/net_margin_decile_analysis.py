#!/usr/bin/env python
"""Net Margin factor validity check - same Book3 Ch11-style decile / forward-
return method as momentum_decile_analysis.py (reuses its rebalance-date,
decile, binary-split and monotonicity helpers directly - the only new part is
how the ranking value is looked up: a PIT as-of join against A3 fundamentals
instead of a rolling price computation).

Net Margin = netIncome / revenue (Book3 9.18). Chosen over the other Book3 Ch9
gaps (FCF Yield, EV/EBITDA, ROA, PSR) because those need fields this repo does
not collect (OCF, CapEx, EBITDA, total assets) or would reproduce the known
A2a(adjusted price)-vs-A3c(unadjusted shares) mismatch that already blocks
peg/perRelative (docs/verification/BF-1.1-vertical-slice, LAB-7) - Net Margin
needs neither price nor share count, so that mismatch class doesn't apply.

PIT rule: for rebalance date d, use the latest A3 record with
availableFrom <= d (Book3 9.12 - "availableAt <= decisionTime"), same
principle lib/a5/resolver.js already applies in production; this script does
not touch that file, it is a standalone research read.

Read-only against data/backfill/ (CLAUDE.md rule 4). Writes only under
research/strategy-lab/reports/.
"""
import bisect
import glob
import gzip
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from momentum_decile_analysis import (  # noqa: E402
    HORIZONS, decile_table, monotonicity, monthly_rebalance_dates, positive_vs_negative,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_GLOB = "data/backfill/fundamentals/a3/*.jsonl.gz"


def load_net_margin_series(repo_root, tickers):
    """ticker -> sorted [(availableFrom, netMargin), ...]. Skips zero/missing
    revenue (Book3 9.18: "Revenue가 0이면 계산하지 않는다") and missing netIncome."""
    by_ticker = {}
    for fp in sorted(glob.glob(os.path.join(repo_root, A3_GLOB))):
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                if t not in tickers:
                    continue
                revenue = r.get("revenue")
                net_income = r.get("netIncome")
                if not revenue or net_income is None:
                    continue
                by_ticker.setdefault(t, []).append((r["availableFrom"], net_income / revenue))
    for t in by_ticker:
        by_ticker[t].sort()
    return by_ticker


def build_panel_fundamental(bars_by_ticker, fundamental_series, rebalance_dates):
    """Same row shape as momentum_decile_analysis.build_panel, column named
    'momentum' for direct reuse of decile_table/positive_vs_negative/
    monotonicity (they only care about a ranking column + fwd{h} columns, not
    what the ranking factor actually is)."""
    rows = []
    for ticker, series in fundamental_series.items():
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            continue
        avail_dates = [d for d, _ in series]
        close = bars["close"]
        fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        for d in rebalance_dates:
            i = pos.get(d)
            if i is None:
                continue
            j = bisect.bisect_right(avail_dates, d) - 1  # PIT as-of: latest availableFrom <= d
            if j < 0:
                continue
            row = {"ticker": ticker, "date": d, "momentum": series[j][1]}
            ok = True
            for h in HORIZONS:
                v = fwd[h].iloc[i]
                if pd.isna(v):
                    ok = False
                    break
                row[f"fwd{h}"] = float(v)
            if ok:
                rows.append(row)
    return pd.DataFrame(rows)


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    start, end = calendar.days[0], calendar.days[-1]

    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, start, end, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    net_margin_series = load_net_margin_series(REPO_ROOT, universe.tickers)
    rebalance_dates = monthly_rebalance_dates(calendar, start, end)
    panel = build_panel_fundamental(bars_by_ticker, net_margin_series, rebalance_dates)

    table, panel_with_deciles = decile_table(panel)
    binary = positive_vs_negative(panel)  # here: profitable (netMargin>0) vs unprofitable
    mono = monotonicity(table)

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-17-net-margin-decile-analysis")
    os.makedirs(out_dir, exist_ok=True)
    report = {
        "question": "Does Net Margin (netIncome/revenue, PIT as-of A3) have forward-return predictive power in the A1A_ONLY universe?",
        "universeMode": universe.mode,
        "tickersWithFundamentalData": len(net_margin_series),
        "rebalanceDates": len(rebalance_dates),
        "panelRowsBeforeDecile": len(panel),
        "panelRowsAfterDecile": len(panel_with_deciles),
        "horizonsDays": list(HORIZONS),
        "decileTable": table.round(5).to_dict(orient="index"),
        "profitableVsUnprofitable": binary,
        "monotonicity": mono,
        "caveats": [
            "A1A_ONLY universe, same scope as the momentum re-check for direct comparability.",
            "PIT as-of join on A3 annual reports (availableFrom <= rebalance date) - no restatement/rceptNo tie-break beyond 'latest available' (A3's PIT rule is simpler than A3b/A3c's multi-report tie-break since A3 is one annual record per corp-year).",
            "No execution cost, slippage, or position sizing applied - raw forward price return only.",
            "Monthly rebalance windows overlap across horizons (20D/60D/120D) - not independent observations.",
        ],
    }
    out_path = os.path.join(out_dir, "v1.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"tickers with A3 data (in universe)={len(net_margin_series)}, rebalanceDates={len(rebalance_dates)}, "
          f"panel rows (with decile)={len(panel_with_deciles)}")
    print("\n-- decile table (mean forward return, 1=lowest Net Margin, 10=highest) --")
    print(table[[f"mean_fwd{h}" for h in HORIZONS] + ["n"]].round(4))
    print("\n-- profitable vs unprofitable --")
    for k, v in binary.items():
        print(f"{k}: n={v['n']}, " + ", ".join(f"mean_fwd{h}={v[f'mean_fwd{h}']:.4f}" for h in HORIZONS))
    print("\n-- monotonicity --")
    print(mono)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
