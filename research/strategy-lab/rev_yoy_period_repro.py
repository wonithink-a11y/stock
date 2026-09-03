#!/usr/bin/env python
"""Reproducibility check: rev_yoy × PBR nonlinear interaction across TRAIN/VALID/TEST."""
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
    base["period"] = base["date"].map(period_of)
    if not LIQUID_GATE_OFF:
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

    full = base[["ticker", "date", "period", "fwd1M", "rev_yoy", "pbr", "dv20_log"]].dropna(subset=["rev_yoy", "pbr", "fwd1M"])
    print(f"Final sample: {len(full)} rows, {full['ticker'].nunique()} tickers")

    # Compute monthly spreads per PBR quintile
    period_spreads = {"TRAIN": [], "VALID": [], "TEST": []}
    pbr_q_spreads = {p: {"TRAIN": [], "VALID": [], "TEST": []} for p in range(1, 6)}

    for ddate in months[:-1]:
        grp = full[full["date"] == ddate].copy()
        if len(grp) < MIN_NAMES:
            continue
        
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        grp["rev_q"] = pd.qcut(grp["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        
        m = grp.groupby(["pbr_q", "rev_q"])["fwd1M"].mean()
        
        period = period_of(ddate)
        
        for pbr_q in range(1, 6):
            if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                spread = float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])
                pbr_q_spreads[pbr_q][period].append((ddate, spread))

    # Print results
    print("\n" + "="*100)
    print("rev_yoy Q5-Q1 Spread by PBR Quintile × Period (KOSPI, Monthly Rebalance, 12M Forward)")
    print("="*100)
    
    print(f"\n{'Period':<8} | {'PBR_Q':<6} | {'Spread':>10} | {'t-stat':>8} | {'posYR':>6} | {'nMonths':>7} | {'HitRate':>7}")
    print("-"*100)
    
    for period in ["TRAIN", "VALID", "TEST"]:
        for pbr_q in range(1, 6):
            spreads = pbr_q_spreads[pbr_q][period]
            if len(spreads) >= 10:
                stats = monthly_spread_stats(spreads)
                print(f"{period:<8} | Q{pbr_q:<5} | {stats['mean']:>9.4f} | {stats['t']:>8} | {stats['posYearRatio']:>5.2f} | {stats['nMonths']:>7} | {stats['hitRate']:>6.2f}")
            else:
                print(f"{period:<8} | Q{pbr_q:<5} | {'N/A':>9} | {'N/A':>8} | {'N/A':>5} | {'N/A':>7} | {'N/A':>6}")
        print()

    # Also print overall (no period split)
    print("\n" + "="*100)
    print("OVERALL (All periods combined)")
    print("="*100)
    print(f"\n{'PBR_Q':<6} | {'Spread':>10} | {'t-stat':>8} | {'posYR':>6} | {'nMonths':>7} | {'HitRate':>7}")
    print("-"*60)
    for pbr_q in range(1, 6):
        all_spreads = pbr_q_spreads[pbr_q]["TRAIN"] + pbr_q_spreads[pbr_q]["VALID"] + pbr_q_spreads[pbr_q]["TEST"]
        if len(all_spreads) >= 10:
            stats = monthly_spread_stats(all_spreads)
            print(f"Q{pbr_q:<5} | {stats['mean']:>9.4f} | {stats['t']:>8} | {stats['posYearRatio']:>5.2f} | {stats['nMonths']:>7} | {stats['hitRate']:>6.2f}")

    # Yearly breakdown for overall
    print("\nYearly breakdown (overall):")
    for pbr_q in range(1, 6):
        all_spreads = pbr_q_spreads[pbr_q]["TRAIN"] + pbr_q_spreads[pbr_q]["VALID"] + pbr_q_spreads[pbr_q]["TEST"]
        if len(all_spreads) >= 10:
            stats = monthly_spread_stats(all_spreads)
            if stats['yearly']:
                yr_str = "  ".join([f"{y}:{v:.2%}" for y, v in stats['yearly'].items()])
                print(f"  Q{pbr_q}: {yr_str}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()