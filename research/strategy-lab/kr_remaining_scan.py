#!/usr/bin/env python
"""10-KR-22: Remaining untested fundamental/value factor screening.

Inventory of PIT-safe split-safe raw features already validated:
  PBR(valuation-panel), ROE(quality-panel), revenueGrowth, netIncomeGrowth,
  opProfitGrowth, equityGrowth(growth family), netMargin, opMargin,
  retention, debtRatio, currentRatio. PER/EPS/DPS/dividendYield excluded
  (split mismatch). Note: equity/assets is dropped as a deterministic mirror
  (rename) of debtRatio -- not tested as new.

NEW split-safe PIT-safe candidates this scan:
  1. assetTurnover  = revenue / (equity + liabilities)   [A3]  efficiency
  2. treasuryRatio  = istcTotqy / isuStockTotqy          [A3c] buyback intensity
  3. dividendPresent= dividendRowPresent flag (bool)     [A3b] has-dividend

A4 monthly 2016~2026, TRAIN/VALID/TEST, 30bps/side, next-day entry.
Per factor: 5/20/60/120D IC + Q5-Q1, TEST residual IC | (mom60+roe+pbr+
revenueGrowth+retention+debtRatio+opMargin+netMargin), top-Q portfolio.
No threshold/config optimization on TEST. Screening only -> pick top 1-3.
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
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-remaining-scan")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
RESID_CTRL = ["mom60", "roe", "pbr", "revenueGrowth", "retention", "debtRatio", "netMargin", "opMargin"]


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


def summarize_ic(recs):
    if not recs: return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "icMean": round(float(v.mean()), 5),
            "icT": round(t, 3) if t is not None else None}


def profile(monthly):
    if not monthly: return {}
    mr = np.array([x["ret"] for x in monthly]); n = len(mr); span = n / 12
    eq = float(np.prod(1 + mr))
    cn = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr: cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
    return {"n": n, "cagrNet": round(cn, 4),
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

    print("Loading raw A3 / A3b / A3c...")
    REV, EQ, LIAB, OP, NI = {}, {}, {}, {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("12-31"): continue
                t = r.get("ticker")
                if t is None: continue
                af = str(r["availableFrom"]); fy = int(r["fiscalYear"])
                try:
                    if r.get("revenue") is not None: REV.setdefault(t, []).append((af, fy, float(r["revenue"])))
                    if r.get("opProfit") is not None: OP.setdefault(t, []).append((af, fy, float(r["opProfit"])))
                    if r.get("netIncome") is not None: NI.setdefault(t, []).append((af, fy, float(r["netIncome"])))
                    if r.get("equity") is not None: EQ.setdefault(t, []).append((af, fy, float(r["equity"])))
                    if r.get("liabilities") is not None: LIAB.setdefault(t, []).append((af, fy, float(r["liabilities"])))
                except (TypeError, ValueError):
                    pass
    TREAS, ISSUED = {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"): continue
                t = r.get("ticker")
                if t is None: continue
                af = normd(str(r["availableFrom"])); fy = int(r["fiscalYear"])
                try:
                    if r.get("istcTotqy") is not None: TREAS.setdefault(t, []).append((af, fy, float(r["istcTotqy"])))
                    if r.get("isuStockTotqy") is not None: ISSUED.setdefault(t, []).append((af, fy, float(r["isuStockTotqy"])))
                except (TypeError, ValueError):
                    pass
    DIVPR = {}
    for y in range(2016, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"): continue
                t = r.get("ticker")
                if t is None: continue
                af = normd(str(r["availableFrom"])); fy = int(r["fiscalYear"])
                if r.get("dividendRowPresent") is not None:
                    DIVPR.setdefault(t, []).append((af, fy, int(bool(r["dividendRowPresent"]))))

    def val(rm, t, as_of):
        cur = select_as_of(rm.get(t, []), as_of)
        return cur[2] if cur is not None else None
    def grow(rm, t, as_of):
        recs = rm.get(t, [])
        cur = select_as_of(recs, as_of)
        if cur is None: return None
        prev = None
        for rec in recs:
            if rec[1] == cur[1] - 1:
                a = normd(rec[0])
                if a <= as_of and (prev is None or a > normd(prev[0])): prev = rec
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0: return None
        return cur[2] / prev[2] - 1.0

    qdf = pd.DataFrame([json.loads(l) for l in open(QUALITY_PANEL, encoding="utf-8")])
    qkey = qdf.set_index(["ticker", "asOf"])
    vdf = pd.DataFrame([json.loads(l) for l in open(VALUATION_PANEL, encoding="utf-8")])
    vkey = vdf.set_index(["ticker", "asOf"])
    def lookup(key, t, d, field):
        try:
            v = key.loc[(t, d), field]
            return None if pd.isna(v) or v is None else float(v)
        except KeyError:
            return None
    a3b = {}
    for y in range(2016, 2026):
        fp = os.path.join(A3B_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp): continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"): continue
                t = r.get("ticker")
                if t is None: continue
                a3b.setdefault(t, []).append((normd(str(r["availableFrom"])), int(r["fiscalYear"]),
                                              r.get("eps"), r.get("dividendPerShare")))
    def retention(t, d):
        cur = select_as_of(a3b.get(t, []), d)
        if cur is None or cur[2] is None or cur[2] <= 0 or cur[3] is None: return None
        return 1.0 - cur[3] / cur[2]

    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                         "f5", "f20", "f60", "f120"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        rev = val(REV, t, d); eq = val(EQ, t, d); liab = val(LIAB, t, d)
        tr = val(TREAS, t, d); isu = val(ISSUED, t, d)
        ni = val(NI, t, d); op = val(OP, t, d)
        ta = (eq + liab) if (eq is not None and liab is not None) else None
        rows.append({"ticker": t, "date": d,
                     "assetTurnover": rev / ta if (rev is not None and ta and ta != 0) else None,
                     "treasuryRatio": tr / isu if (tr is not None and isu and isu != 0) else None,
                     "dividendPresent": val(DIVPR, t, d),
                     "roe": lookup(qkey, t, d, "roe"),
                     "pbr": lookup(vkey, t, d, "pbr"),
                     "debtRatio": lookup(qkey, t, d, "debtRatio"),
                     "revenueGrowth": grow(REV, t, d),
                     "retention": retention(t, d),
                     "netMargin": ni / rev if (ni is not None and rev) else None,
                     "opMargin": op / rev if (op is not None and rev) else None})
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    print(f"  merged {len(m)}  rows {len(m)}")
    nall = len(m)
    for cand in ["assetTurnover", "treasuryRatio", "dividendPresent"]:
        print(f"  coverage {cand}: {100*m[cand].notna().mean():.1f}%")

    result = {"experiment": "10-KR-22: remaining fundamental/value factor screening", "costBps": COST_BPS}

    def eval_factor(fcol, sign=1.0):
        ic_tab = {}
        for hn, fc in FWD.items():
            ic_tab[hn] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                dates = [d for d in months if period_of(d) == p]
                recs, spreads = [], []
                for sd in dates:
                    this = m[(m["date"] == sd)].dropna(subset=[fc, fcol])
                    if len(this) < MIN_NAMES or this[fcol].nunique() <= 1: continue
                    r = spearmanr(this[fcol], this[fc])
                    if not np.isnan(r.statistic): recs.append(float(r.statistic))
                    t2 = this.copy(); t2["q"] = pd.qcut(t2[fcol].rank(method="first"), 5, labels=False)
                    spreads.append(float(t2.loc[t2["q"] == 4, fc].mean() - t2.loc[t2["q"] == 0, fc].mean()))
                ic_tab[hn][p] = {**summarize_ic(recs),
                                 "q5q1": round(float(np.mean(spreads)), 5) if spreads else None}
        # portfolio (top quintile, sign applied)
        port = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            out = []
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                this = m[(m["date"] == sd)].dropna(subset=[fcol])
                if len(this) < MIN_NAMES: continue
                this = this.copy()
                this["_r"] = this[fcol].rank(method="average") * sign
                picks = this.sort_values("_r", ascending=False).head(
                    max(int(np.ceil(len(this) * 0.20)), 1))["ticker"].tolist()
                ent_d = next((x for x in all_dates if x > sd), None)
                if ent_d is None: continue
                ext_d = next((x for x in dates if x > ent_d), None)
                if ext_d is None: continue
                ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets: continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
            port[p] = profile(out)
        return ic_tab, port

    # TEST residual IC | controls
    def test_resid_ic(fcol, sign=1.0):
        fc = "f120"
        s2 = m[m["period"] == "TEST"].dropna(subset=[fcol] + RESID_CTRL + [fc])
        recs = []
        for d, gd in s2.groupby("date"):
            gg = gd.dropna(subset=[fcol] + RESID_CTRL + [fc])
            if len(gg) < MIN_NAMES or gg[fcol].nunique() <= 1: continue
            if any(gg[c].nunique() <= 1 for c in RESID_CTRL): continue
            X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in RESID_CTRL])
            y = (gg[fcol].rank(method="average") * sign).to_numpy(dtype=float)
            try:
                beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                resid_ = y - beta[0] - X @ beta[1:]
            except np.linalg.LinAlgError:
                continue
            r = spearmanr(resid_, gg[fc].to_numpy(dtype=float))
            if not np.isnan(r.statistic): recs.append(float(r.statistic))
        return summarize_ic(recs)

    cands = {
        "assetTurnover": {"sign": 1.0, "desc": "revenue/(equity+liabilities) efficiency"},
        "treasuryRatio": {"sign": 1.0, "desc": "istcTotqy/isuStockTotqy buyback"},
        "dividendPresent": {"sign": 1.0, "desc": "has-dividend flag"},
    }
    out = {}
    for name, spec in cands.items():
        fcol, sign = name, spec["sign"]
        ic_tab, port = eval_factor(fcol, sign)
        trich = test_resid_ic(fcol, sign)
        out[name] = {"desc": spec["desc"], "sign": sign,
                     "coverage": round(100 * m[fcol].notna().mean(), 1),
                     "ic": ic_tab, "portfolio": port, "test_resid_ic120": trich}
        print(f"\n===== {name} ({spec['desc']}) sign={sign} coverage={out[name]['coverage']}% =====")
        for hn in FWD:
            line = f"  {hn}: "
            for p in ["TRAIN", "VALID", "TEST"]:
                x = ic_tab[hn][p]
                line += f"{p} IC={x.get('icMean')}(t={x.get('icT')}) Q5Q1={x.get('q5q1')}  "
            print(line)
        print(f"  TEST resid|ctrl 120D: {trich}")
        print(f"  port: " + "  ".join(
            f"{p}={port[p]['cagrNet']}(Sh {port[p]['sharpe']}/MDD {port[p]['mdd']})" for p in ["TRAIN", "VALID", "TEST"]))
    result["candidates"] = out

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-remaining-scan-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()