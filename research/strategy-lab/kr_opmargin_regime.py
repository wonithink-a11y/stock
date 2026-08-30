#!/usr/bin/env python
"""10-KR-21: opMargin time & regime stability.

opMargin alone + opMargin residual(allOther controls).
A4 PIT monthly panel 2016~2026, next-day entry, monthly rebalance, 30bps/side.

  1. monthly / yearly IC and Q5-Q1
  2. 24-month rolling IC
  3. Bull / Bear / Sideways regime IC
  4. high / low volatility regime IC
  5. residual IC same analysis
  6. per-regime top-quintile portfolio CAGR/Sharpe/MDD
  7. alongside TRAIN/VALID/TEST

No new threshold/weight optimization; use fixed opMargin definition/configuration.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-opmargin-regime")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}
CONTROLS = ["netMargin", "roe", "revenueGrowth", "mom60"]


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

    print("Loading raw A3 (opMargin) + controls...")
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

    # ---- market index (equal-weight cross-sectional daily returns) for regimes ----
    print("Building market index (equal-weight cross-sectional return) for regimes...")
    ret_px = df[["ticker", "date", "close"]].copy()
    ret_px["dret"] = ret_px.groupby("ticker", sort=False)["close"].pct_change(fill_method=None)
    idx_day = ret_px.groupby("date")["dret"].mean()
    idx_day = idx_day.dropna().sort_index()
    idx_cum = (1.0 + idx_day).cumprod()
    idx_ret60 = idx_cum.pct_change(60)
    idx_vol = idx_day.rolling(60, min_periods=30).std() * np.sqrt(252)
    idx_ret60_dt = {k: float(v) for k, v in idx_ret60.items() if not pd.isna(v)}
    idx_vol_dt = {k: float(v) for k, v in idx_vol.items() if not pd.isna(v)}

    regime = {}
    for d in months:
        cand = [v for k, v in idx_ret60_dt.items() if k <= d]
        hist = [v for k, v in idx_vol_dt.items() if k <= d]
        r60 = float(cand[-1]) if cand else None
        if r60 is None:
            regime[d] = None; continue
        if r60 > 0.05: regime[d] = "Bull"
        elif r60 < -0.05: regime[d] = "Bear"
        else: regime[d] = "Sideways"
    vol_med = float(np.nanmedian([v for k, v in idx_vol_dt.items()])) if idx_vol_dt else float("nan")
    m["regime"] = m["date"].map(regime)
    m["volFlag"] = None
    for d in months:
        hist = [v for k, v in idx_vol_dt.items() if k <= d]
        if hist:
            m.loc[m["date"] == d, "volFlag"] = "highVol" if hist[-1] > vol_med else "lowVol"
    print(f"  regime counts: Bull={sum(1 for v in regime.values() if v=='Bull')} "
          f"Bear={sum(1 for v in regime.values() if v=='Bear')} "
          f"Sideways={sum(1 for v in regime.values() if v=='Sideways')} "
          f"None={sum(1 for v in regime.values() if v is None)}")
    print(f"  vol median={vol_med:.4f}  highVol={sum(1 for v in m['volFlag'] if v=='highVol')} "
          f"lowVol={sum(1 for v in m['volFlag'] if v=='lowVol')}")

    result = {"experiment": "10-KR-21: opMargin time & regime stability", "costBps": COST_BPS}

    periods = ["TRAIN", "VALID", "TEST"]

    # residual-IC helper over a subset of rows (per date)
    def resid_ic_rows(m2, hn="120D"):
        fc = FWD[hn]
        recs = []
        for d, gd in m2.groupby("date"):
            gg = gd.dropna(subset=["opMargin"] + CONTROLS + [fc])
            if len(gg) < MIN_NAMES or gg["opMargin"].nunique() <= 1: continue
            if any(gg[c].nunique() <= 1 for c in CONTROLS): continue
            X = np.column_stack([gg[c].rank(method="average").to_numpy(dtype=float) for c in CONTROLS])
            y = gg["opMargin"].rank(method="average").to_numpy(dtype=float)
            try:
                beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)
                resid_ = y - beta[0] - X @ beta[1:]
            except np.linalg.LinAlgError:
                continue
            r = spearmanr(resid_, gg[fc].to_numpy(dtype=float))
            if not np.isnan(r.statistic): recs.append(float(r.statistic))
        return recs

    # ---- 1. monthly IC (raw + resid) ----
    print("\n=== 1. monthly IC (120D) raw + residual ===")
    monthly_ic = {}
    for d in months:
        this = m[m["date"] == d].dropna(subset=["f120", "opMargin"])
        raw = None; rs = None
        if len(this) >= MIN_NAMES and this["opMargin"].nunique() > 1:
            r = spearmanr(this["opMargin"], this["f120"])
            if not np.isnan(r.statistic): raw = float(r.statistic)
        rrec = resid_ic_rows(this)
        if rrec: rs = float(rrec[0])
        monthly_ic[d] = {"raw": raw, "resid": rs}
    # yearly aggregate
    print("\n  Yearly mean raw IC / resid IC + Q5-Q1 raw:")
    yearly = {}
    for yr in sorted(set(d[:4] for d in months)):
        dts = [d for d in months if d[:4] == yr]
        raw = [monthly_ic[d]["raw"] for d in dts if monthly_ic[d]["raw"] is not None]
        rs = [monthly_ic[d]["resid"] for d in dts if monthly_ic[d]["resid"] is not None]
        # Q5-Q1 per month then mean
        q = []
        for d in dts:
            this = m[m["date"] == d].dropna(subset=["f120", "opMargin"])
            if len(this) < MIN_NAMES: continue
            t2 = this.copy(); t2["q"] = pd.qcut(t2["opMargin"].rank(method="first"), 5, labels=False)
            q.append(float(t2.loc[t2["q"] == 4, "f120"].mean() - t2.loc[t2["q"] == 0, "f120"].mean()))
        yearly[yr] = {"rawIC": round(float(np.mean(raw)), 4) if raw else None,
                      "residIC": round(float(np.mean(rs)), 4) if rs else None,
                      "q5q1": round(float(np.mean(q)), 4) if q else None,
                      "nMonths": len(dts)}
        print(f"  {yr}: rawIC={yearly[yr]['rawIC']} residIC={yearly[yr]['residIC']} "
              f"Q5-Q1={yearly[yr]['q5q1']} (n={yearly[yr]['nMonths']})")
    result["yearly"] = yearly

    # ---- 2. 24-month rolling IC ----
    print("\n=== 2. 24-month rolling raw/resid IC (120D) ===")
    rolling = []
    raw_seq = [(d, monthly_ic[d]["raw"]) for d in months if monthly_ic[d]["raw"] is not None]
    rs_seq = [(d, monthly_ic[d]["resid"]) for d in months if monthly_ic[d]["resid"] is not None]
    for i in range(24, len(raw_seq) + 1):
        win = raw_seq[i - 24:i]
        d0, d1 = win[0][0], win[-1][0]
        raw_mean = float(np.mean([x[1] for x in win]))
        rs_win = [x for x in rs_seq if x[0] in {w[0] for w in win}]
        rs_mean = float(np.mean([x[1] for x in rs_win])) if rs_win else None
        rolling.append({"from": d0, "to": d1, "rawIC24m": round(raw_mean, 4),
                        "residIC24m": round(rs_mean, 4) if rs_mean is not None else None})
    result["rolling24m"] = rolling
    pos = sum(1 for r in rolling if r["rawIC24m"] > 0)
    print(f"  24m rolling windows={len(rolling)}, raw>0: {pos}/{len(rolling)} "
          f"({100*pos/max(len(rolling),1):.0f}%)")
    posr = sum(1 for r in rolling if r["residIC24m"] is not None and r["residIC24m"] > 0)
    nrr = sum(1 for r in rolling if r["residIC24m"] is not None)
    print(f"  resid>0: {posr}/{nrr} ({100*posr/max(nrr,1):.0f}%)")

    # ---- 3/4. regime IC (raw + resid) + 6. portfolio per regime ----
    print("\n=== 3/4. regime IC (120D) raw + resid; top-Q portfolio per regime ===")
    regime_res = {}
    for rg in ["Bull", "Bear", "Sideways"]:
        sub = m[m["regime"] == rg]
        raw = [x["raw"] for d, x in monthly_ic.items() if regime.get(d) == rg and x["raw"] is not None]
        rs = [monthly_ic[d]["resid"] for d in monthly_ic if regime.get(d) == rg
              and monthly_ic[d]["resid"] is not None]
        raw_ic = summarize_ic(raw)
        rs_ic = summarize_ic(rs)
        # portfolio: long top quintile (opMargin), next monthly rebalance
        port = {p: [] for p in periods}
        for k in range(len(months) - 1):
            sd = months[k]; nd = months[k + 1]
            if regime.get(sd) != rg: continue
            this = m[m["date"] == sd].dropna(subset=["opMargin"])
            if len(this) < MIN_NAMES: continue
            picks = this.sort_values("opMargin", ascending=False).head(
                max(int(np.ceil(len(this) * 0.20)), 1))["ticker"].tolist()
            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None or nd <= ent_d: continue
            ent = close_by_date[ent_d]
            # exit at rebalance date's close (start of nd)
            ext_dates = [x for x in all_dates if x >= ent_d and x < nd]
            if not ext_dates: continue
            ext = close_by_date[ext_dates[-1]]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets: continue
            gr = float(np.mean(rets))
            port[period_of(sd)].append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
        port_stats = {p: profile(port[p]) for p in periods}
        regime_res[rg] = {"rawIC": raw_ic, "residIC": rs_ic, "portfolio": port_stats,
                          "nMonths": len(raw)}
        print(f"  {rg} (n={len(raw)}m): rawIC={raw_ic}  residIC={rs_ic}")
        print(f"    portfolio: TRAIN={port_stats['TRAIN']['cagrNet']}(Sh {port_stats['TRAIN']['sharpe']})"
              f" VALID={port_stats['VALID']['cagrNet']}(Sh {port_stats['VALID']['sharpe']})"
              f" TEST={port_stats['TEST']['cagrNet']}(Sh {port_stats['TEST']['sharpe']})")
    result["regime"] = regime_res

    # ---- 4. vol regime IC + portfolio ----
    print("\n=== 4. high/low vol regime IC (120D) + top-Q portfolio ===")
    vol_res = {}
    for vlab in ["highVol", "lowVol"]:
        sub = m[m["volFlag"] == vlab]
        raw = [monthly_ic[d]["raw"] for d in monthly_ic if m.loc[m['date'] == d, 'volFlag'].iloc[0] == vlab
               and monthly_ic[d]["raw"] is not None]
        rs = [monthly_ic[d]["resid"] for d in monthly_ic if m.loc[m['date'] == d, 'volFlag'].iloc[0] == vlab
              and monthly_ic[d]["resid"] is not None]
        port = {p: [] for p in periods}
        for k in range(len(months) - 1):
            sd = months[k]
            if m.loc[m['date'] == sd, 'volFlag'].iloc[0] != vlab: continue
            this = m[m["date"] == sd].dropna(subset=["opMargin"])
            if len(this) < MIN_NAMES: continue
            picks = this.sort_values("opMargin", ascending=False).head(
                max(int(np.ceil(len(this) * 0.20)), 1))["ticker"].tolist()
            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None: continue
            ext_d = next((x for x in months if x > ent_d), None)
            if ext_d is None: continue
            ent = close_by_date[ent_d]; ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets: continue
            gr = float(np.mean(rets))
            port[period_of(sd)].append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr})
        port_stats = {p: profile(port[p]) for p in periods}
        vol_res[vlab] = {"rawIC": summarize_ic(raw), "residIC": summarize_ic(rs),
                         "portfolio": port_stats, "nMonths": len(raw)}
        print(f"  {vlab} (n={len(raw)}m): rawIC={vol_res[vlab]['rawIC']}  residIC={vol_res[vlab]['residIC']}")
        print(f"    portfolio: TRAIN={port_stats['TRAIN']['cagrNet']}(Sh {port_stats['TRAIN']['sharpe']})"
              f" VALID={port_stats['VALID']['cagrNet']}(Sh {port_stats['VALID']['sharpe']})"
              f" TEST={port_stats['TEST']['cagrNet']}(Sh {port_stats['TEST']['sharpe']})")
    result["vol_regime"] = vol_res

    # ---- 7. TRAIN/VALID/TEST raw + resid IC + portfolio (reference) ----
    print("\n=== 7. TRAIN/VALID/TEST (reference) ===")
    ref = {}
    for p in periods:
        dates = [d for d in months if period_of(d) == p]
        ic = summarize_ic([monthly_ic[d]["raw"] for d in dates if monthly_ic[d]["raw"] is not None])
        ric = summarize_ic([monthly_ic[d]["resid"] for d in dates if monthly_ic[d]["resid"] is not None])
        ref[p] = {"rawIC": ic, "residIC": ric}
        print(f"  {p}: rawIC={ic} residIC={ric}")
    result["period_ref"] = ref

    result["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "kr-opmargin-regime-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()