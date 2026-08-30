#!/usr/bin/env python
"""10-KR-3: Gap / Overnight Effect 최소 검증.

Features:
  gap[t]         = open[t] / close[t-1] - 1     (전일 close → 당일 open)
  intraday[t]    = close[t] / open[t] - 1        (당일 open → 당일 close)
  next_overnight[t] = open[t+1] / close[t] - 1   (당일 close → 다음 open)

Return decomposition (close-to-close):
  close_to_close[t] = close[t] / close[t-1] - 1 = (1+gap[t]) * (1+intraday[t]) - 1

PIT-safe feature-return pairs:
  gap[t]          → intraday[t]        (signal at open, return open→close)
  intraday[t]     → next_overnight[t]  (signal at close, return close→next open)
  next_overnight[t] → intraday[t+1]    (signal at next open, return open→close)

OOS: TRAIN 2016~2022-06, VALID 2022-06~2024-01, TEST 2024-01~.
Cost: 15bps per side.

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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-gap-overnight")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES_PER_DATE = 30
NW_LAG = 3
COST_BPS = 15.0


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
        "monthlySpreadNWT": newey_west_t(sp, NW_LAG),
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())},
    }


def compute_long_only_portfolio(df, feat, h, rebal_dates, cost_bps=COST_BPS):
    sorted_dates = sorted(rebal_dates)
    dates_set = set(df["date"].unique())
    rebal_list = [d for d in sorted_dates if d in dates_set]
    if len(rebal_list) < 2:
        return None
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
    monthly_rets = []
    for i in range(len(rebal_list) - 1):
        sig_date = rebal_list[i]
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
            continue
        raw_ret = float(np.mean(rets))
        net_ret = raw_ret - 2 * cost_bps / 10000
        equity *= (1.0 + net_ret)
        monthly_rets.append(net_ret)
    mr = np.array(monthly_rets)
    if len(mr) < 2:
        return None
    sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    total_ret = equity / 100_000_000.0 - 1
    n_years = max((pd.Timestamp(rebal_list[min(len(monthly_rets), len(rebal_list)-1)]) -
                   pd.Timestamp(rebal_list[0])).days / 365.25, 1/12)
    cagr = (1 + total_ret) ** (1 / n_years) - 1
    peak = 100_000_000.0
    mdd = 0.0
    cum = 100_000_000.0
    for r in monthly_rets:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    return {"cagr": round(cagr, 4), "sharpe": round(sharpe, 4) if sharpe else None,
            "mdd": round(mdd, 4), "totalReturn": round(total_ret, 4),
            "nMonths": len(monthly_rets)}


def gap_regime_analysis(df, rebal):
    sub = df[df["date"].isin(rebal)].copy()
    sub = sub.dropna(subset=["gap", "intraday"])
    regimes = {
        "gap_up": sub[sub["gap"] > 0],
        "gap_down": sub[sub["gap"] < 0],
        "gap_flat": sub[sub["gap"].abs() < 0.001],
        "large_gap_up": sub[sub["gap"] > sub["gap"].quantile(0.9)],
        "large_gap_down": sub[sub["gap"] < sub["gap"].quantile(0.1)],
    }
    results = {}
    for name, grp in regimes.items():
        if len(grp) < 100:
            continue
        results[name] = {
            "n": int(len(grp)),
            "meanGap": round(float(grp["gap"].mean()), 5),
            "meanIntraday": round(float(grp["intraday"].mean()), 5),
            "meanNextOvernight": round(float(grp["next_overnight"].mean()) if "next_overnight" in grp else np.nan, 5),
            "meanCloseToClose": round(float(grp["close_to_close"].mean()), 5),
            "intradayPositiveShare": round(float((grp["intraday"] > 0).mean()), 4),
        }
    return results


def continuation_reversal(df, rebal):
    sub = df[df["date"].isin(rebal)].dropna(subset=["gap", "intraday", "next_overnight"]).copy()
    gap_sign = np.sign(sub["gap"])
    intraday_sign = np.sign(sub["intraday"])
    cont = (gap_sign == intraday_sign) & (gap_sign != 0)
    rev = (gap_sign != intraday_sign) & (gap_sign != 0) & (intraday_sign != 0)
    results = {
        "gap_and_intraday_same_sign": {
            "n": int(cont.sum()),
            "share": round(float(cont.mean()), 4),
            "meanIntraday_when_cont": round(float(sub.loc[cont, "intraday"].mean()), 5),
            "meanIntraday_when_rev": round(float(sub.loc[rev, "intraday"].mean()), 5) if rev.sum() > 0 else None,
        },
        "intraday_and_next_overnight": {
            "n_same": int((intraday_sign == np.sign(sub["next_overnight"])).sum()),
            "share_same": round(float((intraday_sign == np.sign(sub["next_overnight"])).mean()), 4),
        },
    }
    return results


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("Loading A4 research dataset...")
    a4_cols = ["ticker", "date", "close"]
    a4 = pd.read_parquet(A4_PATH, columns=a4_cols)
    a4 = a4.drop_duplicates(subset=["ticker", "date"], keep="last")
    a4 = a4.dropna(subset=["close"])
    a4 = a4[a4["close"] > 0]
    a4_tickers = set(a4["ticker"].unique())
    print(f"  A4: {len(a4)} rows, {len(a4_tickers)} tickers")

    print("Loading A2a OHLCV...")
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
    print(f"  A2a: {len(a2a)} rows ({time.time()-t0:.0f}s)")

    print("Merging + computing features...")
    a4["date"] = pd.to_datetime(a4["date"])
    df = a4.merge(a2a[["ticker", "date", "open", "high", "low", "close"]], on=["ticker", "date"], how="inner",
                  suffixes=("_a4", "_a2a"))
    if "close_a4" in df.columns:
        df["close"] = df["close_a4"]
        df.drop(columns=["close_a2a"], inplace=True, errors="ignore")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")

    g = df.groupby("ticker", sort=False)
    df["prev_close"] = g["close"].shift(1)
    df["next_open"] = g["open"].shift(-1)
    df["gap"] = df["open"] / df["prev_close"] - 1.0
    df["intraday"] = df["close"] / df["open"] - 1.0
    df["next_overnight"] = df["next_open"] / df["close"] - 1.0
    df["close_to_close"] = df["close"] / df["prev_close"] - 1.0
    print(f"  Merged: {len(df)} rows, {df['ticker'].nunique()} tickers")

    n_gap = int(df["gap"].notna().sum())
    n_id = int(df["intraday"].notna().sum())
    n_no = int(df["next_overnight"].notna().sum())
    print(f"  gap: {n_gap} ({100*n_gap/len(df):.1f}%), intraday: {n_id} ({100*n_id/len(df):.1f}%), "
          f"next_overnight: {n_no} ({100*n_no/len(df):.1f}%)")

    rebal = monthly_rebalance_dates(df["date"])
    rebal_list = sorted(rebal)
    print(f"  Rebal months: {len(rebal_list)}")

    def split(d):
        if d <= TRAIN_END: return "TRAIN"
        elif d <= VALID_END: return "VALID"
        else: return "TEST"
    train_r = {d for d in rebal if split(d) == "TRAIN"}
    valid_r = {d for d in rebal if split(d) == "VALID"}
    test_r = {d for d in rebal if split(d) == "TEST"}
    print(f"  TRAIN: {len(train_r)}, VALID: {len(valid_r)}, TEST: {len(test_r)}")

    # --- PIT-safe feature-return pairs ---
    # gap[t] → intraday[t]: signal at open[t], return open→close
    # intraday[t] → next_overnight[t]: signal at close[t], return close→next open
    # next_overnight[t] → intraday[t+1]: signal at open[t+1], return open→close

    # For pair 3, we need next_overnight[t] as signal and intraday[t+1] as return
    # next_overnight[t] = open[t+1]/close[t]-1 is known at open[t+1]
    # intraday[t+1] = close[t+1]/open[t+1]-1 is the return from open[t+1] to close[t+1]
    # So: signal at open[t+1], return from open[t+1] to close[t+1] — PIT-safe

    experiments = {
        "gap→intraday": {"signal": "gap", "ret": "intraday",
                         "desc": "gap[t] → intraday[t]: gap predicts today's open→close"},
        "intraday→next_overnight": {"signal": "intraday", "ret": "next_overnight",
                                    "desc": "intraday[t] → next_overnight[t]: open→close predicts close→next open"},
        "next_overnight→intraday": {"signal": "next_overnight", "ret": "intraday",
                                    "desc": "next_overnight[t] → intraday[t+1]: close→next open predicts next open→close"},
    }

    all_results = {}
    for exp_name, exp in experiments.items():
        print(f"\n=== {exp_name}: {exp['desc']} ===")
        sig_col, ret_col = exp["signal"], exp["ret"]
        exp_res = {}
        for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
            r = {}
            r["quintile"] = quintile_spread(df, sig_col, ret_col, r_set)
            ic_recs = []
            for d in r_set:
                sub = df[(df["date"] == d) & df[sig_col].notna() & df[ret_col].notna()]
                if len(sub) < MIN_NAMES_PER_DATE:
                    continue
                rho = spearmanr(sub[sig_col].to_numpy(), sub[ret_col].to_numpy())
                if not np.isnan(rho.statistic):
                    ic_recs.append((d, float(rho.statistic)))
            r["ic"] = summarize_ic(ic_recs)
            exp_res[period_name] = r
            q = r["quintile"]
            ic = r["ic"]
            print(f"  {period_name}: Q5-Q1={q['pooledQ5minusQ1']}(nwt={q['monthlySpreadNWT']}), "
                  f"IC={ic['icMean']}(t={ic['icT']})")
        all_results[exp_name] = exp_res

    # --- Return decomposition ---
    print("\n=== Return decomposition (close-to-close = gap + intraday + cross-term) ===")
    decomp = {}
    for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
        sub = df[df["date"].isin(r_set)].dropna(subset=["gap", "intraday", "close_to_close"])
        decomp[period_name] = {
            "meanGap": round(float(sub["gap"].mean()), 5),
            "meanIntraday": round(float(sub["intraday"].mean()), 5),
            "meanCloseToClose": round(float(sub["close_to_close"].mean()), 5),
            "gapStd": round(float(sub["gap"].std()), 5),
            "intradayStd": round(float(sub["intraday"].std()), 5),
            "gapIntradayCorr": round(float(sub["gap"].corr(sub["intraday"])), 4),
        }
        d = decomp[period_name]
        print(f"  {period_name}: gap={d['meanGap']:.5f}, intraday={d['meanIntraday']:.5f}, "
              f"c2c={d['meanCloseToClose']:.5f}, corr(gap,id)={d['gapIntradayCorr']:.4f}")

    # --- Gap regime analysis ---
    print("\n=== Gap regime analysis ===")
    for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
        regimes = gap_regime_analysis(df, r_set)
        print(f"  {period_name}:")
        for name, v in regimes.items():
            print(f"    {name}: n={v['n']}, gap={v['meanGap']:.5f}, "
                  f"intraday={v['meanIntraday']:.5f}, c2c={v['meanCloseToClose']:.5f}")

    # --- Continuation vs Reversal ---
    print("\n=== Continuation vs Reversal ===")
    cont_results = {}
    for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
        cr = continuation_reversal(df, r_set)
        cont_results[period_name] = cr
        g = cr["gap_and_intraday_same_sign"]
        io = cr["intraday_and_next_overnight"]
        print(f"  {period_name}: gap↔intraday same_sign={g['share']:.1%} "
              f"(cont_mean={g['meanIntraday_when_cont']:.5f}, rev_mean={g['meanIntraday_when_rev']:.5f}), "
              f"intraday↔next_on same_sign={io['share_same']:.1%}")

    # --- Portfolio: gap signal long-only ---
    print("\n=== Portfolio: gap→intraday long-only (top Q1 quintile) ===")
    port_results = {}
    for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
        port = compute_long_only_portfolio(df, "gap", "intraday", r_set)
        port_results[period_name] = port
        if port:
            print(f"  {period_name}: CAGR={port['cagr']}, Sharpe={port['sharpe']}, MDD={port['mdd']}")

    # --- Direction check ---
    print("\n=== Direction: does gap predict intraday reversal? ===")
    for period_name, r_set in [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]:
        sub = df[df["date"].isin(r_set)].dropna(subset=["gap", "intraday"])
        gap_q1 = sub[sub["gap"] <= sub["gap"].quantile(0.2)]["intraday"].mean()
        gap_q5 = sub[sub["gap"] >= sub["gap"].quantile(0.8)]["intraday"].mean()
        print(f"  {period_name}: Q1 gap (most negative) → intraday={gap_q1:.5f}, "
              f"Q5 gap (most positive) → intraday={gap_q5:.5f}, diff={gap_q5-gap_q1:.5f}")

    # --- Save ---
    report = {
        "experiment": "10-KR-3: Gap / Overnight Effect",
        "featureDefinitions": {
            "gap": "open[t] / close[t-1] - 1 (전일 close → 당일 open)",
            "intraday": "close[t] / open[t] - 1 (당일 open → 당일 close)",
            "next_overnight": "open[t+1] / close[t] - 1 (당일 close → 다음 open)",
        },
        "pitPairs": {
            "gap→intraday": "gap[t] known at open[t], intraday[t] = return from open[t]",
            "intraday→next_overnight": "intraday[t] known at close[t], next_overnight[t] = return from close[t]",
            "next_overnight→intraday": "next_overnight[t] known at open[t+1], intraday[t+1] = return from open[t+1]",
        },
        "data": {
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "rebalMonths": len(rebal_list),
        },
        "costBpsPerSide": COST_BPS,
        "experiments": all_results,
        "returnDecomposition": decomp,
        "gapRegimeAnalysis": {p: gap_regime_analysis(df, r) for p, r in
                              [("TRAIN", train_r), ("VALID", valid_r), ("TEST", test_r)]},
        "continuationReversal": cont_results,
        "portfolio": port_results,
        "executionTime_s": round(time.time() - t0, 1),
    }
    out_path = os.path.join(OUT_DIR, "kr-gap-overnight-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
