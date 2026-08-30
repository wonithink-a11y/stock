#!/usr/bin/env python
"""10-KR-23-15A: Risk-On Treasury Weight Robustness.

Tests Risk-On Treasury weight 40-100% with Neutral=0%, Risk-Off=0% fixed.
Includes cost sensitivity at 0.5x, 1x, 2x.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-ro-weight-robust")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

RO_WEIGHTS = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
COST_MULTIPLIERS = [0.5, 1.0, 2.0]
REGIMES = ["Risk-On", "Neutral", "Risk-Off"]


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


def profile(monthly_rets, roundtrip_bps):
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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...")
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers")

    g = df.groupby("ticker", sort=False)["close"]
    df["mom60"] = g.pct_change(60)
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
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20", "close"]].copy()
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

    # === PRE-COMPUTE MONTHLY SLEEVE RETURNS ===
    print("Pre-computing sleeve returns...")
    
    sleeve_data = {"TRAIN": [], "VALID": [], "TEST": []}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        period_qdates = [d for d in qmonths if d in period_dates]
        q_idx_map = {d: i for i, d in enumerate(period_qdates)}
        
        lowmom_sleeves = []
        treas_sleeves = []
        
        for k, sd in enumerate(period_dates):
            regime = get_regime_for_entry(sd)
            if regime not in REGIMES:
                continue
            
            # LOWMOM60 sleeve (monthly)
            this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
            if len(this_low) >= TOP_N:
                this_low = this_low.sort_values("mom60").head(TOP_N)
                lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
            
            # Treasury sleeve (quarterly, 6M = 2 quarters)
            if sd in q_idx_map:
                qk = q_idx_map[sd]
                this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                if len(this_tres) >= MIN_NAMES:
                    this_tres = this_tres.copy()
                    this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                    picks = this_tres[this_tres["q"] == 4]["ticker"].tolist()
                    if picks:
                        treas_sleeves.append((qk, set(picks)))
            
            # Remove expired
            lowmom_sleeves = [(si, sp) for (si, sp) in lowmom_sleeves if k - si < 1]
            current_q_idx = q_idx_map.get(sd, -1)
            treas_sleeves = [(si, sp) for (si, sp) in treas_sleeves if current_q_idx - si < 2]
            
            if not lowmom_sleeves and not treas_sleeves:
                continue
            
            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None or k + 1 >= len(period_dates):
                continue
            ext_d = period_dates[k + 1]
            ent = close_by_date[ent_d]
            ext = close_by_date[ext_d]
            
            # LOWMOM60 sleeve return (100% weight)
            lowmom_ret = 0.0
            for _, picks in lowmom_sleeves:
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if rets:
                    lowmom_ret = float(np.mean(rets))
            
            # Treasury sleeve return (100% weight)
            treas_ret = 0.0
            for _, picks in treas_sleeves:
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if rets:
                    treas_ret = float(np.mean(rets))
            
            sleeve_data[p].append({
                "month": sd,
                "regime": regime,
                "lowmom_ret": lowmom_ret,
                "treas_ret": treas_ret,
                "lowmom_active": len(lowmom_sleeves) > 0,
                "treas_active": len(treas_sleeves) > 0,
            })

    # === TEST WEIGHTS ===
    print("\n=== RISK-ON TREASURY WEIGHT ROBUSTNESS ===")
    
    baselines = {
        "LOWMOM60": 0.0,
        "50_50": 0.5,
        "70_30": 0.7,
    }
    
    # Test at different cost multipliers
    all_results = {}
    
    for cost_mult in COST_MULTIPLIERS:
        rt_bps = ROUNDTRIP_BPS * cost_mult
        print(f"\n=== Cost multiplier: {cost_mult}x (roundtrip={rt_bps:.0f}bps) ===")
        
        cost_results = {"baselines": {}, "ro_weights": {}}
        
        # Baselines
        for name, ro_w in baselines.items():
            weights = {"Risk-On": ro_w, "Neutral": 0.0, "Risk-Off": 0.0}
            baseline_results = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                monthly_rets = []
                for x in sleeve_data[p]:
                    w_treas = weights[x["regime"]]
                    w_lowmom = 1.0 - w_treas
                    comb_ret = w_lowmom * x["lowmom_ret"] + w_treas * x["treas_ret"]
                    net_ret = comb_ret - rt_bps / 10000
                    monthly_rets.append({"ret": net_ret, "gross_ret": comb_ret,
                                         "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                         "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                         "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
                baseline_results[p] = profile(monthly_rets, rt_bps)
            cost_results["baselines"][name] = baseline_results
        
        # Risk-On weights 40-100%
        for ro_w in RO_WEIGHTS:
            weights = {"Risk-On": ro_w, "Neutral": 0.0, "Risk-Off": 0.0}
            ro_results = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                monthly_rets = []
                for x in sleeve_data[p]:
                    w_treas = weights[x["regime"]]
                    w_lowmom = 1.0 - w_treas
                    comb_ret = w_lowmom * x["lowmom_ret"] + w_treas * x["treas_ret"]
                    net_ret = comb_ret - rt_bps / 10000
                    monthly_rets.append({"ret": net_ret, "gross_ret": comb_ret,
                                         "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                         "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                         "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
                ro_results[p] = profile(monthly_rets, rt_bps)
            cost_results["ro_weights"][ro_w] = ro_results
        
        all_results[cost_mult] = cost_results
        
        # Print summary for this cost level
        print(f"\n  Cost {cost_mult}x:")
        print(f"  {'Strategy':12s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s}")
        print(f"  {'-'*55}")
        
        # Baselines
        for name in ["LOWMOM60", "50_50", "70_30"]:
            r = cost_results["baselines"][name]
            for p in ["TRAIN", "VALID", "TEST"]:
                prof = r[p]
                if prof.get("n", 0) > 1:
                    print(f"  {name:12s} | {p:6s} | {prof.get('cagrNet',0):>8.2%} | {prof.get('sharpe',0):>6.3f} | {prof.get('mdd',0):>6.2%} | {prof.get('avgAnnualTurnover',0):>8.1f}x")
        
        # Risk-On weights
        for ro_w in RO_WEIGHTS:
            r = cost_results["ro_weights"][ro_w]
            for p in ["TRAIN", "VALID", "TEST"]:
                prof = r[p]
                if prof.get("n", 0) > 1:
                    label = f"RO={ro_w:.0%}"
                    print(f"  {label:12s} | {p:6s} | {prof.get('cagrNet',0):>8.2%} | {prof.get('sharpe',0):>6.3f} | {prof.get('mdd',0):>6.2%} | {prof.get('avgAnnualTurnover',0):>8.1f}x")
        
        all_results[cost_mult] = cost_results

    # === PLATEAU ANALYSIS ===
    print("\n=== PLATEAU ANALYSIS (1x cost) ===")
    base_cost = all_results[1.0]
    lm = base_cost["baselines"]["LOWMOM60"]
    
    print(f"\n{'Weight':>8s} | {'Train CAGR':>10s} | {'Valid CAGR':>10s} | {'Test CAGR':>10s} | {'Train ΔLM':>10s} | {'Valid ΔLM':>10s} | {'Test ΔLM':>10s}")
    print("-" * 90)
    
    for ro_w in RO_WEIGHTS:
        r = base_cost["ro_weights"][ro_w]
        train_cagr = r["TRAIN"].get("cagrNet", 0)
        valid_cagr = r["VALID"].get("cagrNet", 0)
        test_cagr = r["TEST"].get("cagrNet", 0)
        train_inc = train_cagr - lm["TRAIN"].get("cagrNet", 0)
        valid_inc = valid_cagr - lm["VALID"].get("cagrNet", 0)
        test_inc = test_cagr - lm["TEST"].get("cagrNet", 0)
        print(f"{ro_w:>7.0%} | {train_cagr:>10.2%} | {valid_cagr:>10.2%} | {test_cagr:>10.2%} | {train_inc:>+10.2%} | {valid_inc:>+10.2%} | {test_inc:>+10.2%}")
    
    # Check plateau: is performance relatively flat across 40-100%?
    cagr_vals = [base_cost["ro_weights"][w]["TEST"].get("cagrNet", 0) for w in RO_WEIGHTS]
    cagr_range = max(cagr_vals) - min(cagr_vals)
    print(f"\nTEST CAGR range across 40-100%: {cagr_range:.2%} ({'PLATEAU' if cagr_range < 0.02 else 'SENSITIVE'})")
    
    valid_cagr_vals = [base_cost["ro_weights"][w]["VALID"].get("cagrNet", 0) for w in RO_WEIGHTS]
    valid_range = max(valid_cagr_vals) - min(valid_cagr_vals)
    print(f"VALID CAGR range across 40-100%: {valid_range:.2%} ({'PLATEAU' if valid_range < 0.02 else 'SENSITIVE'})")

    # === COST SENSITIVITY ===
    print("\n=== COST SENSITIVITY (RO=100%) ===")
    ro100 = {cm: all_results[cm]["ro_weights"][1.0] for cm in COST_MULTIPLIERS}
    for cm in COST_MULTIPLIERS:
        r = ro100[cm]
        print(f"  Cost {cm}x: TRAIN={r['TRAIN'].get('cagrNet',0):.2%} VALID={r['VALID'].get('cagrNet',0):.2%} TEST={r['TEST'].get('cagrNet',0):.2%}")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    ro100_1x = base_cost["ro_weights"][1.0]
    ro70_1x = base_cost["ro_weights"][0.7]
    
    # Check if 100% uniquely best or plateau
    test_cagrs = [base_cost["ro_weights"][w]["TEST"].get("cagrNet", 0) for w in RO_WEIGHTS]
    valid_cagrs = [base_cost["ro_weights"][w]["VALID"].get("cagrNet", 0) for w in RO_WEIGHTS]
    train_cagrs = [base_cost["ro_weights"][w]["TRAIN"].get("cagrNet", 0) for w in RO_WEIGHTS]
    
    best_test_idx = np.argmax(test_cagrs)
    best_valid_idx = np.argmax(valid_cagrs)
    best_train_idx = np.argmax(train_cagr_vals := [base_cost["ro_weights"][w]["TRAIN"].get("cagrNet", 0) for w in RO_WEIGHTS])
    
    is_plateau_test = (max(test_cagrs) - min(test_cagrs)) < 0.02
    is_plateau_valid = (max(valid_cagrs) - min(valid_cagrs)) < 0.02
    
    unique_best_test = (best_test_idx == len(RO_WEIGHTS) - 1) and (test_cagrs[-1] - test_cagrs[-2] > 0.005)
    unique_best_valid = (best_valid_idx == len(RO_WEIGHTS) - 1) and (valid_cagrs[-1] - valid_cagrs[-2] > 0.005)
    
    print(f"TEST: max at {RO_WEIGHTS[best_test_idx]:.0%} (range={max(test_cagrs)-min(test_cagrs):.2%}) {'UNIQUE' if unique_best_test else ('PLATEAU' if is_plateau_test else 'MIXED')}")
    print(f"VALID: max at {RO_WEIGHTS[best_valid_idx]:.0%} (range={max(valid_cagrs)-min(valid_cagrs):.2%}) {'UNIQUE' if unique_best_valid else ('PLATEAU' if is_plateau_valid else 'MIXED')}")
    
    if is_plateau_test and is_plateau_valid:
        judgment = "PLATEAU - Broad weight range 40-100% works similarly"
    elif unique_best_test and unique_best_valid:
        judgment = "SENSITIVE - Only 100% works; selection bias risk"
    else:
        judgment = "MIXED - Some sensitivity but not extreme"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-15B: Test Neutral/Risk-Off weights given Risk-On plateau"
    if judgment == "PLATEAU":
        next_exp = "10-KR-23-15B: Test continuous weight function f(signal_strength) instead of discrete grid"
    elif judgment == "SENSITIVE":
        next_exp = "10-KR-23-15B: Investigate why only 100% works (overfit?)"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save results
    result = {
        "experiment": "10-KR-23-15A: Risk-On Treasury weight robustness",
        "cost_sensitivity": {str(cm): {k: {p: prof for p, prof in v.items()} for k, v in all_results[cm].items()} for cm in COST_MULTIPLIERS},
        "plateau_analysis": {
            "test_cagr_range": float(max(test_cagrs) - min(test_cagrs)),
            "valid_cagr_range": float(max(valid_cagrs) - min(valid_cagrs)),
            "is_plateau_test": is_plateau_test,
            "is_plateau_valid": is_plateau_valid,
            "unique_best_test": unique_best_test,
            "unique_best_valid": unique_best_valid,
        },
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-ro-weight-robust-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()