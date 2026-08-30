#!/usr/bin/env python
"""10-KR-23-2: Treasury Ratio Tail Dependency Analysis.

Same universe, PIT, treasuryRatio definition, monthly rebalance, next-day entry,
30bps/side, TRAIN/VALID/TEST split as 10-KR-22.
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
QUALITY_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                             "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-tail-dep")

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
    if not monthly:
        return {}
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
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")
    g = df.groupby("ticker", sort=False)["close"]
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    df["turnover20"] = df["total_amount"].groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])
    close_by_date = {d: gd[["ticker", "close"]].set_index("ticker")["close"]
                     for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)

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
    print(f"  merged {len(m)} rows, coverage {100*m['treasuryRatio'].notna().mean():.1f}%")

    # 1. Decile analysis
    print("\n=== DECILE ANALYSIS (120D) ===")
    decile_results = {"TRAIN": [], "VALID": [], "TEST": []}
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
        # Average across months
        for dec in range(10):
            if all_decile_rets[dec]:
                decile_results[p].append(float(np.mean(all_decile_rets[dec])))
            else:
                decile_results[p].append(None)

    print("\nDecile means (120D forward return):")
    print("       D1      D2      D3      D4      D5      D6      D7      D8      D9     D10")
    for p in ["TRAIN", "VALID", "TEST"]:
        vals = decile_results[p]
        line = f"{p:5s}: "
        for v in vals:
            line += f"{v:>8.4f}" if v is not None else "      NA"
        print(line)

    # 2. Monotonicity assessment
    def assess_monotonic(vals):
        if any(v is None for v in vals):
            return "UNKNOWN"
        # Check if generally increasing
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
        elif vals[9] > max(vals[:9]) * 1.5:  # D10 is outlier high
            return "TAIL_D10_ONLY"
        elif vals[0] < min(vals[1:]) * 1.5:  # D1 is outlier low
            return "TAIL_D1_ONLY"
        else:
            return "NON_MONOTONIC"

    for p in ["TRAIN", "VALID", "TEST"]:
        assessment = assess_monotonic(decile_results[p])
        print(f"  {p} monotonicity: {assessment}")

    # 3. Decile CAGR/Sharpe (top decile portfolio)
    print("\n=== DECILE PORTFOLIO CAGR/SHARPE (120D hold, monthly rebal) ===")
    decile_port = {"TRAIN": {}, "VALID": {}, "TEST": {}}
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        for dec in range(10):
            out = []
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates):
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
                ext_d = next((x for x in dates if x > ent_d), None)
                if ext_d is None:
                    continue
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
            decile_port[p][dec] = profile(out)

    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p} Decile Portfolio:")
        print("  Dec  CAGR    Sharpe   MDD")
        for dec in range(10):
            d = decile_port[p].get(dec, {})
            if d:
                print(f"  D{dec+1:2d} {d.get('cagrNet',0):>7.2%} {d.get('sharpe',0):>7.3f} {d.get('mdd',0):>7.2%}")

    # 4. Tail trim analysis (remove top/bottom 10%)
    print("\n=== TAIL TRIM ANALYSIS (120D) ===")
    trim_results = {}
    for trimmed in [False, True]:
        label = "Trimmed" if trimmed else "Original"
        trim_results[label] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            # Q5-Q1 spread
            spreads = []
            # Top-Q portfolio
            port_out = []
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates):
                    break
                this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio"])
                if len(this) < MIN_NAMES:
                    continue
                if trimmed:
                    # Remove top/bottom 10% by treasuryRatio
                    lo = this["treasuryRatio"].quantile(0.10)
                    hi = this["treasuryRatio"].quantile(0.90)
                    this = this[(this["treasuryRatio"] > lo) & (this["treasuryRatio"] < hi)]
                    if len(this) < MIN_NAMES:
                        continue
                this = this.copy()
                this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                # Q5-Q1 spread
                if len(this[this["q"] == 4]) > 0 and len(this[this["q"] == 0]) > 0:
                    spreads.append(float(this[this["q"] == 4]["f120"].mean() - this[this["q"] == 0]["f120"].mean()))
                # Top-Q portfolio
                picks = this[this["q"] == 4]["ticker"].tolist()
                if not picks:
                    continue
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None:
                    continue
                ext_d = next((x for x in dates if x > ent_d), None)
                if ext_d is None:
                    continue
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets:
                    continue
                gr = float(np.mean(rets))
                port_out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
            trim_results[label][p] = {
                "q5q1": round(float(np.mean(spreads)), 5) if spreads else None,
                "portfolio": profile(port_out)
            }

    print("\nTrim Comparison (120D):")
    print(f"{'':15s} | {'TRAIN':>12s} | {'VALID':>12s} | {'TEST':>12s}")
    sep = "-"*15 + "-+-" + "-"*12 + "-+-" + "-"*12 + "-+-" + "-"*12
    print(sep)
    for metric in ["q5q1", "cagrNet", "sharpe"]:
        row = f"{metric:15s} |"
        for label in ["Original", "Trimmed"]:
            for p in ["TRAIN", "VALID", "TEST"]:
                if metric != "q5q1":
                    val = trim_results[label][p].get("portfolio", {}).get(metric)
                else:
                    val = trim_results[label][p].get("q5q1")
                if val is not None:
                    row += f" {val:>10.4f}"
                else:
                    row += "        NA"
            row += " |"
        print(row)

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    orig_test_q5q1 = trim_results["Original"]["TEST"]["q5q1"]
    trim_test_q5q1 = trim_results["Trimmed"]["TEST"]["q5q1"]
    orig_test_cagr = trim_results["Original"]["TEST"]["portfolio"]["cagrNet"]
    trim_test_cagr = trim_results["Trimmed"]["TEST"]["portfolio"]["cagrNet"]

    mono_train = assess_monotonic(decile_results["TRAIN"])
    mono_valid = assess_monotonic(decile_results["VALID"])
    mono_test = assess_monotonic(decile_results["TEST"])

    if mono_train == mono_valid == mono_test == "MONOTONIC_INCREASING":
        judgment = "NON-TAIL"
    elif "TAIL" in mono_test or (trim_test_cagr is not None and orig_test_cagr is not None and trim_test_cagr < orig_test_cagr * 0.5):
        judgment = "TAIL-DEPENDENT"
    elif mono_train != mono_valid or mono_valid != mono_test:
        judgment = "UNSTABLE"
    else:
        judgment = "NON-TAIL"  # default conservative

    print(f"Monotonicity: TRAIN={mono_train}, VALID={mono_valid}, TEST={mono_test}")
    print(f"TEST Q5-Q1: Original={orig_test_q5q1}, Trimmed={trim_test_q5q1}")
    print(f"TEST Top-Q CAGR: Original={orig_test_cagr:.4f}, Trimmed={trim_test_cagr:.4f}")
    print(f"\n>>> JUDGMENT: {judgment} <<<")

    # Save results
    result = {
        "experiment": "10-KR-23-2: treasuryRatio tail dependency",
        "decile_returns": decile_results,
        "decile_portfolio": {p: {str(k): v for k, v in d.items()} for p, d in decile_port.items()},
        "trim_comparison": trim_results,
        "monotonicity": {"TRAIN": mono_train, "VALID": mono_valid, "TEST": mono_test},
        "judgment": judgment,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-tail-dep-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()