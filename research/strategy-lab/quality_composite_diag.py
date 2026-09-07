#!/usr/bin/env python
"""QCOMP OOS — year-concentration & per-period diagnostics for the finding."""
import json
import math
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MIN_NAMES = 30
QCOMP_MEMBERS = [("roe", 1.0), ("op_margin", 1.0), ("net_margin", 1.0),
                 ("debt_ratio", -1.0), ("current_ratio", 1.0),
                 ("roe_consistency", 1.0), ("op_margin_trend", 1.0)]


def build_ranked(panel, members, period):
    sub = panel[panel["period"] == period].sort_values(["date", "ticker"]).copy()
    rows = []
    for _, g in sub.groupby("date"):
        sc = None
        for f, sign in members:
            r = g[f].rank(pct=True) * sign
            sc = r if sc is None else sc + r
        sc = sc / len(members)
        tmp = pd.DataFrame({"ticker": g["ticker"].to_numpy(), "date": g["date"].to_numpy(),
                            "fwd1m": g["fwd1m"].to_numpy(), "score": sc.to_numpy()})
        tmp = tmp.dropna(subset=["score", "fwd1m"])
        if len(tmp) >= MIN_NAMES:
            rows.append(tmp)
    return pd.concat(rows, ignore_index=True)


def yearly_excess(d, topq=0.90):
    """연도별 상위 decile EW / 적격 EW flat fwd 차 (비용 미반영)."""
    out = {}
    for date, g in d.groupby("date"):
        thr = g["score"].quantile(topq)
        sel = g[g["score"] >= thr]
        if len(sel) == 0:
            continue
        y = date[:4]
        out.setdefault(y, []).append(float(sel["fwd1m"].mean()) - float(g["fwd1m"].mean()))
    rows = {y: round(float(np.mean(v)) * 100, 3) for y, v in sorted(out.items())}
    return rows


def monthly_ic_by_year(d):
    out = {}
    for date, g in d.groupby("date"):
        if len(g) < MIN_NAMES:
            continue
        y = date[:4]
        out.setdefault(y, []).append(float(g["score"].corr(g["fwd1m"], method="spearman")))
    rows = {y: round(float(np.mean(v)), 4) for y, v in sorted(out.items())}
    return rows


def check_decile_spread_table(d):
    """decile별 평균 fwd1m 전체기간 — 단조성 확인."""
    acc = {}
    for _, g in d.groupby("date"):
        q = pd.qcut(g["score"].rank(method="first"), 10, labels=False)
        for dec in range(10):
            gm = g[q == dec]
            if len(gm) == 0:
                continue
            acc.setdefault(dec, []).append(gm["fwd1m"].mean())
    line = " | ".join(f"D{dec}:{np.mean(acc[dec])*100:+.3f}%" for dec in range(10))
    return line


panel = pd.read_parquet(PANEL_PATH)
panel = panel[panel["liquid"]].copy()

for period in ["TRAIN", "VALID", "TEST"]:
    d = build_ranked(panel, QCOMP_MEMBERS, period)
    print(f"\n=== QCOMP {period} ===")
    print("  연도별 월평균 초과(T10-EW):", json.dumps(yearly_excess(d), indent=4))
    print("  연도별 월평균 IC:", json.dumps(monthly_ic_by_year(d), indent=4))
    print("  decile:", check_decile_spread_table(d))