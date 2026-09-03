#!/usr/bin/env python
"""10-KR-23-27: TreasuryRatio Alpha single quintile test.

In TEST period only, split TreasuryRatio into Q1..Q5 quintiles and report
mean 3M/6M/9M forward returns (HORIZONS = {"3M":"fwd_d20","6M":"fwd_d60","9M":"fwd_d120"}).

Judgment:
- if Q5 > Q1 in >=2 of 3 horizons -> TREASURY_ALPHA_SUPPORTED
- else -> TREASURY_ALPHA_WEAK
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-kr-treasury-alpha-single")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
MIN_TURNOVER = 100_000_000.0
N_QUINTILES = 5

HORIZONS = {"3M": "fwd_d20", "6M": "fwd_d60", "9M": "fwd_d120"}


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
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
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume", "fwd_d20", "fwd_d60", "fwd_d120"])
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

    # Build treasury panel
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
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

    period_dates = [d for d in months if period_of(d) == "TEST"]
    print(f"\nTEST period: {len(period_dates)} signal dates (from {period_dates[0]} to {period_dates[-1]})")

    quintile_returns = {h: {q: [] for q in range(1, 6)} for h in HORIZONS}
    quintile_counts = {h: {q: 0 for q in range(1, 6)} for h in HORIZONS}

    for sd in period_dates:
        this = liq[liq["date"] == sd].dropna(subset=["treasuryRatio", "mom60"])
        if len(this) < MIN_NAMES:
            continue
        this = this.copy()
        this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), N_QUINTILES,
                            labels=[1, 2, 3, 4, 5], duplicates="drop")
        for q in range(1, 6):
            cell = this[this["q"] == q]
            if len(cell) > 0:
                for h_name, h_col in HORIZONS.items():
                    vals = cell[h_col].dropna()
                    quintile_returns[h_name][q].extend(vals.tolist())
                    quintile_counts[h_name][q] += len(vals)

    print("\n=== TEST TreasuryRatio Q1..Q5 mean forward returns ===")
    header = f"{'Horizon':8s}" + "".join(f"{'Q'+str(q):>9s}" for q in range(1, 6)) + f"{'Q5-Q1':>10s}"
    print(header)
    print("-" * len(header))
    means = {h: {} for h in HORIZONS}
    spreads = {}
    for h_name in HORIZONS:
        row = f"{h_name:8s}"
        for q in range(1, 6):
            vals = quintile_returns[h_name][q]
            mean = float(np.mean(vals)) if len(vals) > 0 else np.nan
            means[h_name][q] = mean
            row += f"{mean:>9.4f}"
        spread = means[h_name][5] - means[h_name][1]
        spreads[h_name] = spread
        row += f"{spread:>+10.4f}"
        print(row)

    print("\n=== counts (N observations per quintile, per horizon) ===")
    for h_name in HORIZONS:
        print(f"  {h_name}: " + "  ".join(f"Q{q}={quintile_counts[h_name][q]}" for q in range(1, 6)))

    n_positive = sum(1 for h in HORIZONS if spreads[h] > 0)
    judgment = "TREASURY_ALPHA_SUPPORTED" if n_positive >= 2 else "TREASURY_ALPHA_WEAK"

    print("\n=== FINAL JUDGMENT ===")
    for h_name in HORIZONS:
        print(f"  {h_name}: Q5-Q1 = {spreads[h_name]:+.4f} ({'Q5>Q1' if spreads[h_name]>0 else 'Q5<=Q1'})")
    print(f"  Horizons with Q5 > Q1: {n_positive} of 3")
    print(f"\n>>> JUDGMENT: {judgment} <<<")

    result = {
        "experiment": "10-KR-23-27: TreasuryRatio Alpha single quintile test (TEST)",
        "horizons": list(HORIZONS.keys()),
        "mean_forward_return_by_quintile": means,
        "spread_Q5_minus_Q1": spreads,
        "counts_by_quintile": quintile_counts,
        "horizons_with_Q5_gt_Q1": n_positive,
        "judgment": judgment,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-alpha-single-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
