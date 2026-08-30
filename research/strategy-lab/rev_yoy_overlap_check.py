#!/usr/bin/env python
"""Overlapping check: rev_yoy × PBR 12M forward vs non-overlapping annual portfolio."""
import bisect
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")

LIQUID_THRESHOLD = 1e8
LIQUID_GATE_OFF = False
MIN_NAMES = 30


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


def monthly_spread_stats(spread_months):
    if not spread_months:
        return None
    arr = np.array([s for d, s in spread_months], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    years = {}
    for (d, s) in spread_months:
        years.setdefault(d[:4], []).append(s)
    yspread = {y: float(np.mean(v)) for y, v in sorted(years.items())}
    pos_year = float(sum(1 for v in yspread.values() if v > 0) / max(len(yspread), 1))
    return {"nMonths": n, "mean": round(float(arr.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None, "hitRate": round(float((arr > 0).mean()), 3),
            "posYearRatio": round(pos_year, 3), "yearly": {y: round(v, 6) for y, v in yspread.items()}}


def annual_spread_stats(spread_years):
    if not spread_years:
        return None
    arr = np.array([s for y, s in spread_years], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    pos_year = float((arr > 0).mean())
    yspread = {str(y): float(s) for y, s in spread_years}
    return {"nYears": n, "mean": round(float(arr.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None, "posYearRatio": round(pos_year, 3),
            "yearly": {y: round(v, 6) for y, v in yspread.items()}}


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
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()

    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    # Build 12M forward for overlapping analysis
    fwd12 = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-12]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[i + 12]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd12.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd12M"] = fwd12
    base = base.dropna(subset=["fwd12M"])
    base = base[base["fwd12M"] > -1].copy()

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    if not LIQUID_GATE_OFF:
        base = base[base["liquid"]].copy()

    # Annual rebalance dates (January first session each year)
    annual_months = [m for m in months if m.endswith("-01")]
    print(f"Annual rebalance dates: {annual_months}")

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

    fwd_col = "fwd12M"
    full = base[["ticker", "date", "market", fwd_col, "rev_yoy", "pbr"]].dropna(subset=["rev_yoy", "pbr", fwd_col])
    print(f"Full sample: {len(full)} rows, {full['ticker'].nunique()} tickers")

    # =============================================
    # 1. OVERLAPPING: Monthly rebalance, 12M forward
    # =============================================
    print("\n" + "="*60)
    print("1. OVERLAPPING: Monthly rebalance, 12M forward")
    print("="*60)
    
    for mkt in ["KOSPI", "KOSDAQ", "ALL"]:
        if mkt == "ALL":
            sub = full.copy()
        else:
            sub = full[full["market"] == mkt].copy()
        
        print(f"\n--- {mkt} (n={len(sub)}) ---")
        
        ds_spreads = []
        for ddate, grp in sub.groupby("date"):
            if len(grp) < MIN_NAMES:
                continue
            g2 = grp.copy()
            g2["pbr_q"] = pd.qcut(g2["pbr"].rank(method="first"), 5, labels=False) + 1
            g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            m = g2.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
            for pbr_q in range(1, 6):
                if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                    ds_spreads.append((ddate, pbr_q, float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])))
        
        if ds_spreads:
            ds_df = pd.DataFrame(ds_spreads, columns=["date", "pbr_q", "spread"])
            for pbr_q in range(1, 6):
                sub_q = ds_df[ds_df["pbr_q"] == pbr_q]
                if len(sub_q) >= 20:
                    sp = monthly_spread_stats(list(zip(sub_q["date"], sub_q["spread"])))
                    print(f"  PBR Q{pbr_q}: spread={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']:.2f} n_months={sp['nMonths']}")
                    if sp['yearly']:
                        yr_str = ", ".join([f"{y}:{v:.2%}" for y, v in sp['yearly'].items()])
                        print(f"    yearly: {yr_str}")

    # =============================================
    # 2. NON-OVERLAPPING: Annual rebalance, 12M hold
    # =============================================
    print("\n" + "="*60)
    print("2. NON-OVERLAPPING: Annual rebalance (Jan), 12M hold")
    print("="*60)
    
    for mkt in ["KOSPI", "KOSDAQ", "ALL"]:
        if mkt == "ALL":
            sub = full.copy()
        else:
            sub = full[full["market"] == mkt].copy()
        
        print(f"\n--- {mkt} ---")
        
        annual_spreads = []
        for sd in annual_months[:-1]:
            rows = sub.index[sub["date"] == sd]
            if len(rows) == 0:
                continue
            grp = sub.loc[rows].copy()
            if len(grp) < MIN_NAMES:
                continue
            
            grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
            grp["rev_q"] = pd.qcut(grp["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            m = grp.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
            
            for pbr_q in range(1, 6):
                if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                    spread = float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])
                    annual_spreads.append((sd[:4], pbr_q, spread))
        
        if annual_spreads:
            ann_df = pd.DataFrame(annual_spreads, columns=["year", "pbr_q", "spread"])
            for pbr_q in range(1, 6):
                sub_q = ann_df[ann_df["pbr_q"] == pbr_q]
                if len(sub_q) >= 5:
                    sp = annual_spread_stats(list(zip(sub_q["year"], sub_q["spread"])))
                    print(f"  PBR Q{pbr_q}: spread={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']:.2f} n_years={sp['nYears']}")
                    if sp['yearly']:
                        yr_str = ", ".join([f"{y}:{v:.2%}" for y, v in sp['yearly'].items()])
                        print(f"    yearly: {yr_str}")

    # =============================================
    # 3. DIRECT COMPARISON: Same PBR Q, overlap vs non-overlap
    # =============================================
    print("\n" + "="*60)
    print("3. DIRECT COMPARISON: Overlapping vs Non-overlapping")
    print("="*60)
    
    for mkt in ["KOSPI", "KOSDAQ"]:
        sub = full[full["market"] == mkt].copy()
        print(f"\n--- {mkt} ---")
        print(f"  {'PBR_Q':>6} | {'Overlap spread':>14} | {'Overlap t':>9} | {'Non-overlap spread':>18} | {'Non-overlap t':>12}")
        print(f"  {'-'*6}-+-{'--'*7}-+-{'--'*4}-+-{'--'*9}-+-{'--'*6}")
        
        # Overlapping
        ds_spreads = []
        for ddate, grp in sub.groupby("date"):
            if len(grp) < MIN_NAMES:
                continue
            g2 = grp.copy()
            g2["pbr_q"] = pd.qcut(g2["pbr"].rank(method="first"), 5, labels=False) + 1
            g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            m = g2.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
            for pbr_q in range(1, 6):
                if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                    ds_spreads.append((ddate, pbr_q, float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])))
        
        # Non-overlapping
        annual_spreads = []
        for sd in annual_months[:-1]:
            rows = sub.index[sub["date"] == sd]
            if len(rows) == 0:
                continue
            grp = sub.loc[rows].copy()
            if len(grp) < MIN_NAMES:
                continue
            grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
            grp["rev_q"] = pd.qcut(grp["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            m = grp.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
            for pbr_q in range(1, 6):
                if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                    spread = float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])
                    annual_spreads.append((sd[:4], pbr_q, spread))
        
        if ds_spreads and annual_spreads:
            ds_df = pd.DataFrame(ds_spreads, columns=["date", "pbr_q", "spread"])
            ann_df = pd.DataFrame(annual_spreads, columns=["year", "pbr_q", "spread"])
            
            for pbr_q in range(1, 6):
                ov_sub = ds_df[ds_df["pbr_q"] == pbr_q]
                nv_sub = ann_df[ann_df["pbr_q"] == pbr_q]
                if len(ov_sub) >= 20 and len(nv_sub) >= 5:
                    ov_sp = monthly_spread_stats(list(zip(ov_sub["date"], ov_sub["spread"])))
                    nv_sp = annual_spread_stats(list(zip(nv_sub["year"], nv_sub["spread"])))
                    print(f"  Q{pbr_q} | {ov_sp['mean']:>12.4f} | {ov_sp['t']:>9} | {nv_sp['mean']:>16.4f} | {nv_sp['t']:>12}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()