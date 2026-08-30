#!/usr/bin/env python
"""10-KR-5: 거래대금 Shock 최소 검증.

Amount Shock feature:
  shock = total_amount[t] / rolling_median(total_amount, 20)[t-1]
  - rolling_median over t-20..t-1 (EXCLUDES today) -> PIT-safe
  - known at close[t]

Existing volume expansion features for comparison:
  amt_surge = log(total_amount[t] / mean(total_amount, 20)[t-1])
  liq_surge = volume5 / volume60 (includes today in baseline)

Compare:
  1. Amount Shock alone
  2. Existing volume expansion alone
  3. Incremental effect of Amount Shock beyond existing

OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~.
Cost: 15bps per side.

data/backfill 읽기 전용, production 무변경.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-amount-shock")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
HORIZONS = {"1D": 1, "5D": 5, "20D": 20}
COST_BPS = 15.0


def newey_west_t(x, lag):
    x = np.asarray(x, dtype=float); x = x[~np.isnan(x)]
    n = len(x)
    if n < 5: return None
    e = x - x.mean(); g0 = float(np.sum(e*e))/n; s = g0
    for l in range(1, min(lag, n-1)+1):
        w = 1.0 - l/(lag+1.0)
        s += 2.0*w*float(np.sum(e[l:]*e[:-l]))/n
    se = np.sqrt(max(s,0.0)/n)
    return round(float(x.mean()/se), 3) if se > 0 else None


def summarize_ic(recs):
    if not recs: return {"nDays": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean()/(sd/np.sqrt(len(vals)))) if sd > 0 else None
    by_year = {}
    for d, v in recs:
        by_year.setdefault(d[:4], []).append(v)
    yearly = {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())}
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd,5), "icT": round(t,3) if t is not None else None,
            "icPositiveShare": round(float((vals>0).mean()), 4), "yearlyICMean": yearly}


def quintile_spread(df, feat, h, rebal):
    sub = df[df["date"].isin(rebal)].dropna(subset=[feat, h]).copy()
    def _q(grp):
        if len(grp) < MIN_NAMES: grp["q"] = np.nan; return grp
        grp["q"] = pd.qcut(grp[feat].rank(method="first"), 5, labels=False) + 1
        return grp
    s = sub.groupby("date", group_keys=False).apply(_q).dropna(subset=["q"])
    s["q"] = s["q"].astype(int)
    pm = s.groupby("q")[h].mean()
    pairs = []
    for d, gd in s.groupby("date"):
        t5, t1 = gd[gd["q"]==5][h], gd[gd["q"]==1][h]
        if len(t5) and len(t1): pairs.append((d, float(t5.mean()-t1.mean())))
    sp = np.array([v for _, v in pairs], dtype=float) if pairs else np.array([])
    by_year = {}
    for d, v in pairs: by_year.setdefault(d[:4], []).append(v)
    return {
        "pooledQ5minusQ1": round(float(pm.get(5,np.nan)-pm.get(1,np.nan)), 5) if 5 in pm and 1 in pm else None,
        "quintileMeans": {int(i): round(float(pm.get(i,np.nan)),5) for i in range(1,6)},
        "monthlySpreadMean": round(float(np.nanmean(sp)),5) if len(sp) else None,
        "monthlySpreadNWT": newey_west_t(sp, 3) if len(sp) else None,
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)),5) for y,v in sorted(by_year.items())},
    }


def daily_ic(df, feat, h, rebal):
    recs = []
    for d in rebal:
        sub = df[(df["date"]==d)]
        sub = sub.dropna(subset=[feat, h])
        if len(sub) < MIN_NAMES: continue
        r = spearmanr(sub[feat].to_numpy(), sub[h].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("Loading A4 research dataset...")
    cols = ["ticker", "date", "close", "total_amount", "fwd_d20", "fwd_d60", "fwd_d120"]
    df = pd.read_parquet(A4_PATH, columns=cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = df.dropna(subset=["close", "total_amount"])
    df = df[(df["close"] > 0) & (df["total_amount"] > 0)]
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers, {df['date'].min()}~{df['date'].max()}")

    # --- Compute features ---
    print("Computing features...")
    g = df.groupby("ticker", sort=False)
    amt = g["total_amount"]
    # PIT-safe: baseline EXCLUDES today
    amt_med20_prior = amt.shift(1).transform(lambda s: s.rolling(20, min_periods=20).median())
    df["shock"] = df["total_amount"] / amt_med20_prior
    df["log_shock"] = np.log1p(df["shock"])
    # Existing: amt_surge (amount, shift-excluded) and liq_surge (volume-based). A4 has total_volume? not loaded.
    # amt_surge = log(total_amount / mean(amount,20)[t-1])
    amt_mean20_prior = amt.shift(1).transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["amt_surge"] = np.log(df["total_amount"] / amt_mean20_prior)
    # forward returns from A4 (already computed in parquet)
    # NOTE: A4 fwd_d20 = close[t+20]/close[t]-1. entry at close[t] => measures close-to-close continuation.

    # Sanity
    print(f"  shock: median={df['shock'].median():.3f}, p99={df['shock'].quantile(0.99):.3f}, "
          f"nonNaN={int(df['shock'].notna().sum())} ({100*df['shock'].notna().mean():.1f}%)")

    # Monthly rebalance
    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen: seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(df["date"])
    print(f"  {len(rebal)} rebalance months")

    def period_of(d):
        return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")
    periods = {"TRAIN": {d for d in rebal if period_of(d)=="TRAIN"},
               "VALID": {d for d in rebal if period_of(d)=="VALID"},
               "TEST": {d for d in rebal if period_of(d)=="TEST"}}

    # Horizon mapping: A4 fwd_d20/60/120 -> approximately 1M/3M/6M (not 1D/5D/20D).
    # For 1D/5D/20D we need to recompute close-shift forwards. A4 gives fwd_d20/60/120 (20/60/120 trading days).
    # Our HORIZONS {1D,5D,20D} -> recompute from close within panel (row-shift caveat for panel gaps).
    print("Recomputing 1D/5D/20D forward returns from close...")
    close_g = df.groupby("ticker", sort=False)["close"]
    for hname, h in {"1D":1, "5D":5, "20D":20}.items():
        df[f"ret_{hname}"] = close_g.shift(-h) / df["close"] - 1.0

    # 1D / 5D / 20D as the analysis horizons
    H = {"1D": "ret_1D", "5D": "ret_5D", "20D": "ret_20D"}

    # --- Experiment 1: Amount Shock alone ---
    print("\n=== Amount Shock alone ===")
    shock_alone = {}
    for period_name in ["TRAIN", "VALID", "TEST"]:
        r_set = periods[period_name]
        shock_alone[period_name] = {}
        for hname, hcol in H.items():
            sh = quintile_spread(df, "shock", hcol, r_set)
            ic = daily_ic(df, "shock", hcol, r_set)
            shock_alone[period_name][hname] = {"quintile": sh, "ic": ic}
            print(f"  {period_name} {hname}: Q5-Q1={sh['pooledQ5minusQ1']}, "
                  f"IC={ic['icMean']}(t={ic['icT']})")

    # --- Experiment 2: existing amt_surge ---
    print("\n=== Existing amt_surge alone ===")
    surge_alone = {}
    for period_name in ["TRAIN", "VALID", "TEST"]:
        r_set = periods[period_name]
        surge_alone[period_name] = {}
        for hname, hcol in H.items():
            sh = quintile_spread(df, "amt_surge", hcol, r_set)
            ic = daily_ic(df, "amt_surge", hcol, r_set)
            surge_alone[period_name][hname] = {"quintile": sh, "ic": ic}
            print(f"  {period_name} {hname}: Q5-Q1={sh['pooledQ5minusQ1']}, "
                  f"IC={ic['icMean']}(t={ic['icT']})")

    # --- Incremental test: shock orthogonalized to amt_surge ---
    print("\n=== Incremental: shock | amt_surge (rank-orthogonalized IC) ===")
    incr = {}
    for period_name in ["TRAIN", "VALID", "TEST"]:
        r_set = periods[period_name]
        incr[period_name] = {}
        sub = df[df["date"].isin(r_set)].dropna(subset=["shock", "amt_surge"])
        for hname, hcol in H.items():
            recs = []
            for d, gd in sub.groupby("date"):
                gg = gd[["shock", "amt_surge", hcol]].dropna()
                if len(gg) < 50: continue
                rs = gg["shock"].rank().to_numpy()
                ra = gg["amt_surge"].rank().to_numpy()
                vr = np.var(ra)
                if vr <= 0: continue
                beta = float(np.cov(ra, rs, bias=True)[0, 1] / vr)
                resid = rs - beta * ra
                r = spearmanr(resid, gg[hcol].to_numpy())
                if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
            incr[period_name][hname] = summarize_ic(recs)
            s = incr[period_name][hname]
            print(f"  {period_name} {hname}: orthIC={s['icMean']}(t={s['icT']})")

    # --- Shock x price direction decomposition ---
    print("\n=== Shock x price direction (5D) ===")
    # price direction: sign of close relative to prior session close (or prior day return)
    df["ret_1d_prev"] = df.groupby("ticker", sort=False)["close"].pct_change()
    shock_dir = {}
    for period_name in ["TRAIN", "VALID", "TEST"]:
        r_set = periods[period_name]
        sub = df[df["date"].isin(r_set)].dropna(subset=["shock", "ret_1D", "ret_1d_prev"])
        high_shock = sub[sub["shock"] >= sub["shock"].median()]
        low_shock = sub[sub["shock"] < sub["shock"].median()]
        cells = {
            "high_shock_up": sub[(sub["shock"]>=sub["shock"].median()) & (sub["ret_1d_prev"]>0)],
            "high_shock_down": sub[(sub["shock"]>=sub["shock"].median()) & (sub["ret_1d_prev"]<0)],
            "low_shock_up": sub[(sub["shock"]<sub["shock"].median()) & (sub["ret_1d_prev"]>0)],
            "low_shock_down": sub[(sub["shock"]<sub["shock"].median()) & (sub["ret_1d_prev"]<0)],
        }
        shock_dir[period_name] = {}
        for name, cell in cells.items():
            r5 = cell["ret_5D"].dropna()
            shock_dir[period_name][name] = {
                "n": int(len(r5)),
                "meanRet5D": round(float(r5.mean()), 5) if len(r5) else None,
                "winRate": round(float((r5>0).mean()), 4) if len(r5) else None,
            }
        hsu = shock_dir[period_name]["high_shock_up"]
        hsd = shock_dir[period_name]["high_shock_down"]
        print(f"  {period_name}: high_shock_up 5D={hsu['meanRet5D']} (n={hsu['n']}), "
              f"high_shock_down 5D={hsd['meanRet5D']} (n={hsd['n']})")

    # --- Portfolio (long top-Q5 shock, monthly, close-to-close entry) ---
    print("\n=== Portfolio: long top-Q5 shock (monthly, net 30bps) ===")
    portfolio = {}
    close_ser = df[["date", "ticker", "close"]].copy()
    close_ser["close_20"] = close_ser.groupby("ticker")["close"].shift(-20)
    df_by_date = {d: gd for d, gd in df.groupby("date")}
    for period_name in ["TRAIN", "VALID", "TEST"]:
        rlist = [d for d in rebal if period_of(d) == period_name]
        dates_set = set(df["date"])
        rlist = [d for d in rlist if d in dates_set]
        if len(rlist) < 2: portfolio[period_name] = None; continue
        equity = 1e8; monthly = []
        for sig_date in rlist:
            day = df_by_date.get(sig_date)
            if day is None: continue
            day = day.dropna(subset=["shock"])
            if len(day) < MIN_NAMES: continue
            top20 = int(max(np.ceil(len(day) * 0.2), 1))
            long = day.nlargest(top20, "shock")
            lt = set(long["ticker"])
            es = close_ser[close_ser["date"] == sig_date].set_index("ticker")
            rets = []
            for t in lt:
                ep = es.loc[t, "close"] if t in es.index else np.nan
                xp = es.loc[t, "close_20"] if t in es.index else np.nan
                if pd.notna(ep) and pd.notna(xp) and ep > 0:
                    rets.append(xp / ep - 1.0)
            if not rets: continue
            raw = float(np.mean(rets)); net = raw - 2 * COST_BPS / 10000
            equity *= (1 + net); monthly.append(net)
        # NOTE: 20-session hold, monthly rebalance (overlapping windows), reported as approximate net return
        if monthly:
            mr = np.array(monthly)
            sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
            total = equity / 1e8 - 1
            cagr = (1 + total) ** (1 / max(len(monthly) / 12, 1 / 12)) - 1
            peak, mdd, cum = 1e8, 0.0, 1e8
            for r in monthly:
                cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
            portfolio[period_name] = {"cagr": round(cagr, 4), "sharpe": round(sharpe, 4) if sharpe else None,
                                      "mdd": round(mdd, 4), "nMonths": len(monthly),
                                      "avgMonthlyNet": round(float(mr.mean()), 5)}
            p = portfolio[period_name]
            print(f"  {period_name}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyNet']}")
        else:
            portfolio[period_name] = None


    report = {
        "experiment": "10-KR-5: 거래대금 Shock",
        "featureDefinitions": {
            "shock": "total_amount[t] / rolling_median(total_amount,20)[t-1]",
            "amt_surge": "log(total_amount[t] / mean(total_amount,20)[t-1]) (existing)",
        },
        "horizons": H,
        "data": {"rows": len(df), "tickers": df["ticker"].nunique(),
                 "period": [df["date"].min(), df["date"].max()]},
        "shockAlone": shock_alone,
        "amtSurgeAlone": surge_alone,
        "incrementalOrthIC": incr,
        "shockPriceDirection": shock_dir,
        "portfolio": portfolio,
        "executionTime_s": round(time.time()-t0,1),
    }
    out_path = os.path.join(OUT_DIR, "kr-amount-shock-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
