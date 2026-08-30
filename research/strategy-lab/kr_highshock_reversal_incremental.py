#!/usr/bin/env python
"""10-KR-13: HighShock Reversal Incremental Alpha (on top of existing KR strategy).

baseline       = LOWMOM60 (lowest 60D momentum top-30, liquid, monthly, equal-weight)
overlay        = HighShock + rev5 Q1 (recent losers among shock names), monthly, equal-weight
combined       = 50/50 two-sleeve: 0.5*baseline + 0.5*overlay  (baseline selection unchanged)

Compare TRAIN/VALID/TEST: CAGR, Sharpe, MDD, turnover, trade count, gross/net, incremental.
cost 15bps/side. Monthly rebalance only. Fixed signal (no re-search).
"""
import json
import os
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-highshock-reversal-incremental")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
TOP_N = 30
MIN_TURNOVER = 100_000_000.0
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen: seen.add(d[:7]); out.append(d)
    return out


def profile(monthly, n_per_year):
    if not monthly:
        return {}
    mr = np.array([x["ret"] for x in monthly])
    mg = np.array([x["gross"] for x in monthly])
    n = len(mr)
    eq = float(np.prod(1 + mr))
    eqg = float(np.prod(1 + mg))
    span = n / n_per_year
    cagr_net = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    cagr_gross = eqg ** (1 / max(span, 1e-9)) - 1 if eqg > 0 else (1 + np.sum(mg)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(n_per_year)) if mr.std(ddof=1) > 0 else None
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
    df["rev5"] = g.pct_change(5)
    ta = df["total_amount"]
    amt_med20_prior = ta.shift(1).transform(lambda s: s.rolling(20, min_periods=20).median())
    df["shock"] = ta / amt_med20_prior
    # turnover20 liquidity proxy = mean daily amount over trailing 20 sessions (ends today)
    df["turnover20"] = ta.groupby(df["ticker"]).transform(lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["mom60", "rev5", "shock", "turnover20"])

    close_all = df[["date", "ticker", "close", "total_amount", "mom60", "rev5", "shock", "turnover20"]]
    close_by_date = {d: dd.set_index("ticker") for d, dd in close_all.groupby("date")}
    by_date = close_by_date
    all_dates = sorted(close_all["date"].unique())
    months = monthly_reb(all_dates)
    months_by_period = {p: [d for d in months if period_of(d) == p] for p in ["TRAIN", "VALID", "TEST"]}

    baseline_months = {}
    overlay_months = {}
    for p, dates in months_by_period.items():
        b = []
        for k, sd in enumerate(dates):
            if k + 1 >= len(dates): break
            nd = dates[k + 1]
            db = by_date[sd]
            liq = db[db["turnover20"] >= MIN_TURNOVER].dropna(subset=["mom60"])
            if len(liq) < TOP_N: continue
            base = liq.sort_values("mom60", ascending=True).head(TOP_N)
            bt = set(base.index)
            ent = by_date[sd]; ext = by_date[nd]
            rets = []
            for t in bt:
                if t in ent.index and t in ext.index and ent.loc[t, "close"] > 0:
                    rets.append(ext.loc[t, "close"] / ent.loc[t, "close"] - 1.0)
            if not rets: continue
            gr = float(np.mean(rets))
            b.append({"sd": sd, "ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr,
                      "trades": len(rets), "names": len(rets)})
        baseline_months[p] = b

        o = []
        for k, sd in enumerate(dates):
            if k + 1 >= len(dates): break
            nd = dates[k + 1]
            do = by_date[sd]
            high = do[do["shock"] > do["shock"].median()].dropna(subset=["rev5"])
            if len(high) < MIN_NAMES: continue
            q = max(int(np.ceil(len(high) * 0.2)), 1)
            ov = high.sort_values("rev5").iloc[:q]
            ot = set(ov.index)
            ent = by_date[sd]; ext = by_date[nd]
            rets = []
            for t in ot:
                if t in ent.index and t in ext.index and ent.loc[t, "close"] > 0:
                    rets.append(ext.loc[t, "close"] / ent.loc[t, "close"] - 1.0)
            if not rets: continue
            gr = float(np.mean(rets))
            o.append({"sd": sd, "ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr,
                      "trades": len(rets), "names": len(rets)})
        overlay_months[p] = o

    combined_months = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        cm = []
        b, o = baseline_months[p], overlay_months[p]
        bs = {x["sd"]: x for x in b}; osd = {x["sd"]: x for x in o}
        for sd in sorted(set(bs) & set(osd)):
            br, orr = bs[sd], osd[sd]
            gr = 0.5 * br["gross"] + 0.5 * orr["gross"]
            r = 0.5 * br["ret"] + 0.5 * orr["ret"]
            cm.append({"sd": sd, "ret": r, "gross": gr,
                       "trades": br["trades"] + orr["trades"], "names": br["names"] + orr["names"]})
        combined_months[p] = cm

    result = {"experiment": "10-KR-13: HighShock Reversal Incremental Alpha",
              "baseline": "LOWMOM60 top-30 liquid monthly", "overlay": "HighShock rev5 Q1",
              "combine": "50/50 two-sleeve", "costBps": COST_BPS}

    print("\n=== Baseline: LOWMOM60 top-30 ===")
    result["baseline"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        pr = profile(baseline_months[p], 12)
        trades = sum(x["trades"] for x in baseline_months[p])
        result["baseline"][p] = {**pr, "totalTrades": trades}
        print(f"  {p}: {pr} trades={trades}")

    print("\n=== Reversal only: HighShock rev5 Q1 ===")
    result["reversal_only"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        pr = profile(overlay_months[p], 12)
        trades = sum(x["trades"] for x in overlay_months[p])
        result["reversal_only"][p] = {**pr, "totalTrades": trades}
        print(f"  {p}: {pr} trades={trades}")

    print("\n=== Combined: baseline + overlay (50/50) ===")
    result["combined"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        pr = profile(combined_months[p], 12)
        trades = sum(x["trades"] for x in combined_months[p])
        result["combined"][p] = {**pr, "totalTrades": trades}
        print(f"  {p}: {pr} trades={trades}")

    # Incremental = combined - baseline (net and gross)
    print("\n=== Incremental (combined - baseline) ===")
    result["incremental"] = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        cb = result["combined"][p]; bs = result["baseline"][p]
        inc = {"cagrNetDiff": round(cb["cagrNet"] - bs["cagrNet"], 4) if "cagrNet" in cb and "cagrNet" in bs else None,
               "cagrGrossDiff": round(cb["cagrGross"] - bs["cagrGross"], 4) if "cagrGross" in cb and "cagrGross" in bs else None,
               "sharpeDiff": round(cb["sharpe"] - bs["sharpe"], 4) if cb.get("sharpe") is not None and bs.get("sharpe") is not None else None,
               "mddDiff": round(cb["mdd"] - bs["mdd"], 4) if "mdd" in cb and "mdd" in bs else None}
        result["incremental"][p] = inc
        print(f"  {p}: {inc}")

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-highshock-reversal-incremental-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
