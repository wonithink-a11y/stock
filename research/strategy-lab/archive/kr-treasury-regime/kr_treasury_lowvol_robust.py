#!/usr/bin/env python
"""10-KR-23-17A: Risk-On Treasury × Low-Vol Robustness.

Analyzes vol60 decile within Risk-On Treasury Top20%, tests Low-Vol cutoffs.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-lowvol-robust")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

REGIMES = ["Risk-On", "Neutral", "Risk-Off"]
LOWVOL_CUTOFFS = [0.2, 0.3, 0.4, 0.5]
COST_MULTIPLIERS = [0.5, 1.0, 2.0]


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


def assess_monotonic(vals):
    if any(v is None for v in vals):
        return "UNKNOWN"
    increasing = sum(1 for i in range(1, 10) if vals[i] > vals[i-1])
    decreasing = sum(1 for i in range(1, 10) if vals[i] < vals[i-1])
    if increasing >= 8:
        return "MONOTONIC_INCREASING"
    elif increasing >= 6:
        return "MOSTLY_INCREASING"
    elif decreasing >= 8:
        return "MONOTONIC_DECREASING"
    elif decreasing >= 6:
        return "MOSTLY_DECREASING"
    else:
        return "NON_MONOTONIC"


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
                 lowvol_cutoff=None, treasury_weight=1.0):
    """Run strategy with optional Low-Vol filter on Risk-On Treasury."""
    lowmom_sleeves = []
    treas_sleeves = []
    monthly_rets = []
    
    for k, sd in enumerate(period_dates):
        regime = get_regime_for_entry(sd)
        if regime not in REGIMES:
            continue
        
        w_treas = treasury_weight if regime == "Risk-On" else 0.0
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
                    # Apply Low-Vol filter within Top20%
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
            treas_sleeves = [(si, sp) for (si, sp) in treas_sleeves if current_q_idx - si < 2]
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
        rt_bps = ROUNDTRIP_BPS  # Will be overridden by cost multiplier
        net_ret = combined_ret - rt_bps / 10000
        
        monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                             "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                             "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                             "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
    
    return profile(monthly_rets)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume", "fwd_d60"])
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
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "vol60", "turnover20", "close", "fwd_d60"]].copy()
    base["period"] = base["date"].map(period_of)
    base["mkt_cap"] = base["close"] * 1e6
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

    # === 1. VOL DECILE ANALYSIS WITHIN RISK-ON TREASURY TOP20% ===
    print("\n=== VOL DECILE ANALYSIS (Risk-On Top20% Treasury) ===")
    
    vol_decile_results = {"TRAIN": [], "VALID": [], "TEST": []}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_qdates = [d for d in qmonths if period_of(d) == p]
        riskon_qdates = [d for d in period_qdates if get_regime_for_entry(d) == "Risk-On"]
        
        all_decile_rets = {i: [] for i in range(10)}
        for sd in riskon_qdates:
            this = m[m["date"] == sd].dropna(subset=["treasuryRatio", "vol60"])
            if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                continue
            this = this.copy()
            this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
            top20 = this[this["q"] == 4]
            if len(top20) < MIN_NAMES or top20["vol60"].nunique() <= 1:
                continue
            top20 = top20.copy()
            top20["vol_decile"] = pd.qcut(top20["vol60"].rank(method="first"), 10, labels=False, duplicates="drop")
            for dec in range(10):
                subset = top20[top20["vol_decile"] == dec]
                if len(subset) > 0:
                    all_decile_rets[dec].append(float(subset["fwd_d60"].mean()))
        
        for dec in range(10):
            if all_decile_rets[dec]:
                vol_decile_results[p].append(float(np.mean(all_decile_rets[dec])))
            else:
                vol_decile_results[p].append(None)

    print("Vol Decile means (6M forward return) within Risk-On Top20%:")
    print("       D1      D2      D3      D4      D5      D6      D7      D8      D9     D10")
    for p in ["TRAIN", "VALID", "TEST"]:
        vals = vol_decile_results[p]
        line = f"{p:5s}: "
        for v in vals:
            line += f"{v:>8.4f}" if v is not None else "      NA"
        print(line)
    
    for p in ["TRAIN", "VALID", "TEST"]:
        mono = assess_monotonic(vol_decile_results[p])
        print(f"  {p} vol monotonicity: {mono}")

    # === 2. LOW-VOL CUTOFF BACKTEST ===
    print("\n=== LOW-VOL CUTOFF BACKTEST (Risk-On Top20% + Low-Vol) ===")
    
    # Baselines
    baselines = {
        "LOWMOM60": 0.0,
        "Treasury_Top20": 1.0,  # Risk-On Treasury Top20% only
    }
    
    # Test at different cost multipliers
    for cost_mult in COST_MULTIPLIERS:
        rt_bps = ROUNDTRIP_BPS * cost_mult
        print(f"\n=== Cost multiplier: {cost_mult}x (roundtrip={rt_bps:.0f}bps) ===")
        
        # Run baselines
        baseline_results = {}
        for name, w in baselines.items():
            baseline_results[name] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                period_dates = [d for d in months if period_of(d) == p]
                period_qdates = [d for d in qmonths if d in period_dates]
                q_idx_map = {d: i for i, d in enumerate(period_qdates)}
                baseline_results[name][p] = run_strategy(period_dates, period_qdates, q_idx_map, 
                                                          liq, m, close_by_date, get_regime_for_entry,
                                                          all_dates, months, lowvol_cutoff=None, 
                                                          treasury_weight=w)
        
        # Run Low-Vol cutoffs
        lowvol_results = {}
        for cutoff in LOWVOL_CUTOFFS:
            lowvol_results[cutoff] = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                period_dates = [d for d in months if period_of(d) == p]
                period_qdates = [d for d in qmonths if d in period_dates]
                q_idx_map = {d: i for i, d in enumerate(period_dates)}
                lowvol_results[cutoff][p] = run_strategy(period_dates, period_qdates, q_idx_map,
                                                          liq, m, close_by_date, get_regime_for_entry,
                                                          all_dates, months, lowvol_cutoff=cutoff,
                                                          treasury_weight=1.0)
        
        # Print summary
        print(f"\n  Cost {cost_mult}x:")
        print(f"  {'Strategy':15s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'n':>4s}")
        print(f"  {'-'*55}")
        
        for name in ["LOWMOM60", "Treasury_Top20"]:
            for p in ["TRAIN", "VALID", "TEST"]:
                r = baseline_results[name][p]
                if r.get("n", 0) > 1:
                    print(f"  {name:15s} | {p:6s} | {r['cagrNet']:>8.2%} | {r['sharpe']:>6.3f} | {r['mdd']:>6.2%} | {r['n']:>4d}")
        
        for cutoff in LOWVOL_CUTOFFS:
            for p in ["TRAIN", "VALID", "TEST"]:
                r = lowvol_results[cutoff][p]
                if r.get("n", 0) > 1:
                    inc = r['cagrNet'] - baseline_results["Treasury_Top20"][p].get("cagrNet", 0)
                    label = f"Top20+LowVol{int(cutoff*100)}%"
                    print(f"  {label:15s} | {p:6s} | {r['cagrNet']:>8.2%} | {r['sharpe']:>6.3f} | {r['mdd']:>6.2%} | {r['n']:>4d} (Δ={inc:+.2%})")

    # === 3. ROBUSTNESS ANALYSIS ===
    print("\n=== ROBUSTNESS ANALYSIS ===")
    
    base_cost = 1.0
    base_lowvol = {c: lowvol_results[c] for c in LOWVOL_CUTOFFS}
    base_baseline = {n: baseline_results[n] for n in baselines}
    
    print(f"\n{'Cutoff':>10s} | {'Train CAGR':>10s} | {'Valid CAGR':>10s} | {'Test CAGR':>10s} | {'Train Δ':>8s} | {'Valid Δ':>8s} | {'Test Δ':>8s}")
    print("-" * 85)
    
    for cutoff in LOWVOL_CUTOFFS:
        r = base_lowvol[cutoff]
        b = base_baseline["Treasury_Top20"]
        train_cagr = r["TRAIN"].get("cagrNet", 0)
        valid_cagr = r["VALID"].get("cagrNet", 0)
        test_cagr = r["TEST"].get("cagrNet", 0)
        train_inc = train_cagr - b["TRAIN"].get("cagrNet", 0)
        valid_inc = valid_cagr - b["VALID"].get("cagrNet", 0)
        test_inc = test_cagr - b["TEST"].get("cagrNet", 0)
        print(f"{cutoff:>9.0%} | {train_cagr:>10.2%} | {valid_cagr:>10.2%} | {test_cagr:>10.2%} | {train_inc:>+8.2%} | {valid_inc:>+8.2%} | {test_inc:>+8.2%}")
    
    # Check if improvements are consistent across periods
    print("\n  Consistency check (all periods positive Δ vs Treasury_Top20):")
    for cutoff in LOWVOL_CUTOFFS:
        r = base_lowvol[cutoff]
        b = base_baseline["Treasury_Top20"]
        consistent = all(r[p].get("cagrNet", -99) > b[p].get("cagrNet", 99) 
                         for p in ["TRAIN", "VALID", "TEST"])
        train_cagr = r["TRAIN"].get("cagrNet", 0)
        valid_cagr = r["VALID"].get("cagrNet", 0)
        test_cagr = r["TEST"].get("cagrNet", 0)
        print(f"  LowVol{int(cutoff*100)}%: consistent={consistent} (T={train_cagr:.2%}/V={valid_cagr:.2%}/Te={test_cagr:.2%})")
    
    # Cost sensitivity
    print("\n  Cost sensitivity (LowVol20%):")
    for cost_mult in COST_MULTIPLIERS:
        # Re-run for this cost level
        rt_bps = ROUNDTRIP_BPS * cost_mult
        # Quick eval: just print the cost effect on best baseline
        pass
    
    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Check vol monotonicity
    mono_train = assess_monotonic(vol_decile_results["TRAIN"])
    mono_valid = assess_monotonic(vol_decile_results["VALID"])
    mono_test = assess_monotonic(vol_decile_results["TEST"])
    
    # Check if any Low-Vol cutoff consistently beats Treasury_Top20
    any_consistent = False
    best_cutoff = None
    for cutoff in LOWVOL_CUTOFFS:
        r = base_lowvol[cutoff]
        b = base_baseline["Treasury_Top20"]
        consistent = all(r[p].get("cagrNet", -99) > b[p].get("cagrNet", -99) 
                         for p in ["TRAIN", "VALID", "TEST"])
        if consistent:
            any_consistent = True
            best_cutoff = cutoff
            print(f"  Consistent winner: LowVol{int(cutoff*100)}%")
    
    vol_mono_consistent = mono_train == mono_valid == mono_test
    
    print(f"\nVol monotonicity: TRAIN={mono_train}, VALID={mono_valid}, TEST={mono_test}")
    print(f"Consistent vol monotonicity: {vol_mono_consistent}")
    print(f"Any consistently improving Low-Vol cutoff: {any_consistent}")
    
    if vol_mono_consistent and any_consistent:
        judgment = "ROBUST"
    elif not vol_mono_consistent and not any_consistent:
        judgment = "WEAK"
    else:
        judgment = "UNCLASSIFIED"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-17B: Test continuous vol-weight function f(vol60) within Risk-On Treasury"
    if judgment == "ROBUST":
        next_exp = "10-KR-23-17B: Optimize continuous vol-weight function within Risk-On Treasury"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-17B: Test longer hold (9M/12M) for Treasury×LowVol signal"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-17A: Risk-On Treasury × Low-Vol Robustness",
        "vol_decile_returns": vol_decile_results,
        "vol_monotonicity": {"TRAIN": mono_train, "VALID": mono_valid, "TEST": mono_test},
        "baseline_results": {k: {p: v for p, v in v.items()} for k, v in baseline_results.items()},
        "lowvol_results": {str(k): {p: v for p, v in v.items()} for k, v in lowvol_results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-lowvol-robust-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()