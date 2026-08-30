#!/usr/bin/env python
"""10-KR-12: HighShock Reversal 수익화 검증.

고정 신호(10-KR-11): HighShock 조건부 단기 반전.
   core = rev5 (primary), rev20 (reference)
   regime = HighShock (shock > per-date xsec median)
   bucket = Q1 (recent losers), and Q1~Q2 (reference)

구현 비교 (각각 Q1-long, 등가중, PIT-safe):
   1. Monthly rebalance  (enter close[rebal], hold to next monthly rebal)
   2. Weekly rebalance   (enter close[rebal], hold to next weekly rebal)
   3. Next-trading-day entry (signal@t -> enter close[t+1], hold to next rebal)

평가: TRAIN/VALID/TEST 각각 CAGR, Sharpe, MDD, turnover, 거래수, 평균 보유기간, 비용 전/후.
비용 15bps/side. threshold 최적화 없음, lookback 신규 없음, TEST 보고 규칙 변경 없음.
"""
import json
import os
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-highshock-reversal-monetization")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen: seen.add(d[:7]); out.append(d)
    return out


def weekly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        kw = pd.Timestamp(d).isocalendar()[:2]
        if kw not in seen: seen.add(kw); out.append(d)
    return out


def run_portfolio(by_date, close_all, rebal, feat, bucket, next_day, n_per_year, cost_roundtrip_bps):
    equity = 1e8
    equity_gross = 1e8
    monthly = []
    monthly_gross = []
    trades = 0
    rebal_info = []
    close_by_date = {d: g.set_index("ticker") for d, g in close_all.groupby("date")}
    all_sorted_dates = sorted(close_by_date.keys())

    for idx, sd in enumerate(rebal):
        day = by_date.get(sd)
        if day is None: continue
        day = day[day["shock"] > day["shock"].median()].dropna(subset=[feat])
        if len(day) < MIN_NAMES: continue
        ranked = day.sort_values(feat)
        q = max(int(np.ceil(len(ranked) * 0.2)), 1)
        q2 = 2 * q
        sig_ticks = set(ranked.iloc[:q]["ticker"]) if bucket == "Q1" else set(ranked.iloc[:q2]["ticker"])

        if next_day:
            later = [dd for dd in all_sorted_dates if dd > sd]
            if not later: continue
            entry_date = later[0]
        else:
            entry_date = sd
        exit_date = None
        for nd in rebal[idx + 1:]:
            if nd > entry_date:
                exit_date = nd; break
        if exit_date is None:
            if next_day:
                nxt = [dd for dd in all_sorted_dates if dd > entry_date]
                if not nxt: continue
                exit_date = nxt[0]
            else:
                continue

        ent = close_by_date[entry_date]
        ext = close_by_date[exit_date]
        common = [t for t in sig_ticks if t in ent.index and t in ext.index]
        rets = []
        for t in common:
            if ent.loc[t, "close"] > 0:
                rets.append(ext.loc[t, "close"] / ent.loc[t, "close"] - 1.0)
        n = len(rets)
        if n == 0: continue
        gross = float(np.mean(rets))
        net = gross - cost_roundtrip_bps / 10000
        equity *= (1 + net)
        equity_gross *= (1 + gross)
        monthly.append(net)
        monthly_gross.append(gross)
        trades += len(common)
        rebal_info.append((sd, n, gross, net, entry_date, exit_date))

    stats = {}
    if not monthly:
        return stats
    mr = np.array(monthly)
    mg = np.array(monthly_gross)
    total = equity / 1e8 - 1
    total_gross = equity_gross / 1e8 - 1
    nperiods = len(mr)
    span_years = nperiods / n_per_year
    cagr_net = (1 + total) ** (1 / max(span_years, 1e-9)) - 1
    cagr_gross = (1 + total_gross) ** (1 / max(span_years, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(n_per_year)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in monthly:
        cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
    avg_n = float(np.mean([x[1] for x in rebal_info]))
    holds = np.array([(pd.Timestamp(x[5]) - pd.Timestamp(x[4])).days for x in rebal_info])
    stats = {
        "nRebalance": len(monthly),
        "cagrNet": round(cagr_net, 4),
        "sharpe": round(sh, 4) if sh is not None else None,
        "mdd": round(mdd, 4),
        "cagrGross": round(cagr_gross, 4),
        "avgTurnoverPerRebal": round(float(trades / len(monthly) / avg_n), 3) if avg_n > 0 else None,
        "totalTradeSides": int(trades),
        "avgNames": round(avg_n, 2),
        "avgHoldDays": round(float(holds.mean()), 1) if len(holds) else None,
    }
    return stats


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    cols = ["ticker", "date", "close", "total_amount", "foreign_net", "inst_net"]
    df = pd.read_parquet(A4_PATH, columns=cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["rev5"] = g.pct_change(5)
    df["rev20"] = g.pct_change(20)
    amt = df["total_amount"]
    amt_med20_prior = amt.shift(1).transform(lambda s: s.rolling(20, min_periods=20).median())
    df["shock"] = df["total_amount"] / amt_med20_prior
    df = df.dropna(subset=["rev5", "rev20", "shock"])
    by_date = {d: gd for d, gd in df.groupby("date")}
    close_all = df[["date", "ticker", "close"]]
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    weeks = weekly_reb(all_dates)

    periods = {p: [d for d in months if period_of(d) == p] for p in ["TRAIN", "VALID", "TEST"]}
    period_weeks = {p: [d for d in weeks if period_of(d) == p] for p in ["TRAIN", "VALID", "TEST"]}

    result = {"experiment": "10-KR-12: HighShock Reversal 수익화", "costBps": COST_BPS,
              "signal": {"regime": "HighShock", "features": ["rev5", "rev20"]}}

    RT = 2 * COST_BPS
    print("\n=== Monthly rebalance, rev5 Q1_long ===")
    result["monthly_rev5_Q1"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        s = run_portfolio(by_date, close_all, periods[p], "rev5", "Q1", False, 12, RT)
        result["monthly_rev5_Q1"][p] = s
        print(f"  {p}: {s}")

    print("\n=== Weekly rebalance, rev5 Q1_long ===")
    result["weekly_rev5_Q1"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        s = run_portfolio(by_date, close_all, period_weeks[p], "rev5", "Q1", False, 52, RT)
        result["weekly_rev5_Q1"][p] = s
        print(f"  {p}: {s}")

    print("\n=== Weekly rebalance, rev20 Q1_long ===")
    result["weekly_rev20_Q1"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        s = run_portfolio(by_date, close_all, period_weeks[p], "rev20", "Q1", False, 52, RT)
        result["weekly_rev20_Q1"][p] = s
        print(f"  {p}: {s}")

    print("\n=== Next-day entry (signal t -> enter t+1), weekly, rev5 Q1 ===")
    result["nextday_weekly_rev5_Q1"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        s = run_portfolio(by_date, close_all, period_weeks[p], "rev5", "Q1", True, 52, RT)
        result["nextday_weekly_rev5_Q1"][p] = s
        print(f"  {p}: {s}")

    print("\n=== Bucket: Q1-Q2 long, weekly, rev5 (vs Q1) ===")
    result["weekly_rev5_Q1Q2"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        s = run_portfolio(by_date, close_all, period_weeks[p], "rev5", "Q1-Q2", False, 52, RT)
        result["weekly_rev5_Q1Q2"][p] = s
        print(f"  {p}: {s}")

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-highshock-reversal-monetization-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
