#!/usr/bin/env python
"""10-KR-6: Volatility / ATR 최소 검증.

Features (from A2a OHLC, A4 universe):
  rv20 = std(log(close).diff(), 20)              # 20D realized volatility (pct)
  atr20pct = mean(TR, 20) / close * 100          # ATR-based vol (simple 20D mean)

PIT: features use up to t-1 (shift), known at close[t-1]. Entry at close[t].
   rv20 uses log-return std over t-19..t (includes t's return) -> shift(1)
   atr20 mean over TR at t-19..t => to be strict, compute with .shift(1)

Compare:
  1. rv20 alone
  2. atr20pct alone
  3. Incremental: orthogonalized vol | mom60, amt_surge

OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~.
Cost: 15bps per side.
"""
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-volatility-atr")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
HORIZONS = {"1D": 1, "5D": 5, "20D": 20}
COST_BPS = 15.0
OLS_LAG = 3


def newey_west_t(x, lag):
    x = np.asarray(x, dtype=float); x = x[~np.isnan(x)]
    n = len(x)
    if n < 5: return None
    e = x - x.mean(); g0 = float(np.sum(e * e)) / n; s = g0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        s += 2.0 * w * float(np.sum(e[l:] * e[:-l])) / n
    se = np.sqrt(max(s, 0.0) / n)
    return round(float(x.mean() / se), 3) if se > 0 else None


def summarize_ic(recs):
    if not recs: return {"nDays": 0}
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


def quintile_spread(by_date, feat, h, rebal):
    rows = []
    for d in sorted(rebal):
        s0 = by_date.get(d)
        if s0 is None: continue
        sub = s0.dropna(subset=[feat, h])
        if len(sub) < MIN_NAMES: continue
        sub = sub.copy()
        sub["q"] = pd.qcut(sub[feat].rank(method="first"), 5, labels=False) + 1
        q5, q1 = sub[sub["q"] == 5][h], sub[sub["q"] == 1][h]
        if not len(q5) or not len(q1): continue
        rows.append((d, sub, float(q5.mean() - q1.mean())))
    if not rows:
        return {"pooledQ5minusQ1": None, "quintileMeans": {}, "monthlySpreadMean": None,
                "monthlySpreadNWT": None, "nMonths": 0, "yearlySpreadMean": {}}
    qm = {}
    for _, sub, _ in rows:
        for q in range(1, 6):
            vals = sub[sub["q"] == q][h]
            qm.setdefault(q, []).append(float(vals.mean()))
    qmeans = {int(q): round(float(np.mean(v)), 5) for q, v in qm.items()}
    sp = np.array([v for _, _, v in rows], dtype=float)
    pairs = [(d, v) for d, _, v in rows]
    return {
        "pooledQ5minusQ1": round(float(qmeans.get(5, np.nan) - qmeans.get(1, np.nan)), 5),
        "quintileMeans": qmeans,
        "monthlySpreadMean": round(float(np.mean(sp)), 5),
        "monthlySpreadNWT": newey_west_t(sp, OLS_LAG),
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year(pairs).items())},
    }


def by_year(sp):
    by = {}
    for d, v in sp: by.setdefault(d[:4], []).append(v)
    return by


def daily_ic(by_date, feat, h, rebal):
    recs = []
    for d in sorted(rebal):
        sub = by_date.get(d)
        if sub is None: continue
        sub = sub.dropna(subset=[feat, h])
        if len(sub) < MIN_NAMES: continue
        r = spearmanr(sub[feat].to_numpy(), sub[h].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def orthogon_ic(by_date, xfeat, ctl_feats, hcol, rebal):
    recs = []
    for d in sorted(rebal):
        gd = by_date.get(d)
        if gd is None: continue
        gd = gd.dropna(subset=[xfeat] + ctl_feats + [hcol])
        if len(gd) < 50: continue
        X = gd[xfeat].rank().to_numpy().astype(float)
        for cf in ctl_feats:
            c = gd[cf].rank().to_numpy().astype(float)
            vr = np.var(c)
            if vr <= 0: break
            beta = float(np.cov(c, X, bias=True)[0, 1] / vr)
            X = X - beta * c
        r = spearmanr(X, gd[hcol].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("Loading A4 universe...")
    a4 = pd.read_parquet(A4_PATH, columns=["ticker"])
    a4_tickers = set(a4["ticker"].unique()); del a4
    print(f"  {len(a4_tickers)} tickers")

    # A4 close + amount for forward returns & control features
    a4d = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    a4d = a4d.drop_duplicates(subset=["ticker", "date"], keep="last")
    a4d = a4d[(a4d["close"] > 0) & (a4d["total_amount"] > 0)]
    a4d["date"] = a4d["date"].astype(str)
    a4d = a4d.sort_values(["ticker", "date"]).reset_index(drop=True)

    # control: mom60 (60d momentum) and amt_surge (amount surge)
    g = a4d.groupby("ticker", sort=False)
    a4d["mom60"] = g["close"].pct_change(60)
    amt_mean20 = g["total_amount"].shift(1).transform(lambda s: s.rolling(20, min_periods=15).mean())
    a4d["amt_surge"] = np.log(a4d["total_amount"] / amt_mean20)

    print("Loading A2a OHLCV (for vol features)...")
    import gzip, json
    recs = []
    for year in range(2016, 2027):
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path): continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["ticker"] in a4_tickers:
                    recs.append(r)
    ohlc = pd.DataFrame(recs)
    ohlc = ohlc[(ohlc["high"] > 0) & (ohlc["low"] > 0)].copy()
    ohlc["date"] = pd.to_datetime(ohlc["date"])
    ohlc = ohlc.sort_values(["ticker", "date"]).reset_index(drop=True)
    og = ohlc.groupby("ticker", sort=False)
     # realized vol: std of log-returns over 20D window ending at t
    ohlc["ret"] = np.log(ohlc["close"]).groupby(ohlc["ticker"], sort=False).diff()
    ohlc["rv20"] = og["ret"].transform(lambda s: s.rolling(20, min_periods=20).std())
    # True Range (PIT: uses prev_close at t-1)
    prev_close = ohlc.groupby("ticker", sort=False)["close"].shift(1)
    tr = pd.concat([(ohlc["high"] - ohlc["low"]),
                    (ohlc["high"] - prev_close).abs(),
                    (ohlc["low"] - prev_close).abs()], axis=1).max(axis=1)
    ohlc["tr"] = tr
    ohlc["atr20"] = og["tr"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    ohlc["date_s"] = ohlc["date"].dt.strftime("%Y-%m-%d")
    # PIT: shift vol so value known at close[t-1], usable at t (before t+1 move)
    ohlc[["rv20", "atr20"]] = og[["rv20", "atr20"]].shift(1)
    vol = ohlc[["ticker", "date_s", "rv20", "atr20", "close"]].dropna(subset=["rv20", "atr20"])
    vol["rv20_pct"] = vol["rv20"] * 100.0
    vol["atr20_pct"] = vol["atr20"] / vol["close"] * 100.0
    vol = vol[["ticker", "date_s", "rv20_pct", "atr20_pct"]]
    del ohlc
    print(f"  vol rows: {len(vol)}")

    # merge vol onto a4d (vol at t-1 -> aligns with a4d date t using date_s)
    a4d = a4d.merge(vol, left_on=["ticker", "date"], right_on=["ticker", "date_s"], how="left")

    # forward returns
    cg = a4d.groupby("ticker", sort=False)["close"]
    for hn, h in HORIZONS.items():
        a4d[f"ret_{hn}"] = cg.shift(-h) / a4d["close"] - 1.0

    a4d = a4d.dropna(subset=["rv20_pct", "atr20_pct", "close"])
    print(f"  panel: {len(a4d)} rows, {a4d['ticker'].nunique()} tickers, {a4d['date'].min()}~{a4d['date'].max()}")

    by_date = {d: gd for d, gd in a4d.groupby("date")}

    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen: seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(a4d["date"])
    periods = {"TRAIN": {d for d in rebal if period_of(d)=="TRAIN"},
               "VALID": {d for d in rebal if period_of(d)=="VALID"},
               "TEST": {d for d in rebal if period_of(d)=="TEST"}}
    H = {k: f"ret_{k}" for k in HORIZONS}
    print(f"  {len(rebal)} rebalance months")

    result = {"experiment": "10-KR-6: Volatility / ATR", "horizons": H,
              "data": {"rows": len(a4d), "tickers": a4d["ticker"].nunique(),
                       "period": [a4d["date"].min(), a4d["date"].max()]}}

    for feat in ["rv20_pct", "atr20_pct"]:
        print(f"\n=== {feat} alone ===")
        result[feat] = {}
        for pname in ["TRAIN", "VALID", "TEST"]:
            rs = periods[pname]
            result[feat][pname] = {}
            for hn, hc in H.items():
                sp = quintile_spread(by_date, feat, hc, rs)
                ic = daily_ic(by_date, feat, hc, rs)
                result[feat][pname][hn] = {"quintile": sp, "ic": ic}
                print(f"  {pname} {hn}: Q5-Q1={sp['pooledQ5minusQ1']}, IC={ic['icMean']}(t={ic['icT']})")

        # independence: orthogonalized vs mom60, amt_surge
        print(f"  -- orthogonalized | mom60+amt_surge --")
        result[feat + "_orth_incremental"] = {}
        ctl = ["mom60", "amt_surge"]
        for pname in ["TRAIN", "VALID", "TEST"]:
            rs = periods[pname]
            result[feat + "_orth_incremental"][pname] = {}
            for hn, hc in H.items():
                s = orthogon_ic(by_date, feat, ctl, hc, rs)
                result[feat + "_orth_incremental"][pname][hn] = s
                print(f"  {pname} {hn}: orthIC={s['icMean']}(t={s['icT']})")

    # Portfolio: long LOW-vol Q1 (if low-vol premium) vs long HIGH-vol Q5
    print("\n=== Portfolio (monthly, close-to-close, net 30bps) ===")
    portfolio = {}
    close_ser = a4d[["date", "ticker", "close"]].copy()
    close_ser["close_20"] = close_ser.groupby("ticker")["close"].shift(-20)
    df_by_date = {d: gd for d, gd in a4d.groupby("date")}
    for feat in ["rv20_pct", "atr20_pct"]:
        portfolio[feat] = {}
        for side in ["lowQ1", "highQ5"]:
            for pname in ["TRAIN", "VALID", "TEST"]:
                rlist = [d for d in rebal if period_of(d) == pname]
                rlist = [d for d in rlist if d in df_by_date]
                if len(rlist) < 2: portfolio[feat][f"{side}_{pname}"] = None; continue
                equity = 1e8; monthly = []
                for sd in rlist:
                    day = df_by_date.get(sd)
                    if day is None: continue
                    day = day.dropna(subset=[feat])
                    if len(day) < MIN_NAMES: continue
                    q = int(max(np.ceil(len(day) * 0.2), 1))
                    long = day.nsmallest(q, feat) if side == "lowQ1" else day.nlargest(q, feat)
                    lt = set(long["ticker"])
                    es = close_ser[close_ser["date"] == sd].set_index("ticker")
                    rets = []
                    for t in lt:
                        ep = es.loc[t, "close"] if t in es.index else np.nan
                        xp = es.loc[t, "close_20"] if t in es.index else np.nan
                        if pd.notna(ep) and pd.notna(xp) and ep > 0:
                            rets.append(xp / ep - 1.0)
                    if not rets: continue
                    raw = float(np.mean(rets)); net = raw - 2 * COST_BPS / 10000
                    equity *= (1 + net); monthly.append(net)
                if monthly:
                    mr = np.array(monthly)
                    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
                    total = equity / 1e8 - 1
                    cagr = (1 + total) ** (1 / max(len(monthly) / 12, 1 / 12)) - 1
                    peak, mdd, cum = 1e8, 0.0, 1e8
                    for r in monthly:
                        cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
                    portfolio[feat][f"{side}_{pname}"] = {"cagr": round(cagr, 4),
                                                          "sharpe": round(sh, 4) if sh else None,
                                                          "mdd": round(mdd, 4), "nMonths": len(monthly),
                                                          "avgMonthlyNet": round(float(mr.mean()), 5)}
                    p = portfolio[feat][f"{side}_{pname}"]
                    print(f"  {feat} {side} {pname}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyNet']}")
                else:
                    portfolio[feat][f"{side}_{pname}"] = None

    result["portfolio"] = portfolio
    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-volatility-atr-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
