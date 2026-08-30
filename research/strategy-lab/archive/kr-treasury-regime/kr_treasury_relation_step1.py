#!/usr/bin/env python
"""10-KR-23-23A STEP 1: TreasuryRatio vs LOWMOM60 Cross-Sectional Relationship Analysis.

Analyzes cross-sectional relationship between TreasuryRatio and LOWMOM60 (mom60).
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-kr-treasury-relation")

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

    # Build treasury panel
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "vol60", "turnover20", "close"]].copy()
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

    # === CROSS-SECTIONAL ANALYSIS ===
    print("\n=== CROSS-SECTIONAL RELATIONSHIP ANALYSIS ===")
    
    results = {"TRAIN": [], "VALID": [], "TEST": []}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n{p}: {len(period_dates)} signal dates")
        
        for sd in period_dates:
            this = liq[liq["date"] == sd].dropna(subset=["mom60", "treasuryRatio", "vol60"])
            if len(this) < 30:
                continue
            
            # 1. Cross-sectional Pearson correlation
            pearson_r, pearson_p = pearsonr(this["treasuryRatio"], this["mom60"])
            
            # 2. Cross-sectional Spearman rank correlation
            spearman_r, spearman_p = spearmanr(this["treasuryRatio"], this["mom60"])
            
            # 3. R² from regression TreasuryRatio on mom60
            try:
                X = this["mom60"].values
                y = this["treasuryRatio"].values
                # Simple linear regression: y = a + b*x
                x_mean = np.mean(X)
                y_mean = np.mean(y)
                xy_cov = np.mean((X - x_mean) * (y - y_mean))
                x_var = np.mean((X - x_mean) ** 2)
                if x_var > 0:
                    b = xy_cov / x_var
                    a = y_mean - b * x_mean
                    y_pred = a + b * X
                    ss_res = np.sum((y - y_pred) ** 2)
                    ss_tot = np.sum((y - y_mean) ** 2)
                    if ss_tot > 0:
                        r2 = 1 - ss_res / ss_tot
                    else:
                        r2 = 0.0
                else:
                    r2 = 0.0
            except:
                r2 = np.nan
            
            # 4. Top20% vs Bottom20% TreasuryRatio: mom60 difference
            this = this.copy()
            this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
            top20 = this[this["q"] == 4]
            bot20 = this[this["q"] == 0]
            if len(top20) > 0 and len(bot20) > 0:
                mom60_diff = top20["mom60"].mean() - bot20["mom60"].mean()
                vol60_diff = top20["vol60"].mean() - bot20["vol60"].mean()
            else:
                mom60_diff = np.nan
                vol60_diff = np.nan
            
            results[p].append({
                "date": sd,
                "pearson_r": float(pearson_r),
                "spearman_r": float(spearman_r),
                "r2": float(r2) if not np.isnan(r2) else None,
                "mom60_top20_bot20_diff": float(mom60_diff),
                "vol60_top20_bot20_diff": float(vol60_diff),
                "n": len(this)
            })
    
    # === SUMMARY STATISTICS ===
    print("\n=== SUMMARY STATISTICS ===")
    summary = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        if not results[p]:
            summary[p] = {}
            continue
        df_r = pd.DataFrame(results[p])
        stats = {}
        for col in ["pearson_r", "spearman_r", "r2", "mom60_top20_bot20_diff", "vol60_top20_bot20_diff"]:
            if col in df_r.columns and df_r[col].notna().any():
                stats[col] = {
                    "mean": float(df_r[col].mean()),
                    "median": float(df_r[col].median()),
                    "std": float(df_r[col].std()),
                    "min": float(df_r[col].min()),
                    "max": float(df_r[col].max()),
                }
        stats["n_dates"] = len(df_r)
        stats["avg_n"] = float(df_r["n"].mean())
        summary[p] = stats
        
        print(f"\n{p} (n_dates={len(df_r)}):")
        for col, s in stats.items():
            if isinstance(s, dict):
                print(f"  {col}: mean={s['mean']:.4f} median={s['median']:.4f} std={s['std']:.4f} min={s['min']:.4f} max={s['max']:.4f}")
    
    # === DIRECTIONAL CONSISTENCY ===
    print("\n=== DIRECTIONAL CONSISTENCY ===")
    for col in ["pearson_r", "spearman_r", "r2", "mom60_top20_bot20_diff", "vol60_top20_bot20_diff"]:
        vals = [summary[p].get(col, {}).get("mean", np.nan) for p in ["TRAIN", "VALID", "TEST"]]
        if not any(np.isnan(v) for v in vals):
            signs = [v > 0 for v in vals]
            print(f"  {col}: TRAIN={vals[0]:.4f} VALID={vals[1]:.4f} TEST={vals[2]:.4f} signs={signs} consistent={all(signs) or not any(signs)}")
    
    # === OVERLAP JUDGMENT ===
    print("\n=== OVERLAP JUDGMENT ===")
    pearson_means = [summary[p].get("pearson_r", {}).get("mean", 0) for p in ["TRAIN", "VALID", "TEST"]]
    spearman_means = [summary[p].get("spearman_r", {}).get("mean", 0) for p in ["TRAIN", "VALID", "TEST"]]
    r2_means = [summary[p].get("r2", {}).get("mean", 0) for p in ["TRAIN", "VALID", "TEST"]]
    
    abs_pearson = [abs(v) for v in pearson_means]
    abs_spearman = [abs(v) for v in spearman_means]
    
    avg_abs_pearson = np.mean(abs_pearson)
    avg_abs_spearman = np.mean(abs_spearman)
    avg_r2 = np.mean([v for v in r2_means if not np.isnan(v)])
    
    print(f"Mean |Pearson|: {avg_abs_pearson:.4f} ({pearson_means})")
    print(f"Mean |Spearman|: {avg_abs_spearman:.4f} ({spearman_means})")
    print(f"Mean R²: {avg_r2:.4f} ({r2_means})")
    
    # Classification
    if avg_abs_pearson > 0.5 or avg_abs_spearman > 0.5 or avg_r2 > 0.3:
        overlap_judgment = "HIGH OVERLAP"
    elif avg_abs_pearson > 0.2 or avg_abs_spearman > 0.2 or avg_r2 > 0.1:
        overlap_judgment = "MODERATE OVERLAP"
    else:
        overlap_judgment = "LOW OVERLAP"
    
    print(f"\n>>> OVERLAP JUDGMENT: {overlap_judgment} <<<")
    print(f"  Criteria: avg |Pearson|={avg_abs_pearson:.3f}, avg |Spearman|={avg_abs_spearman:.3f}, avg R²={avg_r2:.3f}")
    
    # === SAVE RESULTS ===
    result = {
        "experiment": "10-KR-23-23A STEP 1: TreasuryRatio vs LOWMOM60 Cross-Sectional Analysis",
        "period_results": results,
        "summary": summary,
        "overlap_judgment": overlap_judgment,
        "metrics": {
            "avg_abs_pearson": avg_abs_pearson,
            "avg_abs_spearman": avg_abs_spearman,
            "avg_r2": avg_r2,
            "pearson_means": pearson_means,
            "spearman_means": spearman_means,
            "r2_means": r2_means
        },
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-relation-step1-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved JSON: {out_path}")
    
    # Save markdown
    md_path = os.path.join(OUT_DIR, "kr-treasury-relation-step1-findings.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 10-KR-23-23A STEP 1: TreasuryRatio vs LOWMOM60 Cross-Sectional Analysis\n\n")
        f.write(f"- Date: {time.strftime('%Y-%m-%d')}\n")
        f.write(f"- PIT-safe analysis using existing data\n")
        f.write(f"- No forward returns used\n\n")
        f.write("## Summary Statistics\n\n")
        f.write("| Period | n_dates | avg_n | Pearson_r | Spearman_r | R² | mom60_diff | vol60_diff |\n")
        f.write("|--------|--------:|------:|----------:|-----------:|---:|-----------:|-----------:|\n")
        for p in ["TRAIN", "VALID", "TEST"]:
            s = summary[p]
            f.write(f"| {p} | {s.get('n_dates',0)} | {s.get('avg_n',0):.0f} | {s.get('pearson_r',{}).get('mean',0):.4f} | {s.get('spearman_r',{}).get('mean',0):.4f} | {s.get('r2',{}).get('mean',0):.4f} | {s.get('mom60_top20_bot20_diff',{}).get('mean',0):.4f} | {s.get('vol60_top20_bot20_diff',{}).get('mean',0):.4f} |\n")
        f.write("\n## Directional Consistency\n\n")
        for col in ["pearson_r", "spearman_r", "r2", "mom60_top20_bot20_diff", "vol60_top20_bot20_diff"]:
            vals = [summary[p].get(col, {}).get("mean", np.nan) for p in ["TRAIN", "VALID", "TEST"]]
            if not any(np.isnan(v) for v in vals):
                signs = [v > 0 for v in vals]
                f.write(f"- {col}: TRAIN={vals[0]:.4f} VALID={vals[1]:.4f} TEST={vals[2]:.4f} consistent={all(signs) or not any(signs)}\n")
        f.write(f"\n## Overlap Judgment\n\n")
        f.write(f"**{overlap_judgment}**\n\n")
        f.write(f"- Mean |Pearson|: {avg_abs_pearson:.3f}\n")
        f.write(f"- Mean |Spearman|: {avg_abs_spearman:.3f}\n")
        f.write(f"- Mean R²: {avg_r2:.3f}\n\n")
        f.write("## Interpretation\n\n")
        if overlap_judgment == "HIGH OVERLAP":
            f.write("TreasuryRatio와 LOWMOM60은 강한 선형/비선형 관계로 높은 중복성을 가집니다. 두 신호는 거의 같은 정보를 담고 있을 가능성이 높습니다.\n")
        elif overlap_judgment == "MODERATE OVERLAP":
            f.write("TreasuryRatio와 LOWMOM60은 어느 정도의 관계는 있으나, 각각 독립적인 정보도 상당 부분 포함하고 있습니다.\n")
        else:
            f.write("TreasuryRatio와 LOWMOM60은 거의 독립적인 신호로, 결합 시 상호 보완적인 효과를 기대할 수 있습니다.\n")
    print(f"Saved MD: {md_path}")


if __name__ == "__main__":
    main()