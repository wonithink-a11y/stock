#!/usr/bin/env python
"""Diagnostic: Why IC doesn't translate to portfolio spread - quintile analysis within PBR_Q2."""
import bisect
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")

LIQUID_THRESHOLD = 1e8
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS

PERIOD_SPLIT = ("2022-06-30", "2024-01-01")


def period_of(d):
    t_end, v_end = PERIOD_SPLIT
    return "TRAIN" if d <= t_end else ("VALID" if d <= v_end else "TEST")


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
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def select_fiscal_year(records, fy, as_of):
    best = None
    for rec in records:
        if rec[1] != fy:
            continue
        af = rec[0]
        if af > as_of:
            continue
        if best is None or af > best[0]:
            best = rec
    return best


def newey_west_t(series, max_lag=None):
    x = np.array(series, dtype=float)
    n = len(x)
    if n < 10:
        return None
    if max_lag is None:
        max_lag = int(4 * (n / 100) ** (2/9))
    max_lag = min(max_lag, n - 1)
    mean_x = x.mean()
    if max_lag == 0:
        se = x.std(ddof=1) / np.sqrt(n)
        return mean_x / se if se > 0 else None
    gamma = [np.mean((x[:n-k] - mean_x) * (x[k:] - mean_x)) for k in range(max_lag + 1)]
    var = gamma[0] + 2 * sum((1 - k / (max_lag + 1)) * gamma[k] for k in range(1, max_lag + 1))
    se = np.sqrt(var / n)
    return mean_x / se if se > 0 else None


def load_market_map():
    m = {}
    with open(A1A_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("ticker") and r.get("market"):
                m[r["ticker"]] = r["market"]
    return m


def load_panel(path, keep_fields):
    df = pd.read_json(path, lines=True)
    df = df[["ticker", "asOf"] + keep_fields]
    df["asOf"] = df["asOf"].astype(str)
    df = df.dropna(subset=["ticker", "asOf"])
    key = {}
    for t, g in df.groupby("ticker"):
        g = g.sort_values("asOf")
        key[t] = (g["asOf"].tolist(), g[keep_fields].to_dict("records"))
    return key


def panel_lookup(key, t, d, field):
    if t not in key:
        return None
    asofs, recs = key[t]
    i = bisect.bisect_right(asofs, d) - 1
    if i < 0:
        return None
    v = recs[i][field]
    return None if v is None or pd.isna(v) else float(v)


def build_a3_rev():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                pe = str(r.get("periodEnd", ""))
                if not pe.endswith("12-31"):
                    continue
                t = r.get("ticker")
                fy = int(r["fiscalYear"])
                af = normd(str(r["availableFrom"]))
                if t is None:
                    continue
                rev = r.get("revenue")
                if rev is not None:
                    try:
                        out.setdefault(t, []).append((af, fy, float(rev)))
                    except (TypeError, ValueError):
                        pass
    return out


def main():
    t0 = time.time()
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    g = df.groupby("ticker", sort=False)
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()

    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    fwd12 = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[min(i + 1, len(months) - 1)]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd12.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd1M"] = fwd12
    base = base.dropna(subset=["fwd1M"])
    base = base[base["fwd1M"] > -1].copy()

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base = base[base["liquid"]].copy()
    base = base[base["market"] == "KOSPI"].copy()
    print(f"KOSPI sample: {len(base)} rows, {base['ticker'].nunique()} tickers")

    a3_rev = build_a3_rev()
    def rev_yoy(t, d):
        recs = a3_rev.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, d)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])
    vlook = lambda t, d, f: panel_lookup(vdf, t, d, f)

    c_rev, c_pbr = [], []
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c_rev.append(rev_yoy(t, d))
        c_pbr.append(vlook(t, d, "pbr"))
    base["rev_yoy"] = c_rev
    base["pbr"] = c_pbr

    full = base[["ticker", "date", "fwd1M", "rev_yoy", "pbr"]].dropna(subset=["rev_yoy", "pbr", "fwd1M"])
    print(f"Final sample: {len(full)} rows, {full['ticker'].nunique()} tickers")

    months_sorted = sorted(full["date"].unique())

    # ============================================================
    # 1. QUINTILE ANALYSIS WITHIN PBR_Q2
    # ============================================================
    print("\n" + "="*100)
    print("QUINTILE ANALYSIS WITHIN PBR_Q2 (1M forward, 30bps rt cost)")
    print("="*100)

    quintile_data = {q: {"rets": [], "spreads": [], "ics": [], "vols": [], "sizes": []} for q in range(1, 6)}
    topN_data = {10: {"rets": [], "spreads": []}, 20: {"rets": [], "spreads": []}, 
                 30: {"rets": [], "spreads": []}, 50: {"rets": [], "spreads": []}}
    bench_data = []

    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate].copy()
        if len(grp) < MIN_NAMES:
            for q in range(1, 6):
                quintile_data[q]["rets"].append(None)
            for n in topN_data:
                topN_data[n]["rets"].append(None)
            bench_data.append(None)
            continue

        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        q2 = grp[grp["pbr_q"] == 2].copy()
        
        if len(q2) < 20:
            for q in range(1, 6):
                quintile_data[q]["rets"].append(None)
            for n in topN_data:
                topN_data[n]["rets"].append(None)
            bench_data.append(None)
            continue

        # Quintiles within PBR Q2
        q2["rev_q"] = pd.qcut(q2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        
        # Benchmark: all PBR Q2
        bench_ret = q2["fwd1M"].mean()
        bench_data.append(float(bench_ret))

        for q in range(1, 6):
            q_data = q2[q2["rev_q"] == q]
            if len(q_data) > 0:
                ret = q_data["fwd1M"].mean()
                quintile_data[q]["rets"].append(float(ret))
                quintile_data[q]["spreads"].append(float(ret - bench_ret))
                quintile_data[q]["sizes"].append(len(q_data))
                # IC for this month
                if len(q_data) > 10:
                    ic = q_data["rev_yoy"].corr(q_data["fwd1M"], method="spearman")
                    if not np.isnan(ic):
                        quintile_data[q]["ics"].append(ic)
            else:
                quintile_data[q]["rets"].append(None)
                quintile_data[q]["spreads"].append(None)

        # Top-N strategies (by rev_yoy within PBR Q2)
        for n in [10, 20, 30, 50]:
            if len(q2) >= n:
                sel = q2.nlargest(n, "rev_yoy")
                ret = sel["fwd1M"].mean() - ROUNDTRIP_BPS / 10000
                topN_data[n]["rets"].append(float(ret))
                topN_data[n]["spreads"].append(float(ret - bench_ret))
            else:
                topN_data[n]["rets"].append(None)
                topN_data[n]["spreads"].append(None)

    # Print quintile stats
    print(f"\n{'Quintile':<10} | {'MeanRet':>10} | {'Spread':>10} | {'t-stat':>8} | {'NW t-stat':>10} | {'HitRate':>8} | {'AvgSize':>8} | {'IC_mean':>8} | {'IC_NW_t':>8}")
    print("-"*100)
    for q in range(1, 6):
        rets = [x for x in quintile_data[q]["rets"] if x is not None]
        spreads = [x for x in quintile_data[q]["spreads"] if x is not None]
        ics = quintile_data[q]["ics"]
        sizes = quintile_data[q]["sizes"]
        if rets:
            mean_ret = np.mean(rets)
            mean_spread = np.mean(spreads)
            std_t = np.mean(spreads) / (np.std(spreads, ddof=1) / np.sqrt(len(spreads)))
            nw_t = newey_west_t(spreads)
            hit = (np.array(spreads) > 0).mean()
            avg_size = np.mean(sizes)
            ic_mean = np.mean(ics) if ics else 0
            ic_nw = newey_west_t(ics) if ics else 0
            print(f"Q{q:<9} | {mean_ret:>9.4%} | {mean_spread:>9.4%} | {std_t:>7.2f} | {nw_t:>9.2f} | {hit:>7.1%} | {avg_size:>7.1f} | {ic_mean:>7.4f} | {ic_nw:>7.2f}")

    # Overall PBR Q2 (no rev_yoy filter)
    print("\n--- Overall PBR_Q2 (bench) ---")
    bench = [x for x in bench_data if x is not None]
    if bench:
        print(f"  Mean ret: {np.mean(bench):.4%}, Std: {np.std(bench, ddof=1):.4%}")

    # ============================================================
    # 2. TOP-N vs QUINTILE Q5 COMPARISON
    # ============================================================
    print("\n" + "="*100)
    print("TOP-N vs Q5 QUINTILE COMPARISON")
    print("="*100)
    
    q5_spreads = [x for x in quintile_data[5]["spreads"] if x is not None]
    q5_rets = [x for x in quintile_data[5]["rets"] if x is not None]
    
    for n in [10, 20, 30, 50]:
        rets = [x for x in topN_data[n]["rets"] if x is not None]
        spreads = [x for x in topN_data[n]["spreads"] if x is not None]
        if rets and spreads:
            mean_ret = np.mean(rets)
            mean_spread = np.mean(spreads)
            std_t = np.mean(spreads) / (np.std(spreads, ddof=1) / np.sqrt(len(spreads)))
            nw_t = newey_west_t(spreads)
            hit = (np.array(spreads) > 0).mean()
            # Correlation with Q5
            min_len = min(len(spreads), len(q5_spreads))
            corr = np.corrcoef(spreads[:min_len], q5_spreads[:min_len])[0,1] if min_len > 5 else 0
            print(f"\nTop{n}:")
            print(f"  Mean ret: {mean_ret:.4%}, Spread: {mean_spread:.4%}")
            print(f"  t-stat: {std_t:.2f}, NW t-stat: {nw_t:.2f}, HitRate: {hit:.1%}")
            print(f"  Corr with Q5 spread: {corr:.4f}")
            # Compare vs Q5
            if min_len > 5:
                diff = np.mean(np.array(spreads[:min_len]) - np.array(q5_spreads[:min_len])) * 12
                print(f"  Top{n} - Q5 spread diff: {diff:+.2%}pp annualized")

    # ============================================================
    # 3. IC DILUTION ANALYSIS
    # ============================================================
    print("\n" + "="*100)
    print("IC DILUTION ANALYSIS: How much signal lost in Top-N selection?")
    print("="*100)
    
    # Monthly IC for full PBR Q2
    full_ics = []
    q2_ics = []
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate].copy()
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        q2 = grp[grp["pbr_q"] == 2]
        if len(q2) > 10:
            ic = q2["rev_yoy"].corr(q2["fwd1M"], method="spearman")
            if not np.isnan(ic):
                full_ics.append(ic)
    
    # IC for Top-N selected stocks (within selected, what's the IC?)
    # This measures if selection preserves the signal
    topN_ics = {n: [] for n in [10, 20, 30, 50]}
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate].copy()
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        q2 = grp[grp["pbr_q"] == 2]
        if len(q2) >= 50:
            for n in [10, 20, 30, 50]:
                sel = q2.nlargest(n, "rev_yoy")
                if len(sel) > 5:
                    ic = sel["rev_yoy"].corr(sel["fwd1M"], method="spearman")
                    if not np.isnan(ic):
                        topN_ics[n].append(ic)
    
    print(f"\n  Full PBR_Q2 IC: mean={np.mean(full_ics):.4f}, NW_t={newey_west_t(full_ics):.2f}, >0 freq={(np.array(full_ics)>0).mean():.1%}")
    for n in [10, 20, 30, 50]:
        ics = topN_ics[n]
        if ics:
            print(f"  Top{n} IC: mean={np.mean(ics):.4f}, NW_t={newey_west_t(ics):.2f}, >0 freq={(np.array(ics)>0).mean():.1%}")

    # ============================================================
    # 4. VOLATILITY DECOMPOSITION
    # ============================================================
    print("\n" + "="*100)
    print("VOLATILITY DECOMPOSITION: Portfolio spread vs Quintile spread")
    print("="*100)
    
    # Q5 spread volatility
    q5_spread = np.array(q5_spreads)
    print(f"\n  Q5 spread: mean={np.mean(q5_spread):.4%}, std={np.std(q5_spread, ddof=1):.4%}")
    print(f"  Q5 NW t-stat: {newey_west_t(q5_spread):.2f}")
    
    # Top30 spread
    top30_spread = np.array([x for x in topN_data[30]["spreads"] if x is not None])
    print(f"  Top30 spread: mean={np.mean(top30_spread):.4%}, std={np.std(top30_spread, ddof=1):.4%}")
    print(f"  Top30 NW t-stat: {newey_west_t(top30_spread):.2f}")
    
    # Theoretical: if we hold all Q5 stocks (equal weight) vs Top30 from Q2
    # The dilution comes from:
    # 1. Top30 includes non-Q5 stocks from Q2 (lower rev_yoy)
    # 2. Top30 excludes some Q5 stocks (only top 30 by rev_yoy overall)
    
    # Check overlap
    print("\n  Overlap analysis (Top30 vs Q5):")
    overlaps = []
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate].copy()
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        q2 = grp[grp["pbr_q"] == 2]
        if len(q2) >= 30:
            q2["rev_q"] = pd.qcut(q2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            q5_names = set(q2[q2["rev_q"] == 5]["ticker"])
            top30_names = set(q2.nlargest(30, "rev_yoy")["ticker"])
            if q5_names and top30_names:
                overlaps.append(len(q5_names & top30_names) / len(q5_names))
    if overlaps:
        print(f"    Top30 captures {np.mean(overlaps):.1%} of Q5 names on average")
        print(f"    Range: [{min(overlaps):.1%}, {max(overlaps):.1%}]")

    # ============================================================
    # 5. SIGNAL-TO-NOISE RATIO
    # ============================================================
    print("\n" + "="*100)
    print("SIGNAL-TO-NOISE RATIO")
    print("="*100)
    
    # Signal = mean spread, Noise = std of spread
    for n in [10, 20, 30, 50]:
        spreads = np.array([x for x in topN_data[n]["spreads"] if x is not None])
        if len(spreads) > 5:
            snr = np.mean(spreads) / np.std(spreads, ddof=1)
            print(f"  Top{n}: Signal/Noise = {snr:.3f} (mean={np.mean(spreads):.4%}, std={np.std(spreads, ddof=1):.4%})")
    
    q5_spreads_arr = np.array(q5_spreads)
    if len(q5_spreads_arr) > 5:
        snr = np.mean(q5_spreads_arr) / np.std(q5_spreads_arr, ddof=1)
        print(f"  Q5: Signal/Noise = {snr:.3f} (mean={np.mean(q5_spreads_arr):.4%}, std={np.std(q5_spreads_arr, ddof=1):.4%})")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()