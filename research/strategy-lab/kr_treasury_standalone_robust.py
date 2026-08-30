#!/usr/bin/env python
"""10-KR-23-6: TreasuryRatio Standalone Robustness.

Tests if TreasuryRatio Quarterly standalone performance is structural or tail-dependent.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-standalone-robust")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}


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


def summarize_ic(recs):
    if not recs:
        return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "icMean": round(float(v.mean()), 5),
            "icT": round(t, 3) if t is not None else None}


def profile(monthly):
    if not monthly or len(monthly) < 2:
        return {"n": len(monthly) if monthly else 0}
    mr = np.array([x["ret"] for x in monthly])
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
    total_turnover = sum(x.get("turnover", 0) for x in monthly)
    avg_turnover = total_turnover / len(monthly) * 12 if monthly else 0
    roundtrips = sum(x.get("roundtrips", 0) for x in monthly)
    avg_holding = np.mean([x.get("holding_months", 1) for x in monthly]) if monthly else 0
    gross_cagr = None
    if monthly and "gross_ret" in monthly[0]:
        gm = np.array([x["gross_ret"] for x in monthly])
        geq = float(np.prod(1 + gm))
        gross_cagr = geq ** (1 / max(span, 1e-9)) - 1 if geq > 0 else None
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4),
            "avgAnnualTurnover": round(avg_turnover, 2),
            "totalRoundTrips": round(roundtrips, 2),
            "avgHoldingMonths": round(avg_holding, 1),
            "grossCAGR": round(gross_cagr, 4) if gross_cagr is not None else None,
            "costDrag": round(cn - gross_cagr, 4) if gross_cagr is not None else None}


def assess_monotonic(vals):
    if any(v is None for v in vals):
        return "UNKNOWN"
    increasing = sum(1 for i in range(1, 10) if vals[i] > vals[i-1])
    decreasing = sum(1 for i in range(1, 10) if vals[i] < vals[i-1])
    if increasing >= 8:
        return "MONOTONIC_INCREASING"
    elif increasing >= 6:
        return "MOSTLY_MONOTONIC_INCREASING"
    elif decreasing >= 8:
        return "MONOTONIC_DECREASING"
    elif decreasing >= 6:
        return "MOSTLY_MONOTONIC_DECREASING"
    elif vals[9] > max(vals[:9]) * 1.5:
        return "TAIL_D10_ONLY"
    elif vals[0] < min(vals[1:]) * 1.5:
        return "TAIL_D1_ONLY"
    else:
        return "NON_MONOTONIC"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")
    g = df.groupby("ticker", sort=False)["close"]
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    df["turnover20"] = (df["close"] * df["total_volume"]).groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])
    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    qmonths = quarterly_reb(all_dates)

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

    base = df[df["date"].isin(months)][["ticker", "date", "turnover20",
                                         "f5", "f20", "f60", "f120"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        tr = val(TREAS, t, d)
        isu = val(ISSUED, t, d)
        rows.append({"ticker": t, "date": d,
                     "treasuryRatio": tr / isu if (tr is not None and isu and isu != 0) else None})
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    m = m.dropna(subset=["treasuryRatio"])
    print(f"  merged {len(m)} rows")

    # === Experiment 1: Decile Analysis (120D forward return) ===
    print("\n=== EXPERIMENT 1: DECILE ANALYSIS (120D) ===")
    decile_results = {"TRAIN": [], "VALID": [], "TEST": []}
    decile_port_results = {"TRAIN": {}, "VALID": {}, "TEST": {}}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        all_decile_rets = {i: [] for i in range(10)}
        for sd in dates:
            this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio", "f120"])
            if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                continue
            this = this.copy()
            this["decile"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 10, labels=False, duplicates="drop")
            for dec in range(10):
                subset = this[this["decile"] == dec]
                if len(subset) > 0:
                    all_decile_rets[dec].append(float(subset["f120"].mean()))
        for dec in range(10):
            if all_decile_rets[dec]:
                decile_results[p].append(float(np.mean(all_decile_rets[dec])))
            else:
                decile_results[p].append(None)

    print("Decile means (120D forward return):")
    print("       D1      D2      D3      D4      D5      D6      D7      D8      D9     D10")
    for p in ["TRAIN", "VALID", "TEST"]:
        vals = decile_results[p]
        line = f"{p:5s}: "
        for v in vals:
            line += f"{v:>8.4f}" if v is not None else "      NA"
        print(line)

    # Decile monotonicity
    for p in ["TRAIN", "VALID", "TEST"]:
        mono = assess_monotonic(decile_results[p])
        print(f"  {p} monotonicity: {mono}")

    # Decile Portfolio (Quarterly rebal, 3M hold)
    print("\n=== DECILE PORTFOLIO (Quarterly 3M Hold) ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        rebal_dates = [d for d in qmonths if d in dates]
        for dec in range(10):
            out = []
            for k, sd in enumerate(rebal_dates):
                if k + 1 >= len(rebal_dates):
                    break
                this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio"])
                if len(this) < MIN_NAMES:
                    continue
                this = this.copy()
                this["decile"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 10, labels=False, duplicates="drop")
                picks = this[this["decile"] == dec]["ticker"].tolist()
                if not picks:
                    continue
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None:
                    continue
                ext_d = rebal_dates[k + 1]
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                            "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3})
            decile_port_results[p][dec] = profile(out)

    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p} Decile Portfolio:")
        print("  Dec  CAGR    Sharpe   MDD")
        for dec in range(10):
            d = decile_port_results[p].get(dec, {})
            if d and d.get("n", 0) > 1:
                print(f"  D{dec+1:2d} {d.get('cagrNet',0):>7.2%} {d.get('sharpe',0):>7.3f} {d.get('mdd',0):>7.2%}")

    # === Experiment 2: Top-N Portfolio (10%/20%/30%/40%) ===
    print("\n=== EXPERIMENT 2: TOP-N PORTFOLIO (Quarterly 3M Hold) ===")
    topn_results = {}
    for top_pct in [0.10, 0.20, 0.30, 0.40]:
        label = f"Top{int(top_pct*100)}%"
        topn_results[label] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            rebal_dates = [d for d in qmonths if d in dates]
            out = []
            for k, sd in enumerate(rebal_dates):
                if k + 1 >= len(rebal_dates):
                    break
                this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio"])
                if len(this) < MIN_NAMES:
                    continue
                this = this.sort_values("treasuryRatio", ascending=False)
                n_pick = max(int(np.ceil(len(this) * top_pct)), 1)
                picks = this.head(n_pick)["ticker"].tolist()
                if not picks:
                    continue
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None:
                    continue
                ext_d = rebal_dates[k + 1]
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                            "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3})
            topn_results[label][p] = profile(out)

    print(f"{'TopN':10s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s}")
    print("-" * 60)
    for label in ["Top10%", "Top20%", "Top30%", "Top40%"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            d = topn_results[label][p]
            if d.get("n", 0) > 1:
                print(f"{label:10s} | {p:6s} | {d.get('cagrNet',0):>8.2%} | {d.get('sharpe',0):>6.3f} | {d.get('mdd',0):>6.2%} | {d.get('avgAnnualTurnover',0):>8.1f}x")

    # === Experiment 3: Extreme Tail Trim ===
    print("\n=== EXPERIMENT 3: EXTREME TAIL TRIM (Top20%, Quarterly 3M Hold) ===")
    trim_results = {}
    for trimmed in [False, True]:
        label = "Trimmed" if trimmed else "Original"
        trim_results[label] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            rebal_dates = [d for d in qmonths if d in dates]
            out = []
            for k, sd in enumerate(rebal_dates):
                if k + 1 >= len(rebal_dates):
                    break
                this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio"])
                if len(this) < MIN_NAMES:
                    continue
                if trimmed:
                    lo = this["treasuryRatio"].quantile(0.10)
                    hi = this["treasuryRatio"].quantile(0.90)
                    this = this[(this["treasuryRatio"] > lo) & (this["treasuryRatio"] < hi)]
                    if len(this) < MIN_NAMES:
                        continue
                this = this.sort_values("treasuryRatio", ascending=False)
                n_pick = max(int(np.ceil(len(this) * 0.20)), 1)
                picks = this.head(n_pick)["ticker"].tolist()
                if not picks:
                    continue
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None:
                    continue
                ext_d = rebal_dates[k + 1]
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                            "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3})
            trim_results[label][p] = profile(out)

    print("\nTrim Comparison (Top20%, Quarterly 3M Hold):")
    print(f"{'':10s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s}")
    print("-" * 55)
    for label in ["Original", "Trimmed"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            d = trim_results[label][p]
            if d.get("n", 0) > 1:
                print(f"{label:10s} | {p:6s} | {d.get('cagrNet',0):>8.2%} | {d.get('sharpe',0):>6.3f} | {d.get('mdd',0):>6.2%} | {d.get('avgAnnualTurnover',0):>8.1f}x")

    # === Final Judgment ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Check decile monotonicity consistency
    mono_train = assess_monotonic(decile_results["TRAIN"])
    mono_valid = assess_monotonic(decile_results["VALID"])
    mono_test = assess_monotonic(decile_results["TEST"])
    print(f"Decile monotonicity: TRAIN={mono_train}, VALID={mono_valid}, TEST={mono_test}")
    
    # Check if Top20% works across all periods
    top20_train = topn_results["Top20%"]["TRAIN"].get("cagrNet", -99)
    top20_valid = topn_results["Top20%"]["VALID"].get("cagrNet", -99)
    top20_test = topn_results["Top20%"]["TEST"].get("cagrNet", -99)
    print(f"Top20% CAGR: TRAIN={top20_train:.2%} VALID={top20_valid:.2%} TEST={top20_test:.2%}")
    
    # Check if trim preserves performance
    orig_test = trim_results["Original"]["TEST"].get("cagrNet", -99)
    trim_test = trim_results["Trimmed"]["TEST"].get("cagrNet", -99)
    orig_valid = trim_results["Original"]["VALID"].get("cagrNet", -99)
    trim_valid = trim_results["Trimmed"]["VALID"].get("cagrNet", -99)
    print(f"Original vs Trimmed TEST CAGR: {orig_test:.2%} vs {trim_test:.2%}")
    print(f"Original vs Trimmed VALID CAGR: {orig_valid:.2%} vs {trim_valid:.2%}")

    # Decision logic
    mono_consistent = (mono_train == mono_valid == mono_test) or \
                      ("INCREASING" in mono_train and "INCREASING" in mono_valid and "INCREASING" in mono_test) or \
                      ("DECREASING" in mono_train and "DECREASING" in mono_valid and "DECREASING" in mono_test)
    
    top20_all_positive = top20_train > 0 and top20_valid > 0 and top20_test > 0
    trim_preserves = abs(orig_test - trim_test) < 0.03 and abs(orig_valid - trim_valid) < 0.03
    tail_concentrated = (topn_results["Top10%"]["TEST"].get("cagrNet", 0) > topn_results["Top20%"]["TEST"].get("cagrNet", 0) * 1.5) or \
                        (topn_results["Top10%"]["TRAIN"].get("cagrNet", 0) > topn_results["Top20%"]["TRAIN"].get("cagrNet", 0) * 1.5)

    if mono_consistent and top20_all_positive and trim_preserves and not tail_concentrated:
        judgment = "ROBUST"
    elif tail_concentrated or not top20_all_positive or not trim_preserves:
        judgment = "WEAK"
    else:
        judgment = "REJECT"

    print(f"\n  Mono consistent: {mono_consistent}")
    print(f"  Top20% all positive: {top20_all_positive}")
    print(f"  Trim preserves: {trim_preserves}")
    print(f"  Tail concentrated: {tail_concentrated}")
    print(f"\n>>> JUDGMENT: {judgment} <<<")

    if judgment == "ROBUST":
        next_exp = "10-KR-23-7: Optimize TreasuryRatio standalone weighting (not fixed 20%)"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-7: Test TreasuryRatio with timing filter (VIX/trend)"
    else:
        next_exp = "10-KR-23-7: TreasuryRatio standalone not structurally robust; investigate signal quality"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-6: TreasuryRatio standalone robustness",
        "decile_returns": decile_results,
        "decile_portfolio": {p: {str(k): v for k, v in d.items()} for p, d in decile_port_results.items()},
        "topn_results": {k: {p: prof for p, prof in v.items()} for k, v in topn_results.items()},
        "trim_results": {k: {p: prof for p, prof in v.items()} for k, v in trim_results.items()},
        "monotonicity": {"TRAIN": mono_train, "VALID": mono_valid, "TEST": mono_test},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-standalone-robust-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()