#!/usr/bin/env python
"""QCOMP OOS — independence vs ROE: is the composite more than ROE in disguise?
Question 1 (composite adds info vs ROE alone) answered three ways:
  A) composite-minus-ROE (6 others) as its own factor -> IC + backtest
  B) ROE-conditional IC of QCOMP: residual of QCOMP rank on ROE rank, corr fwd
  C) QCOMP vs ROE top-decile excess difference (paired, same months)
"""
import math
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MIN_NAMES = 30

ALL_MEMBERS = [("roe", 1.0), ("op_margin", 1.0), ("net_margin", 1.0),
               ("debt_ratio", -1.0), ("current_ratio", 1.0),
               ("roe_consistency", 1.0), ("op_margin_trend", 1.0)]
NON_ROE = [m for m in ALL_MEMBERS if m[0] != "roe"]


def ranks_by_month(g, members):
    sc = None
    for f, sign in members:
        r = g[f].rank(pct=True) * sign
        sc = r if sc is None else sc + r
    return sc / len(members)


def monthly_excess(d):
    gross, bench, months = [], [], []
    for date, g in d.groupby("date"):
        thr = g["score"].quantile(0.90)
        sel = g[g["score"] >= thr]
        if len(sel) == 0:
            continue
        gross.append(float(sel["fwd1m"].mean()))
        bench.append(float(g["fwd1m"].mean()))
        months.append(date)
    return np.array(gross), np.array(bench), months


def tt(arr):
    if len(arr) < 2 or float(arr.std(ddof=1)) == 0:
        return 0.0
    return float(arr.mean() / (arr.std(ddof=1) / math.sqrt(len(arr))))


def residual_ic(sub):
    """월별로 QCOMP rank를 ROE rank에 회귀한 잔차의 fwd 상관."""
    rows = []
    for _, g in sub.groupby("date"):
        g2 = g.dropna(subset=["roe"])
        if len(g2) < MIN_NAMES:
            continue
        q = g2["score"].to_numpy()
        r = g2["roe"].rank(pct=True).to_numpy()
        b = np.polyfit(r, q, 1)
        res = q - (b[0] * r + b[1])
        rows.append(float(np.corrcoef(res, g2["fwd1m"].to_numpy())[0, 1]))
    rows = np.array(rows)
    rows = rows[np.isfinite(rows)]
    return {"meanResidIC": round(float(rows.mean()), 4),
            "t": round(tt(rows), 3), "n": len(rows)}


panel = pd.read_parquet(PANEL_PATH)
panel = panel[panel["liquid"]].copy()

# A) composite-minus-ROE (6 factors only)
print("=== A) QCOMP minus ROE (6 others) top-decile, 월평균 초과 ===")
for period in ["TRAIN", "VALID", "TEST"]:
    d = panel[panel["period"] == period]
    rows = []
    for _, g in d.groupby("date"):
        sc = ranks_by_month(g, NON_ROE)
        t = pd.DataFrame({"score": sc.to_numpy(), "fwd1m": g["fwd1m"].to_numpy(),
                          "date": g["date"].to_numpy()})
        t = t.dropna()
        if len(t) >= MIN_NAMES:
            rows.append(t)
    dd = pd.concat(rows)
    g, b, m = monthly_excess(dd)
    print(f"  {period:>5} 초과 {float(g.mean() - b.mean())*100:+.3f}%/월 t {tt(g - b):+.2f}  "
          f"(n={len(g)})")

# B) ROE-conditional residual IC of QCOMP
print("\n=== B) QCOMP - 보유 ROE 정보 제거 후 잔차 IC (ROE 조건부) ===")
for period in ["TRAIN", "VALID", "TEST"]:
    d = panel[panel["period"] == period]
    rows = []
    for _, g in d.groupby("date"):
        sc = ranks_by_month(g, ALL_MEMBERS)
        t = pd.DataFrame({"score": sc.to_numpy(), "fwd1m": g["fwd1m"].to_numpy(),
                          "roe": g["roe"].to_numpy(), "date": g["date"].to_numpy()})
        t = t.dropna()
        if len(t) >= MIN_NAMES:
            rows.append(t)
    dd = pd.concat(rows)
    r = residual_ic(dd)
    print(f"  {period:>5} 잔차IC {r['meanResidIC']:+.4f} (t {r['t']:+.2f}, n={r['n']})")

# C) paired top-decile excess difference QCOMP vs ROE, 같은 월
print("\n=== C) QCOMP vs ROE 상위 decile 초과 차이 (같은 월 페어 비교) ===")
for period in ["TRAIN", "VALID", "TEST"]:
    d = panel[panel["period"] == period]
    cmp_rows = []
    for date, g in d.groupby("date"):
        scq = ranks_by_month(g, ALL_MEMBERS)
        scr = ranks_by_month(g, [("roe", 1.0)])
        t = pd.DataFrame({"q": scq.to_numpy(), "r": scr.to_numpy(),
                          "fwd1m": g["fwd1m"].to_numpy()})
        t = t.dropna()
        if len(t) < MIN_NAMES:
            continue
        tq = t[t["q"] >= t["q"].quantile(0.90)]
        tr = t[t["r"] >= t["r"].quantile(0.90)]
        if len(tq) == 0 or len(tr) == 0:
            continue
        eq = tq["fwd1m"].mean() - t["fwd1m"].mean()
        er = tr["fwd1m"].mean() - t["fwd1m"].mean()
        cmp_rows.append((date, eq, er, eq - er))
    cm = pd.DataFrame(cmp_rows, columns=["date", "q", "r", "diff"])
    nm = len(cm)
    print(f"  {period:>5} QCOMP 초과 {cm['q'].mean()*100:+.3f}%  ROE 초과 {cm['r'].mean()*100:+.3f}%  "
          f"차 {cm['diff'].mean()*100:+.4f}%/월 (t {tt(cm['diff'].to_numpy()):+.2f}, n={nm})")