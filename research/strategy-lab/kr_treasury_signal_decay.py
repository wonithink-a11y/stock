#!/usr/bin/env python
"""10-KR-23-18: TreasuryRatio Alpha Stability / Signal Decay Test.

Tests 3M/6M/9M forward returns for TreasuryRatio across periods.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-signal-decay")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS


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


def assess_monotonic(vals):
    if any(v is None for v in vals):
        return "UNKNOWN"
    increasing = sum(1 for i in range(1, len(vals)) if vals[i] > vals[i-1])
    decreasing = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i-1])
    if increasing >= len(vals) - 2:
        return "MONOTONIC_INCREASING"
    elif increasing >= len(vals) * 0.6:
        return "MOSTLY_INCREASING"
    elif decreasing >= len(vals) - 2:
        return "MONOTONIC_DECREASING"
    elif decreasing >= len(vals) * 0.6:
        return "MOSTLY_DECREASING"
    else:
        return "NON_MONOTONIC"


def profile(monthly_rets):
    if not monthly_rets or len(monthly_rets) < 2:
        return {"n": len(monthly_rets) if monthly_rets else 0}
    mr = np.array([x["ret"] for x in monthly_rets])
    n = len(mr)
    span = n / 12
    eq = float(np.prod(1 + mr))
    cn = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    total_turnover = sum(x.get("turnover", 0) for x in monthly_rets)
    avg_turnover = total_turnover / len(monthly_rets) * 12 if monthly_rets else 0
    roundtrips = sum(x.get("roundtrips", 0) for x in monthly_rets)
    avg_holding = np.mean([x.get("holding_months", 1) for x in monthly_rets]) if monthly_rets else 0
    gross_cagr = None
    if monthly_rets and "gross_ret" in monthly_rets[0]:
        gm = np.array([x["gross_ret"] for x in monthly_rets])
        geq = float(np.prod(1 + gm))
        gross_cagr = geq ** (1 / max(span, 1e-9)) - 1 if geq > 0 else None
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4),
            "avgAnnualTurnover": round(avg_turnover, 2),
            "totalRoundTrips": round(roundtrips, 2),
            "avgHoldingMonths": round(avg_holding, 1),
            "grossCAGR": round(gross_cagr, 4) if gross_cagr is not None else None,
            "costDrag": round(cn - gross_cagr, 4) if gross_cagr is not None else None}


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
    base = df[df["date"].isin(months)][["ticker", "date", "turnover20", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
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

    # === 1. QUINTILE/DECILE IC ACROSS HORIZONS ===
    print("\n=== QUINTILE IC ACROSS HORIZONS ===")
    
    horizons = {"3M": "fwd_d20", "6M": "fwd_d60", "9M": "fwd_d120"}
    ic_results = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        ic_results[p] = {}
        
        for h_name, h_col in horizons.items():
            ic_results[p][h_name] = {"quintile": {}, "decile": {}}
            
            for n_bins, label in [(5, "quintile"), (10, "decile")]:
                recs = []
                spreads = []
                for sd in dates:
                    this = m[m["date"] == sd].dropna(subset=["treasuryRatio", h_col])
                    if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                        continue
                    this = this.copy()
                    this["bin"] = pd.qcut(this["treasuryRatio"].rank(method="first"), n_bins, labels=False, duplicates="drop")
                    r = spearmanr(this["treasuryRatio"], this[h_col])
                    if not np.isnan(r.statistic):
                        recs.append(float(r.statistic))
                    if label == "quintile":
                        spreads.append(float(this[this["bin"] == 4][h_col].mean() - this[this["bin"] == 0][h_col].mean()))
                
                if recs:
                    v = np.array(recs)
                    ic_results[p][h_name][label] = {
                        "n": len(recs),
                        "ic_mean": float(v.mean()),
                        "ic_t": float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))) if v.std(ddof=1) > 0 else None,
                        "spread_mean": float(np.mean(spreads)) if spreads else None
                    }
                else:
                    ic_results[p][h_name][label] = {"n": 0}
    
    # Print IC table
    print(f"{'Period':6s} | {'Horizon':5s} | {'Bins':8s} | {'IC_mean':>8s} | {'IC_t':>6s} | {'Q5-Q1_spread':>12s} | {'n':>4s}")
    print("-" * 75)
    for p in ["TRAIN", "VALID", "TEST"]:
        for h in ["3M", "6M", "9M"]:
            for label in ["quintile", "decile"]:
                r = ic_results[p][h][label]
                if r.get("n", 0) > 0:
                    ic_t = r.get('ic_t', 0)
                    spread = r.get('spread_mean', 0)
                    ic_t_str = f"{ic_t:>6.2f}" if ic_t is not None else "    NA"
                    spread_str = f"{spread:>12.4f}" if spread is not None else "         NA"
                    print(f"{p:6s} | {h:5s} | {label:8s} | {r['ic_mean']:>8.4f} | {ic_t_str} | {spread_str} | {r['n']:>4d}")

    # === 2. QUINTILE PORTFOLIO CAGR (6M hold) ===
    print("\n=== QUINTILE PORTFOLIO (6M hold, quarterly rebal) ===")
    
    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}
    
    portfolio_results = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        period_qdates = [d for d in qmonths if d in period_dates]
        portfolio_results[p] = {}
        
        for q in range(5):
            out = []
            for k, sd in enumerate(period_qdates):
                if k + 2 >= len(period_qdates):
                    break
                this = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                if len(this) < MIN_NAMES:
                    continue
                this = this.copy()
                this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                picks = this[this["q"] == q]["ticker"].tolist()
                if not picks:
                    continue
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None:
                    continue
                ext_d = period_qdates[k + 2]  # 6M = 2 quarters
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                            "turnover": 1.0/6.0, "roundtrips": 1.0/6.0, "holding_months": 6})
            portfolio_results[p][f"Q{q+1}"] = profile(out)
    
    print(f"{'Period':6s} | {'Quintile':8s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'n':>4s}")
    print("-" * 55)
    for p in ["TRAIN", "VALID", "TEST"]:
        for q in range(5):
            r = portfolio_results[p][f"Q{q+1}"]
            if r.get("n", 0) > 1:
                print(f"{p:6s} | Q{q+1}       | {r['cagrNet']:>8.2%} | {r['sharpe']:>6.3f} | {r['mdd']:>6.2%} | {r['n']:>4d}")

    # Q5-Q1 spread
    print("\nQ5-Q1 CAGR spread:")
    for p in ["TRAIN", "VALID", "TEST"]:
        q5 = portfolio_results[p]["Q5"].get("cagrNet", 0)
        q1 = portfolio_results[p]["Q1"].get("cagrNet", 0)
        if q5 and q1:
            print(f"  {p}: Q5={q5:.2%} Q1={q1:.2%} Spread={q5-q1:+.2%}")

    # === 3. MONOTONICITY ACROSS HORIZONS ===
    print("\n=== MONOTONICITY ACROSS HORIZONS ===")
    
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        for h_name, h_col in horizons.items():
            # Quintile
            quintile_means = []
            for sd in dates:
                this = m[m["date"] == sd].dropna(subset=["treasuryRatio", h_col])
                if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                    continue
                this = this.copy()
                this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                means = [this[this["q"] == q][h_col].mean() for q in range(5)]
                if len(means) == 5 and not any(pd.isna(m) for m in means):
                    quintile_means.append(means)
            if quintile_means:
                avg_means = np.mean(quintile_means, axis=0)
                mono = assess_monotonic(avg_means.tolist())
                print(f"  {p} {h_name} Q-mono: {mono} - {[f'{v:.4f}' for v in avg_means]}")

    # === 4. SIGNAL DECAY ANALYSIS ===
    print("\n=== SIGNAL DECAY: IC MEAN RATIO (6M/3M, 9M/6M) ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        ic_3m = ic_results[p]["3M"]["quintile"].get("ic_mean", 0)
        ic_6m = ic_results[p]["6M"]["quintile"].get("ic_mean", 0)
        ic_9m = ic_results[p]["9M"]["quintile"].get("ic_mean", 0)
        if ic_3m and ic_6m:
            ratio_63 = ic_6m / ic_3m
        else:
            ratio_63 = None
        if ic_6m and ic_9m:
            ratio_96 = ic_9m / ic_6m
        else:
            ratio_96 = None
        print(f"  {p}: IC_3M={ic_3m:.4f} IC_6M={ic_6m:.4f} IC_9M={ic_9m:.4f} "
              f"6M/3M={ratio_63:.2f}" if ratio_63 else f"  {p}: IC_3M={ic_3m:.4f} IC_6M={ic_6m:.4f} IC_9M={ic_9m:.4f} 6M/3M=NA",
              f" 9M/6M={ratio_96:.2f}" if ratio_96 else " 9M/6M=NA")

    # === 5. SPREAD DECAY ===
    print("\n=== SPREAD DECAY: Q5-Q1 SPREAD RATIO ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        s_3m = ic_results[p]["3M"]["quintile"].get("spread_mean", 0)
        s_6m = ic_results[p]["6M"]["quintile"].get("spread_mean", 0)
        s_9m = ic_results[p]["9M"]["quintile"].get("spread_mean", 0)
        if s_3m and s_6m:
            ratio_63 = s_6m / s_3m
        else:
            ratio_63 = None
        if s_6m and s_9m:
            ratio_96 = s_9m / s_6m
        else:
            ratio_96 = None
        print(f"  {p}: S_3M={s_3m:.4f} S_6M={s_6m:.4f} S_9M={s_9m:.4f} "
              f"6M/3M={ratio_63:.2f}" if ratio_63 else f"  {p}: S_3M={s_3m:.4f} S_6M={s_6m:.4f} S_9M={s_9m:.4f} 6M/3M=NA",
              f" 9M/6M={ratio_96:.2f}" if ratio_96 else " 9M/6M=NA")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Key metrics
    test_ic_6m = ic_results["TEST"]["6M"]["quintile"].get("ic_mean", 0)
    test_ic_3m = ic_results["TEST"]["3M"]["quintile"].get("ic_mean", 0)
    test_ic_9m = ic_results["TEST"]["9M"]["quintile"].get("ic_mean", 0)
    
    train_ic_6m = ic_results["TRAIN"]["6M"]["quintile"].get("ic_mean", 0)
    valid_ic_6m = ic_results["VALID"]["6M"]["quintile"].get("ic_mean", 0)
    
    test_q5_cagr = portfolio_results["TEST"]["Q5"].get("cagrNet", 0)
    test_q1_cagr = portfolio_results["TEST"]["Q1"].get("cagrNet", 0)
    
    print(f"TEST IC 3M/6M/9M: {test_ic_3m:.4f} / {test_ic_6m:.4f} / {test_ic_9m:.4f}")
    print(f"TRAIN/VALID/TEST IC_6M: {train_ic_6m:.4f} / {valid_ic_6m:.4f} / {test_ic_6m:.4f}")
    print(f"TEST Q5 CAGR: {test_q5_cagr:.2%}, Q1 CAGR: {test_q1_cagr:.2%}, Spread: {test_q5_cagr - test_q1_cagr:.2%}")
    
    # Signal decay check
    decay_63 = test_ic_6m / test_ic_3m if test_ic_3m else None
    decay_96 = test_ic_9m / test_ic_6m if test_ic_6m else None
    
    # Consistency check
    ic_consistent = (train_ic_6m > 0 and valid_ic_6m > 0 and test_ic_6m > 0)
    spread_consistent = (test_q5_cagr > test_q1_cagr) if test_q5_cagr and test_q1_cagr else False
    
    # Decay check
    if decay_96 and decay_96 < 0.8:
        decay = True
    elif decay_96 and decay_96 < 1.0:
        decay = True  # some decay
    else:
        decay = False
    
    print(f"TEST IC decay 9M/6M: {decay_96:.2f}" if decay_96 else "TEST IC decay 9M/6M: NA")
    print(f"TEST IC decay 6M/3M: {decay_63:.2f}" if decay_63 else "TEST IC decay 6M/3M: NA")
    print(f"IC consistent across periods: {ic_consistent}")
    print(f"TEST Q5>Q1 spread: {spread_consistent}")
    
    if ic_consistent and spread_consistent and not decay:
        judgment = "KEEP - Stable signal across horizons and periods"
    elif ic_consistent and spread_consistent and decay:
        judgment = "HOLD - Signal decays at longer horizon but consistent"
    elif not ic_consistent or not spread_consistent:
        judgment = "REJECT - Inconsistent across periods or no spread"
    else:
        judgment = "UNCLASSIFIED"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-19: Test TreasuryRatio combined with volatility filter across all horizons"
    if judgment == "KEEP":
        next_exp = "10-KR-23-19: Test TreasuryRatio + LowVol across 3M/6M/9M horizons"
    elif judgment == "HOLD":
        next_exp = "10-KR-23-19: Test 6M as optimal horizon; test 3M for tactical"
    elif judgment == "REJECT":
        next_exp = "10-KR-23-19: Test alternative value factors (PBR, dividend yield)"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-18: TreasuryRatio Alpha Stability / Signal Decay Test",
        "ic_results": ic_results,
        "portfolio_results": {p: {k: v for k, v in d.items()} for p, d in portfolio_results.items()},
        "horizons": horizons,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-signal-decay-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()