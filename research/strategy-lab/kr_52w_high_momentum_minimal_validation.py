#!/usr/bin/env python
"""10-KR-2: 52W High Distance x 60D Momentum 최소 검증.

Feature A = close[t] / rolling_max(high, 252)[t] - 1
Feature B = close[t] / close[t-60] - 1

Experiments: A 단독, B 단독, A x B (equal-rank combination).
OOS splits: TRAIN 2016~2022-06, VALID 2022-06~2024-01, TEST 2024-01~.

Data: A4 (close, fwd_d20/d60/d120, total_amount) + A2a (high, close, open).
reuse 기존 Strategy Lab 관례: monthly rebalance, qcut quintile, daily Spearman IC,
Newey-West t, equal-weight long-only portfolio, curve_metrics.

data/backfill 읽기 전용, production 무변경.
"""
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-52w-momentum-minimal")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES_PER_DATE = 30
NW_LAG = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}
COST_BPS = 15.0  # per side


def newey_west_t(x, lag):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return None
    e = x - x.mean()
    g0 = float(np.sum(e * e)) / n
    s = g0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        s += 2.0 * w * float(np.sum(e[l:] * e[:-l])) / n
    se = np.sqrt(max(s, 0.0) / n)
    return round(float(x.mean() / se), 3) if se > 0 else None


def monthly_rebalance_dates(dates):
    out, seen = [], set()
    for d in sorted(dates.unique()):
        ds = str(d)[:10] if not isinstance(d, str) else d
        ym = ds[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(ds)
    return set(out)


def summarize_ic(recs):
    if not recs:
        return {"nDays": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean() / (sd / np.sqrt(len(vals)))) if sd > 0 else None
    by_year = {}
    for d, v in recs:
        by_year.setdefault(d[:4], []).append(v)
    yearly = {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())}
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd, 5), "icT": round(t, 3) if t is not None else None,
            "icPositiveShare": round(float((vals > 0).mean()), 4), "yearlyICMean": yearly}


def quintile_spread(df, feat, h, rebal):
    sub = df[df["date"].isin(rebal)].dropna(subset=[feat, h]).copy()
    def _q(grp):
        if len(grp) < MIN_NAMES_PER_DATE:
            grp["quintile"] = np.nan
            return grp
        grp["quintile"] = pd.qcut(grp[feat].rank(method="first"), 5, labels=False) + 1
        return grp
    s = sub.groupby("date", group_keys=False).apply(_q)
    s = s.dropna(subset=["quintile"])
    s["quintile"] = s["quintile"].astype(int)
    pooled_mean = s.groupby("quintile")[h].mean()
    sp_pairs = []
    for d, gd in s.groupby("date"):
        top = gd[gd["quintile"] == 5][h]
        bot = gd[gd["quintile"] == 1][h]
        if len(top) and len(bot):
            sp_pairs.append((d, float(top.mean() - bot.mean())))
    sp = np.array([v for _, v in sp_pairs], dtype=float)
    by_year = {}
    for d, v in sp_pairs:
        by_year.setdefault(d[:4], []).append(v)
    return {
        "pooledQuintileMeans": {int(i): round(float(pooled_mean.get(i, np.nan)), 5) for i in range(1, 6)},
        "pooledQ5minusQ1": round(float(pooled_mean.get(5, np.nan) - pooled_mean.get(1, np.nan)), 5),
        "monthlySpreadMean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
        "monthlySpreadNWT": newey_west_t(sp, NW_LAG[h]),
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())},
    }


def quintile_spread_2d(df, feat_a, feat_b, h, rebal):
    sub = df[df["date"].isin(rebal)].dropna(subset=[feat_a, feat_b, h]).copy()
    def _q2d(grp):
        if len(grp) < MIN_NAMES_PER_DATE:
            grp["qA"] = grp["qB"] = np.nan
            return grp
        grp["qA"] = pd.qcut(grp[feat_a].rank(method="first"), 5, labels=False) + 1
        grp["qB"] = pd.qcut(grp[feat_b].rank(method="first"), 5, labels=False) + 1
        return grp
    s = sub.groupby("date", group_keys=False).apply(_q2d).dropna(subset=["qA", "qB"])
    s["qA"] = s["qA"].astype(int)
    s["qB"] = s["qB"].astype(int)
    matrix = {}
    for a in range(1, 6):
        for b in range(1, 6):
            cell = s[(s["qA"] == a) & (s["qB"] == b)][h]
            matrix[f"Q{a}_Q{b}"] = round(float(cell.mean()), 5) if len(cell) else None
    sp_pairs = []
    for d, gd in s.groupby("date"):
        q55 = gd[(gd["qA"] == 5) & (gd["qB"] == 5)][h]
        q11 = gd[(gd["qA"] == 1) & (gd["qB"] == 1)][h]
        if len(q55) and len(q11):
            sp_pairs.append((d, float(q55.mean() - q11.mean())))
    sp = np.array([v for _, v in sp_pairs], dtype=float) if sp_pairs else np.array([])
    return {"matrix": matrix,
            "Q55minusQ11_mean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
            "Q55minusQ11_nwt": newey_west_t(sp, 3) if len(sp) else None,
            "nMonths": int(len(sp))}


def compute_long_only_portfolio(df, feat, rebal_dates):
    sorted_dates = sorted(rebal_dates)
    dates_set = set(df["date"].unique())
    rebal_list = [d for d in sorted_dates if d in dates_set]
    if len(rebal_list) < 2:
        return None, []
    ranked = df[["date", "ticker", feat]].dropna(subset=[feat]).copy()
    ranked["rank"] = ranked.groupby("date")[feat].rank(ascending=True, method="first")
    ranked["nNames"] = ranked.groupby("date")["rank"].transform("count")
    ranked = ranked[ranked["nNames"] >= MIN_NAMES_PER_DATE]
    open_p = df[["date", "ticker", "open"]].dropna(subset=["open"]).copy()
    open_p["next_open"] = open_p.groupby("ticker")["open"].shift(-1)
    rebal_set = set(rebal_list)
    next_open = open_p[open_p["date"].isin(rebal_set)][["date", "ticker", "next_open"]]
    close_p = df[["date", "ticker", "close"]].dropna(subset=["close"]).copy()
    close_p["next_close"] = close_p.groupby("ticker")["close"].shift(-1)
    next_close = close_p[close_p["date"].isin(rebal_set)][["date", "ticker", "next_close"]]
    equity = 100_000_000.0
    equity_curve = [(rebal_list[0], equity)]
    monthly_rets = []
    for i in range(len(rebal_list) - 1):
        sig_date = rebal_list[i]
        exit_date = rebal_list[i + 1]
        day_ranks = ranked[ranked["date"] == sig_date].copy()
        top20pct = int(max(np.ceil(len(day_ranks) * 0.2), 1))
        long = day_ranks.nlargest(top20pct, feat)
        long_tickers = set(long["ticker"])
        entry = next_open[next_open["date"] == sig_date].set_index("ticker")["next_open"]
        ex = next_close[next_close["date"] == sig_date].set_index("ticker")["next_close"]
        rets = []
        for t in long_tickers:
            ep = entry.get(t)
            xp = ex.get(t)
            if pd.notna(ep) and pd.notna(xp) and ep > 0:
                rets.append(xp / ep - 1.0)
        if not rets:
            equity_curve.append((exit_date, equity))
            continue
        raw_ret = float(np.mean(rets))
        turnover = 1.0
        net_ret = raw_ret - turnover * 2 * COST_BPS / 10000
        equity *= (1.0 + net_ret)
        monthly_rets.append(net_ret)
        equity_curve.append((exit_date, equity))
    mr = np.array(monthly_rets)
    if len(mr) > 1 and mr.std(ddof=1) > 0:
        sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12))
    else:
        sharpe = None
    total_ret = equity / 100_000_000.0 - 1
    n_years = max((pd.Timestamp(rebal_list[-1]) - pd.Timestamp(rebal_list[0])).days / 365.25, 1 / 12)
    cagr = (1 + total_ret) ** (1 / n_years) - 1
    peak = 100_000_000.0
    mdd = 0.0
    for _, e in equity_curve:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {
        "cagr": round(cagr, 4), "sharpe": round(sharpe, 4) if sharpe else None,
        "mdd": round(mdd, 4), "totalReturn": round(total_ret, 4),
        "nMonths": len(monthly_rets)}, equity_curve


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    # --- Load A4 ---
    print("Loading A4 research dataset...")
    a4_cols = ["ticker", "date", "close", "total_amount", "fwd_d20", "fwd_d60", "fwd_d120"]
    a4 = pd.read_parquet(A4_PATH, columns=a4_cols)
    a4 = a4.drop_duplicates(subset=["ticker", "date"], keep="last")
    a4 = a4.dropna(subset=["close"])
    a4 = a4[a4["close"] > 0]
    a4_tickers = set(a4["ticker"].unique())
    print(f"  A4: {len(a4)} rows, {len(a4_tickers)} tickers, {a4['date'].min()}~{a4['date'].max()}")

    # --- Load A2a OHLCV (high + open for portfolio) ---
    print("Loading A2a OHLCV for A4 tickers...")
    records = []
    for year in range(2014, 2027):
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path):
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row["ticker"] in a4_tickers:
                    records.append(row)
    a2a = pd.DataFrame(records)
    a2a["date"] = pd.to_datetime(a2a["date"])
    a2a = a2a.sort_values(["ticker", "date"]).reset_index(drop=True)
    a2a = a2a[a2a["date"] >= "2014-06-01"]
    print(f"  A2a: {len(a2a)} rows, {a2a['ticker'].nunique()} tickers, {a2a['date'].min()}~{a2a['date'].max()}")
    print(f"  A2a load: {time.time()-t0:.0f}s")

    # --- Merge ---
    print("Merging A4 + A2a...")
    a4["date"] = pd.to_datetime(a4["date"])
    df = a4.merge(a2a[["ticker", "date", "high", "open"]], on=["ticker", "date"], how="inner")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    print(f"  Merged: {len(df)} rows, {df['ticker'].nunique()} tickers")

    # --- Compute features ---
    print("Computing features...")
    g = df.groupby("ticker", sort=False)
    df["feat_A"] = df["close"] / g["high"].transform(lambda s: s.rolling(252, min_periods=252).max()) - 1.0
    df["feat_B"] = df["close"] / g["close"].shift(60) - 1.0
    n_a = int(df["feat_A"].notna().sum())
    n_b = int(df["feat_B"].notna().sum())
    print(f"  feat_A non-NaN: {n_a} ({100*n_a/len(df):.1f}%), feat_B non-NaN: {n_b} ({100*n_b/len(df):.1f}%)")

    # --- Monthly rebalance dates ---
    rebal = monthly_rebalance_dates(df["date"])
    rebal_list = sorted(rebal)
    print(f"  Monthly rebalance dates: {len(rebal_list)} ({rebal_list[0]} ~ {rebal_list[-1]})")

    # --- OOS splits ---
    def split(d):
        if d <= TRAIN_END:
            return "TRAIN"
        elif d <= VALID_END:
            return "VALID"
        else:
            return "TEST"
    train_rebal = {d for d in rebal if split(d) == "TRAIN"}
    valid_rebal = {d for d in rebal if split(d) == "VALID"}
    test_rebal = {d for d in rebal if split(d) == "TEST"}
    print(f"  TRAIN: {len(train_rebal)}, VALID: {len(valid_rebal)}, TEST: {len(test_rebal)}")

    # --- Data context ---
    data_ctx = {
        "a4_rows": int(len(a4)), "a4_tickers": int(len(a4_tickers)),
        "a2a_rows": int(len(a2a)), "merged_rows": int(len(df)),
        "merged_tickers": int(df["ticker"].nunique()),
        "period": [str(df["date"].min()), str(df["date"].max())],
        "rebalMonths": len(rebal_list),
        "feat_A_coverage": round(100*n_a/len(df), 1),
        "feat_B_coverage": round(100*n_b/len(df), 1),
        "splits": {"TRAIN": [str(min(train_rebal)), str(max(train_rebal))],
                   "VALID": [str(min(valid_rebal)), str(max(valid_rebal))],
                   "TEST": [str(min(test_rebal)), str(max(test_rebal))]},
    }

    # --- Experiment A: feat_A alone ---
    print("\n=== Experiment A: feat_A (52W High Distance) ===")
    results_A = {}
    for period_name, r_set in [("TRAIN", train_rebal), ("VALID", valid_rebal), ("TEST", test_rebal)]:
        r = {}
        for h in ["fwd_d20", "fwd_d60", "fwd_d120"]:
            r[f"quintile_{h}"] = quintile_spread(df, "feat_A", h, r_set)
        ic_recs = []
        for d in r_set:
            sub = df[(df["date"] == d) & df["feat_A"].notna() & df["fwd_d60"].notna()]
            if len(sub) < MIN_NAMES_PER_DATE:
                continue
            rho = spearmanr(sub["feat_A"].to_numpy(), sub["fwd_d60"].to_numpy())
            if not np.isnan(rho.statistic):
                ic_recs.append((d, float(rho.statistic)))
        r["ic_fwd_d60"] = summarize_ic(ic_recs)
        port, ecurve = compute_long_only_portfolio(df, "feat_A", r_set)
        r["portfolio"] = port
        results_A[period_name] = r
        q60 = r.get("quintile_fwd_d60", {})
        ic = r.get("ic_fwd_d60", {})
        p = r.get("portfolio", {})
        print(f"  {period_name}: Q5-Q1(d60)={q60.get('pooledQ5minusQ1')}, "
              f"IC={ic.get('icMean')}(t={ic.get('icT')}), "
              f"CAGR={p.get('cagr')}, Sharpe={p.get('sharpe')}, MDD={p.get('mdd')}")

    # --- Experiment B: feat_B alone ---
    print("\n=== Experiment B: feat_B (60D Momentum) ===")
    results_B = {}
    for period_name, r_set in [("TRAIN", train_rebal), ("VALID", valid_rebal), ("TEST", test_rebal)]:
        r = {}
        for h in ["fwd_d20", "fwd_d60", "fwd_d120"]:
            r[f"quintile_{h}"] = quintile_spread(df, "feat_B", h, r_set)
        ic_recs = []
        for d in r_set:
            sub = df[(df["date"] == d) & df["feat_B"].notna() & df["fwd_d60"].notna()]
            if len(sub) < MIN_NAMES_PER_DATE:
                continue
            rho = spearmanr(sub["feat_B"].to_numpy(), sub["fwd_d60"].to_numpy())
            if not np.isnan(rho.statistic):
                ic_recs.append((d, float(rho.statistic)))
        r["ic_fwd_d60"] = summarize_ic(ic_recs)
        port, ecurve = compute_long_only_portfolio(df, "feat_B", r_set)
        r["portfolio"] = port
        results_B[period_name] = r
        q60 = r.get("quintile_fwd_d60", {})
        ic = r.get("ic_fwd_d60", {})
        p = r.get("portfolio", {})
        print(f"  {period_name}: Q5-Q1(d60)={q60.get('pooledQ5minusQ1')}, "
              f"IC={ic.get('icMean')}(t={ic.get('icT')}), "
              f"CAGR={p.get('cagr')}, Sharpe={p.get('sharpe')}, MDD={p.get('mdd')}")

    # --- Experiment C: A x B combined ---
    print("\n=== Experiment C: feat_A x feat_B (equal-rank combined) ===")
    df["rank_A"] = df.groupby("date")["feat_A"].rank(ascending=True, method="first")
    df["rank_B"] = df.groupby("date")["feat_B"].rank(ascending=True, method="first")
    df["rank_AB"] = df["rank_A"] + df["rank_B"]
    results_C = {}
    for period_name, r_set in [("TRAIN", train_rebal), ("VALID", valid_rebal), ("TEST", test_rebal)]:
        r = {}
        for h in ["fwd_d20", "fwd_d60", "fwd_d120"]:
            r[f"quintile_{h}"] = quintile_spread(df, "rank_AB", h, r_set)
        ic_recs = []
        for d in r_set:
            sub = df[(df["date"] == d) & df["rank_AB"].notna() & df["fwd_d60"].notna()]
            if len(sub) < MIN_NAMES_PER_DATE:
                continue
            rho = spearmanr(sub["rank_AB"].to_numpy(), sub["fwd_d60"].to_numpy())
            if not np.isnan(rho.statistic):
                ic_recs.append((d, float(rho.statistic)))
        r["ic_fwd_d60"] = summarize_ic(ic_recs)
        r["2d_matrix"] = quintile_spread_2d(df, "feat_A", "feat_B", "fwd_d60", r_set)
        port, ecurve = compute_long_only_portfolio(df, "rank_AB", r_set)
        r["portfolio"] = port
        results_C[period_name] = r
        q60 = r.get("quintile_fwd_d60", {})
        ic = r.get("ic_fwd_d60", {})
        p = r.get("portfolio", {})
        mat = r.get("2d_matrix", {})
        print(f"  {period_name}: Q5-Q1(d60)={q60.get('pooledQ5minusQ1')}, "
              f"IC={ic.get('icMean')}(t={ic.get('icT')}), "
              f"Q55-Q11={mat.get('Q55minusQ11_mean')}(nwt={mat.get('Q55minusQ11_nwt')}), "
              f"CAGR={p.get('cagr')}, Sharpe={p.get('sharpe')}, MDD={p.get('mdd')}")

    # --- Redundancy check: A vs B rank correlation ---
    print("\n=== Redundancy: rank(A) vs rank(B) monthly Spearman ===")
    red_recs = []
    for d in rebal:
        sub = df[(df["date"] == d) & df["feat_A"].notna() & df["feat_B"].notna()]
        if len(sub) < MIN_NAMES_PER_DATE:
            continue
        rho = spearmanr(sub["feat_A"].to_numpy(), sub["feat_B"].to_numpy())
        if not np.isnan(rho.statistic):
            red_recs.append((d, float(rho.statistic)))
    redundancy = summarize_ic(red_recs)
    print(f"  rho(A,B) = {redundancy['icMean']:.4f} (t={redundancy['icT']})")

    # --- Cost comparison ---
    print("\n=== Cost drag summary (30bps round-trip) ===")
    for exp_name, res in [("A", results_A), ("B", results_B), ("C", results_C)]:
        for period in ["TRAIN", "VALID", "TEST"]:
            p = res.get(period, {}).get("portfolio", {})
            if p:
                gross_cagr = p.get("cagr")
                net_cagr = p.get("cagr")
                print(f"  {exp_name} {period}: CAGR={gross_cagr}, Sharpe={p.get('sharpe')}")

    # --- Save ---
    report = {
        "experiment": "10-KR-2: 52W High Distance x 60D Momentum minimal validation",
        "featureDefinitions": {
            "feat_A": "close[t] / rolling_max(high, 252)[t] - 1 (52W High Distance)",
            "feat_B": "close[t] / close[t-60] - 1 (60D Momentum)",
        },
        "data": data_ctx,
        "costBpsPerSide": COST_BPS,
        "results": {"A_alone": results_A, "B_alone": results_B, "AB_combined": results_C},
        "redundancy": redundancy,
        "executionTime_s": round(time.time() - t0, 1),
    }
    out_path = os.path.join(OUT_DIR, "kr-52w-momentum-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} (total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
