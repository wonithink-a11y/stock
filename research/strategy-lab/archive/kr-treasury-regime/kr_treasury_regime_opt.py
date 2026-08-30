#!/usr/bin/env python
"""10-KR-23-14: Regime Weight Optimization (Optimized).

Pre-computes sleeve returns, then applies weight grid.
"""
import gzip
import json
import os
import time
from itertools import product

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-regime-opt")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

TREASURY_WEIGHTS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
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
    
    # For each period, compute month-by-month LOWMOM60 and Treasury sleeve returns
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

    # === GRID SEARCH ===
    weight_combos = list(product(TREASURY_WEIGHTS, repeat=3))
    print(f"Total combinations: {len(weight_combos)}")
    
    train_results = []
    best_train_cagr = -np.inf
    best_weights = None
    
    # Pre-compute LOWMOM60 baseline monthly returns for TRAIN
    lm_returns_train = [x["lowmom_ret"] for x in sleeve_data["TRAIN"] if x["lowmom_active"]]
    lm_prof_train = profile([{"ret": r - ROUNDTRIP_BPS/10000, "gross_ret": r} for r in lm_returns_train])
    lm_cagr_train = lm_prof_train.get("cagrNet", -np.inf)
    
    for i, (w_ro, w_neu, w_roff) in enumerate(weight_combos):
        weights = {"Risk-On": w_ro, "Neutral": w_neu, "Risk-Off": w_roff}
        
        # Apply weights to pre-computed sleeve returns
        monthly_rets = []
        for x in sleeve_data["TRAIN"]:
            w_treas = weights[x["regime"]]
            w_lowmom = 1.0 - w_treas
            comb_ret = w_lowmom * x["lowmom_ret"] + w_treas * x["treas_ret"]
            net_ret = comb_ret - ROUNDTRIP_BPS / 10000
            monthly_rets.append({"ret": net_ret, "gross_ret": comb_ret,
                                 "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                 "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                 "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
        
        prof = profile(monthly_rets)
        cagr = prof.get("cagrNet", -np.inf)
        
        train_results.append({
            "weights": weights,
            "cagr": cagr,
            "sharpe": prof.get("sharpe"),
            "mdd": prof.get("mdd"),
            "turnover": prof.get("avgAnnualTurnover"),
            "n": prof.get("n")
        })
        
        if cagr > best_train_cagr:
            best_train_cagr = cagr
            best_weights = weights
        
        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1}/{len(weight_combos)}")

    train_results.sort(key=lambda x: x["cagr"], reverse=True)
    print(f"\nBest TRAIN: RO={best_weights['Risk-On']:.0%} Neu={best_weights['Neutral']:.0%} ROff={best_weights['Risk-Off']:.0%} CAGR={best_train_cagr:.2%}")

    # === EVALUATE BEST ON ALL PERIODS ===
    def eval_weights(weights, period):
        monthly_rets = []
        for x in sleeve_data[period]:
            w_treas = weights[x["regime"]]
            w_lowmom = 1.0 - w_treas
            comb_ret = w_lowmom * x["lowmom_ret"] + w_treas * x["treas_ret"]
            net_ret = comb_ret - ROUNDTRIP_BPS / 10000
            monthly_rets.append({"ret": net_ret, "gross_ret": comb_ret,
                                 "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                 "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                 "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
        return profile(monthly_rets)
    
    # Baselines
    baselines = {
        "LOWMOM60": {"Risk-On": 0.0, "Neutral": 0.0, "Risk-Off": 0.0},
        "50_50": {"Risk-On": 0.5, "Neutral": 0.5, "Risk-Off": 0.5},
        "70_30": {"Risk-On": 0.7, "Neutral": 0.5, "Risk-Off": 0.3},
    }
    
    # Evaluate
    best_results = {p: eval_weights(best_weights, p) for p in ["TRAIN", "VALID", "TEST"]}
    baseline_results = {name: {p: eval_weights(w, p) for p in ["TRAIN", "VALID", "TEST"]} 
                        for name, w in baselines.items()}
    
    # === SUMMARY ===
    print("\n=== PERFORMANCE SUMMARY ===")
    print(f"{'Strategy':25s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s} | {'n':>4s}")
    print("-" * 80)
    
    for name in ["LOWMOM60", "50_50", "70_30", "OPTIMAL"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            if name == "OPTIMAL":
                r = best_results[p]
                w = best_weights
            else:
                r = baseline_results[name][p]
                w = baselines[name]
            
            if r.get("n", 0) > 1:
                label = name if name != "OPTIMAL" else f"OPT(RO={w['Risk-On']:.0%}/N={w['Neutral']:.0%}/R={w['Risk-Off']:.0%})"
                print(f"{label:25s} | {p:6s} | {r.get('cagrNet',0):>8.2%} | {r.get('sharpe',0):>6.3f} | "
                      f"{r.get('mdd',0):>6.2%} | {r.get('avgAnnualTurnover',0):>8.1f}x | {r.get('n',0):>4d}")

    # === Incremental vs LOWMOM60 ===
    print("\n=== INCREMENTAL vs LOWMOM60 ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        lm = baseline_results["LOWMOM60"][p]
        opt = best_results[p]
        b50 = baseline_results["50_50"][p]
        b70 = baseline_results["70_30"][p]
        
        if lm.get("n", 0) > 1 and opt.get("n", 0) > 1:
            print(f"\n{p}:")
            for label, r in [("OPTIMAL", opt), ("70_30", b70), ("50_50", b50)]:
                inc_cagr = r.get("cagrNet", 0) - lm.get("cagrNet", 0)
                inc_sharpe = (r.get("sharpe", 0) or 0) - (lm.get("sharpe", 0) or 0)
                inc_mdd = r.get("mdd", 0) - lm.get("mdd", 0)
                print(f"  {label}: ΔCAGR={inc_cagr:+.2%} ΔSharpe={inc_sharpe:+.3f} ΔMDD={inc_mdd:+.2%}")

    # === TRAIN Top 10 OOS ===
    print("\n=== TOP 10 TRAIN: OOS PERFORMANCE ===")
    print(f"{'Rank':4s} | {'Weights':20s} | {'Train CAGR':>10s} | {'Valid CAGR':>10s} | {'Test CAGR':>10s} | {'Consistent':>10s}")
    print("-" * 80)
    
    for j, r in enumerate(train_results[:10]):
        weights = r["weights"]
        valid_prof = eval_weights(weights, "VALID")
        test_prof = eval_weights(weights, "TEST")
        
        train_cagr = r["cagr"]
        valid_cagr = valid_prof.get("cagrNet", 0)
        test_cagr = test_prof.get("cagrNet", 0)
        
        signs = [train_cagr > 0, valid_cagr > 0, test_cagr > 0]
        consistent = all(signs) or not any(signs)
        
        w_str = f"RO={weights['Risk-On']:.0%}/N={weights['Neutral']:.0%}/R={weights['Risk-Off']:.0%}"
        print(f"{j+1:4d} | {w_str:20s} | {train_cagr:>10.2%} | {valid_cagr:>10.2%} | {test_cagr:>10.2%} | {'YES' if consistent else 'NO':>10s}")

    # === Sample sizes ===
    print("\n=== REGIME SAMPLE SIZES ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        counts = {r: 0 for r in REGIMES}
        for x in sleeve_data[p]:
            if x["regime"] in counts:
                counts[x["regime"]] += 1
        print(f"  {p}: Risk-On={counts['Risk-On']}, Neutral={counts['Neutral']}, Risk-Off={counts['Risk-Off']}")

    # === Final Judgment ===
    print("\n=== FINAL JUDGMENT ===")
    opt_train = best_results["TRAIN"]
    opt_valid = best_results["VALID"]
    opt_test = best_results["TEST"]
    lm_train = baseline_results["LOWMOM60"]["TRAIN"]
    lm_valid = baseline_results["LOWMOM60"]["VALID"]
    lm_test = baseline_results["LOWMOM60"]["TEST"]
    b70_valid = baseline_results["70_30"]["VALID"]
    b70_test = baseline_results["70_30"]["TEST"]
    
    train_beats = opt_train.get("cagrNet", -np.inf) > lm_train.get("cagrNet", -np.inf)
    valid_beats = opt_valid.get("cagrNet", -np.inf) > lm_valid.get("cagrNet", -np.inf)
    test_beats = opt_test.get("cagrNet", -np.inf) > lm_test.get("cagrNet", -np.inf)
    better_70_valid = opt_valid.get("cagrNet", -np.inf) > b70_valid.get("cagrNet", -np.inf)
    better_70_test = opt_test.get("cagrNet", -np.inf) > b70_test.get("cagrNet", -np.inf)
    
    print(f"OPTIMAL weights: RO={best_weights['Risk-On']:.0%} Neu={best_weights['Neutral']:.0%} ROff={best_weights['Risk-Off']:.0%}")
    print(f"TRAIN beats LOWMOM60: {train_beats}")
    print(f"VALID beats LOWMOM60: {valid_beats}")
    print(f"TEST beats LOWMOM60: {test_beats}")
    print(f"VALID beats 70/30: {better_70_valid}")
    print(f"TEST beats 70/30: {better_70_test}")

    if train_beats and valid_beats and test_beats and better_70_valid and better_70_test:
        judgment = "PASS"
    elif train_beats and (valid_beats or test_beats):
        judgment = "WEAK"
    elif not train_beats:
        judgment = "REJECT"
    else:
        judgment = "UNCLASSIFIED"

    print(f"\n>>> JUDGMENT: {judgment} <<<")

    next_exp = "10-KR-23-15: Test continuous regime weights with transaction cost sensitivity"
    if judgment.startswith("PASS"):
        next_exp = "10-KR-23-15: Test continuous regime weights (not discrete grid)"
    elif judgment.startswith("REJECT"):
        next_exp = "10-KR-23-15: Re-evaluate regime definitions"

    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-14: Regime weight optimization",
        "best_weights": best_weights,
        "train_top10": train_results[:10],
        "best_results": {p: prof for p, prof in best_results.items()},
        "baseline_results": {name: {p: prof for p, prof in res.items()} for name, res in baseline_results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-regime-opt-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()