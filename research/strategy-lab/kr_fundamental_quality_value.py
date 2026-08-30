#!/usr/bin/env python
"""10-KR-14: KR Fundamental Quality/Value factor 최소 검증 (factor discovery).

PIT-clean factor sources (모두 availableFrom <= asOf 규칙):
  - quality-panel.jsonl   (build-a5-quality-panel.js)   -> roe, debtRatio
  - valuation-panel.jsonl (build-a5-valuation-panel.js) -> pbr
  - raw A3 annual         revenue YoY (revenue_growth), PIT selectAsOf+selectFiscalYear
  - raw A3b annual        retention = 1 - dividendPerShare/eps (split-invariant ratio)

제외 (resolver.js 문서상 adjustment mismatch, 내부적으로 안정 불가):
  - per/epsGrowthRate: A2a 수정주가 vs DART 원문 EPS의 조정 기준 불일치

평가: monthly rebalance (A4 월초), TRAIN/VALID/TEST, 5D/20D/60D/120D forward close-to-close,
Spearman IC/t, Q5-Q1, long portfolio (방향은 결과로, 30bps round-trip), residual IC.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
QUALITY_PANEL = os.path.join(LAB, "reports", "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(LAB, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
OUT_DIR = os.path.join(LAB, "reports", "2026-08-28-kr-fundamental-quality-value")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_RT_BPS = 30.0
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


def quintile_spread(series):
    if series is None or len(series) < 5: return None
    q = pd.qcut(series["feat"].rank(method="first"), 5, labels=False)
    return float(series.loc[q == 4, "fwd"].mean() - series.loc[q == 0, "fwd"].mean())


def load_a3_annual(values_map):
    """return {ticker: [(availableFrom, fiscalYear, value)]} for mapped field."""
    out = {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                pe = str(r.get("periodEnd", ""))
                if not pe.endswith("12-31"): continue
                t = r.get("ticker"); v = values_map(r)
                if t is None or v is None or np.isnan(v): continue
                out.setdefault(t, []).append((str(r["availableFrom"]), int(r["fiscalYear"]), float(v)))
    return out


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def select_as_of(records, as_of, nvals=3):
    best = None
    for rec in records:
        af = normd(rec[0])
        if af > as_of: continue
        if best is None or rec[1] > best[1] or (rec[1] == best[1] and af > normd(best[0])):
            best = rec
    return best


def select_fiscal_year(records, fy, as_of, nvals=3):
    best = None
    for rec in records:
        if rec[1] != fy: continue
        af = normd(rec[0])
        if af > as_of: continue
        if best is None or af > normd(best[0]):
            best = rec
    return best


def build_fundamental_panel():
    """per (ticker, asOf) -> revenueGrowth, retention, using resolver PIT rules."""
    print("Loading A3/A3b raw (annual)...")
    a3_rev = load_a3_annual(lambda r: r.get("revenue"))
    a3b = {}
    for y in range(2016, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                t = r.get("ticker")
                if t is None: continue
                pe = normd(str(r.get("periodEnd", "")))
                if not pe.endswith("12-31"): continue
                eps = r.get("eps"); dps = r.get("dividendPerShare")
                a3b.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                              eps, dps))
    return a3_rev, a3b


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    # forward returns
    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0

    # monthly rebalance dates = A4 first session of month
    rebal = []
    seen = set()
    for d in sorted(df["date"].unique()):
        if d[:7] not in seen: seen.add(d[:7]); rebal.append(d)
    print(f"  {len(rebal)} rebalance months")

    # PIT factor panels -> (ticker, asOf) lookup
    print("Loading PIT factor panels...")
    qdf = pd.DataFrame([json.loads(l) for l in open(QUALITY_PANEL, encoding="utf-8")])
    qkey = qdf.set_index(["ticker", "asOf"])
    vdf = pd.DataFrame([json.loads(l) for l in open(VALUATION_PANEL, encoding="utf-8")])
    vkey = vdf.set_index(["ticker", "asOf"])
    a3_rev, a3b = build_fundamental_panel()

    # Build factor value per (ticker, rebal date)
    print("Resolving factors at rebalance dates (PIT)...")
    rows = []
    base = df[df["date"].isin(rebal)].copy()
    base_idx = base.set_index(["ticker", "date"])
    tickers = sorted(base_idx.index.get_level_values(0).unique())
    for (t, d), _ in base_idx.iterrows():
        row = {"ticker": t, "asOf": d}
        try:
            q = qkey.loc[(t, d)]
        except KeyError:
            q = None
        row["roe"] = q["roe"] if q is not None and pd.notna(q["roe"]) else np.nan
        row["debtRatio"] = q["debtRatio"] if q is not None and pd.notna(q["debtRatio"]) else np.nan
        try:
            v = vkey.loc[(t, d)]
        except KeyError:
            v = None
        row["pbr"] = v["pbr"] if v is not None and pd.notna(v["pbr"]) else np.nan
        # revenue growth
        recs = a3_rev.get(t, [])
        cur = select_as_of(recs, d)
        if cur is not None:
            prev = select_fiscal_year(recs, cur[1] - 1, d)
            if prev is not None and prev[2]:
                row["revenueGrowth"] = cur[2] / prev[2] - 1.0
            else:
                row["revenueGrowth"] = np.nan
        else:
            row["revenueGrowth"] = np.nan
        # retention = 1 - DPS/EPS
        b = a3b.get(t, [])
        curb = select_as_of(b, d)
        if curb is not None and curb[2] is not None and curb[2] > 0 and curb[3] is not None:
            row["retention"] = 1.0 - curb[3] / curb[2]
        else:
            row["retention"] = np.nan
        rows.append(row)
    panel = pd.DataFrame(rows)
    print(f"  panel rows {len(panel)}")

    pcols = {"roe", "debtRatio", "pbr", "revenueGrowth", "retention"}
    for f in pcols:
        print(f"  {f:14s} non-null {int(panel[f].notna().sum()):7d} ({100*panel[f].notna().mean():.1f}%)")

    m = pd.merge(base, panel, left_on=["ticker", "date"], right_on=["ticker", "asOf"], how="left")
    m = m.drop(columns=["asOf"])
    def per(d):
        return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")
    m["period"] = m["date"].map(per)

    result = {"experiment": "10-KR-14 KR Fundamental Quality/Value factor discovery",
              "excluded": {"per": "A2a adjusted price vs A3b raw EPS (split) mismatch",
                           "epsGrowthRate": "same mismatch (resolver.js)"},
              "costRtBps": COST_RT_BPS}
    factor_tables = {}

    fwd = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
    for fname in ["roe", "revenueGrowth", "debtRatio", "retention", "pbr"]:
        print(f"\n===== {fname} =====")
        factor_tables[fname] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            sub = m[m["period"] == p].dropna(subset=[fname])
            factor_tables[fname][p] = {}
            for hn, fc in fwd.items():
                s2 = sub[["date", fname, fc]].dropna()
                recs = []
                for d, gd in s2.groupby("date"):
                    if len(gd) < MIN_NAMES: continue
                    if gd[fname].nunique() <= 1: continue
                    r = spearmanr(gd[fname], gd[fc])
                    if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
                ic = summarize_ic(recs)
                # Q5-Q1 pooled
                qm = {"q1": None, "q5": None}
                if len(s2) >= 5:
                    gg = s2.copy()
                    gg["q"] = pd.qcut(gg[fname].rank(method="first"), 5, labels=False)
                    qm = {"q1": round(float(gg.loc[gg["q"] == 0, fc].mean()), 5),
                          "q5": round(float(gg.loc[gg["q"] == 4, fc].mean()), 5)}
                factor_tables[fname][p][hn] = {"ic": ic, "q": qm}
                print(f"  {p} {hn}: IC={ic['icMean']}(t={ic['icT']}) Q5-Q1={round(float(qm['q5'])-float(qm['q1']) if qm['q1'] is not None else 0,5)}")
        # portfolio: long Q5 and separately Q1 (monthly, 20D hold approx)
        factor_tables[fname]["portfolio"] = {}
        for qname, qp in [("topQ5", 4), ("bottomQ1", 0)]:
            factor_tables[fname]["portfolio"][qname] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                sub = m[m["period"] == p].dropna(subset=[fname])
                if len(sub) < MIN_NAMES:
                    factor_tables[fname]["portfolio"][qname][p] = None; continue
                monthly = []
                for d, gd in sub.groupby("date"):
                    if len(gd) < MIN_NAMES: continue
                    g2 = gd.copy()
                    g2["q"] = pd.qcut(g2[fname].rank(method="first"), 5, labels=False)
                    sel = g2[g2["q"] == qp]
                    fwd20 = sel["f20"].dropna()
                    if len(fwd20) < 5: continue
                    gr = float(fwd20.mean())
                    monthly.append(gr - COST_RT_BPS / 10000)
                if not monthly:
                    factor_tables[fname]["portfolio"][qname][p] = None; continue
                mr = np.array(monthly)
                eq = float(np.prod(1 + mr))
                n = len(mr); span = n / 12
                cagr = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else np.nan
                sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
                peak, mdd, cum = 1e8, 0.0, 1e8
                for rr in mr:
                    cum *= (1 + rr); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
                factor_tables[fname]["portfolio"][qname][p] = {"cagr": round(cagr, 4),
                                                                "sharpe": round(sh, 4) if sh is not None else None,
                                                                "mdd": round(mdd, 4), "n": int(n)}
                print(f"    port {qname} {p}: CAGR={factor_tables[fname]['portfolio'][qname][p]['cagr']} "
                      f"Sh={factor_tables[fname]['portfolio'][qname][p]['sharpe']}")
    result["factors"] = factor_tables

    # ---- residual IC: control mom60 and other fundamentals at 60D/120D ----
    print("\n===== residual IC (controls) =====")
    controls_now = ["mom60"]
    candidates = ["roe", "revenueGrowth", "debtRatio", "retention", "pbr"]
    res = {}
    for fname in candidates:
        res[fname] = {}
        for hn, fc in [("60D", "f60"), ("120D", "f120")]:
            res[fname][hn] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                sub = m[m["period"] == p]
                need = ["date"] + [fname] + controls_now + [fc] + [c for c in candidates if c != fname]
                s2 = sub[need].dropna()
                if len(s2) < MIN_NAMES:
                    res[fname][hn][p] = {"residIC": {"nDays": 0}}; continue
                recs = []
                for d, gd in s2.groupby("date"):
                    if len(gd) < MIN_NAMES: continue
                    controls = controls_now + [c for c in candidates if c != fname]
                    cols = [fname] + controls + [fc]
                    gg = gd[cols].dropna()
                    if len(gg) < MIN_NAMES: continue
                    if gg[fname].nunique() <= 1: continue
                    X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in controls])
                    y = gg[fname].rank(method="average").to_numpy(dtype=float)
                    try:
                        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                        resid = y - beta[0] - X @ beta[1:]
                    except np.linalg.LinAlgError:
                        continue
                    r = spearmanr(resid, gg[fc].to_numpy(dtype=float))
                    if not np.isnan(r.statistic): recs.append((d, float(r.statistic)))
                ric = summarize_ic(recs)
                res[fname][hn][p] = {"residIC": ric}
                print(f"  {fname:13s} {p} {hn} resid IC |mom60+fund: {ric['icMean']}(t={ric['icT']}) "
                      f"n={ric['nDays']}")
    result["residualIC"] = res

    result["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "kr-fundamental-quality-value-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()