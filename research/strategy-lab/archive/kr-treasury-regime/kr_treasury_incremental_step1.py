#!/usr/bin/env python
"""10-KR-23-24 STEP 1: TreasuryRatio Incremental Portfolio Test.

Tests 3 strategies:
1. LOWMOM60 baseline
2. Treasury Top20% baseline
3. LOWMOM 3-bucket × Treasury High50% (incremental)
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-30-kr-treasury-incremental")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

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


def run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date,
                 get_regime_for_entry, all_dates, months,
                 strategy_name, hold_quarters=2, rt_bps=None):
    """Run one of the 3 strategies."""
    lowmom_sleeves = []
    treas_sleeves = []
    monthly_rets = []
    
    for k, sd in enumerate(period_dates):
        regime = get_regime_for_entry(sd)
        if regime not in REGIMES:
            continue
        
        # Strategy 1: LOWMOM60 only
        if strategy_name == "LOWMOM60":
            w_treas = 0.0
            w_lowmom = 1.0
        # Strategy 2: Treasury Top20% only
        elif strategy_name == "Treasury_Top20":
            w_treas = 1.0 if regime == "Risk-On" else 0.0
            w_lowmom = 1.0 - w_treas
        # Strategy 3: LOWMOM 3-bucket × Treasury High50%
        elif strategy_name == "LOWMOM_Treasury_High50":
            w_treas = 1.0 if regime == "Risk-On" else 0.0
            w_lowmom = 1.0 - w_treas
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")
        
        # LOWMOM60 sleeve (monthly rebal, top 30 lowest mom60)
        this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
        if len(this_low) >= TOP_N:
            this_low = this_low.sort_values("mom60").head(TOP_N)
            lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
        
        # Treasury sleeve (quarterly, 6M hold = 2 quarters)
        if sd in q_idx_map and regime == "Risk-On":
            qk = q_idx_map[sd]
            this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
            if len(this_tres) >= MIN_NAMES:
                if strategy_name == "Treasury_Top20":
                    # Top 20% (Top quintile)
                    this_tres = this_tres.copy()
                    this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                    picks = this_tres[this_tres["q"] == 4]["ticker"].tolist()
                elif strategy_name == "LOWMOM_Treasury_High50":
                    # LOWMOM 3-bucket × Treasury High50%
                    this_tres = this_tres.copy()
                    this_tres["mom_bucket"] = pd.qcut(this_tres["mom60"].rank(method="first"), 3, labels=[0, 1, 2], duplicates="drop")
                    this_tres["treas_pct"] = this_tres["treasuryRatio"].rank(method="average", pct=True)
                    # Top 50% treasury within each LOWMOM bucket
                    picks_list = []
                    for bucket in [0, 1, 2]:
                        bucket_stocks = this_tres[this_tres["mom_bucket"] == bucket]
                        if len(bucket_stocks) > 0:
                            top50 = bucket_stocks[bucket_stocks["treas_pct"] >= 0.5]
                            picks_list.extend(top50["ticker"].tolist())
                    picks = picks_list
                else:
                    picks = []
                
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

    strategies = ["LOWMOM60", "Treasury_Top20", "LOWMOM_Treasury_High50"]
    results = {s: {} for s in strategies}
    
    for strat_name in strategies:
        print(f"\n=== Strategy: {strat_name} ===")
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            prof = run_strategy(period_dates, period_qdates, q_idx_map, liq, m, close_by_date,
                                get_regime_for_entry, all_dates, months,
                                strategy_name=strat_name, hold_quarters=2, rt_bps=ROUNDTRIP_BPS)
            results[strat_name][p] = prof
            if prof.get("n", 0) > 1:
                print(f"  {p}: CAGR={prof['cagrNet']:.2%} Sharpe={prof['sharpe']:.3f} MDD={prof['mdd']:.2%} Turnover={prof['avgAnnualTurnover']:.1f}x n={prof['n']}")

    # === SUMMARY TABLE ===
    print("\n=== SUMMARY TABLE ===")
    print(f"{'Strategy':25s} | {'Period':6s} | {'CAGR':>8s} | {'Sharpe':>6s} | {'MDD':>6s} | {'Turnover':>8s} | {'n':>4s}")
    print("-" * 85)
    for strat_name in strategies:
        for p in ["TRAIN", "VALID", "TEST"]:
            r = results[strat_name][p]
            if r.get("n", 0) > 1:
                print(f"{strat_name:25s} | {p:6s} | {r['cagrNet']:>8.2%} | {r['sharpe']:>6.3f} | {r['mdd']:>6.2%} | {r['avgAnnualTurnover']:>8.1f}x | {r['n']:>4d}")

    # === INCREMENTAL vs LOWMOM60 ===
    print("\n=== INCREMENTAL vs LOWMOM60 ===")
    lowmom = results["LOWMOM60"]
    for strat_name in ["Treasury_Top20", "LOWMOM_Treasury_High50"]:
        print(f"\n{strat_name} vs LOWMOM60:")
        for p in ["TRAIN", "VALID", "TEST"]:
            r = results[strat_name][p]
            b = lowmom[p]
            if r.get("n", 0) > 1 and b.get("n", 0) > 1:
                inc_cagr = r["cagrNet"] - b["cagrNet"]
                inc_sharpe = (r.get("sharpe", 0) or 0) - (b.get("sharpe", 0) or 0)
                inc_mdd = r["mdd"] - b["mdd"]
                inc_turnover = r["avgAnnualTurnover"] - b["avgAnnualTurnover"]
                print(f"  {p}: ΔCAGR={inc_cagr:+.2%} ΔSharpe={inc_sharpe:+.3f} ΔMDD={inc_mdd:+.2%} ΔTurnover={inc_turnover:+.1f}x")

    # === INCREMENTAL vs Treasury_Top20 ===
    print("\n=== INCREMENTAL vs Treasury_Top20 ===")
    treasury = results["Treasury_Top20"]
    for strat_name in ["LOWMOM_Treasury_High50"]:
        print(f"\n{strat_name} vs Treasury_Top20:")
        for p in ["TRAIN", "VALID", "TEST"]:
            r = results[strat_name][p]
            b = treasury[p]
            if r.get("n", 0) > 1 and b.get("n", 0) > 1:
                inc_cagr = r["cagrNet"] - b["cagrNet"]
                inc_sharpe = (r.get("sharpe", 0) or 0) - (b.get("sharpe", 0) or 0)
                inc_mdd = r["mdd"] - b["mdd"]
                inc_turnover = r["avgAnnualTurnover"] - b["avgAnnualTurnover"]
                print(f"  {p}: ΔCAGR={inc_cagr:+.2%} ΔSharpe={inc_sharpe:+.3f} ΔMDD={inc_mdd:+.2%} ΔTurnover={inc_turnover:+.1f}x")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    lowmom = results["LOWMOM60"]
    treasury = results["Treasury_Top20"]
    incremental = results["LOWMOM_Treasury_High50"]
    
    # Check if incremental beats both baselines in TEST
    test_inc_vs_lowmom = incremental["TEST"].get("cagrNet", -99) - lowmom["TEST"].get("cagrNet", -99)
    test_inc_vs_treasury = incremental["TEST"].get("cagrNet", -99) - treasury["TEST"].get("cagrNet", -99)
    test_sharpe_inc_vs_lowmom = (incremental["TEST"].get("sharpe", 0) or 0) - (lowmom["TEST"].get("sharpe", 0) or 0)
    test_sharpe_inc_vs_treasury = (incremental["TEST"].get("sharpe", 0) or 0) - (treasury["TEST"].get("sharpe", 0) or 0)
    
    # Check TRAIN/VALID direction
    train_inc_vs_lowmom = incremental["TRAIN"].get("cagrNet", -99) - lowmom["TRAIN"].get("cagrNet", -99)
    valid_inc_vs_lowmom = incremental["VALID"].get("cagrNet", -99) - lowmom["VALID"].get("cagrNet", -99)
    
    print(f"TEST vs LOWMOM60: ΔCAGR={test_inc_vs_lowmom:+.2%} ΔSharpe={test_sharpe_inc_vs_lowmom:+.3f}")
    print(f"TEST vs Treasury_Top20: ΔCAGR={test_inc_vs_treasury:+.2%} ΔSharpe={test_sharpe_inc_vs_treasury:+.3f}")
    print(f"TRAIN vs LOWMOM60: ΔCAGR={train_inc_vs_lowmom:+.2%}")
    print(f"VALID vs LOWMOM60: ΔCAGR={valid_inc_vs_lowmom:+.2%}")
    
    # Judgment criteria
    test_beats_both = (test_inc_vs_lowmom > 0.002 and test_inc_vs_treasury > 0.002)
    train_valid_consistent = (train_inc_vs_lowmom > -0.01 and valid_inc_vs_lowmom > -0.01)
    
    if test_beats_both and train_valid_consistent:
        judgment = "YES"
    elif test_inc_vs_lowmom > 0.002 or test_inc_vs_treasury > 0.002:
        judgment = "PARTIAL"
    else:
        judgment = "NO"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-24 STEP 2: Test Treasury selection sensitivity (Top30/50/70%)"
    if judgment == "YES":
        next_exp = "10-KR-23-24 STEP 2: Test cutoff sensitivity (Top30/50/70%)"
    elif judgment == "PARTIAL":
        next_exp = "10-KR-23-24 STEP 2: Investigate cutoff sensitivity"
    else:
        next_exp = "10-KR-23-24 STEP 2: Test alternative incremental construction"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    result = {
        "experiment": "10-KR-23-24 STEP 1: TreasuryRatio Incremental Portfolio",
        "strategies": list(strategies),
        "results": {k: {p: v for p, v in d.items()} for k, d in results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-incremental-step1-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()