#!/usr/bin/env python
"""Attribution: decompose PBR_Q2 x Rev_Q5 performance into PBR, rev_yoy, interaction."""
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


def select_top_n(df, n=TOP_N, sort_col="rev_yoy"):
    """Select top-N names by sort_col within the dataframe (equal-weight)."""
    if len(df) <= n:
        return df.copy()
    return df.nlargest(n, sort_col)


def build_returns(full, strategy_fn, cost=ROUNDTRIP_BPS / 10000):
    """Build monthly portfolio returns for a strategy function.
    strategy_fn(grp) -> dataframe of selected names for a given month group."""
    monthly_rets = []
    months_sorted = sorted(full["date"].unique())
    holdings_list = []
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate]
        if len(grp) < MIN_NAMES:
            monthly_rets.append(None)
            holdings_list.append([])
            continue
        sel = strategy_fn(grp)
        if len(sel) == 0:
            monthly_rets.append(None)
            holdings_list.append([])
            continue
        port_ret = sel["fwd1M"].mean() - cost
        monthly_rets.append(float(port_ret))
        holdings_list.append(set(sel["ticker"]))
    return monthly_rets, holdings_list


def compute_turnover(holdings_list):
    """Compute monthly turnover given list of holding sets."""
    turnovers = []
    for i in range(1, len(holdings_list)):
        if not holdings_list[i] or not holdings_list[i - 1]:
            turnovers.append(0.0)
            continue
        intersection = len(holdings_list[i] & holdings_list[i - 1])
        turnover = 1.0 - intersection / max(len(holdings_list[i]), 1)
        turnovers.append(turnover)
    return turnovers


def compute_turnover_from_holdings(holdings_list):
    """Compute monthly turnover from list of holding sets.
    Result has same length as holdings_list: turnover[0]=0, turnover[i] for i>=1 computed from holdings[i]&holdings[i-1]."""
    turnovers = [0.0]  # first month has no prior turnover
    for i in range(1, len(holdings_list)):
        if not holdings_list[i] or not holdings_list[i - 1]:
            turnovers.append(0.0)
            continue
        intersection = len(holdings_list[i] & holdings_list[i - 1])
        turnover = 1.0 - intersection / max(len(holdings_list[i]), 1)
        turnovers.append(turnover)
    return turnovers


def period_stats(monthly_rets, turnover_list, periods):
    """Compute stats per period."""
    out = {}
    n_rets = len(monthly_rets)
    for p in ["TRAIN", "VALID", "TEST"]:
        # Only consider indices that are valid for monthly_rets (0 to n_rets-1)
        valid_indices = [i for i in range(n_rets) if i < len(periods) and periods[i] == p]
        rets = [monthly_rets[i] for i in valid_indices if monthly_rets[i] is not None]
        turns = [turnover_list[i] for i in valid_indices if i < len(turnover_list)]
        s = port_stats(rets)
        s["turnover"] = round(float(np.mean(turns)), 4) if turns else None
        s["n"] = len(rets)
        out[p] = s
    return out


def regression_attribution(full, months_sorted):
    """Monthly excess-return regression: Combined_excess ~ PBR_excess + Rev_excess.
    excess = strategy return - KOSPI_EW benchmark return."""
    bench = full.groupby("date")["fwd1M"].mean().reindex(months_sorted).shift(0).values
    # Build combined, PBR, Rev monthly returns
    comb = []
    pbr = []
    rev = []
    for ddate in months_sorted[:-1]:
        grp = full[full["date"] == ddate]
        if len(grp) < MIN_NAMES:
            comb.append(np.nan); pbr.append(np.nan); rev.append(np.nan); continue
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        sel_pbr = g[g["pbr_q"] == 2]
        sel_rev = g[g["rev_q"] == 5]
        sel_both = g[(g["pbr_q"] == 2) & (g["rev_q"] == 5)]
        if len(sel_pbr) == 0 or len(sel_rev) == 0 or len(sel_both) == 0:
            comb.append(np.nan); pbr.append(np.nan); rev.append(np.nan); continue
        comb.append(sel_both["fwd1M"].mean())
        pbr.append(sel_pbr["fwd1M"].mean())
        rev.append(sel_rev["fwd1M"].mean())
    comb = np.array(comb[:-1]); pbr = np.array(pbr[:-1]); rev = np.array(rev[:-1]); bench = np.array(bench[:-1])
    mask = ~(np.isnan(comb) | np.isnan(pbr) | np.isnan(rev) | np.isnan(bench))
    comb = comb[mask]; pbr = pbr[mask]; rev = rev[mask]; bench = bench[mask]
    comb_ex = comb - bench
    pbr_ex = pbr - bench
    rev_ex = rev - bench
    # OLS: comb_ex ~ pbr_ex + rev_ex
    # Ensure all arrays same length after removing last element
    min_len = min(len(comb)-1, len(pbr)-1, len(rev)-1, len(bench)-1)
    comb = np.array(comb[:min_len+1]); pbr = np.array(pbr[:min_len+1]); rev = np.array(rev[:min_len+1]); bench = np.array(bench[:min_len+1])
    comb_ex = comb - bench
    pbr_ex = pbr - bench
    rev_ex = rev - bench
    mask = ~(np.isnan(comb_ex) | np.isnan(pbr_ex) | np.isnan(rev_ex) | np.isnan(bench_ex))


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

    def s_rev_q5(grp):
        g = grp.copy()
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        return g[g["rev_q"] == 5].nlargest(TOP_N, "rev_yoy")

    def s_both(grp):
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        sel = g[(g["pbr_q"] == 2) & (g["rev_q"] == 5)]
        if len(sel) <= TOP_N:
            return sel
        return sel.nlargest(TOP_N, "rev_yoy")

    def s_mix50(grp):
        pbr = s_pbr_q2(grp)
        rev = s_rev_q5(grp)
        combined = pd.concat([pbr, rev]).drop_duplicates(subset="ticker")
        return combined.head(TOP_N)

    def s_bench(grp):
        return grp.copy()

    strategies = {
        "PBR_Q2_only": s_pbr_q2,
        "Rev_Q5_only": s_rev_q5,
        "PBR_Q2xRev_Q5": s_both,
        "50:50_mix": s_mix50,
        "KOSPI_EW": s_bench,
    }

    results = {}
    for name, fn in strategies.items():
        rets, holdings = build_returns(full, fn)
        # Compute turnover from holdings
        tor = compute_turnover_from_holdings(holdings)
        results[name] = {"rets": rets, "holdings": holdings, "turnover": tor, "periods": periods}

    # Print table
    stats_summary = {}
    for name in ["PBR_Q2_only", "Rev_Q5_only", "PBR_Q2xRev_Q5", "50:50_mix", "KOSPI_EW"]:
        r = results[name]
        s = period_stats(r["rets"], r["turnover"], r["periods"])
        stats_summary[name] = s
        for p in ["TRAIN", "VALID", "TEST"]:
            ss = s[p]
            print(f"{name:<16} | {p:<7} {ss['cagr']:>7.2%} {ss['sharpe']:>7} {ss['mdd']:>8.2%} {ss['turnover']:>8.1%} {ss['n']:>4}")
        print()

    # Excess return vs benchmark
    print("\n" + "="*80)
    print("EXCESS RETURN vs KOSPI_EW (annualized, pp)")
    print("="*80)
    bench_cagr = stats_summary["KOSPI_EW"]
    for name in ["PBR_Q2_only", "Rev_Q5_only", "PBR_Q2xRev_Q5", "50:50_mix"]:
        row = stats_summary[name]
        print(f"\n{name}:")
        for p in ["TRAIN", "VALID", "TEST"]:
            excess = row[p]["cagr"] - bench_cagr[p]["cagr"]
            print(f"  {p}: {excess:>+7.2%}pp (CAGR {row[p]['cagr']:.2%} vs bench {bench_cagr[p]['cagr']:.2%})")

    # Interaction attribution
    print("="*80)
    print("INTERACTION ATTRIBUTION")
    print("="*80)
    pbr_cagr = stats_summary["PBR_Q2_only"]
    rev_cagr = stats_summary["Rev_Q5_only"]
    mix_cagr = stats_summary["50:50_mix"]
    both_cagr = stats_summary["PBR_Q2xRev_Q5"]

    print("\n--- CAGR Decomposition ---")
    for p in ["TRAIN", "VALID", "TEST"]:
        pbr_s = pbr_cagr[p]["cagr"]
        rev_s = rev_cagr[p]["cagr"]
        mix_s = mix_cagr[p]["cagr"]
        both_s = both_cagr[p]["cagr"]
        naive_mix = (pbr_s + rev_s) / 2
        interaction = both_s - naive_mix
        print(f"  {p}: PBR={pbr_s:.2%} Rev={rev_s:.2%} NaiveMix={naive_mix:.2%} Intersection={both_s:.2%} Interaction={interaction:+.2%}")

    print("\n--- Excess over simple average of single factors ---")
    for p in ["TRAIN", "VALID", "TEST"]:
        both_excess = both_cagr[p]["cagr"] - (pbr_cagr[p]["cagr"] + rev_cagr[p]["cagr"]) / 2
        mix_excess = mix_cagr[p]["cagr"] - (pbr_cagr[p]["cagr"] + rev_cagr[p]["cagr"]) / 2
        both_vs_mix = both_cagr[p]["cagr"] - mix_cagr[p]["cagr"]
        print(f"  {p}: Intersection excess={both_excess:+.2%}pp | Mix excess={mix_excess:+.2%}pp | Intersection-Mix={both_vs_mix:+.2%}pp")

    # Regression
    print("="*80)
    print("MONTHLY EXCESS-RETURN REGRESSION")
    print("  Combined_excess ~ PBR_excess + Rev_excess")
    print("="*80)
    reg = regression_attribution(full, months_sorted)
    print(f"\n  alpha (intercept): {reg['alpha']:+.6f} monthly  (t={reg['t_alpha']})")
    print(f"  beta_PBR:          {reg['beta_pbr']:.3f}  (t={reg['t_pbr']})")
    print(f"  beta_Rev:          {reg['beta_rev']:.3f}  (t={reg['t_rev']})")
    print(f"  R-squared:         {reg['r2']:.3f}")
    print(f"  n months:          {reg['n']}")
    print(f"\n  Mean monthly excess returns:")
    print(f"    Combined: {reg['mean_comb_ex']:+.6f}")
    print(f"    PBR-only: {reg['mean_pbr_ex']:+.6f}")
    print(f"    Rev-only: {reg['mean_rev_ex']:+.6f}")
    print(f"    Residual (interaction): {reg['mean_interaction']:+.6f}")

    # Interpretation
    print("\n" + "="*80)
    print("INTERPRETATION")
    print("="*80)
    pbr_share = reg['beta_pbr'] * reg['mean_pbr_ex'] if reg['mean_pbr_ex'] != 0 else 0
    rev_share = reg['beta_rev'] * reg['mean_rev_ex'] if reg['mean_rev_ex'] != 0 else 0
    total_exp = pbr_share + rev_share + reg['alpha']
    print(f"\n  Decomposition of mean combined excess ({reg['mean_comb_ex']:+.6f}):")
    print(f"    PBR linear effect:  {pbr_share:+.6f}  ({pbr_share/total_exp*100:.0f}% of total)" if total_exp != 0 else "    PBR linear effect:  --")
    print(f"    Rev linear effect:  {rev_share:+.6f}  ({rev_share/total_exp*100:.0f}% of total)" if total_exp != 0 else "    Rev linear effect:  --")
    print(f"    Interaction (alpha):{reg['alpha']:+.6f}  ({reg['alpha']/total_exp*100:.0f}% of total)" if total_exp != 0 else "    Interaction (alpha):--")

    if abs(reg['alpha']) < abs(reg['mean_pbr_ex']) * 0.3 and abs(reg['alpha']) < abs(reg['mean_rev_ex']) * 0.3:
        print("\n  => Most of the combined excess is explained by linear PBR + Rev effects.")
        print("     The intersection provides NO significant incremental interaction alpha.")
    elif reg['alpha'] > 0 and reg['r2'] < 0.7:
        print("\n  => Positive intercept: intersection adds incremental value beyond linear")
        print("     combination of single factors (non-additive interaction effect).")
    else:
        print("\n  => Mixed: both linear and interaction effects contribute.")

    print(f"\n  R²={reg['r2']:.3f}: ", end="")
    if reg['r2'] > 0.8:
        print("High fit → combined excess is well-explained by linear PBR + Rev.")
        print("    Interaction (alpha) is the residual only.")
    elif reg['r2'] > 0.5:
        print("Moderate fit → some interaction effect present.")
    else:
        print("Low fit → factors are not linearly additive; significant interaction.")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()