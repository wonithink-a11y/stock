#!/usr/bin/env python
"""10-KR-17: PBR Nonlinearity — extreme-tail vs nonlinear relationship.

Purpose: is the low-PBR edge due to an extreme-low tail, or a genuine nonlinear
(monotone across deciles) relationship? Reproduces/extends 10-KR-14~16 without
re-optimizing thresholds.

Target: A4 PIT monthly panel 2016~2026, TRAIN/VALID/TEST, PIT-safe,
30bps/side, next-day entry, no LOWMOM60 combination.

  1. PBR as cross-sectional percentile/rank
  2. forward 5/20/60/120D returns & IC by PBR percentile band
  3. Q1~Q10 decile portfolios -> monotonicity
  4. low-PBR sub-bands: Q1, Q1~Q2, Q1~Q3, bottom 5/10/20%
  5. each over TRAIN/VALID/TEST: CAGR, Sharpe, MDD, turnover, txn
  6. mom60-residual IC same check
  7. core: is TEST effect confined to extreme tail?
"""
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                               "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-pbr-nonlinearity")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_TURNOVER = 100_000_000.0
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen: seen.add(d[:7]); out.append(d)
    return out


def profile(monthly):
    if not monthly:
        return {}
    mr = np.array([x["ret"] for x in monthly])
    mg = np.array([x["gross"] for x in monthly])
    n = len(mr)
    eq = float(np.prod(1 + mr))
    eqg = float(np.prod(1 + mg))
    span = n / 12
    cagr_net = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    cagr_gross = eqg ** (1 / max(span, 1e-9)) - 1 if eqg > 0 else (1 + np.sum(mg)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr:
        cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
    return {"n": n, "cagrNet": round(cagr_net, 4), "cagrGross": round(cagr_gross, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    cols = ["ticker", "date", "close", "total_amount"]
    df = pd.read_parquet(A4_PATH, columns=cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    ta = df["total_amount"]
    df["turnover20"] = ta.groupby(df["ticker"]).transform(lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])

    close_by_date = {d: gd[["ticker", "close"]].set_index("ticker")["close"]
                     for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)

    print("Loading PBR panel...")
    pbr_lookup = {}
    with open(VALUATION_PANEL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("pbr") and r["pbr"] > 0:
                pbr_lookup[(r["ticker"], r["asOf"])] = r["pbr"]
    sel = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                       "f5", "f20", "f60", "f120"]].copy()
    sel["pbr"] = sel.apply(lambda r: pbr_lookup.get((r["ticker"], r["date"]), np.nan), axis=1)
    sel = sel.dropna(subset=["pbr"])
    sel_by_date = {d: gd for d, gd in sel.groupby("date")}

    result = {"experiment": "10-KR-17: PBR Nonlinearity (tail vs nonlinear)", "costBps": COST_BPS}

    # ---- helper to build a monthly portfolio series for a band selector ----
    def run_band(band_fn):
        stats = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            out, prev, tkl, tot = [], None, [], 0
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                nd = dates[k + 1]
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER]
                picks = band_fn(db)
                if not picks: continue
                cur = set(picks)
                if prev is not None: tkl.append(len(cur - prev) / len(cur))
                prev = cur
                ent_d = next((d for d in all_dates if d > sd), None)
                if ent_d is None: continue
                ext_d = next((d for d in dates[k + 1:] if d > ent_d), None)
                if ext_d is None: continue
                ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets: continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr, "trades": len(rets)})
                tot += len(rets)
            stats[p] = {**profile(out), "totalTradeSides": int(tot),
                        "avgTurnover": round(float(np.mean(tkl)), 3) if tkl else None}
        return stats

    # ---- 1. IC by period (raw) on liquid universe ----
    print("\n=== IC (raw, liquid universe, monthly) ===")
    ic_raw = {}
    for hn, fc in [("5D", "f5"), ("20D", "f20"), ("60D", "f60"), ("120D", "f120")]:
        ic_raw[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            recs = []
            for sd in dates:
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER].dropna(subset=["f" + hn[:-1]])
                if len(db) < MIN_NAMES or db["pbr"].nunique() <= 1: continue
                r = spearmanr(db["pbr"], db[fc])
                if not np.isnan(r.statistic): recs.append(float(r.statistic))
            ic_raw[hn][p] = {"icMean": round(float(np.mean(recs)), 5) if recs else None,
                             "icT": round(float(np.mean(recs) / (np.std(recs, ddof=1) / np.sqrt(len(recs)))), 3)
                                    if len(recs) > 1 and np.std(recs, ddof=1) > 0 else None,
                             "n": len(recs)}
            print(f"  {hn} {p}: {ic_raw[hn][p]}")
    result["ic_raw"] = ic_raw

    # ---- 2. mom60 residual IC ----
    print("\n=== Residual IC | mom60 ===")
    ic_res = {}
    for hn, fc in [("20D", "f20"), ("60D", "f60"), ("120D", "f120")]:
        ic_res[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            recs = []
            for sd in dates:
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER].dropna(
                    subset=["pbr", "mom60", fc])
                if len(db) < MIN_NAMES or db["pbr"].nunique() <= 1: continue
                pb = db["pbr"].rank(method="average").to_numpy(dtype=float)
                mo = db["mom60"].rank(method="average").to_numpy(dtype=float)
                fr = db[fc].to_numpy(dtype=float)
                try:
                    beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(pb)), mo]), pb, rcond=None)
                    resid = pb - beta[0] - mo * beta[1]
                except np.linalg.LinAlgError:
                    continue
                r = spearmanr(resid, fr)
                if not np.isnan(r.statistic): recs.append(float(r.statistic))
            ic_res[hn][p] = {"icMean": round(float(np.mean(recs)), 5) if recs else None,
                             "icT": round(float(np.mean(recs) / (np.std(recs, ddof=1) / np.sqrt(len(recs)))), 3)
                                    if len(recs) > 1 and np.std(recs, ddof=1) > 0 else None,
                             "n": len(recs)}
            print(f"  {hn} {p}: {ic_res[hn][p]}")
    result["ic_resid_mom60"] = ic_res

    # ---- 3. forward returns by PBR percentile band (pooled) ----
    print("\n=== Mean forward return by PBR decile (pooled, liquid) ===")
    band_ret = {}
    for hn, fc in [("5D", "f5"), ("20D", "f20"), ("60D", "f60"), ("120D", "f120")]:
        band_ret[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            acc = []
            for sd in dates:
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER].dropna(subset=[fc])
                if len(db) < MIN_NAMES: continue
                db = db.copy()
                db["dec"] = pd.qcut(db["pbr"].rank(method="first"), 10, labels=False)
                acc.append(db.groupby("dec")[fc].mean())
            if acc:
                dfr = pd.concat(acc, axis=1).T
                band_ret[hn][p] = {f"D{i+1}": round(float(dfr[i].mean()), 5) if i in dfr.columns else None
                                   for i in range(10)}
            print(f"  {hn} {p}: {band_ret[hn][p]}")
    result["decile_forward_ret"] = band_ret

    # ---- 4. decile portfolios Q1..Q10 (net CAGR) ----
    print("\n=== Decile portfolios (net CAGR / Sharpe) ===")
    dec_stats = {}
    for dec in range(10):
        band = lambda db, dec=dec: db.assign(_d=pd.qcut(db["pbr"].rank(method="first"), 10, labels=False)).query(
            f"_d=={dec}")["ticker"].tolist()
        st = run_band(band)
        dec_stats[f"D{dec+1}"] = st
        print(f"  D{dec+1}: " + "  ".join(f"{p}={st[p]['cagrNet']}(Sh {st[p]['sharpe']})" for p in ["TRAIN", "VALID", "TEST"]))
    result["decile_portfolios"] = dec_stats

    # ---- 5. low-PBR sub-bands ----
    print("\n=== Low-PBR sub-bands (next-day, 30bps) ===")
    def bands_of(db, size):
        db = db.copy()
        db["_q"] = pd.qcut(db["pbr"].rank(method="first"), size, labels=False)
        return db

    sub_stats = {}
    # quintile bands
    q1 = lambda db: db.assign(_q=pd.qcut(db["pbr"].rank(method="first"), 5, labels=False)).query("_q==0")["ticker"].tolist()
    q1q2 = lambda db, n=2: bands_of(db, 5).query(f"_q<={n-1}")["ticker"].tolist()
    q1q3 = lambda db, n=3: bands_of(db, 5).query(f"_q<={n-1}")["ticker"].tolist()
    # percentile tail cuts
    bot5 = lambda db: db[db["pbr"] <= db["pbr"].quantile(0.05)]["ticker"].tolist()
    bot10 = lambda db: db[db["pbr"] <= db["pbr"].quantile(0.10)]["ticker"].tolist()
    bot20 = lambda db: db[db["pbr"] <= db["pbr"].quantile(0.20)]["ticker"].tolist()
    for nm, fn in [("Q1", q1), ("Q1-Q2", q1q2), ("Q1-Q3", q1q3),
                   ("bottom5pct", bot5), ("bottom10pct", bot10), ("bottom20pct", bot20)]:
        st = run_band(fn)
        sub_stats[nm] = st
        print(f"  {nm}: " + "  ".join(f"{p}={st[p]['cagrNet']}(Sh {st[p]['sharpe']}/MDD {st[p]['mdd']})"
                                      for p in ["TRAIN", "VALID", "TEST"]))
    result["low_pbr_subbands"] = sub_stats

    # Q5-Q1 decile spread (net CAGR) as monotonicity summary
    print("\n=== Monotonicity summary: D1 vs D10 net CAGR ===")
    mono = {p: {"D1": dec_stats["D1"][p]["cagrNet"], "D10": dec_stats["D10"][p]["cagrNet"],
                "D1-D10": round(dec_stats["D1"][p]["cagrNet"] - dec_stats["D10"][p]["cagrNet"], 4)}
            for p in ["TRAIN", "VALID", "TEST"]}
    for p in ["TRAIN", "VALID", "TEST"]: print(f"  {p}: {mono[p]}")
    result["decile_monotonicity"] = mono
    result["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "kr-pbr-nonlinearity-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()