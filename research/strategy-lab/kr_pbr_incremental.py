#!/usr/bin/env python
"""10-KR-15: PBR Incremental Alpha (vs LOWMOM60).

compare (same universe/period/cost, PIT-safe next-day entry):
  baseline = LOWMOM60   (top-30 lowest mom60, liquid turnover20>=1e8, monthly, ew)  [strategies/lowmom60_v1]
  pbr_only = PBR low    (top-30 lowest pbr>0, liquid turnover20>=1e8, monthly, ew)  [strategies/pbr_value_v1]
  combined = 50/50 two-sleeve baseline + pbr_only

Metrics per TRAIN/VALID/TEST: CAGR net/gross, Sharpe, MDD, turnover, 거래수, incremental.
Core: does PBR add OOS-stable incremental alpha to LOWMOM60?
"""
import json
import os
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                               "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-28-kr-pbr-incremental")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_TURNOVER = 100_000_000.0
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen: seen.add(d[:7]); out.append(d)
    return out


def profile(monthly):
    if not monthly:
        return {}
    mr = np.array([x["ret"] for x in monthly])
    mg = np.array([x["gross"] for x in monthly])
    n = len(mr)
    eq = float(np.prod(1 + mr))
    eqg = float(np.prod(1 + mg))
    span = n / 12
    cagr_net = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    cagr_gross = eqg ** (1 / max(span, 1e-9)) - 1 if eqg > 0 else (1 + np.sum(mg)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr:
        cum *= (1 + r); peak = max(peak, cum); mdd = min(mdd, cum / peak - 1)
    return {"n": n, "cagrNet": round(cagr_net, 4), "cagrGross": round(cagr_gross, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    cols = ["ticker", "date", "close", "total_amount"]
    df = pd.read_parquet(A4_PATH, columns=cols)
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    for n, col in [(20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    ta = df["total_amount"]
    df["turnover20"] = ta.groupby(df["ticker"]).transform(lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["mom60", "turnover20"])

    close_by_date = {d: gd[["ticker", "close"]].set_index("ticker")["close"]
                     for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)

    print("Loading PBR panel...")
    pbr_lookup = {}
    with open(VALUATION_PANEL, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("pbr") and r["pbr"] > 0:
                pbr_lookup[(r["ticker"], r["asOf"])] = r["pbr"]
    sel = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20", "f20", "f60", "f120"]].copy()
    sel["pbr"] = sel.apply(lambda r: pbr_lookup.get((r["ticker"], r["date"]), np.nan), axis=1)
    sel_by_date = {d: gd for d, gd in sel.groupby("date")}

    def run_sleeve(rank_col, ascending):
        months_out = {}
        name_overlap_prev = {}
        pbr_stats = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            out, prev = [], None
            tot_trades = 0
            tkl = []
            for k, sd in enumerate(dates):
                if k + 1 >= len(dates): break
                nd = dates[k + 1]
                db = sel_by_date[sd]
                db = db[db["turnover20"] >= MIN_TURNOVER].dropna(subset=[rank_col])
                if len(db) < MIN_NAMES: continue
                sel = db.sort_values(rank_col, ascending=ascending).head(TOP_N)["ticker"].tolist()
                cur = set(sel)
                if prev is not None:
                    tkl.append(len(cur - prev) / len(cur))
                prev = cur
                # next-day PIT-safe entry
                ent_d = next((d for d in all_dates if d > sd), None)
                if ent_d is None: continue
                ext_d = next((d for d in dates[k + 1:] if d > ent_d), None)
                if ext_d is None: continue
                ent = close_by_date[ent_d]
                ext = close_by_date[ext_d]
                rets = []
                for t in sel:
                    if t in ent.index and t in ext.index and ent.loc[t] > 0:
                        rets.append(ext.loc[t] / ent.loc[t] - 1.0)
                if not rets: continue
                gr = float(np.mean(rets))
                out.append({"sd": sd, "ret": gr - ROUNDTRIP_BPS / 10000, "gross": gr,
                            "trades": len(rets), "names": len(rets)})
                tot_trades += len(rets)
            months_out[p] = out
            pbr_stats[p] = {"totalTradeSides": int(tot_trades),
                            "avgTurnoverPerRebal": round(float(np.mean(tkl)), 3) if tkl else None}
            pr = profile(out)
            pbr_stats[p].update(pr)
        return months_out, pbr_stats

    print("\n=== LOWMOM60 baseline ===")
    base_months, base_stats = run_sleeve("mom60", ascending=True)
    print(f"  TRAIN: {base_stats['TRAIN']}\n  VALID: {base_stats['VALID']}\n  TEST : {base_stats['TEST']}")

    print("\n=== PBR low-value (pbr_value_v1 rule) ===")
    pbr_months, pbr_stats = run_sleeve("pbr", ascending=True)
    print(f"  TRAIN: {pbr_stats['TRAIN']}\n  VALID: {pbr_stats['VALID']}\n  TEST : {pbr_stats['TEST']}")

    # combined 50/50 (month-matched)
    combined_months = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        b = {x["sd"]: x for x in base_months[p]}
        o = {x["sd"]: x for x in pbr_months[p]}
        cm = []
        for sd in sorted(set(b) & set(o)):
            gr = 0.5 * b[sd]["gross"] + 0.5 * o[sd]["gross"]
            r = 0.5 * b[sd]["ret"] + 0.5 * o[sd]["ret"]
            cm.append({"sd": sd, "ret": r, "gross": gr, "trades": b[sd]["trades"] + o[sd]["trades"],
                       "names": b[sd]["names"] + o[sd]["names"]})
        combined_months[p] = cm
    combined_stats = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        pr = profile(combined_months[p])
        combined_stats[p] = {**pr, "totalTradeSides": int(sum(x["trades"] for x in combined_months[p]))}
    print("\n=== Combined 50/50 ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"  {p}: {combined_stats[p]}")

    # incremental
    print("\n=== Incremental (combined - baseline) / (pbr_only - baseline) ===")
    result = {"experiment": "10-KR-15: PBR Incremental Alpha vs LOWMOM60",
              "baseline": "LOWMOM60 top-30 liquid monthly next-day entry",
              "pbr_only": "PBR low-value top-30 liquid monthly next-day entry (pbr_value_v1 rule)",
              "combine": "50/50 two-sleeve", "costBps": COST_BPS}
    incremental = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        cb, bs, pb = combined_stats[p], base_stats[p], pbr_stats[p]
        def diff(x, y, k):
            return round(x[k] - y[k], 4) if x.get(k) is not None and y.get(k) is not None else None
        incremental[p] = {
            "comb_minus_base_cagrNet": diff(cb, bs, "cagrNet"),
            "comb_minus_base_cagrGross": diff(cb, bs, "cagrGross"),
            "comb_minus_base_sharpe": diff(cb, bs, "sharpe"),
            "comb_minus_base_mdd": diff(cb, bs, "mdd"),
            "pbr_minus_base_cagrNet": diff(pb, bs, "cagrNet"),
            "pbr_minus_base_cagrGross": diff(pb, bs, "cagrGross"),
            "pbr_minus_base_sharpe": diff(pb, bs, "sharpe"),
            "pbr_minus_base_mdd": diff(pb, bs, "mdd"),
        }
        print(f"  {p}: comb-base {incremental[p]}")
    result["incremental"] = incremental

    # portfolio overlap / return correlation (독립성 검증)
    print("\n=== Name overlap + return correlation ===")
    overlap = {}
    retcorr = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        b = {x["sd"]: x for x in base_months[p]}
        o = {x["sd"]: x for x in pbr_months[p]}
        common = sorted(set(b) & set(o))
        ov = []
        for sd in common:
            t = set()
            db = sel_by_date[sd][sel_by_date[sd]["turnover20"] >= MIN_TURNOVER]
            nb = set(db.dropna(subset=["mom60"]).sort_values("mom60", ascending=True).head(TOP_N)["ticker"])
            no = set(db.dropna(subset=["pbr"]).sort_values("pbr", ascending=True).head(TOP_N)["ticker"])
            ov.append(len(nb & no) / len(nb | no))
        rb = np.array([b[sd]["gross"] for sd in common])
        ro = np.array([o[sd]["gross"] for sd in common])
        cc = float(np.corrcoef(rb, ro)[0, 1]) if len(common) > 2 and rb.std() > 0 and ro.std() > 0 else None
        overlap[p] = {"nMonths": len(common), "jaccardNames": round(float(np.mean(ov)), 3) if ov else None,
                      "returnCorr": round(cc, 4) if cc is not None else None}
        print(f"  {p}: {overlap[p]}")
    result["independence"] = {"nameOverlap": overlap}

    result["baseline"] = base_stats
    result["pbr_only"] = pbr_stats
    result["combined"] = combined_stats

    # PBR IC and residual IC | mom60 (liquid universe, monthly rebalance dates)
    from scipy.stats import spearmanr
    print("\n=== PBR IC / residual IC | mom60 (liquid universe) ===")
    resid_ic = {}
    for hn, fc in [("20D", "f20"), ("60D", "f60"), ("120D", "f120")]:
        resid_ic[hn] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            dates = [d for d in months if period_of(d) == p]
            ic_recs, ric_recs = [], []
            for sd in dates:
                db = sel_by_date[sd]
                db = db[db["turnover20"] >= MIN_TURNOVER].dropna(subset=["mom60", "pbr", fc])
                if len(db) < MIN_NAMES: continue
                if db["pbr"].nunique() <= 1: continue
                pb = db["pbr"].rank(method="average").to_numpy(dtype=float)
                mo = db["mom60"].rank(method="average").to_numpy(dtype=float)
                fr = db[fc].to_numpy(dtype=float)
                r = spearmanr(db["pbr"], fr)
                if not np.isnan(r.statistic): ic_recs.append(float(r.statistic))
                try:
                    beta, *_ = np.linalg.lstsq(np.column_stack([np.ones(len(pb)), mo]), pb, rcond=None)
                    resid = pb - beta[0] - mo * beta[1]
                except np.linalg.LinAlgError:
                    continue
                rr = spearmanr(resid, fr)
                if not np.isnan(rr.statistic): ric_recs.append(float(rr.statistic))
            resid_ic[hn][p] = {
                "ic": {"n": len(ic_recs),
                       "mean": round(float(np.mean(ic_recs)), 5) if ic_recs else None,
                       "t": round(float(np.mean(ic_recs) / (np.std(ic_recs, ddof=1) / np.sqrt(len(ic_recs)))), 3)
                            if len(ic_recs) > 1 and np.std(ic_recs, ddof=1) > 0 else None},
                "residIC_mom60": {"n": len(ric_recs),
                       "mean": round(float(np.mean(ric_recs)), 5) if ric_recs else None,
                       "t": round(float(np.mean(ric_recs) / (np.std(ric_recs, ddof=1) / np.sqrt(len(ric_recs)))), 3)
                            if len(ric_recs) > 1 and np.std(ric_recs, ddof=1) > 0 else None},
            }
            print(f"  {hn} {p}: IC={resid_ic[hn][p]['ic']}  resid|mom60={resid_ic[hn][p]['residIC_mom60']}")
    result["residualIC"] = resid_ic
    result["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "kr-pbr-incremental-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()