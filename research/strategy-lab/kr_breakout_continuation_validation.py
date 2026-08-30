#!/usr/bin/env python
"""10-KR-4: 신고가 이후 지속성 (Breakout continuation) - optimized streaming."""
import gzip, json, os, sys, time
import numpy as np, pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-breakout-continuation")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
LOOKBACKS = [20, 60, 252]
HORIZONS = {"1D": 1, "5D": 5, "15D": 15}


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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("Loading A4 ticker set...")
    a4 = pd.read_parquet(A4_PATH, columns=["ticker"])
    a4_tickers = set(a4["ticker"].unique())
    del a4
    print(f"  {len(a4_tickers)} tickers")

    print("Loading A2a OHLCV...")
    records = []
    for year in range(2014, 2027):
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path): continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row["ticker"] in a4_tickers:
                    records.append(row)
    a2a = pd.DataFrame(records)
    a2a["date"] = pd.to_datetime(a2a["date"])
    a2a = a2a[(a2a["date"] >= "2014-06-01")]
    a2a = a2a.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(a2a)} rows, {a2a['ticker'].nunique()} tickers ({time.time()-t0:.0f}s)")

    df = a2a[["ticker", "date", "open", "high", "close"]].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    del a2a

    # Efficient feature computation: group on ticker, sorted by date already
    print("Computing features...")
    g = df.groupby("ticker", sort=False)
    high = g["high"]
    close = g["close"]
    for n in LOOKBACKS:
        # prior_high[t] = max(high[t-n .. t-1])
        prior_high = high.shift(1).transform(lambda s: s.rolling(n, min_periods=n).max())
        sig = (df["close"] > prior_high).astype(float)
        sig[pd.isna(prior_high)] = np.nan
        df[f"bo_{n}"] = sig
    for hname, h in HORIZONS.items():
        df[f"fwd_{hname}"] = close.transform(lambda s: s.shift(-h)) / df["close"] - 1.0
    df["period"] = df["date"].apply(lambda d: "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST"))
    print(f"  features done ({time.time()-t0:.0f}s)")

    # Event counts per lookback
    print("\n=== Event counts ===")
    for n in LOOKBACKS:
        col = f"bo_{n}"
        valid = df[col].notna()
        print(f"  bo_{n}: n={int(df[col].notna().sum())}, pos_rate={float(df.loc[df[col].notna(), col].mean()):.4f}")

    # --- Event study + IC per lookback x horizon x period ---
    print("\n=== Event study & IC ===")
    event_study = {}
    ic_block = {}
    for n in LOOKBACKS:
        sig_col = f"bo_{n}"
        event_study[n] = {}
        ic_block[n] = {}
        for hname in HORIZONS:
            fwd_col = f"fwd_{hname}"
            ic_block[n][hname] = {}
        for period in ["TRAIN", "VALID", "TEST"]:
            sub = df[df["period"] == period]
            sub = sub.dropna(subset=[sig_col, "fwd_1D"])
            # non-breakout baseline
            non = sub[sub[sig_col] == 0]
            event_study[n][period] = {}
            for hname in HORIZONS:
                fwd_col = f"fwd_{hname}"
                ev = sub.loc[sub[sig_col] == 1, fwd_col].dropna()
                nb = non[fwd_col].dropna()
                event_study[n][period][hname] = {
                    "nBreakout": int(len(ev)),
                    "breakoutMean": round(float(ev.mean()), 5) if len(ev) else None,
                    "breakoutMedian": round(float(ev.median()), 5) if len(ev) else None,
                    "nonBreakoutMean": round(float(nb.mean()), 5) if len(nb) else None,
                    "excess": round(float(ev.mean() - nb.mean()), 5) if len(ev) and len(nb) else None,
                    "winRate": round(float((ev > 0).mean()), 4) if len(ev) else None,
                }
            # IC
            for hname in HORIZONS:
                fwd_col = f"fwd_{hname}"
                recs = []
                for d, gd in sub.groupby("date"):
                    if len(gd) < MIN_NAMES: continue
                    gg = gd[[sig_col, fwd_col]].dropna()
                    if len(gg) < MIN_NAMES: continue
                    r = spearmanr(gg[sig_col].to_numpy(), gg[fwd_col].to_numpy())
                    if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
                ic_block[n][hname][period] = summarize(recs)
                s = ic_block[n][hname][period]
                e = event_study[n][period][hname]
                print(f"  bo_{n} {period} {hname}: n={e['nBreakout']} mean={e['breakoutMean']} "
                      f"excess={e['excess']} win={e['winRate']} | IC={s['icMean']}(t={s['icT']})")

    # --- Persistence table ---
    print("\n=== Persistence (breakout event mean forward returns) ===")
    persist = {}
    for n in LOOKBACKS:
        sig_col = f"bo_{n}"
        persist[n] = {}
        for period in ["TRAIN", "VALID", "TEST"]:
            ev = df[(df[sig_col] == 1) & (df["period"] == period)]
            row = {}
            for hname in HORIZONS:
                ret = ev[f"fwd_{hname}"].dropna()
                row[hname] = round(float(ret.mean()), 5) if len(ret) else None
            persist[n][period] = row
            print(f"  bo_{n} {period}: " + ", ".join(f"{k}={v}" for k, v in row.items()))

    # --- Portfolio (long breakout, close-to-close, monthly) ---
    print("\n=== Portfolio (long breakout, monthly, net 30bps) ===")
    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen:
                seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(df["date"])
    portfolio = {}
    for n in LOOKBACKS:
        sig_col = f"bo_{n}"
        portfolio[n] = {}
        for period in ["TRAIN", "VALID", "TEST"]:
            if period == "TRAIN": rlist = [d for d in rebal if d <= TRAIN_END]
            elif period == "VALID": rlist = [d for d in rebal if TRAIN_END < d <= VALID_END]
            else: rlist = [d for d in rebal if d > VALID_END]
            dates_set = set(df["date"])
            rlist = [d for d in rlist if d in dates_set]
            if len(rlist) < 2: portfolio[n][period] = None; continue
            equity = 1e8; monthly = []
            df_by_date = {d: gd for d, gd in df.groupby("date")}
            for i in range(len(rlist) - 1):
                sig_date = rlist[i]
                day = df_by_date.get(sig_date)
                if day is None: continue
                day = day.dropna(subset=[sig_col])
                if len(day) < MIN_NAMES: continue
                long = day[day[sig_col] == 1]
                if len(long) == 0: continue
                lt = long["ticker"]
                ep = day.set_index("ticker")["open"]
                xp = day.set_index("ticker")["close"]
                rets = []
                for t in lt:
                    e0, x0 = ep.get(t), xp.get(t)
                    if pd.notna(e0) and pd.notna(x0) and e0 > 0:
                        rets.append(x0/e0 - 1.0)
                if not rets: continue
                raw = float(np.mean(rets)); net = raw - 30/10000
                equity *= (1+net); monthly.append(net)
            if not monthly: portfolio[n][period] = None; continue
            mr = np.array(monthly)
            sharpe = float(mr.mean()/mr.std(ddof=1)*np.sqrt(12)) if mr.std(ddof=1) > 0 else None
            total = equity/1e8 - 1
            cagr = (1+total)**(1/max(len(monthly)/12,1/12)) - 1
            peak, mdd, cum = 1e8, 0.0, 1e8
            for r in monthly:
                cum *= (1+r); peak = max(peak, cum); mdd = min(mdd, cum/peak-1)
            portfolio[n][period] = {"cagr": round(cagr,4), "sharpe": round(sharpe,4) if sharpe else None,
                                    "mdd": round(mdd,4), "nMonths": len(monthly),
                                    "avgMonthlyRet": round(float(mr.mean()),5)}
            p = portfolio[n][period]
            print(f"  bo_{n} {period}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyRet']}")

    report = {
        "experiment": "10-KR-4: 신고가 이후 지속성 (Breakout continuation)",
        "breakoutDefinitions": {str(n): f"close[t] > rolling_max(high, {n})[t-1]" for n in LOOKBACKS},
        "horizons": HORIZONS,
        "data": {"rows": len(df), "tickers": df["ticker"].nunique(),
                 "period": [df["date"].min(), df["date"].max()]},
        "eventStudy": {str(k): v for k, v in event_study.items()},
        "dailyIC": {str(k): v for k, v in ic_block.items()},
        "persistence": {str(k): v for k, v in persist.items()},
        "portfolio": {str(k): v for k, v in portfolio.items()},
        "executionTime_s": round(time.time()-t0, 1),
    }
    out_path = os.path.join(OUT_DIR, "kr-breakout-continuation-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


def summarize(recs):
    if not recs: return {"nDays": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean()/(sd/np.sqrt(len(vals)))) if sd > 0 else None
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd,5), "icT": round(t,3) if t is not None else None,
            "icPositiveShare": round(float((vals>0).mean()), 4)}


if __name__ == "__main__":
    main()
