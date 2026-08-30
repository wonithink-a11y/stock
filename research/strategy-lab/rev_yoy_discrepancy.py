#!/usr/bin/env python
"""Discrepancy investigation: rev_yoy residualization vs double-sort."""
import bisect
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")

MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
LIQUID_THRESHOLD = 1e8
LIQUID_GATE_OFF = False


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


def monthly_spread_stats(spread_months):
    if not spread_months:
        return None
    arr = np.array([s for d, s in spread_months], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    hit = float((arr > 0).mean())
    years = {}
    for (d, s) in spread_months:
        years.setdefault(d[:4], []).append(s)
    yspread = {y: float(np.mean(v)) for y, v in sorted(years.items())}
    pos_year = float(sum(1 for v in yspread.values() if v > 0) / max(len(yspread), 1))
    return {"nMonths": n, "mean": round(float(arr.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None, "hitRate": round(hit, 3),
            "posYearRatio": round(pos_year, 3), "yearly": {y: round(v, 6) for y, v in yspread.items()}}


def decile_analysis(sub, f, fwd_col):
    if sub.empty:
        return None
    spread_months, ic_months = [], []
    ns = []
    for ddate, g in sub.groupby("date"):
        if len(g) < MIN_NAMES or g[f].nunique() <= 1:
            continue
        g2 = g.copy()
        g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
        ns.append(len(g2))
        m = g2.groupby("dec")[fwd_col].mean()
        if 10 in m.index and 1 in m.index:
            spread_months.append((ddate, float(m[10] - m[1])))
        r = spearmanr(g2[f], g2[fwd_col])
        if not np.isnan(r.statistic):
            ic_months.append(float(r.statistic))
    sp = monthly_spread_stats(spread_months)
    ic_t = None
    if ic_months:
        ic_arr = np.array(ic_months)
        ic_t = round(float(ic_arr.mean() / ic_arr.std(ddof=1) * np.sqrt(len(ic_arr))), 3)
    return {"n": int(len(sub)), "nMonths": len(ns),
            "spread": sp, "ic_t": ic_t}


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


def load_kospi():
    df = pd.read_parquet(KOSPI_PATH)
    df["date"] = df["date"].astype(str)
    df = df.set_index("date")["value"]
    return df


def main():
    t0 = time.time()
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    g = df.groupby("ticker", sort=False)
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vv20"] = g["total_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()

    # 12M forward
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
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
    base["period"] = base["date"].map(period_of)
    if not LIQUID_GATE_OFF:
        base = base[base["liquid"]].copy()

    # Build rev_yoy
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

    c_rev, c_pbr, c_per = [], [], []
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c_rev.append(rev_yoy(t, d))
        c_pbr.append(vlook(t, d, "pbr"))
        c_per.append(vlook(t, d, "per"))
    base["rev_yoy"] = c_rev
    base["pbr"] = c_pbr
    base["per"] = c_per

    fwd_col = "fwd12M"
    
    # ============================================
    # SAME SAMPLE for all tests
    # ============================================
    full = base[["ticker", "date", "market", "period", fwd_col, "rev_yoy", "pbr", "per", "dv20_log"]].dropna(subset=["rev_yoy", "pbr", "per", fwd_col])
    print(f"Common sample: {len(full)} rows, {full['ticker'].nunique()} tickers")
    
    # ---------- 1. Overall baseline ----------
    print("\n=== 1. Baseline (no control) ===")
    res = decile_analysis(full, "rev_yoy", fwd_col)
    print(f"  Q10-Q1: {res['spread']['mean']:.4f} t={res['spread']['t']} IC={res['ic_t']} posYR={res['spread']['posYearRatio']}")
    
    # ---------- 2. Residualization (PBR + PER) ----------
    print("\n=== 2. Cross-sectional Residualization (PBR+PER) ===")
    full["rev_resid"] = np.nan
    for ddate, grp in full.groupby("date"):
        mask = grp["rev_yoy"].notna() & grp["pbr"].notna() & grp["per"].notna()
        if mask.sum() < 50:
            continue
        X = grp.loc[mask, ["pbr", "per"]].values
        y = grp.loc[mask, "rev_yoy"].values
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ beta
            full.loc[grp.index[mask], "rev_resid"] = resid
        except np.linalg.LinAlgError:
            continue
    sub_r = full.dropna(subset=["rev_resid", fwd_col])
    res = decile_analysis(sub_r, "rev_resid", fwd_col)
    print(f"  Q10-Q1: {res['spread']['mean']:.4f} t={res['spread']['t']} IC={res['ic_t']} posYR={res['spread']['posYearRatio']} n={res['n']}")
    
    # ---------- 3. Residualization (PBR only) ----------
    print("\n=== 3. Cross-sectional Residualization (PBR only) ===")
    full["rev_resid_pbr"] = np.nan
    for ddate, grp in full.groupby("date"):
        mask = grp["rev_yoy"].notna() & grp["pbr"].notna()
        if mask.sum() < 50:
            continue
        X = grp.loc[mask, ["pbr"]].values
        y = grp.loc[mask, "rev_yoy"].values
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ beta
            full.loc[grp.index[mask], "rev_resid_pbr"] = resid
        except np.linalg.LinAlgError:
            continue
    sub_r = full.dropna(subset=["rev_resid_pbr", fwd_col])
    res = decile_analysis(sub_r, "rev_resid_pbr", fwd_col)
    print(f"  Q10-Q1: {res['spread']['mean']:.4f} t={res['spread']['t']} IC={res['ic_t']} posYR={res['spread']['posYearRatio']} n={res['n']}")

    # ---------- 4. Double-sort: PBR 5x5 within-cell ----------
    print("\n=== 4. Double-sort: PBR quintile x rev_yoy quintile ===")
    sub_ds = full.copy()
    ds_spreads = []
    for ddate, grp in sub_ds.groupby("date"):
        if len(grp) < MIN_NAMES:
            continue
        g2 = grp.copy()
        g2["pbr_q"] = pd.qcut(g2["pbr"].rank(method="first"), 5, labels=False) + 1
        g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        m = g2.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
        if (1, 5) in m.index and (1, 1) in m.index:
            # Within each PBR quintile, rev Q5 - Q1
            for pbr_q in range(1, 6):
                if (pbr_q, 5) in m.index and (pbr_q, 1) in m.index:
                    ds_spreads.append((ddate, pbr_q, float(m.loc[(pbr_q, 5)] - m.loc[(pbr_q, 1)])))
    
    if ds_spreads:
        ds_df = pd.DataFrame(ds_spreads, columns=["date", "pbr_q", "spread"])
        for pbr_q in range(1, 6):
            sub = ds_df[ds_df["pbr_q"] == pbr_q]
            if len(sub) > 0:
                sp = monthly_spread_stats(list(zip(sub["date"], sub["spread"])))
                print(f"  PBR Q{pbr_q}: Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} n_months={sp['nMonths']}")
        
        # Overall within-cell average
        overall = monthly_spread_stats(list(zip(ds_df["date"], ds_df["spread"])))
        print(f"  OVERALL within-cell: Q10-Q1={overall['mean']:.4f} t={overall['t']} posYR={overall['posYearRatio']} n_months={overall['nMonths']}")

    # ---------- 5. PBR decile (10) x rev_yoy Q5-Q1 ----------
    print("\n=== 5. PBR decile x rev_yoy Q5-Q1 ===")
    sub_ds = full.copy()
    ds_spreads = []
    for ddate, grp in sub_ds.groupby("date"):
        if len(grp) < MIN_NAMES:
            continue
        g2 = grp.copy()
        g2["pbr_d"] = pd.qcut(g2["pbr"].rank(method="first"), 10, labels=False) + 1
        g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        m = g2.groupby(["pbr_d", "rev_q"])[fwd_col].mean()
        for pbr_d in range(1, 11):
            if (pbr_d, 5) in m.index and (pbr_d, 1) in m.index:
                ds_spreads.append((ddate, pbr_d, float(m.loc[(pbr_d, 5)] - m.loc[(pbr_d, 1)])))
    
    if ds_spreads:
        ds_df = pd.DataFrame(ds_spreads, columns=["date", "pbr_d", "spread"])
        for pbr_d in range(1, 11):
            sub = ds_df[ds_df["pbr_d"] == pbr_d]
            if len(sub) >= 20:
                sp = monthly_spread_stats(list(zip(sub["date"], sub["spread"])))
                print(f"  PBR D{pbr_d:2d}: Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} n_months={sp['nMonths']}")

    # ---------- 6. KOSPI only ----------
    print("\n=== 6. KOSPI ONLY ===")
    kospi = full[full["market"] == "KOSPI"].copy()
    print(f"  KOSPI sample: {len(kospi)} rows")
    
    # Baseline
    res = decile_analysis(kospi, "rev_yoy", fwd_col)
    print(f"  Baseline: Q10-Q1={res['spread']['mean']:.4f} t={res['spread']['t']} IC={res['ic_t']} posYR={res['spread']['posYearRatio']}")
    
    # Residualization PBR
    kospi["rev_resid_pbr"] = np.nan
    for ddate, grp in kospi.groupby("date"):
        mask = grp["rev_yoy"].notna() & grp["pbr"].notna()
        if mask.sum() < 30:
            continue
        X = grp.loc[mask, ["pbr"]].values
        y = grp.loc[mask, "rev_yoy"].values
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ beta
            kospi.loc[grp.index[mask], "rev_resid_pbr"] = resid
        except np.linalg.LinAlgError:
            continue
    sub_r = kospi.dropna(subset=["rev_resid_pbr", fwd_col])
    res = decile_analysis(sub_r, "rev_resid_pbr", fwd_col)
    print(f"  Resid(PBR): Q10-Q1={res['spread']['mean']:.4f} t={res['spread']['t']} IC={res['ic_t']} posYR={res['spread']['posYearRatio']} n={res['n']}")
    
    # Double-sort KOSPI
    ds_spreads = []
    for ddate, grp in kospi.groupby("date"):
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
            sub = ds_df[ds_df["pbr_q"] == pbr_q]
            if len(sub) > 0:
                sp = monthly_spread_stats(list(zip(sub["date"], sub["spread"])))
                print(f"  KOSPI PBR Q{pbr_q}: Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} n_months={sp['nMonths']}")
        overall = monthly_spread_stats(list(zip(ds_df["date"], ds_df["spread"])))
        print(f"  KOSPI OVERALL within-cell: Q10-Q1={overall['mean']:.4f} t={overall['t']} posYR={overall['posYearRatio']} n_months={overall['nMonths']}")

    # ---------- 7. Low PBR + High rev_yoy cell decomposition ----------
    print("\n=== 7. Cell decomposition: Low PBR + High rev_yoy ===")
    sub_ds = full.copy()
    cell_returns = {}
    for ddate, grp in sub_ds.groupby("date"):
        if len(grp) < MIN_NAMES:
            continue
        g2 = grp.copy()
        g2["pbr_q"] = pd.qcut(g2["pbr"].rank(method="first"), 5, labels=False) + 1
        g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
        m = g2.groupby(["pbr_q", "rev_q"])[fwd_col].mean()
        for pbr_q in range(1, 6):
            for rev_q in range(1, 6):
                if (pbr_q, rev_q) in m.index:
                    cell_returns.setdefault((pbr_q, rev_q), []).append((ddate, float(m.loc[(pbr_q, rev_q)])))
    
    for (pbr_q, rev_q), vals in sorted(cell_returns.items()):
        if len(vals) >= 20:
            arr = np.array([v for d, v in vals])
            t = arr.mean() / arr.std(ddof=1) * np.sqrt(len(arr)) if arr.std(ddof=1) > 0 else None
            posYR = sum(1 for v in arr if v > 0) / len(arr)
            print(f"  PBR Q{pbr_q} x Rev Q{rev_q}: mean={arr.mean():.4f} t={t:.2f} posYR={posYR:.2f} n={len(vals)}")

    # Check Low PBR Q1 x Rev Q5 vs Low PBR Q1 x Rev Q1
    if (1, 5) in cell_returns and (1, 1) in cell_returns:
        v5 = np.array([v for d, v in cell_returns[(1, 5)]])
        v1 = np.array([v for d, v in cell_returns[(1, 1)]])
        print(f"\n  Low PBR + High Rev (Q5): {v5.mean():.4f} (n={len(v5)})")
        print(f"  Low PBR + Low Rev (Q1):  {v1.mean():.4f} (n={len(v1)})")
        print(f"  Difference (Q5-Q1 in Low PBR): {v5.mean() - v1.mean():.4f}")

    # Also check High PBR Q5 x Rev Q5 vs High PBR Q5 x Rev Q1
    if (5, 5) in cell_returns and (5, 1) in cell_returns:
        v5 = np.array([v for d, v in cell_returns[(5, 5)]])
        v1 = np.array([v for d, v in cell_returns[(5, 1)]])
        print(f"\n  High PBR + High Rev (Q5): {v5.mean():.4f} (n={len(v5)})")
        print(f"  High PBR + Low Rev (Q1):  {v1.mean():.4f} (n={len(v1)})")
        print(f"  Difference (Q5-Q1 in High PBR): {v5.mean() - v1.mean():.4f}")

    print(f"\nTotal time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()