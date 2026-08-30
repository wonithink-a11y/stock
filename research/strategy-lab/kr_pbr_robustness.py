#!/usr/bin/env python
"""10-KR-16: PBR Robustness (factor itself, NO LOWMOM60 combination).

Fixed: low-PBR long, PIT-safe, monthly rebalance, same universe, same cost (30bps/side).
Checks:
  1. existing selection (top-30 lowest PBR, liquid)
  2. PBR quintile portfolios (Q1..Q5), Q5-Q1 spread, monotonicity
  3. continuous-rank long-only portfolio (liquid names, weight ~ (1-rank))
  4. extreme-name influence: top-30 minus subset & trimmed variants
Metrics per TRAIN/VALID/TEST: CAGR net/gross, Sharpe, MDD, turnover, txn, IC, Q5-Q1.
Core: is 10-KR-14 PASS robust (not a few extreme names / one period / not monotonic)?
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-pbr-robustness")

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
    for n, col in [(20, "f20"), (60, "f60"), (120, "f120")]:
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
    sel = df[df["date"].isin(months)][["ticker", "date", "turnover20", "f20", "f60", "f120"]].copy()
    sel["pbr"] = sel.apply(lambda r: pbr_lookup.get((r["ticker"], r["date"]), np.nan), axis=1)
    sel = sel.dropna(subset=["pbr"])
    sel_by_date = {d: gd for d, gd in sel.groupby("date")}

    # IC + Q5-Q1 by period (liquid universe)
    print("\n=== IC / Q5-Q1 (liquid universe, monthly) ===")
    ic_tab = {}
    for hn, fc in [("20D", "f20"), ("60D", "f60"), ("120D", "f120")]:
        ic_tab[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            recs, spreads = [], []
            for sd in dates:
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER]
                db = db.dropna(subset=["pbr", fc])
                if len(db) < MIN_NAMES or db["pbr"].nunique() <= 1: continue
                r = spearmanr(db["pbr"], db[fc])
                if not np.isnan(r.statistic): recs.append(float(r.statistic))
                db2 = db.copy()
                db2["q"] = pd.qcut(db2["pbr"].rank(method="first"), 5, labels=False)
                spreads.append(float(db2.loc[db2["q"] == 4, fc].mean() - db2.loc[db2["q"] == 0, fc].mean()))
            ic_tab[hn][p] = {
                "icMean": round(float(np.mean(recs)), 5) if recs else None,
                "icT": round(float(np.mean(recs) / (np.std(recs, ddof=1) / np.sqrt(len(recs)))), 3)
                       if len(recs) > 1 and np.std(recs, ddof=1) > 0 else None,
                "nMonths": len(recs),
                "q5q1": round(float(np.mean(spreads)), 5) if spreads else None}
            print(f"  {hn} {p}: {ic_tab[hn][p]}")
    result = {"experiment": "10-KR-16: PBR Robustness (low-PBR factor)", "costBps": COST_BPS}
    result["ic"] = ic_tab

    def run(select_fn, name):
        months_out = {}
        stats = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            out, prev = [], None
            tkl, tot_trades = [], 0
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                nd = dates[k + 1]
                if sd not in sel_by_date: continue
                db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER]
                picks = select_fn(db, sd)
                if not picks: continue
                cur = set(picks)
                if prev is not None:
                    tkl.append(len(cur - prev) / len(cur))
                prev = cur
                ent_d = next((d for d in all_dates if d > sd), None)
                if ent_d is None: continue
                ext_d = next((d for d in dates[k + 1:] if d > ent_d), None)
                if ext_d is None: continue
                ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                rets = []
                for t in picks:
                    if t in ent.index and t in ext.index and ent.loc[t] > 0:
                        rets.append(ext.loc[t] / ent.loc[t] - 1.0)
                if not rets: continue
                gr = float(np.mean(rets))
                out.append({"sd": sd, "ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr,
                            "trades": len(rets)})
                tot_trades += len(rets)
            months_out[p] = out
            stats[p] = {**profile(out),
                        "totalTradeSides": int(tot_trades),
                        "avgTurnoverPerRebal": round(float(np.mean(tkl)), 3) if tkl else None}
        return months_out, stats

    # 1) existing top-30
    top30 = lambda db, sd: db.sort_values("pbr", ascending=True).head(TOP_N)["ticker"].tolist()
    print("\n=== PBR top-30 (existing) ===")
    _, s_top30 = run(top30, "top30")
    for p in ["TRAIN", "VALID", "TEST"]: print(f"  {p}: {s_top30[p]}")
    result["top30"] = s_top30

    # 2) quintile portfolios Q1..Q5
    quint_stats = {}
    for q in range(5):
        qf = lambda db, sd, q=q: db.assign(_grp=pd.qcut(db["pbr"].rank(method="first"), 5,
                                                        labels=False)).query(f"_grp=={q}")["ticker"].tolist()
        _, st = run(qf, f"Q{q+1}")
        quint_stats[f"Q{q+1}"] = st
        print(f"  Q{q+1}: " + "  ".join(f"{p}={st[p]['cagrNet']}(Sh {st[p]['sharpe']})" for p in ["TRAIN", "VALID", "TEST"]))
    result["quintiles"] = quint_stats

    # 3) continuous-rank long-only (weight ~ (1-rank); report equal-rank proxy as avg of Q1~Q5 holdings)
    #    long-only all liquid, weight = 1 - normalized_rank; to keep bookkeeping simple use
    #    weighted-return decomposition per month.
    print("\n=== Continuous-rank long-only (weight ~ 1-rank, all liquid) ===")
    rank_stats = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        out = []
        for k, sd in enumerate(dates):
            if k + 1 >= len(dates): break
            nd = dates[k + 1]
            if sd not in sel_by_date: continue
            db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER].dropna(subset=["pbr"])
            if len(db) < MIN_NAMES: continue
            db = db.copy()
            db["r"] = db["pbr"].rank(method="first")
            db["w"] = db["r"].max() - db["r"] + 1
            db["w"] = db["w"] / db["w"].sum()
            ent_d = next((d for d in all_dates if d > sd), None)
            if ent_d is None: continue
            ext_d = next((d for d in dates[k + 1:] if d > ent_d), None)
            if ext_d is None: continue
            ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
            gr = 0.0
            wgt = {}
            for t, w in zip(db["ticker"], db["w"]):
                if t in ent.index and t in ext.index and ent.loc[t] > 0:
                    gr += w * (ext.loc[t] / ent.loc[t] - 1.0)
                    wgt[t] = w
            if not wgt: continue
            out.append({"sd": sd, "ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr, "trades": len(wgt)})
        rank_stats[p] = {**profile(out), "totalTradeSides": int(sum(x["trades"] for x in out))}
        print(f"  {p}: {rank_stats[p]}")
    result["rank_longonly"] = rank_stats

    # 4) extreme-name influence: top-30 after dropping excluded-by-trim (only lowest-decile).
    #    Variant A: top-30 with pbr in middle band (drop lowest 10% of pbr values each month)
    print("\n=== Top-30 minus extreme-low decile (trim) ===")
    trim_stats = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        out, prev, tkl = [], None, []
        for k, sd in enumerate(dates):
            if k + 1 >= len(dates): break
            nd = dates[k + 1]
            if sd not in sel_by_date: continue
            db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER]
            if len(db) < MIN_NAMES: continue
            db = db.copy()
            # keep only pbr above its 10th percentile (drop the extreme-low band)
            lo = db["pbr"].quantile(0.10)
            db = db[db["pbr"] > lo]
            picks = db.sort_values("pbr").head(TOP_N)["ticker"].tolist()
            cur = set(picks)
            if prev is not None: tkl.append(len(cur - prev) / len(cur))
            prev = cur
            ent_d = next((d for d in all_dates if d > sd), None)
            ext_d = next((d for d in dates[k + 1:] if d > ent_d), None)
            if ent_d is None or ext_d is None: continue
            ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets: continue
            gr = float(np.mean(rets))
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr, "trades": len(rets)})
        trim_stats[p] = {**profile(out), "avgTurnover": round(float(np.mean(tkl)), 3) if tkl else None}
        print(f"  {p}: {trim_stats[p]}")
    result["top30_trim10"] = trim_stats

    # monotonicity: mean net CAGR across Q1..Q5
    print("\n=== Monotonicity (net CAGR by quintile) ===")
    mono = {p: {"Q1": quint_stats["Q1"][p]["cagrNet"], "Q2": quint_stats["Q2"][p]["cagrNet"],
                "Q3": quint_stats["Q3"][p]["cagrNet"], "Q4": quint_stats["Q4"][p]["cagrNet"],
                "Q5": quint_stats["Q5"][p]["cagrNet"]}
            for p in ["TRAIN", "VALID", "TEST"]}
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"  {p}: {mono[p]}")
    result["monotonicity"] = mono
    result["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "kr-pbr-robustness-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()