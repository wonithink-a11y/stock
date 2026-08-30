#!/usr/bin/env python
"""Portfolio backtest: KOSPI rev_yoy × PBR combination."""
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
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")
OUT_DIR = os.path.join(LAB, "reports", "2026-08-30-revyoy-portfolio")

LIQUID_THRESHOLD = 1e8
LIQUID_GATE_OFF = False
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
TOP_N = 30


def period_of(d, train_end="2022-06-30", valid_end="2024-01-01"):
    return "TRAIN" if d <= train_end else ("VALID" if d <= valid_end else "TEST")


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


def port_stats(monthly_rets, label=""):
    if not monthly_rets:
        return {}
    m = np.array(monthly_rets, dtype=float)
    n = len(m)
    eq = float(np.prod(1 + m))
    span = n / 12
    cagr = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(m)) ** (1 / max(span, 1e-9)) - 1
    sh = float(m.mean() / m.std(ddof=1) * np.sqrt(12)) if m.std(ddof=1) > 0 else None
    peak, mdd, cum = 1.0, 0.0, 1.0
    for r in m:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    # Yearly
    yearly = {}
    return {"label": label, "nMonths": n, "cagr": round(cagr, 4), "sharpe": round(sh, 3) if sh is not None else None,
            "mdd": round(mdd, 4), "meanMonthly": round(float(m.mean()), 6)}


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
    os.makedirs(OUT_DIR, exist_ok=True)
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

    # KOSPI only
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

    fwd_col = "fwd1M"
    full = base[["ticker", "date", "period", fwd_col, "rev_yoy", "pbr", "dv20_log"]].dropna(subset=["rev_yoy", "pbr", fwd_col])
    print(f"Final sample: {len(full)} rows, {full['ticker'].nunique()} tickers")

    # =============================================
    # Strategy definitions
    # =============================================
    strategies = {
        "PBR_Q2_only": lambda g: g[g["pbr_q"] == 2],
        "Rev_Q5_only": lambda g: g[g["rev_q"] == 5],
        "PBR_Q2_Rev_Q5": lambda g: g[(g["pbr_q"] == 2) & (g["rev_q"] == 5)],
        "KOSPI_EW": lambda g: g,
    }

    results = {k: {"monthly_rets": [], "turnover": [], "holdings": []} for k in strategies}
    
    # Benchmark: KOSPI EW all liquid names
    kospi_bench_rets = []

    for ddate in months[:-1]:
        grp = full[full["date"] == ddate].copy()
        if len(grp) < MIN_NAMES:
            continue
        
        # Rank within month
        grp = grp.copy()
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        grp["rev_q"] = pd.qcut(grp["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        
        # Benchmark return
        bench_ret = grp[fwd_col].mean()
        kospi_bench_rets.append(float(bench_ret))
        
        # Each strategy
        for name, selector in strategies.items():
            sel = selector(grp).copy()
            if len(sel) == 0:
                results[name]["monthly_rets"].append(0.0)
                results[name]["turnover"].append(0.0)
                continue
            
            # Top N by rev_yoy (for PBR_Q2_Rev_Q5, already filtered)
            if name == "Rev_Q5_only":
                sel = sel.nlargest(TOP_N, "rev_yoy")
            elif name == "PBR_Q2_only":
                sel = sel.nlargest(TOP_N, "rev_yoy")  # within PBR Q2, pick highest rev_yoy
            elif name == "PBR_Q2_Rev_Q5":
                # Already exactly PBR Q2 & Rev Q5, take all up to TOP_N
                if len(sel) > TOP_N:
                    sel = sel.nlargest(TOP_N, "rev_yoy")
            else:
                # KOSPI_EW
                pass
            
            if len(sel) == 0:
                results[name]["monthly_rets"].append(0.0)
                results[name]["turnover"].append(0.0)
                continue
            
            # Equal weight portfolio return
            port_ret = sel[fwd_col].mean() - ROUNDTRIP_BPS / 10000
            results[name]["monthly_rets"].append(float(port_ret))
            
            # Track turnover (simplified: count new names)
            new_names = set(sel["ticker"])
            if results[name]["holdings"]:
                old_names = set(results[name]["holdings"][-1])
                turnover = 1.0 - len(new_names & old_names) / max(len(new_names), 1)
            else:
                turnover = 1.0
            results[name]["turnover"].append(turnover)
            results[name]["holdings"].append(list(new_names))

    # Compute stats per period
    print("\n=== Portfolio Backtest Results ===")
    for name, data in results.items():
        print(f"\n--- {name} ---")
        for period_label, period_filter in [("ALL", lambda x: True),
                                              ("TRAIN", lambda x: x <= "2022-06-30"),
                                              ("VALID", lambda x: "2022-07-01" <= x <= "2024-01-01"),
                                              ("TEST", lambda x: x >= "2024-02-01")]:
            # Filter monthly rets by period
            period_rets = []
            period_turnover = []
            for i, ddate in enumerate(months[:-1]):
                if period_filter(ddate) and i < len(data["monthly_rets"]):
                    period_rets.append(data["monthly_rets"][i])
                    if i < len(data["turnover"]):
                        period_turnover.append(data["turnover"][i])
            
            if period_rets:
                stats = port_stats(period_rets, name)
                avg_turnover = np.mean(period_turnover) if period_turnover else 0
                print(f"  {period_label}: CAGR={stats['cagr']:.2%} Sharpe={stats['sharpe']} "
                      f"MDD={stats['mdd']:.2%} Turnover={avg_turnover:.1%} nMonths={stats['nMonths']}")
                
                # Yearly breakdown
                yearly = {}
                for i, ddate in enumerate(months[:-1]):
                    if period_filter(ddate) and i < len(data["monthly_rets"]):
                        yr = ddate[:4]
                        yearly.setdefault(yr, []).append(data["monthly_rets"][i])
                print(f"    Yearly: ", end="")
                for yr in sorted(yearly.keys()):
                    y_ret = np.prod([1 + r for r in yearly[yr]]) - 1
                    print(f"{yr}:{y_ret:.2%} ", end="")
                print()

    # Benchmark
    print(f"\n--- KOSPI_EW Benchmark ---")
    for period_label, period_filter in [("ALL", lambda x: True),
                                          ("TRAIN", lambda x: x <= "2022-06-30"),
                                          ("VALID", lambda x: "2022-07-01" <= x <= "2024-01-01"),
                                          ("TEST", lambda x: x >= "2024-02-01")]:
        period_rets = []
        for i, ddate in enumerate(months[:-1]):
            if period_filter(ddate) and i < len(kospi_bench_rets):
                period_rets.append(kospi_bench_rets[i])
        if period_rets:
            stats = port_stats(period_rets, "KOSPI_EW")
            print(f"  {period_label}: CAGR={stats['cagr']:.2%} Sharpe={stats['sharpe']} "
                  f"MDD={stats['mdd']:.2%} nMonths={stats['nMonths']}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()