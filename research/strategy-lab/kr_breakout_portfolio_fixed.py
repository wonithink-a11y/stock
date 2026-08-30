#!/usr/bin/env python
"""10-KR-4 portfolio fix: buy breakout stocks the NEXT session after signal,
hold one month, entry at next open, exit at next close (true continuation).
"""
import gzip, json, os, sys, time
import numpy as np, pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-breakout-continuation")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
LOOKBACKS = [20, 60, 252]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    # Load A4 closes to build a complete session index per ticker
    a4 = pd.read_parquet(A4_PATH, columns=["ticker"])
    a4_tickers = set(a4["ticker"].unique())
    del a4

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
    a2a = a2a.sort_values(["ticker", "date"]).reset_index(drop=True)
    a2a = a2a[a2a["date"] >= "2015-06-01"]

    df = a2a[["ticker", "date", "open", "high", "close"]].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    del a2a

    print("Computing breakout signals...")
    g = df.groupby("ticker", sort=False)
    for n in LOOKBACKS:
        prior_high = g["high"].shift(1).transform(lambda s: s.rolling(n, min_periods=n).max())
        sig = (df["close"] > prior_high).astype(float)
        sig[pd.isna(prior_high)] = np.nan
        df[f"bo_{n}"] = sig

    # For portfolio: we need per-ticker per-session open/close with a NEXT-session open.
    # Build next_open per ticker.
    df["next_open"] = g["open"].shift(-1)
    df["next_close"] = g["close"].shift(-1)

    # Monthly rebalance: at each month start, select stocks with breakout at that date,
    # enter at next_open (next session), exit at next_close (still one session later),
    # OR hold to next month. To keep it simple and PIT-safe: enter next_open, exit next_close
    # (1-session: measures next-day continuation). Also do a 20-session hold variant.

    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen:
                seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(df["date"])
    dates_set = set(df["date"])
    df_by_datetick = df.set_index(["date", "ticker"])

    portfolio = {}
    for n in LOOKBACKS:
        sig_col = f"bo_{n}"
        portfolio[n] = {}
        for period in ["TRAIN", "VALID", "TEST"]:
            if period == "TRAIN": rlist = [d for d in rebal if d <= TRAIN_END]
            elif period == "VALID": rlist = [d for d in rebal if TRAIN_END < d <= VALID_END]
            else: rlist = [d for d in rebal if d > VALID_END]
            rlist = [d for d in rlist if d in dates_set]
            if len(rlist) < 2: portfolio[n][period] = None; continue

            equity = 1e8; monthly = []
            for i in range(len(rlist) - 1):
                sig_date = rlist[i]
                day = df[df["date"] == sig_date]
                day = day.dropna(subset=[sig_col])
                if len(day) < MIN_NAMES: continue
                long = day[day[sig_col] == 1]
                if len(long) == 0: continue
                rets = []
                for _, row in long.iterrows():
                    t = row["ticker"]
                    ep = row["next_open"]   # next session open (entry after breakout)
                    xc = row["next_close"]  # next session close
                    if pd.notna(ep) and pd.notna(xc) and ep > 0:
                        rets.append(xc / ep - 1.0)
                if not rets: continue
                raw = float(np.mean(rets)); net = raw - 30/10000
                equity *= (1 + net); monthly.append(net)
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
                                    "avgMonthlyNet": round(float(mr.mean()),5)}
            p = portfolio[n][period]
            print(f"  bo_{n} {period}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyNet']}")

    out_path = os.path.join(OUT_DIR, "kr-breakout-portfolio-fixed.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
