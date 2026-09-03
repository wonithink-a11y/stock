#!/usr/bin/env python
"""Separate rev_yoy selection effect from concentration effect."""
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
    def s_pbr_q2_rev_rank_top30(grp):
        """PBR Q2에서 rev_yoy 순위 Top 30 (기존 PBR_Q2_only)"""
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        return g[g["pbr_q"] == 2].nlargest(TOP_N, "rev_yoy")

    def s_pbr_q2_rev_rank_top10(grp):
        """PBR Q2에서 rev_yoy 순위 Top 10 (Q5 교집합과 보유수 매칭)"""
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        return g[g["pbr_q"] == 2].nlargest(10, "rev_yoy")

    def s_pbr_q2_rev_q5(grp):
        """PBR Q2 ∩ Rev Q5 교집합 (최대 30)"""
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        g["rev_q"] = pd.qcut(g["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        sel = g[(g["pbr_q"] == 2) & (g["rev_q"] == 5)]
        if len(sel) <= TOP_N:
            return sel
        return sel.nlargest(TOP_N, "rev_yoy")

    def s_pbr_q2_random30(grp):
        """PBR Q2에서 rev_yoy 사용 없이 임의 Top 30 (seed 고정)"""
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        pbr_q2 = g[g["pbr_q"] == 2].copy()
        if len(pbr_q2) <= TOP_N:
            return pbr_q2
        # Use date-based seed for reproducibility
        date_str = grp["date"].iloc[0]
        seed = int(date_str.replace("-", "")) % 1000000
        return pbr_q2.sample(n=TOP_N, random_state=seed)

    def s_pbr_q2_random10(grp):
        """PBR Q2에서 임의 Top 10 (Q5 교집합과 보유수 매칭)"""
        g = grp.copy()
        g["pbr_q"] = pd.qcut(g["pbr"].rank(method="first"), 5, labels=False) + 1
        pbr_q2 = g[g["pbr_q"] == 2].copy()
        if len(pbr_q2) <= 10:
            return pbr_q2
        date_str = grp["date"].iloc[0]
        seed = int(date_str.replace("-", "")) % 1000000
        return pbr_q2.sample(n=10, random_state=seed)

    def s_bench(grp):
        return grp.copy()

    strategies = {
        "PBR_Q2_random30": s_pbr_q2_random30,
        "PBR_Q2_rev_rank_top30": s_pbr_q2_rev_rank_top30,
        "PBR_Q2_rev_rank_top10": s_pbr_q2_rev_rank_top10,
        "PBR_Q2xRev_Q5": s_pbr_q2_rev_q5,
        "PBR_Q2_random10": s_pbr_q2_random10,
        "KOSPI_EW": s_bench,
    }

    results = {}
    holding_sizes = {}

    for name, fn in strategies.items():
        monthly_rets = []
        holdings_list = []
        for ddate in months_sorted[:-1]:
            grp = full[full["date"] == ddate]
            if len(grp) < MIN_NAMES:
                monthly_rets.append(None)
                holdings_list.append(set())
                continue
            sel = fn(grp)
            if len(sel) == 0:
                monthly_rets.append(None)
                holdings_list.append(set())
                continue
            port_ret = sel["fwd1M"].mean() - ROUNDTRIP_BPS / 10000
            monthly_rets.append(float(port_ret))
            holdings_list.append(set(sel["ticker"]))
        tor = compute_turnover_from_holdings(holdings_list)
        results[name] = {"rets": monthly_rets, "holdings": holdings_list, "periods": periods, "tor": tor}
        holding_sizes[name] = [len(h) for h in holdings_list]

    # Print results
    strategy_names = ["PBR_Q2_random30", "PBR_Q2_rev_rank_top30", "PBR_Q2_rev_rank_top10", 
                      "PBR_Q2xRev_Q5", "PBR_Q2_random10", "KOSPI_EW"]
    
    print("\n" + "="*100)
    print("CONCENTRATION vs SELECTION EFFECT TEST")
    print("="*100)
    
    print(f"\n{'Strategy':<24} | {'Period':<7} {'CAGR':>8} {'Sharpe':>7} {'MDD':>8} {'Turnover':>9} {'n':>4}")
    print("-"*100)
    stats_summary = {}
    for name in strategy_names:
        r = results[name]
        s = period_stats(r["rets"], r["tor"], r["periods"])
        stats_summary[name] = s
        for p in ["TRAIN", "VALID", "TEST"]:
            ss = s[p]
            print(f"{name:<24} | {p:<7} {ss['cagr']:>7.2%} {ss['sharpe']:>7} {ss['mdd']:>8.2%} {ss['turnover']:>8.1%} {ss['n']:>4}")
        all_rets = [x for x in r["rets"] if x is not None]
        all_tor = [x for x in r["tor"] if x is not None]
        overall = port_stats(all_rets)
        overall["turnover"] = round(float(np.mean(all_tor)), 4) if all_tor else None
        overall["n"] = len(all_rets)
        print(f"{name:<24} | {'ALL':<7} {overall['cagr']:>7.2%} {overall['sharpe']:>7} {overall['mdd']:>8.2%} {overall['turnover']:>8.1%} {overall['n']:>4}")
        print()

    # Holdings stats
    print("\n" + "="*100)
    print("HOLDINGS STATISTICS")
    print("="*100)
    for name in strategy_names:
        hs = holding_sizes[name]
        hs_valid = [x for x in hs if x > 0]
        if hs_valid:
            print(f"\n{name}:")
            print(f"  Mean holdings: {np.mean(hs_valid):.1f}")
            print(f"  Min holdings:  {np.min(hs_valid)}")
            print(f"  Max holdings:  {np.max(hs_valid)}")

    # Excess vs benchmark
    print("\n" + "="*100)
    print("EXCESS RETURN vs KOSPI_EW (annualized %pp)")
    print("="*100)
    bench_rets = [x for x in results["KOSPI_EW"]["rets"] if x is not None]
    for name in ["PBR_Q2_random30", "PBR_Q2_rev_rank_top30", "PBR_Q2_rev_rank_top10", 
                 "PBR_Q2xRev_Q5", "PBR_Q2_random10"]:
        r = results[name]
        rets = [x for x in r["rets"] if x is not None]
        min_len = min(len(rets), len(bench_rets))
        print(f"\n{name}:")
        for p in ["TRAIN", "VALID", "TEST"]:
            idx = [i for i in range(min_len) if i < len(periods) and periods[i] == p]
            if idx:
                p_rets = [rets[i] for i in idx]
                b_rets = [bench_rets[i] for i in idx]
                excess = (np.mean(np.array(p_rets) - np.array(b_rets)) * 12) if p_rets else 0
                span = len(p_rets) / 12
                cagr_p = (np.prod(1 + np.array(p_rets)) - 1) if p_rets else 0
                cagr_p = (1 + cagr_p) ** (1 / span) - 1 if span > 0 and cagr_p > -1 else 0
                cagr_b = (np.prod(1 + np.array(b_rets)) - 1) if b_rets else 0
                cagr_b = (1 + cagr_b) ** (1 / span) - 1 if span > 0 and cagr_b > -1 else 0
                print(f"  {p}: {excess:>+7.2%}pp (CAGR {cagr_p:.2%} vs bench {cagr_b:.2%})")
        excess_all = np.mean(np.array(rets[:min_len]) - np.array(bench_rets[:min_len])) * 12
        print(f"  ALL: {excess_all:>+7.2%}pp (annualized mean monthly diff)")

    # Key comparisons
    print("\n" + "="*100)
    print("KEY COMPARISONS: Selection vs Concentration")
    print("="*100)
    
    # 1. 30 holdings: rev_rank vs random
    print("\n--- 30 holdings: rev_rank_top30 vs random30 ---")
    r30 = results["PBR_Q2_rev_rank_top30"]
    rand30 = results["PBR_Q2_random30"]
    for p in ["TRAIN", "VALID", "TEST"]:
        idx = [i for i in range(min(len(r30["rets"]), len(rand30["rets"]))) if i < len(periods) and periods[i] == p]
        a = [r30["rets"][i] for i in idx if r30["rets"][i] is not None]
        b = [rand30["rets"][i] for i in idx if rand30["rets"][i] is not None]
        if a and b:
            min_len = min(len(a), len(b))
            diff = np.mean(np.array(a[:min_len]) - np.array(b[:min_len])) * 12
            cagr_a = (np.prod(1 + np.array(a[:min_len])) - 1) if a else 0
            cagr_a = (1 + cagr_a) ** (12/min_len) - 1 if cagr_a > -1 else 0
            cagr_b = (np.prod(1 + np.array(b[:min_len])) - 1) if b else 0
            cagr_b = (1 + cagr_b) ** (12/min_len) - 1 if cagr_b > -1 else 0
            print(f"  {p}: rev_rank - random = {diff:+.2%}pp (rev_rank={cagr_a:.2%}, random={cagr_b:.2%})")
    
    # 2. 10 holdings: rev_rank_top10 vs Q5 intersection vs random10
    print("\n--- 10 holdings: rev_rank_top10 vs Q5 intersection vs random10 ---")
    r10 = results["PBR_Q2_rev_rank_top10"]
    q5 = results["PBR_Q2xRev_Q5"]
    rand10 = results["PBR_Q2_random10"]
    for p in ["TRAIN", "VALID", "TEST"]:
        idx = [i for i in range(min(len(r10["rets"]), len(q5["rets"]), len(rand10["rets"]))) if i < len(periods) and periods[i] == p]
        a = [r10["rets"][i] for i in idx if r10["rets"][i] is not None]
        b = [q5["rets"][i] for i in idx if q5["rets"][i] is not None]
        c = [rand10["rets"][i] for i in idx if rand10["rets"][i] is not None]
        if a and b and c:
            min_len = min(len(a), len(b), len(c))
            diff_rq = np.mean(np.array(a[:min_len]) - np.array(b[:min_len])) * 12
            diff_rr = np.mean(np.array(a[:min_len]) - np.array(c[:min_len])) * 12
            diff_qr = np.mean(np.array(b[:min_len]) - np.array(c[:min_len])) * 12
            cagr_a = (np.prod(1 + np.array(a[:min_len])) - 1) if a else 0
            cagr_a = (1 + cagr_a) ** (12/min_len) - 1 if cagr_a > -1 else 0
            cagr_b = (np.prod(1 + np.array(b[:min_len])) - 1) if b else 0
            cagr_b = (1 + cagr_b) ** (12/min_len) - 1 if cagr_b > -1 else 0
            cagr_c = (np.prod(1 + np.array(c[:min_len])) - 1) if c else 0
            cagr_c = (1 + cagr_c) ** (12/min_len) - 1 if cagr_c > -1 else 0
            print(f"  {p}: rev_rank={cagr_a:.2%}, Q5={cagr_b:.2%}, random={cagr_c:.2%}")
            print(f"       rev_rank - Q5 = {diff_rq:+.2%}pp | rev_rank - random = {diff_rr:+.2%}pp | Q5 - random = {diff_qr:+.2%}pp")

    # 3. Q5 intersection holding size distribution
    print("\n--- PBR_Q2xRev_Q5 holding size (actual intersection size) ---")
    q5_hs = holding_sizes["PBR_Q2xRev_Q5"]
    q5_valid = [x for x in q5_hs if x > 0]
    if q5_valid:
        print(f"  Mean: {np.mean(q5_valid):.1f}, Min: {np.min(q5_valid)}, Max: {np.max(q5_valid)}")
        # Distribution
        from collections import Counter
        dist = Counter(q5_valid)
        print(f"  Distribution: {dict(sorted(dist.items()))}")

    # Correlation
    print("\n--- Monthly return correlations ---")
    pairs = [
        ("PBR_Q2_rev_rank_top30", "PBR_Q2_random30"),
        ("PBR_Q2_rev_rank_top10", "PBR_Q2xRev_Q5"),
        ("PBR_Q2_rev_rank_top10", "PBR_Q2_random10"),
        ("PBR_Q2xRev_Q5", "PBR_Q2_random10"),
    ]
    for n1, n2 in pairs:
        r1 = [x for x in results[n1]["rets"] if x is not None]
        r2 = [x for x in results[n2]["rets"] if x is not None]
        min_len = min(len(r1), len(r2))
        if min_len > 10:
            corr = np.corrcoef(r1[:min_len], r2[:min_len])[0,1]
            print(f"  {n1} vs {n2}: {corr:.4f}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()