#!/usr/bin/env python
"""rev_yoy Deep-Dive Verification — KR Research Lab (2026-08-30).

Tests rev_yoy 12M forward return independence:
1. KOSPI / KOSDAQ split
2. Size terciles (dv20_log)
3. Year-by-year Top 10% returns
4. Valuation control (PBR, PER residualization)
5. Double sort: rev_yoy × PBR
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
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")
OUT_DIR = os.path.join(LAB, "reports", "2026-08-30-revyoy-deepdive")

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
    top10_yearly = {}
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
            yr = ddate[:4]
            top10_yearly.setdefault(yr, []).append(float(top_g.mean()))
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
    top10_yearly_mean = {y: round(float(np.mean(v)), 6) for y, v in top10_yearly.items()}
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
        "top10YearlyMean": top10_yearly_mean,
    }
    return out


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
    df["liquid"] = df["dv20"] >= LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # 12M forward return
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {}
    for i, sd in enumerate(months):
        if i + 12 < len(months):
            exit_map[sd] = months[i + 12]
    
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
    print(f"  with fwd12M {len(base)} rows ({time.time()-t0:.0f}s)", flush=True)

    market_map = load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(period_of)
    if not LIQUID_GATE_OFF:
        n_pre = len(base)
        base = base[base["liquid"]].copy()
        print(f"  liquidity gate dv20>=1e8: {n_pre} -> {len(base)} rows", flush=True)

    # Size tercile labels
    base["size_tercile"] = base.groupby("date")["dv20_log"].transform(
        lambda x: pd.qcut(x.rank(method="first"), 3, labels=["Small", "Mid", "Large"])
    )

    # ---- fundamentals (PIT) ----
    print("loading A3 revenue ...", flush=True)
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

    print("loading valuation panel ...", flush=True)
    vdf = load_panel(VALUATION_PANEL, ["pbr", "per"])
    vlook = lambda t, d, f: panel_lookup(vdf, t, d, f)

    print("building factor columns ...", flush=True)
    c_rev = []
    c_pbr = []
    c_per = []
    for _, rr in base[["ticker", "date"]].iterrows():
        t, d = rr["ticker"], rr["date"]
        c_rev.append(rev_yoy(t, d))
        c_pbr.append(vlook(t, d, "pbr"))
        c_per.append(vlook(t, d, "per"))
    base["rev_yoy"] = c_rev
    base["pbr"] = c_pbr
    base["per"] = c_per
    base["earnings_yield"] = np.where((base["per"].notna()) & (base["per"] > 0),
                                       1.0 / base["per"], np.nan)
    print(f"  base columns ready ({time.time()-t0:.0f}s)", flush=True)

    # ---- Neutralize rev_yoy against PBR and PER ----
    print("neutralizing rev_yoy vs PBR/PER ...", flush=True)
    base["rev_yoy_resid"] = np.nan
    for ddate, g in base.groupby("date"):
        mask = g["rev_yoy"].notna() & g["pbr"].notna() & g["per"].notna()
        if mask.sum() < 50:
            continue
        X = g.loc[mask, ["pbr", "per"]].values
        y = g.loc[mask, "rev_yoy"].values
        X = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
            resid = y - X @ beta
            base.loc[g.index[mask], "rev_yoy_resid"] = resid
        except np.linalg.LinAlgError:
            continue
    print(f"  neutralized ({time.time()-t0:.0f}s)", flush=True)

    # ---- Analysis ----
    fwd_col = "fwd12M"
    results = {"experiment": "REV_YOY_DEEPDIVE-2026-08",
               "conventions": {"rebalance": "monthly first session",
                               "entry": "next trading day close",
                               "exit": "12 months later first session close",
                               "costBpsPerSide": COST_BPS, "roundTripBps": ROUNDTRIP_BPS,
                               "deciles": "cross-sectional per month, rank-based",
                               "minNamesPerMonth": MIN_NAMES,
                               "liquidityGate": "dv20>=1e8 KRW"},
               "analyses": {}}

    # 1. Overall
    print("\n=== Overall ===")
    sub = base[["ticker", "date", "market", "period", fwd_col, "rev_yoy", "size_tercile", "pbr", "per"]].dropna(subset=["rev_yoy", fwd_col])
    res = decile_analysis(sub, "rev_yoy", fwd_col)
    res["nObs"] = int(len(sub))
    res["periods"] = {p: int(len(sub[sub["period"] == p])) for p in ["TRAIN", "VALID", "TEST"]}
    results["analyses"]["overall"] = res
    sp = res["spread"]
    print(f"  n={res['nObs']} Q10-Q1={sp['mean']:.4f} t={sp['t']} hit={sp['hitRate']} posYR={sp['posYearRatio']} IC_t={res['ic'].get('t')}")

    # 2. By Market
    print("\n=== By Market ===")
    for mkt in ["KOSPI", "KOSDAQ"]:
        sub_m = sub[sub["market"] == mkt].copy()
        if len(sub_m) == 0:
            continue
        res = decile_analysis(sub_m, "rev_yoy", fwd_col)
        res["nObs"] = int(len(sub_m))
        results["analyses"][f"market_{mkt}"] = res
        sp = res["spread"]
        print(f"  {mkt}: n={res['nObs']} Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} IC_t={res['ic'].get('t')}")

    # 3. By Size Tercile
    print("\n=== By Size Tercile ===")
    for sz in ["Small", "Mid", "Large"]:
        sub_s = sub[sub["size_tercile"] == sz].copy()
        if len(sub_s) == 0:
            continue
        res = decile_analysis(sub_s, "rev_yoy", fwd_col)
        res["nObs"] = int(len(sub_s))
        results["analyses"][f"size_{sz}"] = res
        sp = res["spread"]
        print(f"  {sz}: n={res['nObs']} Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} IC_t={res['ic'].get('t')}")

    # 4. Valuation-controlled: rev_yoy residual
    print("\n=== Valuation-Controlled (rev_yoy_resid) ===")
    sub_r = base[["ticker", "date", "market", "period", fwd_col, "rev_yoy_resid"]].dropna(subset=["rev_yoy_resid", fwd_col])
    if len(sub_r) > 0:
        res = decile_analysis(sub_r, "rev_yoy_resid", fwd_col)
        res["nObs"] = int(len(sub_r))
        results["analyses"]["rev_yoy_resid_vs_pbr_per"] = res
        sp = res["spread"]
        print(f"  n={res['nObs']} Q10-Q1={sp['mean']:.4f} t={sp['t']} posYR={sp['posYearRatio']} IC_t={res['ic'].get('t')}")

    # 5. Double sort: rev_yoy quintile x pbr quintile
    print("\n=== Double Sort: rev_yoy x PBR ===")
    sub_ds = base[["ticker", "date", "market", "period", fwd_col, "rev_yoy", "pbr"]].dropna(subset=["rev_yoy", "pbr", fwd_col])
    if len(sub_ds) > 0:
        ds_results = {}
        for ddate, g in sub_ds.groupby("date"):
            if len(g) < MIN_NAMES:
                continue
            g2 = g.copy()
            g2["rev_q"] = pd.qcut(g2["rev_yoy"].rank(method="first"), 5, labels=False) + 1
            g2["pbr_q"] = pd.qcut(g2["pbr"].rank(method="first"), 5, labels=False) + 1
            m = g2.groupby(["rev_q", "pbr_q"])[fwd_col].mean()
            if (5, 1) in m.index and (1, 5) in m.index:
                ds_results.setdefault("high_rev_low_pbr", []).append(float(m.loc[(5, 1)]))
                ds_results.setdefault("low_rev_high_pbr", []).append(float(m.loc[(1, 5)]))
            if 5 in g2["rev_q"].values and 1 in g2["rev_q"].values:
                top = g2[g2["rev_q"] == 5][fwd_col].mean()
                bot = g2[g2["rev_q"] == 1][fwd_col].mean()
                ds_results.setdefault("rev_q5_q1", []).append((ddate, float(top - bot)))
        if ds_results:
            for k, v in ds_results.items():
                if k in ["high_rev_low_pbr", "low_rev_high_pbr"]:
                    arr = np.array(v)
                    print(f"  {k}: mean={arr.mean():.4f} t={arr.mean()/arr.std()*np.sqrt(len(arr)):.2f} n={len(arr)}")
                else:
                    arr = np.array([x[1] for x in v])
                    t = arr.mean() / arr.std() * np.sqrt(len(arr)) if arr.std() > 0 else None
                    yrs = {}
                    for d, s in v:
                        yrs.setdefault(d[:4], []).append(s)
                    posYR = sum(1 for v in yrs.values() if np.mean(v) > 0) / max(len(yrs), 1)
                    print(f"  rev_q5-q1 (pbr controlled): mean={arr.mean():.4f} t={t:.2f} posYR={posYR:.2f} n={len(arr)}")
            results["analyses"]["double_sort_rev_pbr"] = {k: (float(np.mean(v)), int(len(v))) if isinstance(v[0], float) else v for k, v in ds_results.items()}

    # 6. Yearly Top 10% detailed
    print("\n=== Yearly Top 10% Returns (Overall) ===")
    if "top10YearlyMean" in res:
        for yr in sorted(res["top10YearlyMean"].keys()):
            print(f"  {yr}: {res['top10YearlyMean'][yr]:.4f}")

    results["baseRows"] = int(len(base))
    results["baseTickers"] = int(base["ticker"].nunique())
    results["months"] = len(months)
    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "revyoy-deepdive-results.json")
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