#!/usr/bin/env python
"""Compare PBR_Q2 only vs PBR_Q2∩Rev_Q3 vs PBR_Q2∩Rev_Q5."""
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
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
TOP_N = 30

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


def port_stats(monthly_rets):
    if not monthly_rets:
        return {"cagr": None, "sharpe": None, "mdd": None, "n": 0}
    m = np.array(monthly_rets, dtype=float)
    n = len(m)
    eq = float(np.prod(1 + m))
    span = n / 12
    cagr = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(m)) ** (1 / max(span, 1e-9)) - 1
    sd = float(m.std(ddof=1))
    sh = float(m.mean() / sd * np.sqrt(12)) if sd > 0 else None
    peak, mdd, cum = 1.0, 0.0, 1.0
    for r in m:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    return {"cagr": round(cagr, 4), "sharpe": round(sh, 3) if sh is not None else None,
            "mdd": round(mdd, 4), "n": n}


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


def compute_turnover_from_holdings(holdings_list):
    turnovers = [0.0]
    for i in range(1, len(holdings_list)):
        if not holdings_list[i] or not holdings_list[i - 1]:
            turnovers.append(0.0)
            continue
        intersection = len(holdings_list[i] & holdings_list[i - 1])
        turnover = 1.0 - intersection / max(len(holdings_list[i]), 1)
        turnovers.append(turnover)
    return turnovers


def period_stats(monthly_rets, turnover_list, periods):
    out = {}
    n_rets = len(monthly_rets)
    for p in ["TRAIN", "VALID", "TEST"]:
        valid_indices = [i for i in range(n_rets) if i < len(periods) and periods[i] == p]
        rets = [monthly_rets[i] for i in valid_indices if monthly_rets[i] is not None]
        turns = [turnover_list[i] for i in valid_indices if i < len(turnover_list)]
        s = port_stats(rets)
        s["turnover"] = round(float(np.mean(turns)), 4) if turns else None
        s["n"] = len(rets)
        out[p] = s
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

    months_sorted = sorted(full["date"].unique())
    periods = [period_of(d) for d in months_sorted]

    # Strategy functions
    def s_pbr_q2(grp):
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        return g[g["pbr_q"] == 2].nlargest(TOP_N, "rev_yoy")

    def s_pbr_q2_rev_q3(grp):
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        sel = g[(g["pbr_q"] == 2) & (g["rev_q"] == 3)]
        if len(sel) <= TOP_N:
            return sel
        return sel.nlargest(TOP_N, "rev_yoy")

    def s_pbr_q2_rev_q5(grp):
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        sel = g[(g["pbr_q"] == 2) & (g["rev_q"] == 5)]
        if len(sel) <= TOP_N:
            return sel
        return sel.nlargest(TOP_N, "rev_yoy")

    def s_bench(grp):
        return grp.copy()

    strategies = {
        "PBR_Q2_only": s_pbr_q2,
        "PBR_Q2xRev_Q3": s_pbr_q2_rev_q3,
        "PBR_Q2xRev_Q5": s_pbr_q2_rev_q5,
        "KOSPI_EW": s_bench,
    }

    results = {}
    candidate_counts = {}
    holding_sizes = {}

    for name, fn in strategies.items():
        monthly_rets = []
        holdings_list = []
        candidates_list = []
        for ddate in months_sorted[:-1]:
            grp = full[full["date"] == ddate]
            if len(grp) < MIN_NAMES:
                monthly_rets.append(None)
                holdings_list.append(set())
                candidates_list.append(0)
                continue
            sel = fn(grp)
            candidates_list.append(len(grp))  # total KOSPI liquid candidates that month
            if len(sel) == 0:
                monthly_rets.append(None)
                holdings_list.append(set())
                continue
            port_ret = sel["fwd1M"].mean() - ROUNDTRIP_BPS / 10000
            monthly_rets.append(float(port_ret))
            holdings_list.append(set(sel["ticker"]))
        tor = compute_turnover_from_holdings(holdings_list)
        results[name] = {"rets": monthly_rets, "holdings": holdings_list, "periods": periods, "tor": tor}
        candidate_counts[name] = candidates_list
        holding_sizes[name] = [len(h) for h in holdings_list]

    # Print results
    strategy_names = ["PBR_Q2_only", "PBR_Q2xRev_Q3", "PBR_Q2xRev_Q5", "KOSPI_EW"]
    
    print("\n" + "="*100)
    print("PORTFOLIO PERFORMANCE: PBR_Q2 only vs PBR_Q2xRev_Q3 vs PBR_Q2xRev_Q5")
    print("="*100)
    
    print(f"\n{'Strategy':<16} | {'Period':<7} {'CAGR':>8} {'Sharpe':>7} {'MDD':>8} {'Turnover':>9} {'n':>4}")
    print("-"*100)
    stats_summary = {}
    for name in strategy_names:
        r = results[name]
        s = period_stats(r["rets"], r["tor"], r["periods"])
        stats_summary[name] = s
        for p in ["TRAIN", "VALID", "TEST"]:
            ss = s[p]
            print(f"{name:<16} | {p:<7} {ss['cagr']:>7.2%} {ss['sharpe']:>7} {ss['mdd']:>8.2%} {ss['turnover']:>8.1%} {ss['n']:>4}")
        # Overall
        all_rets = [x for x in r["rets"] if x is not None]
        all_tor = [x for x in r["tor"] if x is not None]
        overall = port_stats(all_rets)
        overall["turnover"] = round(float(np.mean(all_tor)), 4) if all_tor else None
        overall["n"] = len(all_rets)
        print(f"{name:<16} | {'ALL':<7} {overall['cagr']:>7.2%} {overall['sharpe']:>7} {overall['mdd']:>8.2%} {overall['turnover']:>8.1%} {overall['n']:>4}")
        print()

    # Holdings stats
    print("\n" + "="*100)
    print("HOLDINGS STATISTICS (per strategy)")
    print("="*100)
    for name in strategy_names:
        hs = holding_sizes[name]
        hs_valid = [x for x in hs if x > 0]
        if hs_valid:
            print(f"\n{name}:")
            print(f"  Mean holdings: {np.mean(hs_valid):.1f}")
            print(f"  Min holdings:  {np.min(hs_valid)}")
            print(f"  Max holdings:  {np.max(hs_valid)}")
        # Monthly candidates
        cc = candidate_counts[name]
        cc_valid = [x for x in cc if x > 0]
        if cc_valid:
            print(f"  Mean monthly candidates: {np.mean(cc_valid):.0f}")
            print(f"  Min monthly candidates:  {np.min(cc_valid)}")
            print(f"  Max monthly candidates:  {np.max(cc_valid)}")

    # Excess vs benchmark
    print("\n" + "="*100)
    print("EXCESS RETURN vs KOSPI_EW (annualized %pp)")
    print("="*100)
    bench_cagr = stats_summary["KOSPI_EW"]
    for name in ["PBR_Q2_only", "PBR_Q2xRev_Q3", "PBR_Q2xRev_Q5"]:
        row = stats_summary[name]
        print(f"\n{name}:")
        for p in ["TRAIN", "VALID", "TEST"]:
            excess = row[p]["cagr"] - bench_cagr[p]["cagr"]
            print(f"  {p}: {excess:>+7.2%}pp (CAGR {row[p]['cagr']:.2%} vs bench {bench_cagr[p]['cagr']:.2%})")
        # Overall
        all_rets = [x for x in results[name]["rets"] if x is not None]
        all_bench = [x for x in results["KOSPI_EW"]["rets"] if x is not None]
        min_len = min(len(all_rets), len(all_bench))
        if min_len > 0:
            excess = np.mean(np.array(all_rets[:min_len]) - np.array(all_bench[:min_len])) * 12
            print(f"  ALL: {excess:>+7.2%}pp (annualized mean monthly diff)")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()