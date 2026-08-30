#!/usr/bin/env python
"""10-KR-19: opMargin Robustness (tail vs broad-band).

opMargin only. A4 PIT monthly panel 2016~2026, TRAIN/VALID/TEST, next-day entry,
monthly rebalance, 30bps/side. No threshold/config optimization on TEST.

  1. opMargin Q1~Q10 forward 5/20/60/120D returns
  2. Q5-Q1 spread & monotonicity
  3. top 10/20/30/40% portfolios
  4. trimmed ranking (drop extreme top tail then re-pick)
  5. residual IC | (mom60 + existing major factors)
  6. each config TRAIN/VALID/TEST CAGR, Sharpe, MDD

Goal: is opMargin effect only in the top tail, or consistently across a broad band?
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-opmargin-robustness")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
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

    print("Loading raw A3 (opMargin)...")
    REV, OP = {}, {}
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
                except (TypeError, ValueError):
                    pass

    def val(rm, t, as_of):
        cur = select_as_of(rm.get(t, []), as_of)
        return cur[2] if cur is not None else None

    print("Building opMargin + controls panel at rebalance dates...")
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                        "f5", "f20", "f60", "f120"]].copy()
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        rev = val(REV, t, d); op = val(OP, t, d)
        rows.append({"ticker": t, "date": d,
                     "opMargin": op / rev if (op is not None and rev) else None})
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    m = m.dropna(subset=["opMargin"])

    qdf = pd.DataFrame([json.loads(l) for l in open(QUALITY_PANEL, encoding="utf-8")])
    qkey = qdf.set_index(["ticker", "asOf"])
    vdf = pd.DataFrame([json.loads(l) for l in open(VALUATION_PANEL, encoding="utf-8")])
    vkey = vdf.set_index(["ticker", "asOf"])
    def lookup(key, t, d, field):
        try:
            row = key.loc[(t, d)]
        except KeyError:
            return None
        v = row[field]
        return None if pd.isna(v) or v is None else float(v)
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
    ctrl = {"roe": [], "debtRatio": [], "pbr": [], "revenueGrowth": [], "retention": []}
    for _, rr in m.iterrows():
        t, d = rr["ticker"], rr["date"]
        ctrl["roe"].append(lookup(qkey, t, d, "roe"))
        ctrl["debtRatio"].append(lookup(qkey, t, d, "debtRatio"))
        ctrl["pbr"].append(lookup(vkey, t, d, "pbr"))
        ctrl["retention"].append(retention(t, d))
    m["roe"] = ctrl["roe"]; m["debtRatio"] = ctrl["debtRatio"]
    m["pbr"] = ctrl["pbr"]; m["retention"] = ctrl["retention"]
    # revenueGrowth control properly (YoY)
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
    m["revenueGrowth"] = [grow(REV, t, d) for t, d in zip(m["ticker"], m["date"])]
    m["period"] = m["date"].map(period_of)
    print(f"  merged {len(m)}  opMargin coverage {100*m['opMargin'].notna().mean():.0f}%")

    result = {"experiment": "10-KR-19: opMargin Robustness", "costBps": COST_BPS}

    # residual IC | controls @60D/120D
    print("\n=== residual IC | (mom60+roe+pbr+revG+ret+debt) ===")
    resid = {}
    for hn, fc in [("60D", "f60"), ("120D", "f120")]:
        resid[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            s2 = m[m["period"] == p][["date", "opMargin"] + CONTROLS + [fc]].dropna()
            recs = []
            for d, gd in s2.groupby("date"):
                if len(gd) < MIN_NAMES: continue
                gg = gd.dropna(subset=["opMargin"] + CONTROLS + [fc])
                if len(gg) < MIN_NAMES or gg["opMargin"].nunique() <= 1: continue
                X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in CONTROLS])
                y = gg["opMargin"].rank(method="average").to_numpy(dtype=float)
                try:
                    beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                    resid_ = y - beta[0] - X @ beta[1:]
                except np.linalg.LinAlgError:
                    continue
                rr = spearmanr(resid_, gg[fc].to_numpy(dtype=float))
                if not np.isnan(rr.statistic): recs.append(float(rr.statistic))
            resid[hn][p] = summarize_ic(recs)
            print(f"  {hn} {p}: {resid[hn][p]}")
    result["resid_ic"] = resid

    # 1) Q1~Q10 forward returns (pooled)
    print("\n=== opMargin decile forward returns (pooled, net) ===")
    dec_ret = {}
    for hn, fc in FWD.items():
        dec_ret[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            acc = []
            for sd in dates:
                this = m[(m["date"] == sd)].dropna(subset=[fc])
                if len(this) < MIN_NAMES: continue
                this = this.copy()
                this["dec"] = pd.qcut(this["opMargin"].rank(method="first"), 10, labels=False)
                acc.append(this.groupby("dec")[fc].mean())
            d = pd.concat(acc, axis=1).T if acc else pd.DataFrame()
            dec_ret[hn][p] = {f"D{i+1}": round(float(d[i].mean()), 5) if i in d.columns else None for i in range(10)}
        print(f"  {hn}: TRAIN D1={dec_ret[hn]['TRAIN']['D1']} D5={dec_ret[hn]['TRAIN']['D5']} D10={dec_ret[hn]['TRAIN']['D10']}"
              f" | VALID D1={dec_ret[hn]['VALID']['D1']} D10={dec_ret[hn]['VALID']['D10']}"
              f" | TEST D1={dec_ret[hn]['TEST']['D1']} D10={dec_ret[hn]['TEST']['D10']}")
    result["decile_forward"] = dec_ret

    # 2) IC + Q5-Q1
    print("\n=== opMargin IC + Q5-Q1 (liquid) ===")
    ic_tab = {}
    for hn, fc in FWD.items():
        ic_tab[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            recs, spreads = [], []
            for sd in dates:
                this = m[(m["date"] == sd)].dropna(subset=[fc])
                if len(this) < MIN_NAMES or this["opMargin"].nunique() <= 1: continue
                r = spearmanr(this["opMargin"], this[fc])
                if not np.isnan(r.statistic): recs.append(float(r.statistic))
                t2 = this.copy(); t2["q"] = pd.qcut(t2["opMargin"].rank(method="first"), 5, labels=False)
                spreads.append(float(t2.loc[t2["q"] == 4, fc].mean() - t2.loc[t2["q"] == 0, fc].mean()))
            ic_tab[hn][p] = {**summarize_ic(recs),
                             "q5q1": round(float(np.mean(spreads)), 5) if spreads else None}
            print(f"  {hn} {p}: {ic_tab[hn][p]}")
    result["ic"] = ic_tab

    def run_band(band_fn):
        stats = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            out, prev, tkl, tot = [], None, [], 0
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                this = m[(m["date"] == sd)]
                if len(this) < MIN_NAMES: continue
                picks = band_fn(this)
                if not picks: continue
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
                tot += len(rets)
            stats[p] = {**profile(out), "totalTradeSides": int(tot),
                        "avgTurnover": round(float(np.mean(tkl)), 3) if tkl else None}
        return stats

    # 3) top 10/20/30/40%
    print("\n=== top N% portfolios (net CAGR/Sharpe/MDD) ===")
    topN = {}
    for frac in [0.10, 0.20, 0.30, 0.40]:
        fn = lambda this, frac=frac: this.sort_values("opMargin", ascending=False).head(
            max(int(np.ceil(len(this) * frac)), 1))["ticker"].tolist()
        st = run_band(fn)
        topN[str(int(frac * 100))] = st
        print(f"  top{int(frac*100)}%: " + "  ".join(
            f"{p}={st[p]['cagrNet']}(Sh {st[p]['sharpe']}/MDD {st[p]['mdd']})" for p in ["TRAIN", "VALID", "TEST"]))
    result["top_N"] = topN

    # 4) trimmed ranking: drop top extreme decile (top 10% opMargin) then choose top 20% of remainder
    print("\n=== trimmed (drop top 10% extreme, then top 20% of remainder) ===")
    trim_stats = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        out, tkl = [], []
        for k, sd in enumerate(dates):
            if k + 1 >= len(dates): break
            this = m[(m["date"] == sd)]
            if len(this) < MIN_NAMES: continue
            cut = this["opMargin"].quantile(0.90)
            sub = this[this["opMargin"] <= cut]
            frac = 0.20
            picks = sub.sort_values("opMargin", ascending=False).head(
                max(int(np.ceil(len(sub) * frac)), 1))["ticker"].tolist()
            ent_d = next((x for x in all_dates if x > sd), None)
            ext_d = next((x for x in dates[k + 1:] if x > ent_d), None)
            if ent_d is None or ext_d is None: continue
            ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets: continue
            gr = float(np.mean(rets))
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr, "trades": len(rets)})
        trim_stats[p] = profile(out)
        print(f"  {p}: {trim_stats[p]}")
    result["trimmed_top20_after_drop10"] = trim_stats

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-opmargin-robustness-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()