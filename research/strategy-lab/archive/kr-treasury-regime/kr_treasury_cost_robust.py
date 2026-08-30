#!/usr/bin/env python
"""10-KR-23-22: Treasury Continuous Weight + Transaction Cost Robustness.

Tests continuous rank weighting with transaction cost sensitivity.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-cost-robust")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

REGIMES = ["Risk-On", "Neutral", "Risk-Off"]
COST_MULTIPLIERS = [0.5, 1.0, 2.0]

# Strategies to test
STRATEGIES = {
    "Equal_Top20": {"type": "rank", "weight_func": "equal", "treasury_weight": 1.0},
    "Linear": {"type": "rank", "weight_func": "linear", "treasury_weight": 1.0},
    "Convex": {"type": "rank", "weight_func": "convex", "treasury_weight": 1.0},
    "Fixed_70": {"type": "fixed", "weight_func": "equal", "treasury_weight": 0.7},
    "Fixed_80": {"type": "fixed", "weight_func": "equal", "treasury_weight": 0.8},
    "Fixed_90": {"type": "fixed", "weight_func": "equal", "treasury_weight": 0.9},
    "Fixed_100": {"type": "fixed", "weight_func": "equal", "treasury_weight": 1.0},
}


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
                 strategy_config, hold_quarters=2, rt_bps=None):
    """Run strategy with given configuration."""
    lowmom_sleeves = []
    treas_sleeves = []
    monthly_rets = []
    
    strategy_type = strategy_config["type"]
    weight_func = strategy_config["weight_func"]
    treasury_weight = strategy_config["treasury_weight"]
    
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
        
        # Treasury sleeve
        if sd in q_idx_map and regime == "Risk-On":
            qk = q_idx_map[sd]
            this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
            if len(this_tres) >= MIN_NAMES:
                this_tres = this_tres.copy()
                this_tres["rank_pct"] = this_tres["treasuryRatio"].rank(method="average", pct=True)
                
                if weight_func == "equal":
                    this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                    top20 = this_tres[this_tres["q"] == 4]
                    top20 = top20.copy()
                    top20["weight"] = 1.0
                elif weight_func == "linear":
                    top20 = this_tres.copy()
                    top20["weight"] = top20["rank_pct"]
                elif weight_func == "convex":
                    top20 = this_tres.copy()
                    top20["weight"] = top20["rank_pct"] ** 2
                else:
                    raise ValueError(f"Unknown weight_func: {weight_func}")
                
                if top20["weight"].sum() > 0:
                    top20["weight"] = top20["weight"] / top20["weight"].sum()
                    picks = top20["ticker"].tolist()
                    weights = top20["weight"].tolist()
                    treas_sleeves.append((qk, picks, weights))
        
        # Remove expired
        lowmom_sleeves = [(si, sp) for (si, sp) in lowmom_sleeves if k - si < 1]
        current_q_idx = q_idx_map.get(sd, -1)
        if regime == "Risk-On":
            treas_sleeves = [(si, sp, sw) for (si, sp, sw) in treas_sleeves if current_q_idx - si < 2]
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
        for _, picks, weights in treas_sleeves:
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if rets:
                valid_picks = [t for t in picks if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if valid_picks:
                    valid_weights = [weights[picks.index(t)] for t in valid_picks]
                    valid_rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in valid_picks]
                    treas_ret = w_treas * float(np.average(valid_rets, weights=valid_weights))
        
        combined_ret = lowmom_ret + treas_ret
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

    # Run all strategies at all cost levels
    all_results = {}
    
    for cost_mult in COST_MULTIPLIERS:
        rt_bps = ROUNDTRIP_BPS * cost_mult
        print(f"\n=== Cost multiplier: {cost_mult}x (roundtrip={rt_bps:.0f}bps) ===")
        
        cost_results = {}
        
        for strat_name, strat_config in STRATEGIES.items():
            strat_results = {}
            
            for p in ["TRAIN", "VALID", "TEST"]:
                period_dates = [d for d in months if period_of(d) == p]
                period_qdates = [d for d in qmonths if d in period_dates]
                q_idx_map = {d: i for i, d in enumerate(period_qdates)}
                
                prof = run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date,
                                    get_regime_for_entry, all_dates, months,
                                    strat_config, hold_quarters=2, rt_bps=rt_bps)
                strat_results[p] = prof
                if prof.get("n", 0) > 1:
                    print(f"  {strat_name} {p}: CAGR={prof['cagrNet']:.2%} Sharpe={prof['sharpe']:.3f} MDD={prof['mdd']:.2%} Turnover={prof['avgAnnualTurnover']:.1f}x n={prof['n']}")
            
            cost_results[strat_name] = strat_results
        
        all_results[cost_mult] = cost_results
    
    # === SUMMARY TABLE ===
    print("\n=== SUMMARY TABLE ===")
    
    base = all_results[1.0]
    equal_top20 = base["Equal_Top20"]
    
    print(f"\n{'Strategy':15s} | {'Cost':6s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s} | {'n':>4s}")
    print("-" * 90)
    for cost_mult in COST_MULTIPLIERS:
        r = all_results[cost_mult]
        for strat_name in STRATEGIES:
            for p in ["TRAIN", "VALID", "TEST"]:
                prof = r[strat_name][p]
                if prof.get("n", 0) > 1:
                    print(f"{strat_name:15s} | {cost_mult:6.1f}x | {p:6s} | {prof['cagrNet']:>8.2%} | {prof['sharpe']:>6.3f} | {prof['mdd']:>6.2%} | {prof['avgAnnualTurnover']:>8.1f}x | {prof['n']:>4d}")
    
    # === INCREMENTAL vs Equal_Top20 ===
    print("\n=== INCREMENTAL vs Equal_Top20 ===")
    for cost_mult in COST_MULTIPLIERS:
        base_equal = all_results[cost_mult]["Equal_Top20"]
        print(f"\n=== Cost {cost_mult}x ===")
        for strat_name in ["Linear", "Convex", "Fixed_70", "Fixed_80", "Fixed_90", "Fixed_100"]:
            if strat_name not in all_results[cost_mult]:
                continue
            print(f"\n{strat_name} vs Equal_Top20 (cost {cost_mult}x):")
            for p in ["TRAIN", "VALID", "TEST"]:
                r = all_results[cost_mult][strat_name][p]
                b = all_results[cost_mult]["Equal_Top20"][p]
                if r.get("n", 0) > 1 and b.get("n", 0) > 1:
                    inc_cagr = r["cagrNet"] - b["cagrNet"]
                    inc_sharpe = (r.get("sharpe", 0) or 0) - (b.get("sharpe", 0) or 0)
                    inc_mdd = r["mdd"] - b["mdd"]
                    inc_turnover = r["avgAnnualTurnover"] - b["avgAnnualTurnover"]
                    print(f"  {p}: ΔCAGR={inc_cagr:+.2%} ΔSharpe={inc_sharpe:+.3f} ΔMDD={inc_mdd:+.2%} ΔTurnover={inc_turnover:+.1f}x")
    
    # === ROBUSTNESS CHECK ===
    print("\n=== ROBUSTNESS: Cost 0.5x → 2.0x ===")
    for strat_name in STRATEGIES:
        print(f"\n{strat_name}:")
        for p in ["TRAIN", "VALID", "TEST"]:
            c05 = all_results[0.5][strat_name][p].get("cagrNet", 0)
            c10 = all_results[1.0][strat_name][p].get("cagrNet", 0)
            c20 = all_results[2.0][strat_name][p].get("cagrNet", 0)
            s05 = all_results[0.5][strat_name][p].get("sharpe", 0)
            s10 = all_results[1.0][strat_name][p].get("sharpe", 0)
            s20 = all_results[2.0][strat_name][p].get("sharpe", 0)
            if c10 and c20:
                cost_impact_cagr = c20 - c10
                cost_impact_sharpe = s20 - s10
                print(f"  {p}: CAGR {c05:.2%}→{c10:.2%}→{c20:.2%} (Δ={c20-c10:+.2%}) Sharpe {s05:.3f}→{s10:.3f}→{s20:.3f} (Δ={s20-s10:+.3f})")
    
    # === VALID/TEST ROBUSTNESS ===
    print("\n=== VALID/TEST ROBUSTNESS CHECK ===")
    for strat_name in STRATEGIES:
        r = all_results[1.0][strat_name]
        valid_prof = r.get("VALID", {})
        test_prof = r.get("TEST", {})
        equal_valid = all_results[1.0]["Equal_Top20"].get("VALID", {})
        equal_test = all_results[1.0]["Equal_Top20"].get("TEST", {})
        
        if valid_prof.get("n", 0) > 1 and test_prof.get("n", 0) > 1:
            valid_inc = valid_prof.get("cagrNet", 0) - equal_valid.get("cagrNet", 0)
            test_inc = test_prof.get("cagrNet", 0) - equal_test.get("cagrNet", 0)
            valid_sharpe_inc = (valid_prof.get("sharpe", 0) or 0) - (equal_valid.get("sharpe", 0) or 0)
            test_sharpe_inc = (test_prof.get("sharpe", 0) or 0) - (equal_test.get("sharpe", 0) or 0)
            print(f"  {strat_name}: Valid ΔCAGR={valid_inc:+.2%} ΔSharpe={valid_sharpe_inc:+.3f} | Test ΔCAGR={test_inc:+.2%} ΔSharpe={test_sharpe_inc:+.3f}")
    
    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Check if any strategy beats Equal_Top20 in both VALID and TEST at 1x cost
    valid_winners = []
    test_winners = []
    both_winners = []
    
    for strat_name in ["Linear", "Convex", "Fixed_70", "Fixed_80", "Fixed_90", "Fixed_100"]:
        if strat_name not in all_results[1.0]:
            continue
        valid_prof = all_results[1.0][strat_name].get("VALID", {})
        test_prof = all_results[1.0][strat_name].get("TEST", {})
        equal_valid = all_results[1.0]["Equal_Top20"].get("VALID", {})
        equal_test = all_results[1.0]["Equal_Top20"].get("TEST", {})
        
        valid_cagr = valid_prof.get("cagrNet", 0)
        test_cagr = test_prof.get("cagrNet", 0)
        equal_valid_cagr = equal_valid.get("cagrNet", 0)
        equal_test_cagr = equal_test.get("cagrNet", 0)
        
        if valid_cagr > equal_valid_cagr + 0.002:  # >0.2% meaningful
            valid_winners.append(strat_name)
        if test_cagr > equal_test_cagr + 0.002:
            test_winners.append(strat_name)
        if valid_cagr > equal_valid_cagr + 0.002 and test_cagr > equal_test_cagr + 0.002:
            both_winners.append(strat_name)
    
    print(f"Valid winners (>0.2%): {valid_winners}")
    print(f"Test winners (>0.2%): {test_winners}")
    print(f"Both winners: {both_winners}")
    
    # Check if any winner survives cost 2x
    robust_winners = []
    for strat_name in both_winners:
        r2 = all_results[2.0][strat_name]
        eq2 = all_results[2.0]["Equal_Top20"]
        valid_cagr2 = r2.get("VALID", {}).get("cagrNet", 0)
        test_cagr2 = r2.get("TEST", {}).get("cagrNet", 0)
        eq_valid2 = eq2.get("VALID", {}).get("cagrNet", 0)
        eq_test2 = eq2.get("TEST", {}).get("cagrNet", 0)
        if valid_cagr2 > eq_valid2 and test_cagr2 > eq_test2:
            robust_winners.append(strat_name)
    
    print(f"Robust winners at 2x cost: {robust_winners}")
    
    # Check if alpha is cost-sensitive
    meaningful_alpha = any(
        all_results[1.0][s]["VALID"].get("cagrNet", 0) - all_results[1.0]["Equal_Top20"]["VALID"].get("cagrNet", 0) > 0.005
        for s in ["Linear", "Convex", "Fixed_70", "Fixed_80", "Fixed_90", "Fixed_100"]
        if s in all_results[1.0]
    )
    
    cost_sensitive = False
    for s in ["Linear", "Convex", "Fixed_70", "Fixed_80", "Fixed_90", "Fixed_100"]:
        if s in all_results[1.0]:
            c10 = all_results[1.0][s].get("TEST", {}).get("cagrNet", 0)
            c20 = all_results[2.0][s].get("TEST", {}).get("cagrNet", 0)
            if c10 and c20 and (c20 - c10) < -0.02:  # >2% CAGR drop when cost doubles
                cost_sensitive = True
    
    if both_winners and robust_winners and not cost_sensitive:
        judgment = "KEEP - Robust alpha across cost levels"
    elif both_winners and cost_sensitive:
        judgment = "HOLD - Alpha exists but cost-sensitive"
    elif any(test_winners) and not both_winners:
        judgment = "HOLD - Only TEST improvement"
    elif not test_winners:
        judgment = "REJECT - No meaningful improvement in TEST"
    else:
        judgment = "UNCLASSIFIED"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-23: Test regime-dependent fixed weights with cost optimization"
    if judgment == "KEEP":
        next_exp = "10-KR-23-23: Optimize fixed weights per regime with cost awareness"
    elif judgment == "HOLD":
        next_exp = "10-KR-23-23: Test cost-aware continuous weight functions"
    elif judgment == "REJECT":
        next_exp = "10-KR-23-23: Re-evaluate Equal Top20 as optimal"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-22: Treasury Continuous Weight + Transaction Cost Robustness",
        "strategies": list(STRATEGIES.keys()),
        "results": {str(cm): {k: {p: v for p, v in d.items()} for k, d in v.items()} for cm, v in all_results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-cost-robust-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()