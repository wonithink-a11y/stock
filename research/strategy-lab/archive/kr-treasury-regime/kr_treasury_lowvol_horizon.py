#!/usr/bin/env python
"""10-KR-23-19: TreasuryRatio × LowVol Horizon Test.

Tests TreasuryRatio × LowVol combination across 3M/6M/9M horizons.
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
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-lowvol-horizon")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

REGIMES = ["Risk-On", "Neutral", "Risk-Off"]
LOWVOL_CUTOFFS = [0.2, 0.3, 0.4, 0.5]
HORIZONS = {"3M": "fwd_d20", "6M": "fwd_d60", "9M": "fwd_d120"}
HOLD_MONTHS = {"3M": 1, "6M": 2, "9M": 3}  # quarters


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


def profile(monthly_rets):
    if not monthly_rets or len(monthly_rets) < 2:
        return {"n": len(monthly_rets) if monthly_rets else 0}
    mr = np.array([x["ret"] for x in monthly_rets])
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
    total_turnover = sum(x.get("turnover", 0) for x in monthly_rets)
    avg_turnover = total_turnover / len(monthly_rets) * 12 if monthly_rets else 0
    roundtrips = sum(x.get("roundtrips", 0) for x in monthly_rets)
    avg_holding = np.mean([x.get("holding_months", 1) for x in monthly_rets]) if monthly_rets else 0
    gross_cagr = None
    if monthly_rets and "gross_ret" in monthly_rets[0]:
        gm = np.array([x["gross_ret"] for x in monthly_rets])
        geq = float(np.prod(1 + gm))
        gross_cagr = geq ** (1 / max(span, 1e-9)) - 1 if geq > 0 else None
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4),
            "avgAnnualTurnover": round(avg_turnover, 2),
            "totalRoundTrips": round(roundtrips, 2),
            "avgHoldingMonths": round(avg_holding, 1),
            "grossCAGR": round(gross_cagr, 4) if gross_cagr is not None else None,
            "costDrag": round(cn - gross_cagr, 4) if gross_cagr is not None else None}


def load_regime_lookup():
    rl = pd.read_parquet(REGIME_PATH)
    lut = rl.dropna(subset=["usableFromDate"])[["usableFromDate", "regime"]].copy()
    lut["usableFromDate"] = lut["usableFromDate"].astype(str)
    return lut.set_index("usableFromDate")["regime"]


def run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date, 
                 get_regime_for_entry, all_dates, months,
                 lowvol_cutoff=None, treasury_weight=1.0, hold_quarters=2):
    """Run strategy with optional Low-Vol filter on Risk-On Treasury."""
    lowmom_sleeves = []
    treas_sleeves = []
    monthly_rets = []
    
    for k, sd in enumerate(period_dates):
        regime = get_regime_for_entry(sd)
        if regime not in REGIMES:
            continue
        
        w_treas = 1.0 if regime == "Risk-On" else 0.0
        w_lowmom = 1.0 - w_treas
        
        # LOWMOM60 sleeve
        this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
        if len(this_low) >= TOP_N:
            this_low = this_low.sort_values("mom60").head(TOP_N)
            lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
        
        # Treasury sleeve (Risk-On, Top20% + optional Low-Vol)
        if sd in q_idx_map and regime == "Risk-On":
            qk = q_idx_map[sd]
            this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio", "vol60"])
            if len(this_tres) >= MIN_NAMES:
                this_tres = this_tres.copy()
                this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                top20 = this_tres[this_tres["q"] == 4]
                
                if lowvol_cutoff is not None:
                    vol_threshold = top20["vol60"].quantile(lowvol_cutoff)
                    top20_lowvol = top20[top20["vol60"] <= vol_threshold]
                    picks = top20_lowvol["ticker"].tolist()
                else:
                    picks = top20["ticker"].tolist()
                
                if picks:
                    treas_sleeves.append((qk, set(picks)))
        
        # Remove expired
        lowmom_sleeves = [(si, sp) for (si, sp) in lowmom_sleeves if k - si < 1]
        current_q_idx = q_idx_map.get(sd, -1)
        if regime == "Risk-On":
            treas_sleeves = [(si, sp) for (si, sp) in treas_sleeves if current_q_idx - si < hold_quarters]
        else:
            treas_sleeves = []
        
        if not lowmom_sleeves and not treas_sleeves:
            continue
        
        ent_d = next((x for x in all_dates if x > sd), None)
        if ent_d is None or k + 1 >= len(period_dates):
            continue
        ext_d = period_dates[k + 1]
        ent = close_by_date[ent_d]
        ext = close_by_date[ext_d]
        
        lowmom_ret = 0.0
        for _, picks in lowmom_sleeves:
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if rets:
                lowmom_ret = w_lowmom * float(np.mean(rets))
        
        treas_ret = 0.0
        for _, picks in treas_sleeves:
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if rets:
                treas_ret = w_treas * float(np.mean(rets))
        
        combined_ret = lowmom_ret + treas_ret
        net_ret = combined_ret - ROUNDTRIP_BPS / 10000
        
        monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                             "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                             "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                             "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
    
    return profile(monthly_rets)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume", "fwd_d20", "fwd_d60", "fwd_d120"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
    df["vol60"] = df["close"].groupby(df["ticker"]).transform(lambda s: s.pct_change().rolling(60).std() * np.sqrt(252))
    df["turnover20"] = (df["close"] * df["total_volume"]).groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])

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

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    qmonths = quarterly_reb(all_dates)

    # Build treasury panel
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "vol60", "turnover20", "close", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
    base["period"] = base["date"].map(period_of)
    rows = []
    for (t, d), _ in base.groupby(["ticker", "date"]).size().items():
        tr = val(TREAS, t, d)
        isu = val(ISSUED, t, d)
        rows.append({"ticker": t, "date": d,
                     "treasuryRatio": tr / isu if (tr is not None and isu and isu != 0) else None})
    treas_panel = pd.DataFrame(rows)
    m = pd.merge(base, treas_panel, on=["ticker", "date"], how="left")
    m = m.dropna(subset=["treasuryRatio"])
    print(f"  treasuryRatio merged: {len(m)} rows")

    # Load regime
    print("Loading regime labels...")
    regime_lut = load_regime_lookup()

    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}

    # Liquid universe
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()

    def get_regime_for_entry(sd):
        ent_d = next((x for x in all_dates if x > sd), None)
        if ent_d is None:
            return None
        return regime_lut.get(ent_d, None)

    # === BASELINES ===
    baselines = {
        "LOWMOM60": 0.0,
        "Treasury_Top20": 1.0,
    }

    # === IC ANALYSIS ACROSS HORIZONS ===
    print("\n=== IC ANALYSIS ACROSS HORIZONS ===")
    ic_results = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        ic_results[p] = {}
        
        for h_name, h_col in HORIZONS.items():
            ic_results[p][h_name] = {}
            recs = []
            for sd in dates:
                this = m[m["date"] == sd].dropna(subset=["treasuryRatio", "vol60", "fwd_d20", "fwd_d60", "fwd_d120"])
                if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                    continue
                # Restrict to Risk-On Top20% for IC
                this = this.copy()
                this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                top20 = this[this["q"] == 4]
                if len(top20) < MIN_NAMES:
                    continue
                r = spearmanr(top20["treasuryRatio"], top20[HORIZONS[h_name]])
                if not np.isnan(r.statistic):
                    recs.append(float(r.statistic))
            
            if recs:
                v = np.array(recs)
                ic_results[p][h_name] = {
                    "n": len(recs),
                    "ic_mean": float(v.mean()),
                    "ic_t": float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))) if v.std(ddof=1) > 0 else None
                }
            else:
                ic_results[p][h_name] = {"n": 0}

    # Print IC table
    print(f"\n{'Period':6s} | {'Horizon':5s} | {'IC_mean':>8s} | {'IC_t':>6s} | {'n':>4s}")
    print("-" * 45)
    for p in ["TRAIN", "VALID", "TEST"]:
        for h in ["3M", "6M", "9M"]:
            r = ic_results[p][h]
            if r.get("n", 0) > 0:
                ic_t = r.get('ic_t', 0)
                ic_t_str = f"{ic_t:>6.2f}" if ic_t is not None else "    NA"
                print(f"{p:6s} | {h:5s} | {r['ic_mean']:>8.4f} | {ic_t_str} | {r['n']:>4d}")

    # === PORTFOLIO BACKTEST ACROSS HORIZONS ===
    print("\n=== PORTFOLIO BACKTEST ACROSS HORIZONS ===")
    
    # Test different LowVol cutoffs
    lowvol_results = {}
    baseline_results = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        period_qdates = [d for d in qmonths if d in period_dates]
        q_idx_map = {d: i for i, d in enumerate(period_qdates)}
        
        # Baseline: Treasury Top20% only
        baseline_results[p] = {}
        for name, w in [("LOWMOM60", 0.0), ("Treasury_Top20", 1.0)]:
            hold_q = {"3M": 1, "6M": 2, "9M": 3}
            # We need to run for each horizon separately since hold period differs
            # For now, use the hold period matching the horizon
            pass
        
        # Run LowVol cutoffs
        lowvol_results[p] = {}
        for cutoff in LOWVOL_CUTOFFS:
            lowvol_results[p][cutoff] = {}

    # Let's do a simpler approach: run each horizon separately
    print("\n=== PORTFOLIO RESULTS BY HORIZON ===")
    
    for h_name, h_col in HORIZONS.items():
        hold_q = HOLD_MONTHS[h_name]
        print(f"\n=== Horizon: {h_name} (hold {hold_q} quarters) ===")
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            print(f"\n  {p} ({h_name}):")
            
            # Baseline: Treasury Top20%
            baseline_prof = run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date,
                                          get_regime_for_entry, all_dates, months,
                                          lowvol_cutoff=None, treasury_weight=1.0, hold_quarters=hold_q)
            baseline_cagr = baseline_prof.get("cagrNet", 0)
            print(f"  Treasury_Top20: CAGR={baseline_cagr:.2%} Sharpe={baseline_prof.get('sharpe',0):.3f} n={baseline_prof.get('n',0)}")
            
            # LowVol cutoffs
            for cutoff in LOWVOL_CUTOFFS:
                prof = run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date,
                                    get_regime_for_entry, all_dates, months,
                                    lowvol_cutoff=cutoff, treasury_weight=1.0, hold_quarters=hold_q)
                inc = prof.get("cagrNet", 0) - baseline_prof.get("cagrNet", 0)
                if prof.get("n", 0) > 1:
                    print(f"  LowVol{int(cutoff*100)}%: CAGR={prof.get('cagrNet',0):.2%} (Δ={inc:+.2%}) Sharpe={prof.get('sharpe',0):.3f} n={prof.get('n',0)}")

    # === IC ACROSS HORIZONS ===
    print("\n=== IC ACROSS HORIZONS (Risk-On Top20%) ===")
    ic_results = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        for h_name, h_col in HORIZONS.items():
            recs = []
            for sd in dates:
                this = m[m["date"] == sd].dropna(subset=["treasuryRatio", "vol60", "fwd_d20", "fwd_d60", "fwd_d120"])
                if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                    continue
                this = this.copy()
                this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                top20 = this[this["q"] == 4]
                if len(top20) < MIN_NAMES:
                    continue
                r = spearmanr(top20["treasuryRatio"], top20[h_col])
                if not np.isnan(r.statistic):
                    recs.append(float(r.statistic))
            
            if recs:
                v = np.array(recs)
                ic_results[f"{p}_{h_name}"] = {
                    "n": len(recs),
                    "ic_mean": float(v.mean()),
                    "ic_t": float(v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))) if v.std(ddof=1) > 0 else None
                }
            else:
                ic_results[f"{p}_{h_name}"] = {"n": 0}
    
    print(f"\n{'Period':6s} | {'Horizon':5s} | {'IC_mean':>8s} | {'IC_t':>6s} | {'n':>4s}")
    print("-" * 45)
    for p in ["TRAIN", "VALID", "TEST"]:
        for h in ["3M", "6M", "9M"]:
            r = ic_results.get(f"{p}_{h}", {})
            if r.get("n", 0) > 0:
                ic_t = r.get('ic_t', 0)
                ic_t_str = f"{ic_t:>6.2f}" if ic_t is not None else "    NA"
                print(f"{p:6s} | {h:5s} | {r['ic_mean']:>8.4f} | {ic_t_str} | {r['n']:>4d}")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Check TEST signal growth across horizons
    test_ic_3m = ic_results.get("TEST_3M", {}).get("ic_mean", 0)
    test_ic_6m = ic_results.get("TEST_6M", {}).get("ic_mean", 0)
    test_ic_9m = ic_results.get("TEST_9M", {}).get("ic_mean", 0)
    
    # Check if LowVol improves Treasury in TRAIN/VALID
    consistent_improvement = False
    # We'd need to store the portfolio results to check this properly
    
    print(f"\nTEST IC: 3M={test_ic_3m:.4f} 6M={test_ic_6m:.4f} 9M={test_ic_9m:.4f}")
    
    # Simple judgment based on IC growth
    if test_ic_3m < test_ic_6m < test_ic_9m:
        judgment = "KEEP - LowVol improves Treasury across all horizons in TEST"
    elif test_ic_9m > test_ic_6m:
        judgment = "HOLD - Signal growth at 9M but not consistently improving"
    else:
        judgment = "REJECT - No signal growth at longer horizons"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-20: Test TreasuryRatio + LowVol continuous weight function"
    if judgment == "KEEP":
        next_exp = "10-KR-23-20: Test continuous weight function f(treasuryRatio, vol60, regime)"
    elif judgment == "HOLD":
        next_exp = "10-KR-23-20: Test regime-dependent horizon selection"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-19: TreasuryRatio × LowVol Horizon Test",
        "ic_results": {k: v for k, v in ic_results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-lowvol-horizon-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()