#!/usr/bin/env python
"""Final OOS validation: PBR_Q2 rev_yoy Top30 with rolling/expanding windows."""
import bisect
import gzip
import json
import os
import sys
import time
from collections import Counter

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
TOP_N = 30

# Cost scenarios in bps
COST_SCENARIOS = [0, 15, 25, 50]  # one-way; round-trip = 2x

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
        return {"cagr": None, "sharpe": None, "mdd": None, "n": 0, "hit": None}
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
            "mdd": round(mdd, 4), "n": n, "hit": round(float((m > 0).mean()), 3)}


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


def compute_turnover(holdings_list):
    turnovers = [0.0]
    for i in range(1, len(holdings_list)):
        if not holdings_list[i] or not holdings_list[i - 1]:
            turnovers.append(0.0)
            continue
        inter = len(holdings_list[i] & holdings_list[i - 1])
        turnovers.append(1.0 - inter / max(len(holdings_list[i]), 1))
    return turnovers


def period_stats(monthly_rets, turnover_list, periods):
    out = {}
    n_rets = len(monthly_rets)
    for p in ["TRAIN", "VALID", "TEST"]:
        idx = [i for i in range(n_rets) if i < len(periods) and periods[i] == p]
        rets = [monthly_rets[i] for i in idx if monthly_rets[i] is not None]
        turns = [turnover_list[i] for i in idx if i < len(turnover_list)]
        s = port_stats(rets)
        s["turnover"] = round(float(np.mean(turns)), 4) if turns else None
        out[p] = s
    return out


def newey_west_t(series, max_lag=None):
    """Newey-West t-stat for mean of series."""
    x = np.array(series, dtype=float)
    n = len(x)
    if n < 10:
        return None
    if max_lag is None:
        max_lag = int(4 * (n / 100) ** (2/9))  # Newey-West rule
    max_lag = min(max_lag, n - 1)
    mean_x = x.mean()
    if max_lag == 0:
        se = x.std(ddof=1) / np.sqrt(n)
        return mean_x / se if se > 0 else None
    gamma = [np.mean((x[:n-k] - mean_x) * (x[k:] - mean_x)) for k in range(max_lag + 1)]
    var = gamma[0] + 2 * sum((1 - k / (max_lag + 1)) * gamma[k] for k in range(1, max_lag + 1))
    se = np.sqrt(var / n)
    return mean_x / se if se > 0 else None


def yearly_win_rate(monthly_rets, months):
    """Yearly win rate from monthly returns."""
    yearly = {}
    for i, d in enumerate(months):
        if i < len(monthly_rets) and monthly_rets[i] is not None:
            yr = d[:4]
            yearly.setdefault(yr, []).append(monthly_rets[i])
    wins = sum(1 for v in yearly.values() if sum(v) > 0)
    return round(wins / max(len(yearly), 1), 3), yearly


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
    base["period"] = base["date"].map(period_of)
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

    full = base[["ticker", "date", "period", "fwd1M", "rev_yoy", "pbr"]].dropna(subset=["rev_yoy", "pbr", "fwd1M"])
    print(f"Final sample: {len(full)} rows, {full['ticker'].nunique()} tickers")

    months_sorted = sorted(full["date"].unique())
    periods = [period_of(d) for d in months_sorted]

    # Strategy: PBR Q2, rev_yoy rank Top 30
    def strategy_fn(grp):
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        return g[g["pbr_q"] == 2].nlargest(TOP_N, "rev_yoy")

    # Build monthly returns for all cost scenarios
    all_cost_rets = {c: [] for c in COST_SCENARIOS}
    all_holdings = []
    all_spreads = {c: [] for c in COST_SCENARIOS}  # strategy - bench
    bench_rets = []

    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate]
        if len(grp) < MIN_NAMES:
            for c in COST_SCENARIOS:
                all_cost_rets[c].append(None)
            all_holdings.append(set())
            bench_rets.append(None)
            for c in COST_SCENARIOS:
                all_spreads[c].append(None)
            continue
        sel = strategy_fn(grp)
        if len(sel) == 0:
            for c in COST_SCENARIOS:
                all_cost_rets[c].append(None)
            all_holdings.append(set())
            bench_rets.append(None)
            for c in COST_SCENARIOS:
                all_spreads[c].append(None)
            continue
        # Strategy return
        strat_ret = sel["fwd1M"].mean()
        # Benchmark return
        bench_ret = grp["fwd1M"].mean()
        bench_rets.append(float(bench_ret))
        for c in COST_SCENARIOS:
            cost = 2 * c / 10000  # round-trip
            net = float(strat_ret - cost)
            all_cost_rets[c].append(net)
            all_spreads[c].append(net - float(bench_ret))
        all_holdings.append(set(sel["ticker"]))

    # 1. STATIC PERIOD RESULTS
    print("\n" + "="*100)
    print("STATIC PERIOD RESULTS (TRAIN/VALID/TEST)")
    print("="*100)
    print(f"\n{'Cost(bps)':<10} | {'Period':<7} {'CAGR':>8} {'Sharpe':>7} {'MDD':>8} {'Turnover':>9} {'HitRate':>7} {'n':>4}")
    print("-"*100)
    for c in COST_SCENARIOS:
        rets = all_cost_rets[c]
        tor = compute_turnover(all_holdings)
        s = period_stats(rets, tor, periods)
        for p in ["TRAIN", "VALID", "TEST"]:
            ss = s[p]
            print(f"{2*c:<10} | {p:<7} {ss['cagr']:>7.2%} {ss['sharpe']:>7} {ss['mdd']:>8.2%} {ss['turnover']:>8.1%} {ss['hit']:>6.2f} {ss['n']:>4}")
        # Overall
        all_r = [x for x in rets if x is not None]
        all_t = [x for x in tor if x is not None]
        ov = port_stats(all_r)
        ov["turnover"] = round(float(np.mean(all_t)), 4) if all_t else None
        print(f"{2*c:<10} | {'ALL':<7} {ov['cagr']:>7.2%} {ov['sharpe']:>7} {ov['mdd']:>8.2%} {ov['turnover']:>8.1%} {ov['hit']:>6.2f} {ov['n']:>4}")
        print()

    # 2. YEARLY WIN RATE & SPREAD
    print("\n" + "="*100)
    print("YEARLY WIN RATE & SPREAD")
    print("="*100)
    # 30bps round-trip = 15 one-way in COST_SCENARIOS
    c_idx = COST_SCENARIOS.index(15)
    for c in COST_SCENARIOS:
        rets = all_cost_rets[c]
        wr, yr = yearly_win_rate(rets, months_sorted[:-1])
        print(f"\nCost {2*c}bps round-trip:")
        print(f"  Yearly win rate: {wr:.1%}")
        print(f"  Yearly CAGR: ", end="")
        for y in sorted(yr.keys()):
            if yr[y]:
                y_cagr = np.prod(1 + np.array(yr[y])) - 1
                print(f"{y}:{y_cagr:.2%} ", end="")
        print()
        # Yearly spread
        spr = [s for s in all_spreads[c] if s is not None]
        spr_by_year = {}
        for i, d in enumerate(months_sorted[:-1]):
            if i < len(all_spreads[c]) and all_spreads[c][i] is not None:
                spr_by_year.setdefault(d[:4], []).append(all_spreads[c][i])
        print(f"  Yearly spread: ", end="")
        for y in sorted(spr_by_year.keys()):
            print(f"{y}:{np.mean(spr_by_year[y]):.2%} ", end="")
        print()

# 3. MONTHLY SPREAD & IC
    print("\n" + "="*100)
    print("MONTHLY SPREAD & IC (30bps round-trip)")
    print("="*100)
    rets_30 = all_cost_rets[15]
    spread_30 = [s for s in all_spreads[15] if s is not None]
    bench_valid = [b for b in bench_rets if b is not None]
    
    # Monthly spread stats
    print(f"  Mean monthly spread: {np.mean(spread_30):.4%}")
    print(f"  Monthly spread std:  {np.std(spread_30, ddof=1):.4%}")
    
    # Newey-West t-stat
    nw_t = newey_west_t(spread_30)
    print(f"  Newey-West t-stat:   {nw_t:.2f}")
    
    # Standard t-stat (for comparison)
    std_t = np.mean(spread_30) / (np.std(spread_30, ddof=1) / np.sqrt(len(spread_30)))
    print(f"  Standard t-stat:     {std_t:.2f}")
    
    # IC: rank correlation between rev_yoy and forward returns within PBR Q2
    print("\n  Monthly IC (rev_yoy vs fwd1M within PBR Q2):")
    ics = []
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate].copy()
        grp["pbr_q"] = pd.qcut(grp["pbr"].rank(method="first"), 5, labels=False) + 1
        q2 = grp[grp["pbr_q"] == 2]
        if len(q2) >= 20:
            ic = q2["rev_yoy"].corr(q2["fwd1M"], method="spearman")
            if not np.isnan(ic):
                ics.append(ic)
    if ics:
        print(f"    Mean IC: {np.mean(ics):.4f}")
        print(f"    IC std:  {np.std(ics, ddof=1):.4f}")
        print(f"    IC t-stat (NW): {newey_west_t(ics):.2f}")
        print(f"    IC > 0 freq: {(np.array(ics) > 0).mean():.1%}")
    
    # 4. ROLLING/EXPANDING OOS
    print("\n" + "="*100)
    print("ROLLING/EXPANDING OUT-OF-SAMPLE VALIDATION")
    print("="*100)
    
    # Expanding window: train grows, test is next 12 months
    min_train = 36
    results_exp = []
    for i in range(min_train, len(months_sorted) - 12):
        train_dates = months_sorted[:i]
        test_dates = months_sorted[i:i+12]
        
        # Build portfolio using data up to train_dates
        train_data = full[full["date"].isin(train_dates)]
        test_data = full[full["date"].isin(test_dates)]
        
        # Strategy on test period
        test_rets = []
        for td in test_dates:
            grp = test_data[test_data["date"] == td]
            if len(grp) < MIN_NAMES:
                test_rets.append(None)
                continue
            sel = strategy_fn(grp)
            if len(sel) == 0:
                test_rets.append(None)
                continue
            test_rets.append(float(sel["fwd1M"].mean() - 2*30/10000))
        
        valid = [x for x in test_rets if x is not None]
        if len(valid) >= 6:
            cagr = np.prod(1 + np.array(valid)) ** (12/len(valid)) - 1
            results_exp.append({"start": test_dates[0], "end": test_dates[-1], 
                              "cagr": cagr, "n": len(valid), "hit": (np.array(valid) > 0).mean()})
    
    print(f"\nExpanding window (train≥{min_train}m, test=12m):")
    print(f"  Windows tested: {len(results_exp)}")
    if results_exp:
        cagrs = [r["cagr"] for r in results_exp]
        print(f"  Mean OOS CAGR: {np.mean(cagrs):.2%}")
        print(f"  OOS CAGR t-stat (NW): {newey_west_t(cagrs):.2f}")
        print(f"  OOS win rate: {sum(1 for r in results_exp if r['cagr']>0)/len(results_exp):.1%}")
        print(f"  CAGR range: [{min(cagrs):.2%}, {max(cagrs):.2%}]")
    
    # Rolling window: fixed 60m train, 12m test
    train_window = 60
    results_roll = []
    for i in range(train_window, len(months_sorted) - 12):
        train_dates = months_sorted[i-train_window:i]
        test_dates = months_sorted[i:i+12]
        
        test_data = full[full["date"].isin(test_dates)]
        test_rets = []
        for td in test_dates:
            grp = test_data[test_data["date"] == td]
            if len(grp) < MIN_NAMES:
                test_rets.append(None)
                continue
            sel = strategy_fn(grp)
            if len(sel) == 0:
                test_rets.append(None)
                continue
            test_rets.append(float(sel["fwd1M"].mean() - 2*30/10000))
        
        valid = [x for x in test_rets if x is not None]
        if len(valid) >= 6:
            cagr = np.prod(1 + np.array(valid)) ** (12/len(valid)) - 1
            results_roll.append({"start": test_dates[0], "end": test_dates[-1], 
                               "cagr": cagr, "n": len(valid), "hit": (np.array(valid) > 0).mean()})
    
    print(f"\nRolling window ({train_window}m train, 12m test):")
    print(f"  Windows tested: {len(results_roll)}")
    if results_roll:
        cagrs = [r["cagr"] for r in results_roll]
        print(f"  Mean OOS CAGR: {np.mean(cagrs):.2%}")
        print(f"  OOS CAGR t-stat (NW): {newey_west_t(cagrs):.2f}")
        print(f"  OOS win rate: {sum(1 for r in results_roll if r['cagr']>0)/len(results_roll):.1%}")
        print(f"  CAGR range: [{min(cagrs):.2%}, {max(cagrs):.2%}]")

    # 5. COST SENSITIVITY SUMMARY
    print("\n" + "="*100)
    print("COST SENSITIVITY (Overall CAGR, Sharpe)")
    print("="*100)
    for c in COST_SCENARIOS:
        rets = [x for x in all_cost_rets[c] if x is not None]
        tor = compute_turnover(all_holdings)
        all_t = [x for x in tor if x is not None]
        s = port_stats(rets)
        s["turnover"] = round(float(np.mean(all_t)), 4) if all_t else None
        # Annual cost drag
        cost_drag = 2 * c / 10000 * s["turnover"] * 12 if s["turnover"] else 0
        print(f"  {2*c}bps: CAGR={s['cagr']:.2%} Sharpe={s['sharpe']} Turnover={s['turnover']:.1%} CostDrag={cost_drag:.2%}")

    # 6. TURNOVER & HOLDINGS DETAIL
    print("\n" + "="*100)
    print("HOLDINGS & TURNOVER DETAIL")
    print("="*100)
    hs = [len(h) for h in all_holdings if h]
    print(f"  Mean holdings: {np.mean(hs):.1f}")
    print(f"  Min holdings:  {np.min(hs)}")
    print(f"  Max holdings:  {np.max(hs)}")
    print(f"  Monthly turnover (30bps): {np.mean(compute_turnover(all_holdings)):.1%}")
    
    # Turnover by period
    for p in ["TRAIN", "VALID", "TEST"]:
        idx = [i for i in range(len(periods)-1) if periods[i] == p]
        tor_p = [compute_turnover(all_holdings)[i] for i in idx if i < len(compute_turnover(all_holdings))]
        if tor_p:
            print(f"  {p} turnover: {np.mean(tor_p):.1%}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()