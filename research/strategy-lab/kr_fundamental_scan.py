#!/usr/bin/env python
"""10-KR-18: Fundamental/Value factor 탐색 (A3/A3b에서 아직 미검증 후보).

Given validated: PBR, ROE, revenueGrowth, retention, debtRatio (10-KR-14).
New PIT-safe candidates from raw A3 (all absolute KRW / ratios -> split-invariant):
  netMargin, opMargin, netIncomeGrowth, opProfitGrowth, equityGrowth, currentRatio

Per factor standalone: 5/20/60/120D IC, Q5-Q1, long portfolio CAGR/Sharpe/MDD,
residual IC | (mom60 + 기존 주요 factor roe/pbr/revenueGrowth/retention/debtRatio).
TRAIN/VALID/TEST, 30bps/side, next-day entry.
No threshold/lookback optimization. No TEST-driven selection.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
QUALITY_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                             "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                               "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-fundamental-scan")
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
CANDIDATES = ["netMargin", "opMargin", "netIncomeGrowth", "opProfitGrowth", "equityGrowth", "currentRatio"]
CONTROLS = ["mom60", "roe", "pbr", "revenueGrowth", "retention", "debtRatio"]


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen: seen.add(d[:7]); out.append(d)
    return out


def normd(s):
    s = str(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def select_as_of(records, as_of):
    best = None
    for rec in records:
        af = normd(rec[0])
        if af > as_of: continue
        if best is None or rec[1] > best[1] or (rec[1] == best[1] and af > normd(best[0])):
            best = rec
    return best


def select_fiscal_year(records, fy, as_of):
    best = None
    for rec in records:
        if rec[1] != fy: continue
        af = normd(rec[0])
        if af > as_of: continue
        if best is None or af > normd(best[0]):
            best = rec
    return best


def summarize_ic(recs):
    if not recs: return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "icMean": round(float(v.mean()), 5),
            "icT": round(t, 3) if t is not None else None}


def profile(monthly):
    if not monthly: return {}
    mr = np.array([x["ret"] for x in monthly]); mg = np.array([x["gross"] for x in monthly])
    n = len(mr)
    eq = float(np.prod(1 + mr)); eqg = float(np.prod(1 + mg)); span = n / 12
    cn = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    cg = eqg ** (1 / max(span, 1e-9)) - 1 if eqg > 0 else (1 + np.sum(mg)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr: cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
    return {"n": n, "cagrNet": round(cn, 4), "cagrGross": round(cg, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")
    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    df["turnover20"] = df["total_amount"].groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])
    close_by_date = {d: gd[["ticker", "close"]].set_index("ticker")["close"]
                     for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)

    # ---- build A3 PIT panel: per (ticker, asOf) candidate values ----
    print("Loading raw A3 (annual)...")
    REV, NI, OP, EQ, CA, CL, LIAB = {}, {}, {}, {}, {}, {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                pe = str(r.get("periodEnd", ""))
                if not pe.endswith("12-31"): continue
                t = r.get("ticker"); fy = int(r["fiscalYear"]); af = str(r["availableFrom"])
                if t is None: continue
                def put(m, val):
                    if val is not None:
                        try: m.setdefault(t, []).append((af, fy, float(val)))
                        except (TypeError, ValueError): pass
                put(REV, r.get("revenue")); put(NI, r.get("netIncome")); put(OP, r.get("opProfit"))
                put(EQ, r.get("equity")); put(CA, r.get("currentAssets")); put(CL, r.get("currentLiab"))

    def val(rec_map, t, as_of, fy_shift=0):
        recs = rec_map.get(t, [])
        if fy_shift == 0:
            cur = select_as_of(recs, as_of)
            return cur[2] if cur is not None else None
        cur = select_as_of(recs, as_of)
        if cur is None: return None
        prev = select_fiscal_year(recs, cur[1] - 1, as_of)
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0: return None
        return cur[2] / prev[2] - 1.0

    # base frame at rebalance dates
    print("Building factor panel at rebalance dates...")
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                        "f5", "f20", "f60", "f120"]].copy()
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        rev = val(REV, t, d); ni = val(NI, t, d); op = val(OP, t, d); eq = val(EQ, t, d)
        ca = val(CA, t, d); cl = val(CL, t, d)
        rec = {"ticker": t, "date": d}
        rec["netMargin"] = ni / rev if (ni is not None and rev) else None
        rec["opMargin"] = op / rev if (op is not None and rev) else None
        rec["netIncomeGrowth"] = val(NI, t, d, 1)
        rec["opProfitGrowth"] = val(OP, t, d, 1)
        rec["equityGrowth"] = val(EQ, t, d, 1)
        rec["currentRatio"] = ca / cl if (ca is not None and cl) else None
        rows.append(rec)
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    print(f"  panel rows {len(panel)}")

    # existing factor panels (for residual control)
    print("Loading existing factor panels for residual control...")
    qdf = pd.DataFrame([json.loads(l) for l in open(QUALITY_PANEL, encoding="utf-8")])
    qkey = qdf.set_index(["ticker", "asOf"])
    vdf = pd.DataFrame([json.loads(l) for l in open(VALUATION_PANEL, encoding="utf-8")])
    vkey = vdf.set_index(["ticker", "asOf"])
    a3bx = {}
    # retention from prebuilt not available -> recompute quick via a3b; but we only need retention as control.
    # Load a3b raw for retention + reuse quality roe/debt, valuation pbr. revenueGrowth from panel (already in scan via netMargin path? reuse).
    print("Loading A3b (retention) + computing revenueGrowth (existing controls)...")
    a3b_eps = {}
    A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
    for y in range(2016, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if str(r.get("periodEnd", "")).endswith("1231"):
                    t = r.get("ticker")
                    if t is None: continue
                    a3b_eps.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                                      r.get("eps"), r.get("dividendPerShare")))

    def lookup(key, t, d, field):
        try:
            row = key.loc[(t, d)]
        except KeyError:
            return None
        v = row[field]
        return None if pd.isna(v) or v is None else float(v)

    def retention(t, d):
        recs = a3b_eps.get(t, [])
        cur = select_as_of(recs, d)
        if cur is None or cur[2] is None or cur[2] <= 0 or cur[3] is None: return None
        return 1.0 - cur[3] / cur[2]

    roe_ = m["ticker"].combine(m["date"], lambda t, d: lookup(qkey, t, d, "roe"))
    # rebuild rows via loop for controls (vector lambda may not work for tuple key)
    ctrl = {"roe": [], "debtRatio": [], "pbr": [], "revenueGrowth": [], "retention": []}
    for _, rr in m.iterrows():
        t, d = rr["ticker"], rr["date"]
        ctrl["roe"].append(lookup(qkey, t, d, "roe"))
        ctrl["debtRatio"].append(lookup(qkey, t, d, "debtRatio"))
        ctrl["pbr"].append(lookup(vkey, t, d, "pbr"))
        ctrl["revenueGrowth"].append(val(REV, t, d, 1))
        ctrl["retention"].append(retention(t, d))
    for f in ctrl:
        m[f] = ctrl[f]
    m["period"] = m["date"].map(period_of)
    print(f"  merged {len(m)}")

    # ---- per-candidate analysis ----
    result = {"experiment": "10-KR-18: fundamental scan (new A3 candidates)",
              "controls": CONTROLS, "costBps": COST_BPS,
              "excluded": {"per/eps-related": "split mismatch (resolver.js), already excluded",
                           "dividendYield": "adjusted price vs raw DPS split mismatch",
                           "grossMargin": "no COGS in A3", "totalAssetsTurnover": "no total assets field"}}
    cand_tables = {}
    for f in CANDIDATES:
        print(f"\n===== {f} =====")
        cand_tables[f] = {"coverage": float(m[f].notna().mean())}
        print(f"  coverage {100*m[f].notna().mean():.0f}%")
        ft = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            sub = m[m["period"] == p].dropna(subset=[f])
            ft[p] = {}
            for hn, fc in FWD.items():
                s2 = sub[["date", f, fc]].dropna()
                recs = []
                for d, gd in s2.groupby("date"):
                    if len(gd) < MIN_NAMES or gd[f].nunique() <= 1: continue
                    r = spearmanr(gd[f], gd[fc])
                    if not np.isnan(r.statistic): recs.append(float(r.statistic))
                ic = summarize_ic(recs)
                qq = {}
                if len(s2) >= 5:
                    gg = s2.copy(); gg["q"] = pd.qcut(gg[f].rank(method="first"), 5, labels=False)
                    qq = {"q1": round(float(gg.loc[gg["q"] == 0, fc].mean()), 5),
                          "q5": round(float(gg.loc[gg["q"] == 4, fc].mean()), 5)}
                ft[p][hn] = {"ic": ic, "q5q1": round(float(qq["q5"]) - float(qq["q1"]), 5)
                             if qq.get("q1") is not None else None}
            print(f"    {p}: " + "  ".join(f"{hn} IC={ft[p][hn]['ic'].get('icMean')}(t={ft[p][hn]['ic'].get('icT')})"
                                           f" Q5Q1={ft[p][hn]['q5q1']}" for hn in FWD))
        cand_tables[f]["ic"] = ft

        # long portfolio (annual freq approx, monthly) - long Q5 and separately Q1
        ft["portfolio"] = {}
        for qname, qp in [("topQ5", 4), ("bottomQ1", 0)]:
            ft["portfolio"][qname] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                sub = m[m["period"] == p].dropna(subset=[f])
                out, prev, tkl = [], None, []
                dates = [d for d in months if period_of(d) == p]
                for k, sd in enumerate(dates):
                    if k + 1 >= len(dates): break
                    nd = dates[k + 1]
                    this = sub[sub["date"] == sd]
                    if len(this) < MIN_NAMES: continue
                    if sd not in close_by_date: continue
                    g2 = this.copy(); g2["q"] = pd.qcut(g2[f].rank(method="first"), 5, labels=False)
                    picks = g2.loc[g2["q"] == qp, "ticker"].tolist()
                    cur = set(picks)
                    if prev is not None: tkl.append(len(cur - prev) / len(cur))
                    prev = cur
                    ent_d = next((x for x in all_dates if x > sd), None)
                    if ent_d is None: continue
                    ext_d = next((x for x in dates[k + 1:] if x > ent_d), None)
                    if ext_d is None: continue
                    ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                    rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                            if t in ent.index and t in ext.index and ent.loc[t] > 0]
                    if not rets: continue
                    gr = float(np.mean(rets))
                    out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr, "trades": len(rets)})
                pr = profile(out)
                ft["portfolio"][qname][p] = {**pr, "avgTurnover": round(float(np.mean(tkl)), 3) if tkl else None}
            print(f"    port {qname}: " + "  ".join(f"{p}={ft['portfolio'][qname][p].get('cagrNet')}"
                                                     f"(Sh {ft['portfolio'][qname][p].get('sharpe')})"
                                                     for p in ["TRAIN", "VALID", "TEST"]))
        cand_tables[f] = ft

        # residual IC | (mom60 + existing factors) at 60D/120D
        print(f"    residual IC | (mom60+roe+pbr+revG+ret+debt) 60D/120D:")
        cand_tables[f]["resid"] = {}
        for hn, fc in [("60D", "f60"), ("120D", "f120")]:
            cand_tables[f]["resid"][hn] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                need = [f] + CONTROLS + [fc]
                s2 = m[m["period"] == p][["date"] + need].dropna()
                recs = []
                for d, gd in s2.groupby("date"):
                    if len(gd) < MIN_NAMES: continue
                    feas = [c for c in CONTROLS if c in gd.columns]
                    cols = [c for c in [f] + feas + [fc] if c in gd.columns]
                    gg = gd[cols].dropna()
                    if len(gg) < MIN_NAMES or gg[f].nunique() <= 1: continue
                    X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in feas])
                    y = gg[f].rank(method="average").to_numpy(dtype=float)
                    try:
                        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                        resid = y - beta[0] - X @ beta[1:]
                    except np.linalg.LinAlgError:
                        continue
                    fr = gg[fc].to_numpy(dtype=float)
                    rr = spearmanr(resid, fr)
                    if not np.isnan(rr.statistic): recs.append(float(rr.statistic))
                ric = summarize_ic(recs)
                cand_tables[f]["resid"][hn][p] = ric
                print(f"      {hn} {p}: {ric}")
    result["factors"] = cand_tables
    result["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "kr-fundamental-scan-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()