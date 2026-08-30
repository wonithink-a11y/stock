#!/usr/bin/env python
"""10-KR-7: 외국인 수급 고도화 — 기존 foreign-flow factor 너머 추가 정보 검증.

Axes (A4 dataset; all PIT via backward rolling):
 1. magnitude     foreign_net / total_amount          (baseline existing factor)
 2. persistence   foreign_nb20_ratio                  (existing, already amount-normalized)
 3. acceleration  (foreign_net/total_amount) - foreign_nb20_ratio   (existing def)
 4. price response foreign_net/total_amount x prior price move (interaction bins)
 5. regime        foreign_net/total_amount split by market Risk-On/Neutral/Risk-Off

Incremental: orthogonalize each candidate against existing foreign_net/total_amount
(and + nb20_ratio) residual IC.

OOS: TRAIN 2016~2022-06, VALID 2022-07~2023-12, TEST 2024-01~.
forward: 5D / 20D. cost 15bps/side.
"""
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-foreign-flow-enhancement")

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
    by = {}
    for d, v in recs: by.setdefault(d[:4], []).append(v)
    yearly = {y: round(float(np.mean(v)), 5) for y, v in sorted(by.items())}
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd, 5), "icT": round(t, 3) if t is not None else None,
            "icPositiveShare": round(float((vals > 0).mean()), 4), "yearlyICMean": yearly}


def quintile_spread(by_date, feat, h, rebal, regmap=None):
    rows = []
    for d in sorted(rebal):
        s0 = by_date.get(d)
        if s0 is None: continue
        sub = s0.dropna(subset=[feat, h])
        if len(sub) < MIN_NAMES: continue
        if regmap is not None and regmap.get(d) not in regmap.values():
            pass
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
    by = {}
    for d, st, v in rows: by.setdefault(d[:4], []).append(v)
    return {
        "pooledQ5minusQ1": round(float(qmeans.get(5, np.nan) - qmeans.get(1, np.nan)), 5),
        "quintileMeans": qmeans,
        "monthlySpreadMean": round(float(np.mean(sp)), 5),
        "monthlySpreadNWT": newey_west_t(sp, OLS_LAG),
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by.items())},
    }


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
        ok = True
        for cf in ctl_feats:
            c = gd[cf].rank().to_numpy().astype(float)
            vr = np.var(c)
            if vr <= 0: ok = False; break
            beta = float(np.cov(c, X, bias=True)[0, 1] / vr)
            X = X - beta * c
        if not ok: continue
        r = spearmanr(X, gd[hcol].to_numpy())
        if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
    return summarize_ic(recs)


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    print("Loading A4...")
    cols = ["ticker", "date", "close", "total_amount", "foreign_net",
            "foreign_nb_5d", "foreign_nb_20d", "foreign_nb20_ratio",
            "inst_net", "indiv_net"]
    df = pd.read_parquet(A4_PATH, columns=cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    ta = df["total_amount"].replace(0, np.nan)
    df["foreign_flow_ratio"] = df["foreign_net"] / ta          # magnitude (baseline)
    df["acceleration"] = df["foreign_flow_ratio"] - df["foreign_nb20_ratio"]
    # liquidity-adjusted: foreign net flow relative to log-liquidity; nb20_ratio is native
    df["fgn_per_logamt"] = df["foreign_net"] / np.log1p(df["total_amount"].clip(lower=1))
    # price response: prior price move (5d momentum of close) cross feature
    g = df.groupby("ticker", sort=False)
    df["price_move_5d"] = g["close"].pct_change(5)
    df["fgn_x_price"] = df["foreign_flow_ratio"] * df["price_move_5d"]

    # forward returns: need 5D and 20D
    cg = g["close"]
    df["fwd5"] = cg.shift(-5) / df["close"] - 1.0
    df["fwd20"] = cg.shift(-20) / df["close"] - 1.0

    # Pend pct features on liquidity (drop zero-amount days)
    df = df.dropna(subset=["foreign_flow_ratio"])
    print(f"  after drop: {len(df)} rows")

    # regime LUT (PIT: usableFromDate == date)
    regime = None
    if os.path.exists(REGIME_PATH):
        rl = pd.read_parquet(REGIME_PATH)
        rl = rl.dropna(subset=["usableFromDate", "regime"])[["usableFromDate", "regime"]]
        rl["usableFromDate"] = rl["usableFromDate"].astype(str)
        rl = rl.drop_duplicates("usableFromDate").rename(columns={"usableFromDate": "date"})
        df = df.merge(rl, on="date", how="left")
        regime = True
        print(f"  regime merged")

    by_date = {d: gd for d, gd in df.groupby("date")}

    def month_starts(dates):
        out, seen = [], set()
        for d in sorted(dates.unique()):
            if d[:7] not in seen: seen.add(d[:7]); out.append(d)
        return out
    rebal = month_starts(df["date"])
    periods = {"TRAIN": {d for d in rebal if period_of(d)=="TRAIN"},
               "VALID": {d for d in rebal if period_of(d)=="VALID"},
               "TEST": {d for d in rebal if period_of(d)=="TEST"}}
    H = {"5D": "fwd5", "20D": "fwd20"}
    print(f"  {len(rebal)} rebalance months")

    result = {"experiment": "10-KR-7: 외국인 수급 고도화", "horizons": H,
              "baseline_factor": "foreign_flow_ratio = foreign_net/total_amount",
              "data": {"rows": len(df), "tickers": df["ticker"].nunique(),
                       "period": [df["date"].min(), df["date"].max()]}}

    # Axis standalone
    FEATS = {
        "magnitude": "foreign_flow_ratio",
        "persistence(nb20_ratio)": "foreign_nb20_ratio",
        "acceleration": "acceleration",
        "liquidity_adjusted(logamt)": "fgn_per_logamt",
        "price_response": "fgn_x_price",
    }
    result["standalone"] = {}
    for axis, feat in FEATS.items():
        print(f"\n=== {axis} ===")
        result["standalone"][axis] = {"feature": feat}
        for pname in ["TRAIN", "VALID", "TEST"]:
            rs = periods[pname]
            result["standalone"][axis][pname] = {}
            for hn, hc in H.items():
                sp = quintile_spread(by_date, feat, hc, rs)
                ic = daily_ic(by_date, feat, hc, rs)
                result["standalone"][axis][pname][hn] = {"quintile": sp, "ic": ic}
                print(f"  {pname} {hn}: Q5-Q1={sp['pooledQ5minusQ1']}, IC={ic['icMean']}(t={ic['icT']})")

    # Incremental: orthogonalize vs baseline (foreign_flow_ratio) [+ nb20_ratio]
    print("\n=== Incremental (orth | foreign_flow_ratio) ===")
    result["incremental_vs_baseline"] = {}
    for axis, feat in FEATS.items():
        if axis == "magnitude": continue  # baseline has trivial residual
        result["incremental_vs_baseline"][axis] = {"feature": feat}
        for pname in ["TRAIN", "VALID", "TEST"]:
            rs = periods[pname]
            result["incremental_vs_baseline"][axis][pname] = {}
            for hn, hc in H.items():
                s = orthogon_ic(by_date, feat, ["foreign_flow_ratio"], hc, rs)
                result["incremental_vs_baseline"][axis][pname][hn] = s
                print(f"  {axis} {pname} {hn}: orthIC={s['icMean']}(t={s['icT']})")

    # Incremental vs nb20_ratio (persistence)
    print("\n=== Incremental (orth | foreign_nb20_ratio) ===")
    result["incremental_vs_nb20"] = {}
    for axis, feat in FEATS.items():
        if axis == "persistence(nb20_ratio)": continue
        result["incremental_vs_nb20"][axis] = {"feature": feat}
        for pname in ["TRAIN", "VALID", "TEST"]:
            rs = periods[pname]
            result["incremental_vs_nb20"][axis][pname] = {}
            for hn, hc in H.items():
                s = orthogon_ic(by_date, feat, ["foreign_nb20_ratio"], hc, rs)
                result["incremental_vs_nb20"][axis][pname][hn] = s
                print(f"  {axis} {pname} {hn}: orthIC={s['icMean']}(t={s['icT']})")

    # Regime interaction: magnitude factor split by regime
    if regime is not None:
        print("\n=== Regime interaction (magnitude x regime) ===")
        result["regime"] = {}
        for reg in ["Risk-On", "Neutral", "Risk-Off"]:
            result["regime"][reg] = {}
            for pname in ["TRAIN", "VALID", "TEST"]:
                rs = [d for d in periods[pname] ]
                rrecs5, rrecs20 = [], []
                for d in rs:
                    sub = by_date.get(d)
                    if sub is None: continue
                    sreg = sub.dropna(subset=["foreign_flow_ratio", "regime", "fwd5", "fwd20"])
                    sreg = sreg[sreg["regime"] == reg]
                    if len(sreg) < MIN_NAMES: continue
                    r5 = spearmanr(sreg["foreign_flow_ratio"].to_numpy(), sreg["fwd5"].to_numpy())
                    r20 = spearmanr(sreg["foreign_flow_ratio"].to_numpy(), sreg["fwd20"].to_numpy())
                    if not np.isnan(r5.statistic): rrecs5.append((d, float(r5.statistic)))
                    if not np.isnan(r20.statistic): rrecs20.append((d, float(r20.statistic)))
                s5 = summarize_ic(rrecs5); s20 = summarize_ic(rrecs20)
                result["regime"][reg][pname] = {"IC5D": s5, "IC20D": s20}
                print(f"  {reg} {pname}: IC5={s5['icMean']}(t={s5['icT']}) IC20={s20['icMean']}(t={s20['icT']}) nalDays5={s5['nDays']}")

    # Portfolio: long top-Q5 magnitude (existing factor) and top-Q5 acceleration
    print("\n=== Portfolio (monthly, close-to-close, net 30bps) ===")
    portfolio = {}
    close_ser = df[["date", "ticker", "close"]].copy()
    close_ser["close_20"] = close_ser.groupby("ticker")["close"].shift(-20)
    for axis, feat in [("magnitude", "foreign_flow_ratio"), ("acceleration", "acceleration")]:
        portfolio[axis] = {}
        for pname in ["TRAIN", "VALID", "TEST"]:
            rlist = [d for d in rebal if period_of(d) == pname]
            rlist = [d for d in rlist if d in by_date]
            if len(rlist) < 2: portfolio[axis][pname] = None; continue
            equity = 1e8; monthly = []
            for sd in rlist:
                day = by_date.get(sd)
                if day is None: continue
                day = day.dropna(subset=[feat])
                if len(day) < MIN_NAMES: continue
                q = int(max(np.ceil(len(day) * 0.2), 1))
                long = day.nlargest(q, feat)
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
                portfolio[axis][pname] = {"cagr": round(cagr, 4), "sharpe": round(sh, 4) if sh else None,
                                          "mdd": round(mdd, 4), "nMonths": len(monthly),
                                          "avgMonthlyNet": round(float(mr.mean()), 5)}
                p = portfolio[axis][pname]
                print(f"  {axis} {pname}: CAGR={p['cagr']}, Sharpe={p['sharpe']}, MDD={p['mdd']}, avg={p['avgMonthlyNet']}")
            else:
                portfolio[axis][pname] = None

    result["portfolio"] = portfolio
    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-foreign-flow-enhancement-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
