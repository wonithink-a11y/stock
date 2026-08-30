#!/usr/bin/env python
"""10-KR-23-23A STEP 2: TreasuryRatio vs LOWMOM60 Double-Sort Analysis.

Performs 3x3 double-sort to test if TreasuryRatio alpha exists independent of LOWMOM60 level.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-kr-treasury-double-sort")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
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


def load_regime_lookup():
    rl = pd.read_parquet(REGIME_PATH)
    lut = rl.dropna(subset=["usableFromDate"])[["usableFromDate", "regime"]].copy()
    lut["usableFromDate"] = lut["usableFromDate"].astype(str)
    return lut.set_index("usableFromDate")["regime"]


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
    df["vol60"] = df["close"].groupby(df["ticker"]).transform(lambda s: s.pct_change().rolling(60).std() * np.sqrt(252))
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

    # Build treasury panel
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "vol60", "turnover20", "close", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
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
    liq = m[m["turnover20"] >= 100_000_000.0].copy()

    # === DOUBLE-SORT ANALYSIS ===
    print("\n=== 3x3 DOUBLE-SORT ANALYSIS ===")
    
    HORIZONS = {"3M": "fwd_d20", "6M": "fwd_d60", "9M": "fwd_d120"}
    
    # Store results per period
    double_sort_results = {"TRAIN": {}, "VALID": {}, "TEST": {}}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n{p}: {len(period_dates)} signal dates")
        
        # Aggregate results across dates
        cell_returns = {h: {i: {j: [] for j in range(3)} for i in range(3)} for h in HORIZONS}
        cell_vol60 = {i: {j: [] for j in range(3)} for i in range(3)}
        cell_n = {i: {j: [] for j in range(3)} for i in range(3)}
        
        for sd in period_dates:
            this = liq[liq["date"] == sd].dropna(subset=["mom60", "treasuryRatio", "vol60"])
            if len(this) < MIN_NAMES:
                continue
            
            # 3x3 double-sort
            this = this.copy()
            this["mom60_bucket"] = pd.qcut(this["mom60"].rank(method="first"), 3, labels=[0, 1, 2], duplicates="drop")
            this["treas_bucket"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 3, labels=[0, 1, 2], duplicates="drop")
            
            for i in range(3):  # mom60: 0=Low, 1=Mid, 2=High
                for j in range(3):  # treasury: 0=Low, 1=Mid, 2=High
                    cell = this[(this["mom60_bucket"] == i) & (this["treas_bucket"] == j)]
                    if len(cell) > 0:
                        cell_n[i][j].append(len(cell))
                        for h_name, h_col in HORIZONS.items():
                            cell_returns[h_name][i][j].extend(cell[h_col].dropna().tolist())
                        cell_vol60[i][j].extend(cell["vol60"].dropna().tolist())
        
        # Compute statistics for each cell
        double_sort_results[p] = {}
        for h_name in HORIZONS:
            double_sort_results[p][h_name] = {}
            for i in range(3):
                for j in range(3):
                    returns = cell_returns[h_name][i][j]
                    vol60s = cell_vol60[i][j]
                    n_vals = cell_n[i][j]
                    
                    if len(returns) > 0:
                        double_sort_results[p][h_name][f"L{i}_T{j}"] = {
                            "mean_return": float(np.mean(returns)),
                            "median_return": float(np.median(returns)),
                            "std_return": float(np.std(returns, ddof=1)) if len(returns) > 1 else 0,
                            "mean_vol60": float(np.mean(vol60s)) if vol60s else None,
                            "n_obs": len(returns),
                            "n_dates": len(n_vals),
                            "avg_n_per_date": float(np.mean(n_vals)) if n_vals else 0
                        }
                    else:
                        double_sort_results[p][h_name][f"L{i}_T{j}"] = {
                            "mean_return": None,
                            "median_return": None,
                            "std_return": None,
                            "mean_vol60": None,
                            "n_obs": 0,
                            "n_dates": len(n_vals),
                            "avg_n_per_date": 0
                        }
        
        # Print 3x3 table for each horizon
        for h_name in HORIZONS:
            print(f"\n{p} {h_name} double-sort (mean forward return):")
            print(f"        Treasury Low      Treasury Mid      Treasury High")
            for i in range(3):
                mom_label = ["LOWMOM Low", "LOWMOM Mid", "LOWMOM High"][i]
                row = f"  {mom_label:12s}: "
                for j in range(3):
                    key = f"L{i}_T{j}"
                    val = double_sort_results[p][h_name][key].get("mean_return", np.nan)
                    if val is not None:
                        row += f"{val:>8.4f}   "
                    else:
                        row += "      NA   "
                print(row)
    
    # === TREASURY SPREAD WITHIN EACH LOWMOM BUCKET ===
    print("\n=== TREASURY SPREAD (High - Low) WITHIN EACH LOWMOM BUCKET ===")
    
    treasury_spreads = {"TRAIN": {}, "VALID": {}, "TEST": {}}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        treasury_spreads[p] = {}
        for h_name in HORIZONS:
            treasury_spreads[p][h_name] = {}
            for i in range(3):
                mom_label = ["Low", "Mid", "High"][i]
                high_key = f"L{i}_T2"
                low_key = f"L{i}_T0"
                high_val = double_sort_results[p][h_name][high_key].get("mean_return", np.nan)
                low_val = double_sort_results[p][h_name][low_key].get("mean_return", np.nan)
                
                if high_val is not None and low_val is not None:
                    spread = high_val - low_val
                    treasury_spreads[p][h_name][mom_label] = float(spread)
                    print(f"  {p} {h_name} LOWMOM {mom_label}: Treasury High-Low = {spread:.4f}")
                else:
                    treasury_spreads[p][h_name][mom_label] = None
                    print(f"  {p} {h_name} LOWMOM {mom_label}: NA")
    
    # === KEY CELL COMPARISON ===
    print("\n=== KEY CELL COMPARISON ===")
    key_cells = {
        "A": ("Low", "High"),    # LOWMOM Low + Treasury High
        "B": ("Low", "Low"),     # LOWMOM Low + Treasury Low
        "C": ("High", "High"),   # LOWMOM High + Treasury High
        "D": ("High", "Low")     # LOWMOM High + Treasury Low
    }
    
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p}:")
        for h_name in HORIZONS:
            print(f"  {h_name}:")
            for label, (mom, treas) in key_cells.items():
                mom_idx = ["Low", "Mid", "High"].index(mom)
                treas_idx = ["Low", "Mid", "High"].index(treas)
                key = f"L{mom_idx}_T{treas_idx}"
                val = double_sort_results[p][h_name][key].get("mean_return", np.nan)
                vol = double_sort_results[p][h_name][key].get("mean_vol60", np.nan)
                n_obs = double_sort_results[p][h_name][key].get("n_obs", 0)
                if val is not None:
                    print(f"    Cell {label} (LOWMOM {mom}, Treasury {treas}): return={val:.4f}, vol60={vol:.4f}, n={n_obs}")
                else:
                    print(f"    Cell {label} (LOWMOM {mom}, Treasury {treas}): NA")
    
    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Check criteria:
    # - 최소 2개의 LOWMOM bucket에서 Treasury High > Treasury Low
    # - TEST에서 방향이 양(+)
    # - 3M/6M/9M 중 최소 2개 horizon에서 양(+)
    
    test_spreads = treasury_spreads["TEST"]
    
    test_buckets_positive = {}
    for mom in ["Low", "Mid", "High"]:
        count = sum(1 for h in ["3M", "6M", "9M"] if test_spreads[h][mom] is not None and test_spreads[h][mom] > 0)
        test_buckets_positive[mom] = count
    
    test_positive_buckets_by_horizon = {}
    for h in ["3M", "6M", "9M"]:
        count = sum(1 for mom in ["Low", "Mid", "High"] if test_spreads[h][mom] is not None and test_spreads[h][mom] > 0)
        test_positive_buckets_by_horizon[h] = count
    
    moms_with_2plus_horizons = sum(1 for mom in ["Low", "Mid", "High"] if test_buckets_positive[mom] >= 2)
    horizons_with_2plus_buckets = sum(1 for h in ["3M", "6M", "9M"] if test_positive_buckets_by_horizon[h] >= 2)
    
    print(f"\n  Per LOWMOM bucket positive horizons: {test_buckets_positive}")
    print(f"  Per horizon positive buckets: {test_positive_buckets_by_horizon}")
    print(f"  LOWMOM buckets with 2+ positive horizons: {moms_with_2plus_horizons}")
    print(f"  Horizons with 2+ positive buckets: {horizons_with_2plus_buckets}")
    
    # Final judgment
    if moms_with_2plus_horizons >= 2 and horizons_with_2plus_buckets >= 2:
        judgment = "YES"
    elif moms_with_2plus_horizons >= 1 or horizons_with_2plus_buckets >= 1:
        judgment = "PARTIAL"
    else:
        judgment = "NO"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    # === VOL60 CHECK ===
    print("\n=== VOL60 BY DOUBLE-SORT CELL ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p}:")
        for h_name in HORIZONS:
            for i in range(3):
                row = f"  LOWMOM {['Low','Mid','High'][i]}: "
                for j in range(3):
                    key = f"L{i}_T{j}"
                    vol = double_sort_results[p][h_name][key].get("mean_vol60")
                    if vol is not None:
                        row += f"{vol:.4f} "
                    else:
                        row += "NA "
                print(row)
    
    # === SAVE RESULTS ===
    result = {
        "experiment": "10-KR-23-23A STEP 2: TreasuryRatio vs LOWMOM60 Double-Sort",
        "double_sort_results": double_sort_results,
        "treasury_spreads": treasury_spreads,
        "test_buckets_positive": test_buckets_positive,
        "test_positive_buckets_by_horizon": test_positive_buckets_by_horizon,
        "moms_with_2plus_horizons": moms_with_2plus_horizons,
        "horizons_with_2plus_buckets": horizons_with_2plus_buckets,
        "judgment": judgment,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-double-sort-step2-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved JSON: {out_path}")
    
    # Save markdown
    md_path = os.path.join(OUT_DIR, "kr-treasury-double-sort-step2-findings.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 10-KR-23-23A STEP 2: TreasuryRatio vs LOWMOM60 Double-Sort Analysis\n\n")
        f.write(f"- Date: {time.strftime('%Y-%m-%d')}\n")
        f.write(f"- PIT-safe 3x3 double-sort\n\n")
        f.write("## 3x3 Double-Sort Results (Mean Forward Return)\n\n")
        for p in ["TRAIN", "VALID", "TEST"]:
            for h_name in HORIZONS:
                f.write(f"\n### {p} {h_name}\n\n")
                f.write("| | Treasury Low | Treasury Mid | Treasury High |\n")
                f.write("|---|---:|---:|---:|\n")
                for i in range(3):
                    mom_label = ["LOWMOM Low", "LOWMOM Mid", "LOWMOM High"][i]
                    row = f"| {mom_label} |"
                    for j in range(3):
                        key = f"L{i}_T{j}"
                        val = double_sort_results[p][h_name][key].get("mean_return", np.nan)
                        if val is not None:
                            row += f" {val:.4f} |"
                        else:
                            row += " NA |"
                    f.write(row + "\n")
        f.write("\n## Treasury Spread (High - Low) within LOWMOM Bucket\n\n")
        f.write("| Period | Horizon | LOWMOM Low | LOWMOM Mid | LOWMOM High |\n")
        f.write("|--------|--------:|-----------:|-----------:|------------:|\n")
        for p in ["TRAIN", "VALID", "TEST"]:
            for h_name in HORIZONS:
                row = f"| {p} | {h_name} |"
                for mom in ["Low", "Mid", "High"]:
                    val = treasury_spreads[p][h_name].get(mom)
                    if val is not None:
                        row += f" {val:+.4f} |"
                    else:
                        row += " NA |"
                    f.write(row + "\n")
        f.write("\n## Key Cell Comparison\n\n")
        for p in ["TRAIN", "VALID", "TEST"]:
            for h_name in HORIZONS:
                f.write(f"\n### {p} {h_name}\n\n")
                f.write("| Cell | LOWMOM | Treasury | Mean Return | Vol60 | N |\n")
                f.write("|------|--------|----------|------------:|------:|--:|\n")
                for label, (mom, treas) in key_cells.items():
                    mom_idx = ["Low", "Mid", "High"].index(mom)
                    treas_idx = ["Low", "Mid", "High"].index(treas)
                    key = f"L{mom_idx}_T{treas_idx}"
                    val = double_sort_results[p][h_name][key].get("mean_return", np.nan)
                    vol = double_sort_results[p][h_name][key].get("mean_vol60", np.nan)
                    n_obs = double_sort_results[p][h_name][key].get("n_obs", 0)
                    if val is not None:
                        f.write(f"| {label} | {mom} | {treas} | {val:.4f} | {vol:.4f} | {n_obs} |\n")
        f.write("\n## Treasury Spread by LOWMOM Bucket (TEST)\n\n")
        for h_name in HORIZONS:
            f.write(f"\n### {h_name}\n\n")
            f.write("| LOWMOM Bucket | 3M | 6M | 9M |\n")
            f.write("|---|---:|---:|---:|\n")
            for mom in ["Low", "Mid", "High"]:
                s3 = treasury_spreads["TEST"]["3M"].get(mom)
                s6 = treasury_spreads["TEST"]["6M"].get(mom)
                s9 = treasury_spreads["TEST"]["9M"].get(mom)
                s3s = f"{s3:+.4f}" if s3 is not None else "NA"
                s6s = f"{s6:+.4f}" if s6 is not None else "NA"
                s9s = f"{s9:+.4f}" if s9 is not None else "NA"
                f.write(f"| {mom} | {s3s} | {s6s} | {s9s} |\n")
        f.write(f"\n## Judgment\n\n")
        f.write(f"**{judgment}**\n\n")
        f.write("### Criteria Check\n\n")
        f.write(f"- LOWMOM buckets with 2+ positive horizons: {moms_with_2plus_horizons}\n")
        f.write(f"- Horizons with 2+ positive buckets: {horizons_with_2plus_buckets}\n")
        f.write(f"- Per LOWMOM bucket positive horizons: {test_buckets_positive}\n\n")
        f.write("### Interpretation\n\n")
        if judgment == "YES":
            f.write("TreasuryRatio alpha는 LOWMOM60 수준과 관계없이 존재합니다. 여러 LOWMOM 구간에서 여러 호라이즌에 걸쳐 Treasury High가 Treasury Low를 상회합니다.\n")
        elif judgment == "PARTIAL":
            f.write("TreasuryRatio alpha는 일부 LOWMOM 구간/호라이즌에서만 존재합니다. 전 구간에서 독립적이지 않습니다.\n")
        else:
            f.write("TreasuryRatio alpha는 LOWMOM60 수준에 의존적입니다. 독립적인 alpha로 보기 어렵습니다.\n")
    print(f"Saved MD: {md_path}")


if __name__ == "__main__":
    main()