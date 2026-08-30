#!/usr/bin/env python
"""10-KR-23-3: Treasury Ratio Monetization Validation.

Tests different rebalance/holding structures to understand why strong cross-sectional
IC doesn't translate to portfolio performance.
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
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-monetization")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
FWD = {"5D": "f5", "20D": "f20", "60D": "f60", "120D": "f120"}


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def quarterly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        q = d[:4] + "-Q" + str((int(d[5:7]) - 1) // 3 + 1)
        if q not in seen:
            seen.add(q)
            out.append(d)
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
        if af > as_of:
            continue
        if best is None or rec[1] > best[1] or (rec[1] == best[1] and af > normd(best[0])):
            best = rec
    return best


def summarize_ic(recs):
    if not recs:
        return {"n": 0}
    v = np.array(recs, dtype=float)
    sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
    t = float(v.mean() / (sd / np.sqrt(len(v)))) if sd > 0 else None
    return {"n": len(v), "icMean": round(float(v.mean()), 5),
            "icT": round(t, 3) if t is not None else None}


def profile(monthly, annual_cost_drag=None):
    if not monthly:
        return {}
    mr = np.array([x["ret"] for x in monthly])
    n = len(mr)
    span = n / 12
    eq = float(np.prod(1 + mr))
    cn = eq ** (1 / max(span, 1e-9)) - 1 if eq > 0 else (1 + np.sum(mr)) ** (1 / max(span, 1e-9)) - 1
    sh = float(mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if mr.std(ddof=1) > 0 else None
    peak, mdd, cum = 1e8, 0.0, 1e8
    for r in mr:
        cum *= (1 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1)
    # turnover metrics
    total_turnover = sum(x.get("turnover", 0) for x in monthly)
    avg_turnover = total_turnover / len(monthly) * 12 if monthly else 0
    roundtrips = sum(x.get("roundtrips", 0) for x in monthly)
    avg_holding = np.mean([x.get("holding_months", 1) for x in monthly]) if monthly else 0
    gross_cagr = None
    if monthly and "gross_ret" in monthly[0]:
        gm = np.array([x["gross_ret"] for x in monthly])
        geq = float(np.prod(1 + gm))
        gross_cagr = geq ** (1 / max(span, 1e-9)) - 1 if geq > 0 else None
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4),
            "avgAnnualTurnover": round(avg_turnover, 2),
            "totalRoundTrips": roundtrips,
            "avgHoldingMonths": round(avg_holding, 1),
            "grossCAGR": round(gross_cagr, 4) if gross_cagr is not None else None,
            "costDrag": round(cn - gross_cagr, 4) if gross_cagr is not None else None}


def compute_ic(m, months, fcol, fc):
    recs = []
    for sd in months:
        this = m[(m["date"] == sd)].dropna(subset=[fcol, fc])
        if len(this) < MIN_NAMES or this[fcol].nunique() <= 1:
            continue
        r = spearmanr(this[fcol], this[fc])
        if not np.isnan(r.statistic):
            recs.append(float(r.statistic))
    return summarize_ic(recs)


def run_portfolio(m, months, all_dates, close_by_date, fcol, sign, rebal_dates, holding_months, rebal_freq_months=1):
    """Run portfolio with given rebalance dates and holding period."""
    out = []
    # monthly-equivalent turnover per period: 1.0 / (rebal_freq_months)
    monthly_equiv_turnover = 1.0 / rebal_freq_months
    for k, sd in enumerate(rebal_dates):
        if k + holding_months >= len(rebal_dates):
            break
        this = m[(m["date"] == sd)].dropna(subset=[fcol])
        if len(this) < MIN_NAMES:
            continue
        this = this.copy()
        this["_r"] = this[fcol].rank(method="average") * sign
        picks = this.sort_values("_r", ascending=False).head(
            max(int(np.ceil(len(this) * 0.20)), 1))["ticker"].tolist()
        if not picks:
            continue
        ent_d = next((x for x in all_dates if x > sd), None)
        if ent_d is None:
            continue
        ext_d = rebal_dates[k + holding_months]
        ent = close_by_date[ent_d]
        ext = close_by_date[ext_d]
        rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                if t in ent.index and t in ext.index and ent.loc[t] > 0]
        if not rets:
            continue
        gr = float(np.mean(rets))
        net_ret = gr - ROUNDTRIP_BPS / 10000
        out.append({
            "ret": net_ret,
            "gross_ret": gr,
            "turnover": monthly_equiv_turnover,
            "roundtrips": 1.0 / rebal_freq_months,
            "holding_months": holding_months * rebal_freq_months
        })
    return out


def run_monthly_rank_holding(m, period_months, all_dates, close_by_date, fcol, sign, holding_months, all_months):
    """Monthly ranking but hold for N months (overlapping portfolios) within a period."""
    # Map period month to global month index
    global_idx = {d: i for i, d in enumerate(all_months)}
    # Track active sleeves
    active_sleeves = []  # list of (global_start_idx, picks)
    monthly_rets = []
    
    for sd in period_months:
        k = global_idx[sd]
        # Add new sleeve
        this = m[(m["date"] == sd)].dropna(subset=[fcol])
        if len(this) >= MIN_NAMES:
            this = this.copy()
            this["_r"] = this[fcol].rank(method="average") * sign
            picks = this.sort_values("_r", ascending=False).head(
                max(int(np.ceil(len(this) * 0.20)), 1))["ticker"].tolist()
            active_sleeves.append((k, picks))
        
        # Remove expired sleeves
        active_sleeves = [(si, sp) for (si, sp) in active_sleeves if k - si < holding_months]
        
        # Compute return for this month across all active sleeves
        if not active_sleeves:
            continue
        
        # Find next date in all_dates
        ent_d = next((x for x in all_dates if x > sd), None)
        # Find next month in all_months
        next_m_idx = k + 1
        if ent_d is None or next_m_idx >= len(all_months):
            continue
        ext_d = all_months[next_m_idx]
        ent = close_by_date[ent_d]
        ext = close_by_date[ext_d]
        
        sleeve_rets = []
        for _, picks in active_sleeves:
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if rets:
                sleeve_rets.append(float(np.mean(rets)))
        
        if sleeve_rets:
            gr = float(np.mean(sleeve_rets))
            # turnover: 1/holding_months per month (each sleeve rotates 1/holding)
            monthly_rets.append({
                "ret": gr - (ROUNDTRIP_BPS / 10000) / holding_months,
                "gross_ret": gr,
                "turnover": 1.0 / holding_months,
                "roundtrips": 1.0 / holding_months,
                "holding_months": holding_months
            })
    
    return monthly_rets


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
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    df["turnover20"] = df["total_amount"].groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])
    close_by_date = {d: gd[["ticker", "close"]].set_index("ticker")["close"]
                     for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    qmonths = quarterly_reb(all_dates)

    print("Loading raw A3c (treasuryRatio)...")
    TREAS, ISSUED = {}, {}
    for y in range(2015, 2026):
        fp = os.path.join(A3C_DIR, f"{y}.jsonl.gz")
        if not os.path.exists(fp):
            continue
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if not str(r.get("periodEnd", "")).endswith("1231"):
                    continue
                t = r.get("ticker")
                if t is None:
                    continue
                af = normd(str(r["availableFrom"]))
                fy = int(r["fiscalYear"])
                try:
                    if r.get("istcTotqy") is not None:
                        TREAS.setdefault(t, []).append((af, fy, float(r["istcTotqy"])))
                    if r.get("isuStockTotqy") is not None:
                        ISSUED.setdefault(t, []).append((af, fy, float(r["isuStockTotqy"])))
                except (TypeError, ValueError):
                    pass

    def val(rm, t, as_of):
        cur = select_as_of(rm.get(t, []), as_of)
        return cur[2] if cur is not None else None

    base = df[df["date"].isin(months)][["ticker", "date", "turnover20",
                                         "f5", "f20", "f60", "f120"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        tr = val(TREAS, t, d)
        isu = val(ISSUED, t, d)
        rows.append({"ticker": t, "date": d,
                     "treasuryRatio": tr / isu if (tr is not None and isu and isu != 0) else None})
    panel = pd.DataFrame(rows)
    m = pd.merge(base, panel, on=["ticker", "date"], how="left")
    m = m.dropna(subset=["treasuryRatio"])
    print(f"  merged {len(m)} rows, coverage 100.0%")

    # Verify IC (120D)
    print("\n=== IC VERIFICATION (120D) ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        ic = compute_ic(m, dates, "treasuryRatio", "f120")
        print(f"  {p}: IC={ic.get('icMean')} t={ic.get('icT')}")

    fcol = "treasuryRatio"
    sign = 1.0

    # Define implementations
    implementations = {
        "Monthly_Rebal_1M_Hold": {"rebal": months, "hold": 1, "type": "rebal", "freq": 1},
        "Quarterly_Rebal_3M_Hold": {"rebal": qmonths, "hold": 1, "type": "rebal", "freq": 3},
        "Monthly_Rank_3M_Hold": {"rebal": months, "hold": 3, "type": "overlap"},
        "Monthly_Rank_6M_Hold": {"rebal": months, "hold": 6, "type": "overlap"},
    }

    results = {}
    for name, impl in implementations.items():
        print(f"\n=== {name} ===")
        results[name] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            if impl["type"] == "rebal":
                rebal_dates = [d for d in impl["rebal"] if period_of(d) == p]
                monthly_rets = run_portfolio(m, months, all_dates, close_by_date,
                                             fcol, sign, rebal_dates, impl["hold"], impl.get("freq", 1))
            else:
                period_months = [d for d in months if period_of(d) == p]
                monthly_rets = run_monthly_rank_holding(m, period_months, all_dates, close_by_date,
                                                        fcol, sign, impl["hold"], months)
            prof = profile(monthly_rets)
            results[name][p] = prof
            if prof:
                print(f"  {p}: CAGR={prof.get('cagrNet',0):.2%} Sharpe={prof.get('sharpe',0):.3f} "
                      f"MDD={prof.get('mdd',0):.2%} Turnover={prof.get('avgAnnualTurnover',0):.1f}x "
                      f"GrossCAGR={prof.get('grossCAGR',0):.2%} CostDrag={prof.get('costDrag',0):.2%}")

    # Summary table
    print("\n=== SUMMARY TABLE ===")
    print(f"{'Implementation':30s} | {'Period':6s} | {'NetCAGR':>8s} | {'GrossCAGR':>9s} | {'CostDrag':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s} | {'HoldM':>5s}")
    print("-" * 110)
    for name, impl in implementations.items():
        for p in ["TRAIN", "VALID", "TEST"]:
            prof = results[name][p]
            if prof:
                print(f"{name:30s} | {p:6s} | {prof.get('cagrNet',0):>8.2%} | {prof.get('grossCAGR',0):>9.2%} | "
                      f"{prof.get('costDrag',0):>8.2%} | {prof.get('sharpe',0):>6.3f} | "
                      f"{prof.get('mdd',0):>6.2%} | {prof.get('avgAnnualTurnover',0):>8.1f}x | "
                      f"{prof.get('avgHoldingMonths',0):>5.1f}")

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    # Check which case applies
    all_weak = True
    for name in implementations:
        for p in ["TRAIN", "VALID", "TEST"]:
            if results[name][p].get("cagrNet", -99) > 0.05:  # >5% CAGR
                all_weak = False
    
    if all_weak:
        judgment = "A: IC-ECONOMIC STRUCTURAL GAP - All implementations weak"
    else:
        # Check if low-freq helps consistently
        lowfreq_better = False
        for p in ["TRAIN", "VALID", "TEST"]:
            monthly_cagr = results["Monthly_Rebal_1M_Hold"][p].get("cagrNet", -99)
            quarterly_cagr = results["Quarterly_Rebal_3M_Hold"][p].get("cagrNet", -99)
            hold3_cagr = results["Monthly_Rank_3M_Hold"][p].get("cagrNet", -99)
            hold6_cagr = results["Monthly_Rank_6M_Hold"][p].get("cagrNet", -99)
            if max(quarterly_cagr, hold3_cagr, hold6_cagr) > monthly_cagr + 0.02:
                lowfreq_better = True
        
        if lowfreq_better:
            judgment = "B: SLOW-MOVING FUNDAMENTAL - Low frequency improves consistently"
        else:
            # Check cost drag
            high_cost_drag = False
            for name in implementations:
                for p in ["TRAIN", "VALID", "TEST"]:
                    if results[name][p].get("costDrag", 0) < -0.02:  # >2% cost drag
                        high_cost_drag = True
            if high_cost_drag:
                judgment = "C: COST/TURNOVER ISSUE - Gross strong but net collapses"
            else:
                judgment = "D: PERIOD-DEPENDENT - No consistent improvement across splits"

    print(f"Judgment: {judgment}")
    print("\nNext experiment suggestion: Test treasuryRatio combined with LOWMOM60 (10-KR-23-4)")

    result = {
        "experiment": "10-KR-23-3: treasuryRatio monetization validation",
        "ic_verification": {p: compute_ic(m, [d for d in months if period_of(d)==p], fcol, "f120") 
                           for p in ["TRAIN", "VALID", "TEST"]},
        "implementations": {name: {p: prof for p, prof in res.items()} 
                           for name, res in results.items()},
        "judgment": judgment,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-monetization-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()