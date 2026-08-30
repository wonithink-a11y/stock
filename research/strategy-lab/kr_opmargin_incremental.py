#!/usr/bin/env python
"""10-KR-20: opMargin incremental alpha vs other fundamental quality factors.

opMargin + netMargin + ROE + revenueGrowth. A4 PIT monthly panel 2016~2026,
TRAIN/VALID/TEST, next-day entry, monthly rebalance, 30bps/side.

  1. opMargin alone (baseline)
  2. each factor alone
  3. opMargin + each factor 50/50 rank combo
  4. opMargin residual IC after orthogonalizing to each factor
  5. per-combo TRAIN/VALID/TEST IC, residual IC, CAGR, Sharpe, MDD
  6. incremental vs existing LOWMOM60

Key: is opMargin good in itself, a proxy for other quality factors, or adding
independent info? 50/50 fixed only -- no weight/threshold optimization on TEST.
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
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-opmargin-incremental")
MOM60_PATH = None

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
FACTORS = ["opMargin", "netMargin", "roe", "revenueGrowth"]


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
    mr = np.array([x["ret"] for x in monthly]); mg = np.array([x["gross"] for x in monthly])
    n = len(mr); span = n / 12
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

    print("Loading raw A3 (margins, revenue)...")
    REV, OP, NI = {}, {}, {}
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
                except (TypeError, ValueError):
                    pass

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
                af = normd(rec[0])
                if af <= as_of and (prev is None or af > normd(prev[0])): prev = rec
        if prev is None or cur[2] is None or prev[2] is None or prev[2] == 0: return None
        return cur[2] / prev[2] - 1.0

    print("Loading existing quality-panel roe + building factor panel...")
    qdf = pd.DataFrame([json.loads(l) for l in open(QUALITY_PANEL, encoding="utf-8")])
    qkey = qdf.set_index(["ticker", "asOf"])
    def qval(t, d, field):
        try:
            v = qkey.loc[(t, d), field]
            return None if pd.isna(v) or v is None else float(v)
        except KeyError:
            return None

    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                         "f5", "f20", "f60", "f120"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        rev = val(REV, t, d); op = val(OP, t, d); ni = val(NI, t, d)
        rows.append({"ticker": t, "date": d,
                     "opMargin": op / rev if (op is not None and rev) else None,
                     "netMargin": ni / rev if (ni is not None and rev) else None,
                     "roe": qval(t, d, "roe"),
                     "revenueGrowth": grow(REV, t, d)})
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    print(f"  merged {len(m)}")

    mobs = m.dropna(subset=["mom60"])
    result = {"experiment": "10-KR-20: opMargin incremental alpha", "costBps": COST_BPS,
              "factorRanks": {}}

    # ---- factor pair correlations (rank), full sample ----
    print("\n=== factor rank correlation (full sample) ===")
    paircor = {}
    for a in FACTORS:
        for b in FACTORS:
            if a >= b: continue
            sub = m[[a, b]].dropna()
            r = spearmanr(sub[a], sub[b]).statistic
            paircor[f"{a}~{b}"] = round(float(r), 3)
    print(paircor)
    result["rank_corr"] = paircor

    # ---- residual IC: opMargin orthogonalized to each single factor + all ----
    print("\n=== residual IC: opMargin orthogonalized to controls (60D/120D) ===")
    ortho = {}
    ortho_specs = {
        "opMargin|netMargin": ["netMargin"],
        "opMargin|roe": ["roe"],
        "opMargin|revenueGrowth": ["revenueGrowth"],
        "opMargin|mom60": ["mom60"],
        "opMargin|allOther": ["netMargin", "roe", "revenueGrowth", "mom60"],
    }
    for lbl, cx in ortho_specs.items():
        ortho[lbl] = {}
        for hn, fc in [("60D", "f60"), ("120D", "f120")]:
            ortho[lbl][hn] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                s2 = m[(m["period"] == p)][["date", "opMargin"] + cx + [fc]]
                recs = []
                for d, gd in s2.groupby("date"):
                    gg = gd.dropna(subset=["opMargin"] + cx + [fc])
                    if len(gg) < MIN_NAMES or gg["opMargin"].nunique() <= 1: continue
                    if any(gg[c].nunique() <= 1 for c in cx): continue
                    X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in cx])
                    y = gg["opMargin"].rank(method="average").to_numpy(dtype=float)
                    try:
                        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                        resid_ = y - beta[0] - X @ beta[1:]
                    except np.linalg.LinAlgError:
                        continue
                    r = spearmanr(resid_, gg[fc].to_numpy(dtype=float))
                    if not np.isnan(r.statistic): recs.append(float(r.statistic))
                ortho[lbl][hn][p] = summarize_ic(recs)
                print(f"  {lbl} {hn} {p}: {ortho[lbl][hn][p]}")
    result["ortho_resid_ic"] = ortho

    # ---- helper: rank IC + portfolio for a single factor (long top) ----
    def ic_portfolio_column(fcol, nlong=0.20, sign=1.0, resid_on=None, resid_fc="120D"):
        # resid_on: orthogonalize fcol to those controls within period before ranking
        _ = resid_on
        ic_tbl, port_stats = {}, {}
        for hn, fc in FWD.items():
            ic_tbl[hn] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                dates = [d for d in months if period_of(d) == p]
                recs, out, tkl, tot = [], [], [], 0
                for k, sd in enumerate(dates):
                    if k + 1 >= len(dates): break
                    this = m[(m["date"] == sd)]
                    if resid_on:
                        gg = this.dropna(subset=[fcol] + resid_on)
                        core = [c for c in resid_on if c in m.columns]
                        if len(gg) < MIN_NAMES or not core: continue
                        if any(gg[c].nunique() <= 1 for c in core): continue
                        X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in core])
                        y = gg[fcol].rank(method="average").to_numpy(dtype=float)
                        beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                        rv = y - beta[0] - X @ beta[1:]
                        this = gg.copy(); this["_f"] = rv
                        fcollocal = "_f"
                    else:
                        this = this.dropna(subset=[fc, fcol])
                        fcollocal = fcol
                    if len(this) < MIN_NAMES or this[fcollocal].nunique() <= 1: continue
                    r = spearmanr(this[fcollocal], this[fc])
                    if not np.isnan(r.statistic): recs.append(float(r.statistic))
                    if resid_on is None:
                        this = this.copy()
                        this["_r"] = this[fcol].rank(method="average") * sign
                    else:
                        this["_r"] = this[fcollocal].rank(method="average") * sign
                    pick_n = max(int(np.ceil(len(this) * nlong)), 1)
                    picks = this.sort_values("_r", ascending=False).head(pick_n)["ticker"].tolist()
                    ent_d = next((x for x in all_dates if x > sd), None)
                    ext_d = next((x for x in dates[k + 1:] if x > ent_d), None)
                    if ent_d is None or ext_d is None: continue
                    ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                    rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                            if t in ent.index and t in ext.index and ent.loc[t] > 0]
                    if not rets: continue
                    gr = float(np.mean(rets))
                    out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
                    tot += len(rets)
                ic_tbl[hn][p] = summarize_ic(recs)
                port_stats[p] = {**profile(out), "totalTradeSides": int(tot)}
        return ic_tbl, port_stats

    base_port = {}
    print("\n=== 1/2. factor alone (top20%, IC) ===")
    for f in FACTORS:
        ic_tbl, port = ic_portfolio_column(f)
        base_port[f] = port
        print(f"  {f}: IC120 TRAIN={ic_tbl['120D']['TRAIN']['icMean']} VALID={ic_tbl['120D']['VALID']['icMean']} "
              f"TEST={ic_tbl['120D']['TEST']['icMean']} | port "
              f"TRAIN={port['TRAIN']['cagrNet']} VALID={port['VALID']['cagrNet']} TEST={port['TEST']['cagrNet']}")
    result["factor_alone"] = base_port

    print("\n=== 3. opMargin + each 50/50 rank combo (top20%) ===")
    combos = {}
    for f in ["netMargin", "roe", "revenueGrowth"]:
        # build combined rank within each month
        m2 = m.copy()
        m2["_fa"] = m2["opMargin"].groupby(m2["date"]).rank(method="average", pct=True)
        m2["_fb"] = m2[f].groupby(m2["date"]).rank(method="average", pct=True)
        m2["_comb"] = 0.5 * m2["_fa"] + 0.5 * m2["_fb"]
        rows2 = m2[["ticker", "date", "period", "_comb", "mom60", "f5", "f20", "f60", "f120"]].copy()
        ic_tbl, port = ic_portfolio_column_from(rows2, "x", "_comb",
                                                stdates=months, all_dates=all_dates, close_by_date=close_by_date)
        combos[f"opMargin+{f}"] = port
        print(f"  opMargin+{f}: port TRAIN={port['TRAIN']['cagrNet']} "
              f"VALID={port['VALID']['cagrNet']} TEST={port['TEST']['cagrNet']} "
              f"(Sh TEST={port['TEST']['sharpe']})")
    result["combo_5050"] = combos

    # incremental combo minus opMargin-alone and minus baseline
    # 6. vs LOWMOM60
    print("\n=== 6. LOWMOM60 baseline (top20%) ===")
    ic_tbl, port = ic_portfolio_column("mom60", sign=-1.0)
    result["lowmom60_baseline"] = port
    print(f"  LOWMOM60: port TRAIN={port['TRAIN']['cagrNet']} VALID={port['VALID']['cagrNet']} "
          f"TEST={port['TEST']['cagrNet']}")

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-opmargin-incremental-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


def ic_portfolio_column_from(df, fcol, colname, stdates, all_dates, close_by_date):
    ic_tbl, port_stats = {}, {}
    for hn, fc in FWD.items():
        ic_tbl[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in stdates if period_of(d) == p]
            recs, out, tot = [], [], 0
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                this = df[(df["date"] == sd)].dropna(subset=[fc, colname])
                if len(this) < MIN_NAMES or this[colname].nunique() <= 1: continue
                r = spearmanr(this[colname], this[fc])
                if not np.isnan(r.statistic): recs.append(float(r.statistic))
                pick_n = max(int(np.ceil(len(this) * 0.20)), 1)
                picks = this.sort_values(colname, ascending=False).head(pick_n)["ticker"].tolist()
                ent_d = next((x for x in all_dates if x > sd), None)
                ext_d = next((x for x in dates[k + 1:] if x > ent_d), None)
                if ent_d is None or ext_d is None: continue
                ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if not rets: continue
                gr = float(np.mean(rets))
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
                tot += len(rets)
            ic_tbl[hn][p] = summarize_ic(recs)
            port_stats[p] = {**profile(out), "totalTradeSides": int(tot)}
    return ic_tbl, port_stats


if __name__ == "__main__":
    main()
