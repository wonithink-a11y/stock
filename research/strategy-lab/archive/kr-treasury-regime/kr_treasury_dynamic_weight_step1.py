#!/usr/bin/env python
"""10-KR-23-12 STEP 1: Signal Strength Metrics Review for Dynamic Weighting.

Reviews PIT-safe signal-strength metrics available for Treasury6M and LOWMOM60.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def quarterly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        q = d[:4] + "-Q" + str((int(d[5:7]) - 1) // 3 + 1)
        if q not in seen:
            seen.add(q)
            out.append(d)
    return out


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def select_as_of(records, as_of):
    best = None
    for rec in records:
        af = normd(rec[0])
        if af > as_of:
            continue
        if best is None or rec[1] > best[1] or (rec[1] == best[1] and af > normd(best[0])):
            best = rec
    return best


def main():
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    df["turnover20"] = (df["close"] * df["total_volume"]).groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])

    print("Loading raw A3c (treasuryRatio)...")
    TREAS, ISSUED = {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"):
                    continue
                t = r.get("ticker")
                if t is None:
                    continue
                af = normd(str(r["availableFrom"]))
                fy = int(r["fiscalYear"])
                try:
                    if r.get("istcTotqy") is not None:
                        TREAS.setdefault(t, []).append((af, fy, float(r["istcTotqy"])))
                    if r.get("isuStockTotqy") is not None:
                        ISSUED.setdefault(t, []).append((af, fy, float(r["isuStockTotqy"])))
                except (TypeError, ValueError):
                    pass

    def val(rm, t, as_of):
        cur = select_as_of(rm.get(t, []), as_of)
        return cur[2] if cur is not None else None

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    qmonths = quarterly_reb(all_dates)

    # Build treasury panel at monthly dates
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20", "close"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        tr = val(TREAS, t, d)
        isu = val(ISSUED, t, d)
        rows.append({"ticker": t, "date": d,
                     "treasuryRatio": tr / isu if (tr is not None and isu and isu != 0) else None})
    treas_panel = pd.DataFrame(rows)
    m = pd.merge(base, treas_panel, on=["ticker", "date"], how="left")
    m = m.dropna(subset=["treasuryRatio"])
    print(f"  treasuryRatio merged: {len(m)} rows")

    # Liquid universe
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()

    # === Compute PIT-safe signal strength metrics at each rebalance ===
    print("\n=== PIT-SAFE SIGNAL STRENGTH METRICS ===")
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n--- {p} ({len(period_dates)} months) ---")
        
        # LOWMOM60 metrics at monthly rebal
        lowmom_metrics = []
        for sd in period_dates:
            this = liq[liq["date"] == sd].dropna(subset=["mom60"])
            if len(this) < TOP_N:
                continue
            # Cross-sectional rank percentile of the top-N cutoff
            mom60_sorted = this.sort_values("mom60")
            cutoff_rank = TOP_N / len(this)  # ~top 1-2%
            top30 = mom60_sorted.head(TOP_N)
            mom60_spread = top30["mom60"].iloc[-1] - top30["mom60"].iloc[0]  # spread within top 30
            mom60_range = this["mom60"].max() - this["mom60"].min()
            
            lowmom_metrics.append({
                "date": sd,
                "n_liq": len(this),
                "top30_mom60_mean": top30["mom60"].mean(),
                "top30_mom60_spread": mom60_spread,
                "mom60_range": mom60_range,
                "mom60_std": this["mom60"].std(),
            })
        
        # Treasury metrics at quarterly rebal
        treas_metrics = []
        rebal_dates = [d for d in qmonths if d in period_dates]
        for sd in rebal_dates:
            this = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
            if len(this) < MIN_NAMES:
                continue
            this = this.copy()
            this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
            top_q = this[this["q"] == 4]
            treas_spread = top_q["treasuryRatio"].max() - top_q["treasuryRatio"].min()
            treas_range = this["treasuryRatio"].max() - this["treasuryRatio"].min()
            
            treas_metrics.append({
                "date": sd,
                "n_total": len(this),
                "top20pct_count": len(top_q),
                "top20pct_treas_mean": top_q["treasuryRatio"].mean(),
                "top20pct_treas_spread": treas_spread,
                "treas_range": treas_range,
                "treas_std": this["treasuryRatio"].std(),
            })
        
        # Print summary
        if lowmom_metrics:
            lm = pd.DataFrame(lowmom_metrics)
            print(f"  LOWMOM60 (monthly): n={len(lm)}")
            print(f"    mom60_std: mean={lm['mom60_std'].mean():.4f}, range=[{lm['mom60_std'].min():.4f}, {lm['mom60_std'].max():.4f}]")
            print(f"    top30_spread: mean={lm['top30_mom60_spread'].mean():.4f}, range=[{lm['top30_mom60_spread'].min():.4f}, {lm['top30_mom60_spread'].max():.4f}]")
            print(f"    n_liq: mean={lm['n_liq'].mean():.0f}")
        
        if treas_metrics:
            tr = pd.DataFrame(treas_metrics)
            print(f"  Treasury6M (quarterly): n={len(tr)}")
            print(f"    treas_std: mean={tr['treas_std'].mean():.4f}, range=[{tr['treas_std'].min():.4f}, {tr['treas_std'].max():.4f}]")
            print(f"    top20pct_spread: mean={tr['top20pct_treas_spread'].mean():.4f}, range=[{tr['top20pct_treas_spread'].min():.4f}, {tr['top20pct_treas_spread'].max():.4f}]")
            print(f"    n_total: mean={tr['n_total'].mean():.0f}")

    # === Candidate 1: Rolling IC (expanding window, PIT-safe) ===
    print("\n=== CANDIDATE 1: ROLLING IC (EXPANDING, PIT-SAFE) ===")
    # For each period, compute IC using only data up to that point
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        rebal_dates = [d for d in qmonths if d in period_dates]
        
        # Need forward returns for IC calculation - but that's ex-post!
        # PIT-safe: use IC computed from TRAIN period only, applied to VALID/TEST
        # Or: expanding window IC using data available at each rebalance
        
        # Actually, for dynamic weighting we need a metric available AT rebalance time
        # Rolling IC up to current date requires forward returns which we don't have yet
        # So rolling IC is NOT PIT-safe for real-time use
        
        print(f"  {p}: Rolling IC requires forward returns -> NOT PIT-safe for real-time weighting")

    # === Candidate 2: Cross-sectional Rank Percentile (PIT-safe) ===
    print("\n=== CANDIDATE 2: CROSS-SECTIONAL RANK PERCENTILE (PIT-SAFE) ===")
    print("  Available at each rebalance date:")
    print("  - LOWMOM60: mom60 rank percentile of portfolio cutoff (TOP_N / n_liq)")
    print("  - Treasury6M: treasuryRatio rank percentile of top-Q cutoff (always 80th percentile)")
    print("  These are observable and PIT-safe (no forward look)")
    
    # === Candidate 3: Signal Dispersion/Concentration (PIT-safe) ===
    print("\n=== CANDIDATE 3: SIGNAL DISPERSION (PIT-SAFE) ===")
    print("  Available at each rebalance date:")
    print("  - LOWMOM60: mom60 cross-sectional std, range, or top-N spread")
    print("  - Treasury6M: treasuryRatio cross-sectional std, range, top-Q spread")
    print("  High dispersion = stronger signal differentiation = more conviction")
    
    # === Candidate 4: Portfolio Concentration (PIT-safe) ===
    print("\n=== CANDIDATE 4: PORTFOLIO CONCENTRATION (PIT-SAFE) ===")
    print("  - LOWMOM60: Always TOP_N=30, so concentration fixed by construction")
    print("  - Treasury6M: Top-Q (top 20%) count varies with universe size")
    print("  Not very discriminating for LOWMOM60")

    # === Summary of Implementable Candidates ===
    print("\n=== IMPLEMENTABLE CANDIDATES (MAX 2) ===")
    
    print("""
CANDIDATE A: Cross-Sectional Signal Dispersion Ratio
-----------------------------------------------------
Definition:
  weight_treasury = treas_std / (treas_std + mom60_std)
  weight_lowmom   = mom60_std / (treas_std + mom60_std)

Where:
  - treas_std = cross-sectional std of treasuryRatio at quarterly rebalance
  - mom60_std = cross-sectional std of mom60 at monthly rebalance (use latest for quarterly months)

PIT-safe: Yes (both computed from current cross-section)
Available: Yes (already in data pipeline)
Frequency alignment: Need to align quarterly treas_std with monthly mom60_std
  -> Use treas_std from most recent quarterly rebalance for each month
  -> Or compute both at quarterly frequency

Pros: Simple, PIT-safe, reflects signal differentiation strength
Cons: Doesn't capture signal direction quality, only dispersion
""")

    print("""
CANDIDATE B: Top-Portfolio Spread Ratio (Signal-to-Noise Proxy)
---------------------------------------------------------------
Definition:
  weight_treasury = treas_spread / (treas_spread + mom60_spread)
  weight_lowmom   = mom60_spread / (treas_spread + mom60_spread)

Where:
  - treas_spread = top20% mean - bottom20% mean of treasuryRatio at quarterly rebalance
  - mom60_spread = top30 mom60 - bottom30 mom60 (or similar) at monthly rebalance

PIT-safe: Yes (cross-sectional spreads at rebalance)
Available: Yes (spreads computable from current data)
Frequency alignment: Same as Candidate A

Pros: Directly measures signal discriminatory power
Cons: More sensitive to outliers
""")

    # Check alignment feasibility
    print("=== FREQUENCY ALIGNMENT CHECK ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        rebal_dates = [d for d in qmonths if d in period_dates]
        print(f"  {p}: {len(period_dates)} monthly, {len(rebal_dates)} quarterly rebalances")
    
    print("""
  Alignment approach:
  - For each monthly date, find most recent quarterly rebalance date <= monthly date
  - Use that quarter's treasury metrics for the month
  - This is PIT-safe (quarterly signal already known)
""")

    # Save findings
    result = {
        "experiment": "10-KR-23-12 STEP 1: Signal strength metrics review",
        "findings": {
            "pit_safe_metrics_available": [
                "Cross-sectional rank percentile",
                "Cross-sectional std/range/spread",
                "Portfolio concentration (fixed for LOWMOM60)",
                "Universe size (n_liq, n_total)"
            ],
            "not_pit_safe": [
                "Rolling IC (requires forward returns)",
                "Ex-post Sharpe/CAGR",
                "Ex-post signal-to-noise"
            ],
            "implementable_candidates": [
                {
                    "name": "Cross-Sectional Signal Dispersion Ratio",
                    "formula": "w_treas = treas_std / (treas_std + mom60_std)",
                    "pit_safe": True,
                    "data_available": True,
                    "frequency_alignment": "quarterly treas_std carried forward to monthly"
                },
                {
                    "name": "Top-Portfolio Spread Ratio",
                    "formula": "w_treas = treas_spread / (treas_spread + mom60_spread)",
                    "pit_safe": True,
                    "data_available": True,
                    "frequency_alignment": "quarterly treas_spread carried forward to monthly"
                }
            ]
        },
        "executionTime_s": round(time.time() - t0, 1)
    }
    
    OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-dynamic-weight")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "kr-treasury-dynamic-weight-step1-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()