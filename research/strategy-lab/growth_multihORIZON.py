#!/usr/bin/env python
"""Growth Factor Multi-Horizon Forward Return Analysis — KR Research Lab (2026-08-30).

Re-tests HOLD growth factors at 1M, 3M, 6M, 12M forward horizons.
Uses exact same PIT/cost/liquidity conventions as factor_discovery_kr.py.
"""
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
QUALITY_PANEL = os.path.join(LAB, "reports", "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
QUARTERLY_PANEL = os.path.join(LAB, "data", "quarterly-earnings", "quarterly-earnings-panel.jsonl")
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")
OUT_DIR = os.path.join(LAB, "reports", "2026-08-30-growth-multihorizon")

MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
LIQUID_THRESHOLD = 1e8
WARM_BETA = 120
LIQUID_GATE_OFF = False

# HOLD growth factors to test
GROWTH_FACTORS = [
    ("rev_yoy", "A3 revenue YoY", "high"),
    ("op_yoy", "A3 opProfit YoY", "high"),
    ("ni_yoy", "A3 netIncome YoY", "high"),
    ("eps_yoy", "A3b eps YoY", "high"),
    ("qni_yoy", "Quarterly netIncome YoY (recent)", "high"),
]

# Forward horizons in months (approximate trading sessions)
HORIZONS = {
    "1M": 1,
    "3M": 3,
    "6M": 6,
    "12M": 12,
}


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


def agg(recs):
    if not recs:
        return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "mean": round(float(v.mean()), 6), "sd": round(sd, 6),
            "t": round(t, 3) if t is not None else None}


def port_stats(monthly_nets):
    if not monthly_nets:
        return {}
    m = np.array(monthly_nets, dtype=float)
    n = len(m)
    eq = float(np.prod(1 + m))
    span = n / 12
    cagr = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(m)) ** (1 / max(span, 1e-9)) - 1
    sh = float(m.mean() / m.std(ddof=1) * np.sqrt(12)) if m.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in m:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    return {"nMonths": n, "cagr": round(cagr, 4), "sharpe": round(sh, 3) if sh is not None else None,
            "mdd": round(mdd, 4), "meanMonthlyNet": round(float(m.mean()), 5)}


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
    pooled = {d: [] for d in range(1, 11)}
    spread_months, ic_months = [], []
    top_net_months, top_gross_months = [], []
    bot_net_months, bot_gross_months = [], []
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
        for dec_i, gv in g2.groupby("dec"):
            pooled[int(dec_i)].extend(gv[fwd_col].tolist())
        top_g = g2.loc[g2["dec"] == 10, fwd_col]
        bot_g = g2.loc[g2["dec"] == 1, fwd_col]
        if len(top_g):
            top_gross_months.append(float(top_g.mean()))
            top_net_months.append(float(top_g.mean()) - ROUNDTRIP_BPS / 10000)
        if len(bot_g):
            bot_gross_months.append(float(bot_g.mean()))
            bot_net_months.append(float(bot_g.mean()) - ROUNDTRIP_BPS / 10000)
        r = spearmanr(g2[f], g2[fwd_col])
        if not np.isnan(r.statistic):
            ic_months.append(float(r.statistic))
    dec_tab = {}
    dec_means = []
    for dec_i in range(1, 11):
        vals = np.array(pooled[dec_i], dtype=float)
        if len(vals) == 0:
            dec_tab[dec_i] = {"n": 0}
            continue
        dec_tab[dec_i] = {"n": int(len(vals)),
                          "mean": round(float(vals.mean()), 6),
                          "median": round(float(np.median(vals)), 6)}
        dec_means.append(float(vals.mean()))
    dec_slope = None
    if len(dec_means) == 10:
        r = spearmanr(range(1, 11), dec_means)
        dec_slope = round(float(r.statistic), 3)
    out = {
        "n": int(len(sub)), "nMonths": len(ns), "avgNamesPerMonth": round(float(np.mean(ns)), 1) if ns else None,
        "deciles": dec_tab, "decileSlopeSpearman": dec_slope,
        "spread": monthly_spread_stats(spread_months),
        "netSpread": {
            "nMonths": len(spread_months),
            "mean": round(float(np.mean([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months])), 6)
                    if spread_months else None,
            "t": round(float((np.array([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months]).mean() /
                              (np.array([s - ROUNDTRIP_BPS / 10000 for d, s in spread_months]).std(ddof=1)
                               / np.sqrt(len(spread_months))))), 3)
                  if spread_months and len(spread_months) > 1 else None,
        },
        "ic": agg(ic_months),
        "longTopDecile": {"gross": port_stats(top_gross_months), "net": port_stats(top_net_months)},
        "longBottomDecile": {"gross": port_stats(bot_gross_months), "net": port_stats(bot_net_months)},
    }
    return out


def market_split(sub, f, fwd_col):
    out = {}
    for mkt in ["KOSPI", "KOSDAQ"]:
        ss = sub[sub["market"] == mkt]
        spread_months = []
        for ddate, g in ss.groupby("date"):
            if len(g) < MIN_NAMES or g[f].nunique() <= 1:
                continue
            g2 = g.copy()
            g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
            mm = g2.groupby("dec")[fwd_col].mean()
            if 10 in mm.index and 1 in mm.index:
                spread_months.append((ddate, float(mm[10] - mm[1])))
        out[mkt] = monthly_spread_stats(spread_months)
        if out[mkt] is not None:
            out[mkt]["n"] = int(len(ss))
    return out


def load_market_map():
    m = {}
    with open(A1A_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("ticker") and r.get("market"):
                m[r["ticker"]] = r["market"]
    return m


def build_a3_maps():
    REV, NI, OP, EQ, CA, CL = {}, {}, {}, {}, {}, {}
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

                def put(m, val):
                    if val is not None:
                        try:
                            m.setdefault(t, []).append((af, fy, float(val)))
                        except (TypeError, ValueError):
                            pass
                put(REV, r.get("revenue"))
                put(NI, r.get("netIncome"))
                put(OP, r.get("opProfit"))
                put(EQ, r.get("equity"))
                put(CA, r.get("currentAssets"))
                put(CL, r.get("currentLiab"))
    return REV, NI, OP, EQ, CA, CL


def build_a3b_eps():
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
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
                out.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]), r.get("eps")))
    return out


def build_quarterly_ni():
    out = {}
    with open(QUARTERLY_PANEL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            t = r.get("ticker")
            if t is None:
                continue
            thstrm = r.get("thstrm")
            frmtrm = r.get("frmtrm")
            af = normd(str(r["availableFrom"]))
            if thstrm is None or frmtrm is None or frmtrm == 0:
                continue
            try:
                yoy = float(thstrm) / float(frmtrm) - 1.0
            except (TypeError, ValueError, ZeroDivisionError):
                continue
            out.setdefault(t, []).append((af, yoy))
    for t in out:
        out[t].sort(key=lambda x: x[0])
    return out


def load_kospi():
    df = pd.read_parquet(KOSPI_PATH)
    df["date"] = df["date"].astype(str)
    df = df.set_index("date")["value"]
    return df


def main(max_tickers=None):
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    if max_tickers is not None:
        keep = df["ticker"].drop_duplicates().head(max_tickers)
        df = df[df["ticker"].isin(keep)]
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["vv20"] = g["total_volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["dv20_log"] = np.log(df["dv20"].clip(lower=1.0))
    df["vv20_log"] = np.log(df["vv20"].clip(lower=1.0))
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # Build forward returns for multiple horizons
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    
    # For each horizon, compute forward return from signal date
    # Entry: next trading day close, Exit: N months later first session close
    for h_name, h_months in HORIZONS.items():
        exit_map = {}
        for i, sd in enumerate(months):
            if i + h_months < len(months):
                exit_map[sd] = months[i + h_months]
        
        fwd = pd.Series(np.nan, index=base.index, dtype=float)
        for i, sd in enumerate(months[:-h_months]):
            rows = base.index[base["date"] == sd]
            if len(rows) == 0:
                continue
            exit_d = months[i + h_months]
            entry_d = next_date[sd]
            try:
                ec = close_wide.loc[entry_d]
                xc = close_wide.loc[exit_d]
            except KeyError:
                continue
            tks = base.loc[rows, "ticker"]
            vals = (xc.reindex(ec.index) / ec - 1.0)
            fwd.loc[rows] = tks.map(vals).to_numpy(dtype=float)
        base[f"fwd{h_name}"] = fwd
    
    base = base.dropna(subset=[f"fwd{h}" for h in HORIZONS.keys()])
    base = base[base["fwd1M"] > -1].copy()
    print(f"  with all fwd returns {len(base)} rows ({time.time()-t0:.0f}s)", flush=True)

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(period_of)
    if not LIQUID_GATE_OFF:
        n_pre = len(base)
        base = base[base["liquid"]].copy()
        print(f"  liquidity gate dv20>=1e8: {n_pre} -> {len(base)} rows", flush=True)

    # ---- fundamentals (PIT) ----
    print("loading A3/A3b/A3c ...", flush=True)
    REV, NI, OP, EQ, CA, CL = build_a3_maps()
    a3b_eps = build_a3b_eps()
    qni = build_quarterly_ni()

    def val_yoy(rec_map, t, as_of):
        recs = rec_map.get(t, [])
        cur = select_as_of(recs, as_of)
        if cur is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def eps_yoy(t, d):
        recs = a3b_eps.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[2] is None:
            return None
        prev = select_fiscal_year(recs, cur[1] - 1, d)
        if prev is None or prev[2] is None or prev[2] == 0:
            return None
        return cur[2] / prev[2] - 1.0

    def qni_yoy_latest(t, d):
        recs = qni.get(t, [])
        if not recs:
            return None
        lo, hi = 0, len(recs)
        while lo < hi:
            mid = (lo + hi) // 2
            if recs[mid][0] <= d:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        return recs[lo - 1][1]

    print("building growth factor columns ...", flush=True)
    c = {"rev_yoy": [], "op_yoy": [], "ni_yoy": [], "eps_yoy": [], "qni_yoy": []}
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c["rev_yoy"].append(val_yoy(REV, t, d))
        c["op_yoy"].append(val_yoy(OP, t, d))
        c["ni_yoy"].append(val_yoy(NI, t, d))
        c["eps_yoy"].append(eps_yoy(t, d))
        c["qni_yoy"].append(qni_yoy_latest(t, d))

    for f in c:
        base[f] = c[f]
    print(f"  base columns ready ({time.time()-t0:.0f}s)", flush=True)

    # ---- per-factor, per-horizon decile analysis ----
    print("=== multi-horizon decile analysis ===", flush=True)
    results = {"experiment": "GROWTH-MULTIHORIZON-2026-08",
               "conventions": {
                   "rebalance": "monthly first session",
                   "entry": "next trading day close",
                   "exit": "N months later first session close",
                   "costBpsPerSide": COST_BPS, "roundTripBps": ROUNDTRIP_BPS,
                   "deciles": "cross-sectional per month, rank-based",
                   "winsorization": "none (rank-based deciles)",
                   "minNamesPerMonth": MIN_NAMES,
                   "liquidityGate": "dv20>=1e8 KRW" if not LIQUID_GATE_OFF else "off"},
               "factors": {}}
    
    for f, src, exp_dir in GROWTH_FACTORS:
        print(f"\n--- {f} ---", flush=True)
        results["factors"][f] = {"source": src, "expectedGoodDirection": exp_dir, "horizons": {}}
        
        for h_name in HORIZONS.keys():
            fwd_col = f"fwd{h_name}"
            sub = base[["ticker", "date", "market", "period", fwd_col, f]].dropna(subset=[f, fwd_col])
            if len(sub) == 0:
                continue
            
            res = decile_analysis(sub, f, fwd_col)
            if res is None:
                continue
            
            res["coverage"] = round(float(sub["ticker"].nunique()) / max(base["ticker"].nunique(), 1), 3)
            res["nObs"] = int(len(sub))
            res["periods"] = {p: int(len(sub[sub["period"] == p])) for p in ["TRAIN", "VALID", "TEST"]}
            res["marketSplit"] = market_split(sub, f, fwd_col)
            results["factors"][f]["horizons"][h_name] = res
            
            sp = res["spread"]
            ic_t = res["ic"].get("t") if res["ic"] else None
            print(f"  {h_name}: n={res['nObs']:6d} Q10-Q1={sp['mean'] if sp else None:>8} "
                  f"t={sp['t'] if sp else None:>5} hit={sp['hitRate'] if sp else None:>4} "
                  f"posYR={sp['posYearRatio'] if sp else None:>4} IC_t={ic_t}")

    results["baseRows"] = int(len(base))
    results["baseTickers"] = int(base["ticker"].nunique())
    results["months"] = len(months)
    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "growth-multihORIZON-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    mt = None
    if "--max-tickers" in sys.argv:
        mt = int(sys.argv[sys.argv.index("--max-tickers") + 1])
    if "--no-liquid-gate" in sys.argv:
        LIQUID_GATE_OFF = True
    main(max_tickers=mt)