#!/usr/bin/env python
"""Momentum12M factor validity check - Book3 Ch11-style decile / forward-return
analysis. Deliberately does NOT go through engine/execution or engine/portfolio:
those are built for discrete trade-signal strategies with a 10-slot concentrated
portfolio (5DC-v1A-P's shape). Forcing a cross-sectional "most months, most
tickers qualify" filter through that machinery would let slot tie-break rules
dominate the result instead of momentum itself - the same contract mismatch
benchmarks/b0_buy_hold.py's docstring already flags for a full-universe
strategy. So this script only needs A2a close prices + the trading calendar.

Question: does Momentum12M (Close[t]/Close[t-252]-1) have any forward-return
predictive power in the current A1A_ONLY universe, before any trading rule is
built on it.

Method: monthly rebalance dates -> rank all eligible tickers by momentum252 ->
decile split -> forward return at 20D/60D/120D per decile -> monotonicity check.
Also reports the simpler momentum>0 vs momentum<=0 split directly comparable to
the original filter hypothesis.

Read-only against data/backfill/ (CLAUDE.md rule 4). Writes only under
research/strategy-lab/reports/.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402 - reuse the same halt-artifact filter runner.py applies

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MOMENTUM_WINDOW = 252  # ~12 trading months, matches Book3 9.32's Momentum12M definition
SKIP_MONTH = 21  # ~1 trading month, Jegadeesh-Titman J=12,K=1 skip - excludes the short-term-reversal month
HORIZONS = (20, 60, 120)
N_DECILES = 10
VARIANTS = {
    "raw12m": lambda close: close / close.shift(MOMENTUM_WINDOW) - 1,
    "skip1m_12_1": lambda close: close.shift(SKIP_MONTH) / close.shift(MOMENTUM_WINDOW) - 1,
}


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen_months = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen_months:
            seen_months.add(ym)
            out.append(d)
    return out


def build_panel(bars_by_ticker, rebalance_dates, momentum_fn):
    """Long-format rows: one per (ticker, rebalance_date) with momentum and
    forward returns at each horizon. Uses future data on purpose (fwd return
    IS the thing being measured) - momentum itself only looks backward from
    (at most) the rebalance date."""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close = bars["close"]
        mom = momentum_fn(close)
        fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        for d in rebalance_dates:
            i = pos.get(d)
            if i is None:
                continue
            m = mom.iloc[i]
            if pd.isna(m):
                continue
            row = {"ticker": ticker, "date": d, "momentum": float(m)}
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


def decile_table(panel):
    """Assign deciles per rebalance date (cross-sectional rank each month, not
    pooled across the whole sample - Book3 9.47's Cross-Sectional Normalization
    principle: rank within each date's own universe snapshot)."""
    def _assign(group):
        if len(group) < N_DECILES * 3:  # need enough names for 10 bins to be meaningful
            group["decile"] = np.nan
            return group
        group["decile"] = pd.qcut(group["momentum"], N_DECILES, labels=False, duplicates="drop") + 1
        return group

    panel = panel.groupby("date", group_keys=False).apply(_assign)
    panel = panel.dropna(subset=["decile"])
    panel["decile"] = panel["decile"].astype(int)

    agg = {}
    for h in HORIZONS:
        col = f"fwd{h}"
        g = panel.groupby("decile")[col]
        agg[f"mean_fwd{h}"] = g.mean()
        agg[f"median_fwd{h}"] = g.median()
        agg[f"winrate_fwd{h}"] = g.apply(lambda s: float((s > 0).mean()))
    agg["n"] = panel.groupby("decile").size()
    table = pd.DataFrame(agg).sort_index()
    return table, panel


def positive_vs_negative(panel):
    grp = panel["momentum"] > 0
    out = {}
    for label, mask in (("momentum_positive", grp), ("momentum_nonpositive", ~grp)):
        sub = panel[mask]
        row = {"n": int(len(sub))}
        for h in HORIZONS:
            col = f"fwd{h}"
            row[f"mean_fwd{h}"] = float(sub[col].mean()) if len(sub) else None
            row[f"median_fwd{h}"] = float(sub[col].median()) if len(sub) else None
            row[f"winrate_fwd{h}"] = float((sub[col] > 0).mean()) if len(sub) else None
        out[label] = row
    return out


def monotonicity(table):
    out = {}
    for h in HORIZONS:
        col = f"mean_fwd{h}"
        spearman = table[col].corr(pd.Series(table.index, index=table.index), method="spearman")
        out[f"fwd{h}_decile_return_spearman"] = None if pd.isna(spearman) else round(float(spearman), 4)
        out[f"fwd{h}_decile10_minus_decile1"] = round(float(table[col].iloc[-1] - table[col].iloc[0]), 5)
    return out


def run_variant(bars_by_ticker, rebalance_dates, momentum_fn):
    panel = build_panel(bars_by_ticker, rebalance_dates, momentum_fn)
    table, panel_with_deciles = decile_table(panel)
    binary = positive_vs_negative(panel)
    mono = monotonicity(table)
    return {
        "panelRowsBeforeDecile": len(panel),
        "panelRowsAfterDecile": len(panel_with_deciles),
        "decileTable": table.round(5).to_dict(orient="index"),
        "positiveVsNonpositive": binary,
        "monotonicity": mono,
    }, table, binary, mono


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)  # A1A_ONLY, matches 5DC baseline
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    start, end = calendar.days[0], calendar.days[-1]

    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, start, end, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    rebalance_dates = monthly_rebalance_dates(calendar, start, end)

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-17-momentum-decile-analysis")
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "question": "Does Momentum12M have forward-return predictive power in the A1A_ONLY universe? "
                     "raw12m = Close[t]/Close[t-252]-1 (v1 result). "
                     "skip1m_12_1 = Close[t-21]/Close[t-252]-1, Jegadeesh-Titman J=12,K=1 skip-month re-check.",
        "universeMode": universe.mode,
        "tickersInUniverse": len(universe.tickers),
        "rebalanceDates": len(rebalance_dates),
        "horizonsDays": list(HORIZONS),
        "variants": {},
        "caveats": [
            "A1A_ONLY universe (currently-listed tickers only) - same survivorship scope as the 5DC SMOKE baseline, not A1A_A1B_MERGED.",
            "Monthly rebalance, cross-sectional decile assigned per date (Book3 9.47 cross-sectional normalization), not pooled.",
            "No execution cost, slippage, or position sizing applied - this measures raw price forward return only, not a tradeable strategy's P&L.",
            "Overlapping return windows (20D/60D/120D) across consecutive monthly dates are not independent observations - a caveat on statistical significance, not corrected for here.",
        ],
    }

    for name, fn in VARIANTS.items():
        variant_report, table, binary, mono = run_variant(bars_by_ticker, rebalance_dates, fn)
        report["variants"][name] = variant_report

        print(f"\n=== variant: {name} ===")
        print(f"panel rows (with decile)={variant_report['panelRowsAfterDecile']}")
        print(table[[f"mean_fwd{h}" for h in HORIZONS] + ["n"]].round(4))
        print("-- positive vs non-positive momentum --")
        for k, v in binary.items():
            print(f"{k}: n={v['n']}, " + ", ".join(f"mean_fwd{h}={v[f'mean_fwd{h}']:.4f}" for h in HORIZONS))
        print("-- monotonicity --")
        print(mono)

    out_path = os.path.join(out_dir, "v2_skip1m_recheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
