#!/usr/bin/env python
"""10-KR-3 supplement: corrected portfolio using cached A2a parquet."""
import gzip, json, os, sys, time
import numpy as np, pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
CACHE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a_parquet")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0

def main():
    t0 = time.time()

    # Try loading from cached parquet first
    cache_files = sorted([f for f in os.listdir(CACHE_DIR) if f.endswith(".parquet")]) if os.path.exists(CACHE_DIR) else []
    if cache_files:
        print(f"Loading from {len(cache_files)} cached parquet files...")
        a2a = pd.concat([pd.read_parquet(os.path.join(CACHE_DIR, f)) for f in cache_files], ignore_index=True)
    else:
        print("Loading from jsonl.gz...")
        a4_all = pd.read_parquet(A4_PATH, columns=["ticker"])
        a4_tickers = set(a4_all["ticker"].unique())
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
    a2a = a2a[a2a["date"] >= "2014-06-01"]
    print(f"A2a: {len(a2a)} rows ({time.time()-t0:.0f}s)")

    # Build OHLCV panel
    df = a2a[["ticker", "date", "open", "close"]].copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    g = df.groupby("ticker", sort=False)
    df["prev_close"] = g["close"].shift(1)
    df["next_open"] = g["open"].shift(-1)
    df["gap"] = df["open"] / df["prev_close"] - 1.0
    df["intraday"] = df["close"] / df["open"] - 1.0
    df["next_overnight"] = df["next_open"] / df["close"] - 1.0

    # Monthly rebalance
    rebal_set = set()
    seen = set()
    for d in sorted(df["date"].unique()):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            rebal_set.add(d)
    rebal_list = sorted(rebal_set)
    print(f"Rebal: {len(rebal_list)} months ({time.time()-t0:.0f}s)")

    def get_rebal(rlist, period):
        if period == "TRAIN": return [d for d in rlist if d <= TRAIN_END]
        elif period == "VALID": return [d for d in rlist if TRAIN_END < d <= VALID_END]
        else: return [d for d in rlist if d > VALID_END]

    def run_portfolio(df, feat, ret, rebal_dates, go_long_low, cost_bps):
        dates_set = set(df["date"])
        rlist = [d for d in rebal_dates if d in dates_set]
        if len(rlist) < 2: return None

        ranked = df[["date", "ticker", feat]].dropna(subset=[feat]).copy()
        ranked["rank"] = ranked.groupby("date")[feat].rank(ascending=True, method="first")
        ranked["nNames"] = ranked.groupby("date")["rank"].transform("count")
        ranked = ranked[ranked["nNames"] >= MIN_NAMES]

        next_open = df[df["date"].isin(set(rlist))][["date", "ticker", "open"]].copy()
        next_open = next_open.rename(columns={"open": "next_open"})
        next_close = df[df["date"].isin(set(rlist))][["date", "ticker", "close"]].copy()
        next_close = next_close.rename(columns={"close": "next_close"})

        equity = 1e8
        monthly_rets = []
        for i in range(len(rlist) - 1):
            sig_date = rlist[i]
            day_ranks = ranked[ranked["date"] == sig_date].copy()
            n = len(day_ranks)
            if n < MIN_NAMES: continue
            top20pct = int(max(np.ceil(n * 0.2), 1))

            if go_long_low:
                long = day_ranks.nsmallest(top20pct, feat)
            else:
                long = day_ranks.nlargest(top20pct, feat)
            long_tickers = set(long["ticker"])

            # Entry: buy at open[sig_date] (= next_open of previous rebalance)
            # Exit: sell at close[sig_date]
            # This is same-day open→close return for each rebalance date
            entry = df[df["date"] == sig_date].set_index("ticker")["open"]
            exit_ = df[df["date"] == sig_date].set_index("ticker")["close"]

            rets = []
            for t in long_tickers:
                ep = entry.get(t)
                xp = exit_.get(t)
                if pd.notna(ep) and pd.notna(xp) and ep > 0:
                    rets.append(xp / ep - 1.0)

            if not rets: continue
            raw_ret = float(np.mean(rets))
            net_ret = raw_ret - 2 * cost_bps / 10000
            equity *= (1.0 + net_ret)
            monthly_rets.append(net_ret)

        if not monthly_rets: return None
        mr = np.array(monthly_rets)
        sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
        total_ret = equity / 1e8 - 1
        cagr = (1 + total_ret) ** (1 / max(len(monthly_rets)/12, 1/12)) - 1
        peak, mdd, cum = 1e8, 0.0, 1e8
        for r in monthly_rets:
            cum *= (1+r); peak = max(peak, cum); mdd = min(mdd, cum/peak-1)
        return {
            "cagr": round(cagr, 4), "sharpe": round(sharpe, 4) if sharpe else None,
            "mdd": round(mdd, 4), "totalReturn": round(total_ret, 4),
            "nMonths": len(monthly_rets),
            "meanMonthlyRet": round(float(mr.mean()), 5),
            "medianMonthlyRet": round(float(np.median(mr)), 5),
        }

    # --- Corrected portfolios ---
    print("\n=== Gap→Intraday Portfolio (reversal: long gap-down) ===")
    results = {}
    for period in ["TRAIN", "VALID", "TEST"]:
        rlist = get_rebal(rebal_list, period)
        # Long Q1 (lowest gap = gap-down) → reversal
        q1 = run_portfolio(df, "gap", "intraday", rlist, go_long_low=True, cost_bps=COST_BPS)
        # Long Q5 (highest gap = gap-up) → wrong direction
        q5 = run_portfolio(df, "gap", "intraday", rlist, go_long_low=False, cost_bps=COST_BPS)
        results[period] = {"long_gapdown_reversal": q1, "long_gapup": q5}
        print(f"  {period}:")
        if q1: print(f"    Long gap-down (reversal): CAGR={q1['cagr']}, Sharpe={q1['sharpe']}, MDD={q1['mdd']}, avg={q1['meanMonthlyRet']}")
        if q5: print(f"    Long gap-up:             CAGR={q5['cagr']}, Sharpe={q5['sharpe']}, MDD={q5['mdd']}, avg={q5['meanMonthlyRet']}")

    # --- EW benchmark (all stocks, monthly rebalance, open→close) ---
    print("\n=== EW Benchmark (all stocks, monthly open→close) ===")
    for period in ["TRAIN", "VALID", "TEST"]:
        rlist = get_rebal(rebal_list, period)
        dates_set = set(df["date"])
        rlist2 = [d for d in rlist if d in dates_set]
        equity = 1e8
        monthly_rets = []
        for sig_date in rlist2:
            day_data = df[df["date"] == sig_date].dropna(subset=["open", "close"])
            if len(day_data) < MIN_NAMES: continue
            rets = (day_data["close"] / day_data["open"] - 1.0).values
            raw_ret = float(np.mean(rets))
            net_ret = raw_ret - 2 * COST_BPS / 10000
            equity *= (1 + net_ret)
            monthly_rets.append(net_ret)
        if monthly_rets:
            mr = np.array(monthly_rets)
            sharpe = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
            total_ret = equity / 1e8 - 1
            cagr = (1 + total_ret) ** (1 / max(len(monthly_rets)/12, 1/12)) - 1
            print(f"  {period}: CAGR={round(cagr,4)}, Sharpe={round(sharpe,4) if sharpe else None}, n={len(monthly_rets)}, avg={round(float(mr.mean()),5)}")

    out_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-kr-gap-overnight", "kr-gap-portfolio-corrected.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
