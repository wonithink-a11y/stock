#!/usr/bin/env python
"""10-KR-11: Reversal x Volatility / Shock 최소 검증.

Reuse verified features (no new lookback):
  rev5  = close[t]/close[t-5]-1
  rev20 = close[t]/close[t-20]-1
  rv20  = 20D realized vol (sigma of daily log-ret, PIT via shift)
  shock = total_amount[t] / rolling_median(total_amount,20)[t-1]  (PIT-safe, 10-KR-5)

Decompose reversal by Low/High Vol and Low/High Shock. Q1-Q5, Q5-Q1, IC, TRAIN/VALID/TEST.
Residual IC controlling mom60/foreign_ratio/inst_ratio within each regime.
cost 15bps/side.
"""
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-reversal-regime")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
OLS_LAG = 4


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
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icT": round(t, 3) if t is not None else None,
            "icPositiveShare": round(float((vals > 0).mean()), 4)}


def daily_ic(by_date, mask, feat, h, rebal):
    recs = []
    for d in sorted(rebal):
        sub = by_date.get(d)
        if sub is None: continue
        if mask is not None:
            sub = sub[mask(sub)]
        sub = sub.dropna(subset=[feat, h])
        if len(sub) < MIN_NAMES: continue
        if sub[feat].nunique() <= 1: continue
        r = spearmanr(sub[feat].to_numpy(), sub[h].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def quintile_spread(by_date, mask, feat, h, rebal):
    rows = []
    for d in sorted(rebal):
        sub = by_date.get(d)
        if sub is None: continue
        if mask is not None:
            sub = sub[mask(sub)]
        sub = sub.dropna(subset=[feat, h])
        if len(sub) < 5: continue
        sub = sub.copy()
        sub["q"] = pd.qcut(sub[feat].rank(method="first"), 5, labels=False) + 1
        q5, q1 = sub[sub["q"] == 5][h], sub[sub["q"] == 1][h]
        if not len(q5) or not len(q1): continue
        rows.append((d, sub, float(q5.mean() - q1.mean())))
    if not rows: return {"q1": None, "q5": None, "q5-q1": None, "n": 0}
    qm = {}
    for _, sub, _ in rows:
        for q in range(1, 6):
            vals = sub[sub["q"] == q][h]
            qm.setdefault(q, []).append(float(vals.mean()))
    qmeans = {int(q): round(float(np.mean(v)), 5) for q, v in qm.items()}
    sp = np.array([v for _, _, v in rows], dtype=float)
    return {"q1": qmeans.get(1), "q5": qmeans.get(5),
            "q5-q1": round(float(qmeans.get(5, np.nan) - qmeans.get(1, np.nan)), 5),
            "spreadNWT": newey_west_t(sp, OLS_LAG), "n": int(len(sp))}


def orthogon_ic(by_date, mask, xfeat, ctl_feats, hcol, rebal):
    recs = []
    for d in sorted(rebal):
        gd = by_date.get(d)
        if gd is None: continue
        if mask is not None:
            gd = gd[mask(gd)]
        gd = gd.dropna(subset=[xfeat] + ctl_feats + [hcol])
        if len(gd) < 50: continue
        X = gd[xfeat].rank().to_numpy().astype(float)
        ok = True
        for cf in ctl_feats:
            c = gd[cf].rank().to_numpy().astype(float)
            vr = np.var(c)
            if vr <= 0: ok = False; break
            beta = float(np.cov(c, X, bias=True)[0, 1] / vr)
            X = X - beta * c
        if not ok: continue
        if len(np.unique(X)) <= 1: continue
        r = spearmanr(X, gd[hcol].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


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
    df["mom60"] = g.pct_change(60)
    # rv20 PIT: use lag-1 daily log-return up to t-1
    df["logret"] = np.log(df["close"]).groupby(df["ticker"], sort=False).diff()
    df["rv20"] = df.groupby("ticker", sort=False)["logret"].shift(1).transform(
        lambda s: s.rolling(20, min_periods=20).std()) * 100
    # shock PIT-safe (10-KR-5)
    amt = df["total_amount"]
    amt_med20_prior = amt.shift(1).transform(lambda s: s.rolling(20, min_periods=20).median())
    df["shock"] = df["total_amount"] / amt_med20_prior
    ta = df["total_amount"].replace(0, np.nan)
    df["foreign_ratio"] = df["foreign_net"] / ta
    df["inst_ratio"] = df["inst_net"] / ta

    df["fwd5"] = g.shift(-5) / df["close"] - 1.0
    df["fwd20"] = g.shift(-20) / df["close"] - 1.0

    df = df.dropna(subset=["rev5", "rev20", "rv20", "shock"])
    by_date = {d: gd for d, gd in df.groupby("date")}

    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen: seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(df["date"])
    periods = {p: {d for d in rebal if period_of(d) == p} for p in ["TRAIN", "VALID", "TEST"]}
    H = {"5D": "fwd5", "20D": "fwd20"}
    print(f"  {len(rebal)} rebalance months | panel {len(df)} rows")

    # regime masks evaluated per-date sub-frame (median within that date's cross-section)
    def low_rv(sub): return (sub["rv20"] <= sub["rv20"].median()).to_numpy()
    def high_rv(sub): return (sub["rv20"] > sub["rv20"].median()).to_numpy()
    def low_sh(sub): return (sub["shock"] <= sub["shock"].median()).to_numpy()
    def high_sh(sub): return (sub["shock"] > sub["shock"].median()).to_numpy()
    REGIMES = {
        "LowVol": low_rv, "HighVol": high_rv,
        "LowShock": low_sh, "HighShock": high_sh,
    }

    result = {"experiment": "10-KR-11: Reversal x Volatility/Shock", "horizons": H,
              "data": {"rows": len(df), "tickers": df["ticker"].nunique()}}

    print("\n=== Reversal x Regime (Q5-Q1 & IC; negative = mean-reversion) ===")
    result["by_regime"] = {}
    for rname, mask in REGIMES.items():
        result["by_regime"][rname] = {}
        print(f"--- {rname} ---")
        for feat in ["rev5", "rev20"]:
            result["by_regime"][rname][feat] = {}
            for pname in ["TRAIN", "VALID", "TEST"]:
                rs = periods[pname]
                result["by_regime"][rname][feat][pname] = {}
                for hn, hc in H.items():
                    sp = quintile_spread(by_date, mask, feat, hc, rs)
                    ic = daily_ic(by_date, mask, feat, hc, rs)
                    result["by_regime"][rname][feat][pname][hn] = {
                        "quintile": {"q1": sp["q1"], "q5": sp["q5"], "q5-q1": sp["q5-q1"],
                                     "spreadNWT": sp["spreadNWT"]}, "ic": {"icMean": ic["icMean"],
                                     "icT": ic["icT"], "nDays": ic["nDays"]}}
                    print(f"  {feat} {pname} {hn}: Q5-Q1={sp['q5-q1']}(nw t={sp['spreadNWT']}), IC={ic['icMean']}(t={ic['icT']})")

    # Residual: rev5 within HighVol/HighShock vs mom60+foreign+inst
    print("\n=== Residual IC (within regime) | mom60+foreign+inst ===")
    ctl = ["mom60", "foreign_ratio", "inst_ratio"]
    result["resid_by_regime"] = {}
    for rname in ["LowVol", "HighVol", "LowShock", "HighShock"]:
        mask = REGIMES[rname]
        result["resid_by_regime"][rname] = {}
        for feat in ["rev5", "rev20"]:
            result["resid_by_regime"][rname][feat] = {}
            for pname in ["TRAIN", "VALID", "TEST"]:
                rs = periods[pname]
                result["resid_by_regime"][rname][feat][pname] = {}
                for hn, hc in H.items():
                    s = orthogon_ic(by_date, mask, feat, ctl, hc, rs)
                    result["resid_by_regime"][rname][feat][pname][hn] = s
                    print(f"  {rname} {feat} {pname} {hn}: residIC={s['icMean']}(t={s['icT']})")

    # Portfolio: conditional reversal long (Q1 losers) in HighVol / HighShock regimes
    print("\n=== Portfolio (monthly, close-to-close, net 30bps) ===")
    portfolio = {}
    close_ser = df[["date", "ticker", "close"]].copy()
    close_ser["close_20"] = close_ser.groupby("ticker")["close"].shift(-20)
    for rname in ["HighVol", "HighShock"]:
        mask = REGIMES[rname]
        for feat in ["rev5", "rev20"]:
            key = f"{rname}_{feat}_Q1"
            portfolio[key] = {}
            for pname in ["TRAIN", "VALID", "TEST"]:
                rlist = [d for d in rebal if period_of(d) == pname and d in by_date]
                if len(rlist) < 2: portfolio[key][pname] = None; continue
                equity = 1e8; monthly = []
                for sd in rlist:
                    day = by_date.get(sd)
                    if day is None: continue
                    day = day[mask(day)].dropna(subset=[feat])
                    if len(day) < MIN_NAMES: continue
                    long = day.nsmallest(max(int(np.ceil(len(day) * 0.2)), 1), feat)
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
                    portfolio[key][pname] = {"cagr": round(cagr, 4), "sharpe": round(sh, 4) if sh else None,
                                             "mdd": round(mdd, 4), "nMonths": len(monthly),
                                             "avgMonthlyNet": round(float(mr.mean()), 5)}
                    p = portfolio[key][pname]
                    print(f"  {key} {pname}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyNet']}")
                else:
                    portfolio[key][pname] = None
    result["portfolio"] = portfolio

    result["regimeMedianCols"] = {"rv20_med": "per-date x-sec median", "shock_med": "per-date x-sec median"}
    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-reversal-regime-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
