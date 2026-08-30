#!/usr/bin/env python
"""10-KR-23-15B: Risk-On Treasury Signal Strength Analysis.

Analyzes TreasuryRatio decile performance within Risk-On regime.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-ro-signal")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0

REGIMES = ["Risk-On", "Neutral", "Risk-Off"]
RO_WEIGHTS = [0.7, 0.8, 0.9, 1.0]


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
    elif vals[9] > max(vals[:9]) * 1.5:
        return "TAIL_D10_ONLY"
    elif vals[0] < min(vals[1:]) * 1.5:
        return "TAIL_D1_ONLY"
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
    base_all = df[df["date"].isin(months)].copy()
    print(f"  base_all columns: {base_all.columns.tolist()}")
    print(f"  base_all shape: {base_all.shape}")
    base = base_all[["ticker", "date", "mom60", "turnover20", "close", "fwd_d60"]].copy()
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

    # === 1. DECILE ANALYSIS WITHIN RISK-ON (6M forward return) ===
    print("\n=== DECILE ANALYSIS: Risk-On 6M Forward Return ===")
    decile_results = {"TRAIN": [], "VALID": [], "TEST": []}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_qdates = [d for d in qmonths if period_of(d) == p]
        riskon_qdates = [d for d in period_qdates if get_regime_for_entry(d) == "Risk-On"]
        
        all_decile_rets = {i: [] for i in range(10)}
        for sd in riskon_qdates:
            this = m[(m["date"] == sd)].dropna(subset=["treasuryRatio"])
            if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                continue
            this = this.copy()
            this["decile"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 10, labels=False, duplicates="drop")
            for dec in range(10):
                subset = this[this["decile"] == dec]
                if len(subset) > 0:
                    all_decile_rets[dec].append(float(subset["fwd_d60"].mean()))
        
        for dec in range(10):
            if all_decile_rets[dec]:
                decile_results[p].append(float(np.mean(all_decile_rets[dec])))
            else:
                decile_results[p].append(None)

    print("Risk-On Decile means (6M forward return):")
    print("       D1      D2      D3      D4      D5      D6      D7      D8      D9     D10")
    for p in ["TRAIN", "VALID", "TEST"]:
        vals = decile_results[p]
        line = f"{p:5s}: "
        for v in vals:
            line += f"{v:>8.4f}" if v is not None else "      NA"
        print(line)
    
    for p in ["TRAIN", "VALID", "TEST"]:
        mono = assess_monotonic(decile_results[p])
        print(f"  {p} monotonicity: {mono}")

    # === 2. PORTFOLIO PERFORMANCE BY TOP-N (Risk-On only, Neutral/Risk-Off = LOWMOM60) ===
    print("\n=== PORTFOLIO PERFORMANCE BY TOP-N (Risk-On) ===")
    
    # Pre-compute sleeve returns for all regimes
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
            
            # LOWMOM60 sleeve return
            lowmom_ret = 0.0
            for _, picks in lowmom_sleeves:
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if rets:
                    lowmom_ret = float(np.mean(rets))
            
            # Treasury sleeve return
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

    # Test different Top-N within Risk-On
    top_n_pcts = [0.10, 0.20, 0.30, 0.40]
    ro_weight_results = {}
    
    for top_pct in top_n_pcts:
        label = f"Top{int(top_pct*100)}%"
        ro_weight_results[label] = {}
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            lowmom_sleeves = []
            treas_sleeves = []
            monthly_rets = []
            
            for k, sd in enumerate(period_dates):
                regime = get_regime_for_entry(sd)
                if regime not in REGIMES:
                    continue
                
                w_treas = 1.0 if regime == "Risk-On" else 0.0
                w_lowmom = 1.0 - w_treas
                
                # Add LOWMOM60 sleeve
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
                # Add Treasury sleeve (Top-N within Risk-On)
                if sd in q_idx_map and regime == "Risk-On":
                    qk = q_idx_map[sd]
                    this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                    if len(this_tres) >= MIN_NAMES:
                        n_pick = max(int(np.ceil(len(this_tres) * top_pct)), 1)
                        this_tres = this_tres.sort_values("treasuryRatio", ascending=False).head(n_pick)
                        picks = this_tres["ticker"].tolist()
                        if picks:
                            treas_sleeves.append((qk, set(picks)))
                
                # Remove expired
                lowmom_sleeves = [(si, sp) for (si, sp) in lowmom_sleeves if k - si < 1]
                current_q_idx = q_idx_map.get(sd, -1)
                if regime == "Risk-On":
                    treas_sleeves = [(si, sp) for (si, sp) in treas_sleeves if current_q_idx - si < 2]
                else:
                    treas_sleeves = []  # No treasury outside Risk-On
                
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
            
            ro_weight_results[label][p] = profile(monthly_rets)

    # === 3. RISK-ON TREASURY WEIGHT TEST (70/80/90/100%) ===
    print("\n=== RISK-ON TREASURY WEIGHT TEST ===")
    
    weight_results = {}
    for ro_w in RO_WEIGHTS:
        label = f"RO={ro_w:.0%}"
        weight_results[label] = {}
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            lowmom_sleeves = []
            treas_sleeves = []
            monthly_rets = []
            
            for k, sd in enumerate(period_dates):
                regime = get_regime_for_entry(sd)
                if regime not in REGIMES:
                    continue
                
                w_treas = ro_w if regime == "Risk-On" else 0.0
                w_lowmom = 1.0 - w_treas
                
                # Add LOWMOM60 sleeve
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
                # Add Treasury sleeve (Top20% within Risk-On)
                if sd in q_idx_map and regime == "Risk-On":
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
                net_ret = combined_ret - ROUNDTRIP_BPS / 10000
                
                monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                                     "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
            
            weight_results[label][p] = profile(monthly_rets)

    # === 4. TAIL TRIM TEST (Top20%, Risk-On only) ===
    print("\n=== TAIL TRIM TEST (Top20% Risk-On) ===")
    
    trim_results = {}
    for trimmed in [False, True]:
        label = "Trimmed" if trimmed else "Original"
        trim_results[label] = {}
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            lowmom_sleeves = []
            treas_sleeves = []
            monthly_rets = []
            
            for k, sd in enumerate(period_dates):
                regime = get_regime_for_entry(sd)
                if regime not in REGIMES:
                    continue
                
                w_treas = 1.0 if regime == "Risk-On" else 0.0
                w_lowmom = 1.0 - w_treas
                
                # Add LOWMOM60 sleeve
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
                # Add Treasury sleeve (Top20% Risk-On, trimmed)
                if sd in q_idx_map and regime == "Risk-On":
                    qk = q_idx_map[sd]
                    this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                    if len(this_tres) >= MIN_NAMES:
                        if trimmed:
                            lo = this_tres["treasuryRatio"].quantile(0.10)
                            hi = this_tres["treasuryRatio"].quantile(0.90)
                            this_tres = this_tres[(this_tres["treasuryRatio"] > lo) & (this_tres["treasuryRatio"] < hi)]
                        this_tres = this_tres.copy()
                        this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                        picks = this_tres[this_tres["q"] == 4]["ticker"].tolist()
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
                net_ret = combined_ret - ROUNDTRIP_BPS / 10000
                
                monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                                     "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
            
            trim_results[label][p] = profile(monthly_rets)

    # === BASELINES ===
    baselines = {
        "LOWMOM60": {"Risk-On": 0.0, "Neutral": 0.0, "Risk-Off": 0.0},
        "50_50": {"Risk-On": 0.5, "Neutral": 0.5, "Risk-Off": 0.5},
        "70_30": {"Risk-On": 0.7, "Neutral": 0.5, "Risk-Off": 0.3},
        "100_0_0": {"Risk-On": 1.0, "Neutral": 0.0, "Risk-Off": 0.0},
    }
    baseline_results = {}
    for name, w in baselines.items():
        baseline_results[name] = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            lowmom_sleeves = []
            treas_sleeves = []
            monthly_rets = []
            
            for k, sd in enumerate(period_dates):
                regime = get_regime_for_entry(sd)
                if regime not in REGIMES:
                    continue
                
                w_treas = w[regime]
                w_lowmom = 1.0 - w_treas
                
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
                if sd in q_idx_map and regime == "Risk-On":
                    qk = q_idx_map[sd]
                    this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                    if len(this_tres) >= MIN_NAMES:
                        this_tres = this_tres.copy()
                        this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                        picks = this_tres[this_tres["q"] == 4]["ticker"].tolist()
                        if picks:
                            treas_sleeves.append((qk, set(picks)))
                
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
                net_ret = combined_ret - ROUNDTRIP_BPS / 10000
                
                monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                                     "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "holding_months": w_lowmom * 1.0 + w_treas * 6.0})
            
            baseline_results[name][p] = profile(monthly_rets)

    # === PRINT RESULTS ===
    print("\n=== SUMMARY TABLE ===")
    
    # Baselines
    print("\nBaselines:")
    for name in ["LOWMOM60", "50_50", "70_30", "100_0_0"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            r = baseline_results[name][p]
            if r.get("n", 0) > 1:
                print(f"  {name} {p}: CAGR={r['cagrNet']:.2%} Sharpe={r['sharpe']:.3f} MDD={r['mdd']:.2%} Turnover={r['avgAnnualTurnover']:.1f}x n={r['n']}")

    # Decile results
    print("\n=== DECILE MONOTONICITY ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        mono = assess_monotonic(decile_results[p])
        print(f"  {p}: {mono} - {[f'{v:.4f}' if v else 'NA' for v in decile_results[p]]}")

    # Top-N results
    print("\n=== TOP-N WITHIN RISK-ON (RO=100%, Neutral/Off=LOWMOM60) ===")
    for label in ["Top10%", "Top20%", "Top30%", "Top40%"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            r = ro_weight_results[label][p]
            if r.get("n", 0) > 1:
                print(f"  {label} {p}: CAGR={r['cagrNet']:.2%} Sharpe={r['sharpe']:.3f} MDD={r['mdd']:.2%} Turnover={r['avgAnnualTurnover']:.1f}x n={r['n']}")

    # Risk-On weight results
    print("\n=== RISK-ON TREASURY WEIGHT (Top20%) ===")
    for label in ["RO=70%", "RO=80%", "RO=90%", "RO=100%"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            r = weight_results[label][p]
            if r.get("n", 0) > 1:
                lm = baseline_results["LOWMOM60"][p]
                inc = f" (ΔLM={r['cagrNet'] - lm['cagrNet']:+.2%})" if lm.get("cagrNet") else ""
                print(f"  {label} {p}: CAGR={r['cagrNet']:.2%} Sharpe={r['sharpe']:.3f} MDD={r['mdd']:.2%} Turnover={r['avgAnnualTurnover']:.1f}x{inc}")

    # Trim results
    print("\n=== TAIL TRIM (Top20% Risk-On) ===")
    for label in ["Original", "Trimmed"]:
        for p in ["TRAIN", "VALID", "TEST"]:
            r = trim_results[label][p]
            if r.get("n", 0) > 1:
                print(f"  {label} {p}: CAGR={r['cagrNet']:.2%} Sharpe={r['sharpe']:.3f} MDD={r['mdd']:.2%}")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    mono_train = assess_monotonic(decile_results["TRAIN"])
    mono_valid = assess_monotonic(decile_results["VALID"])
    mono_test = assess_monotonic(decile_results["TEST"])
    
    top20_train = ro_weight_results["Top20%"]["TRAIN"].get("cagrNet", -99)
    top20_valid = ro_weight_results["Top20%"]["VALID"].get("cagrNet", -99)
    top20_test = ro_weight_results["Top20%"]["TEST"].get("cagrNet", -99)
    
    w100_test = weight_results["RO=100%"]["TEST"].get("cagrNet", 0)
    w70_test = weight_results["RO=70%"]["TEST"].get("cagrNet", 0)
    w_sensitivity = w100_test - w70_test
    
    orig_test = trim_results["Original"]["TEST"].get("cagrNet", 0)
    trim_test = trim_results["Trimmed"]["TEST"].get("cagrNet", 0)
    trim_sensitivity = abs(orig_test - trim_test)
    
    mono_consistent = mono_train == mono_valid == mono_test
    
    print(f"Monotonicity: TRAIN={mono_train}, VALID={mono_valid}, TEST={mono_test}")
    print(f"Top20% CAGR: TRAIN={top20_train:.2%} VALID={top20_valid:.2%} TEST={top20_test:.2%}")
    print(f"Weight sensitivity (100%-70%): TEST Δ={w_sensitivity:.2%}")
    print(f"Trim sensitivity: TEST Δ={trim_sensitivity:.2%}")
    
    if mono_consistent and top20_train > 0 and top20_valid > 0 and top20_test > 0 and w_sensitivity < 0.02 and trim_sensitivity < 0.02:
        judgment = "ROBUST"
    elif not mono_consistent or top20_test <= 0 or w_sensitivity > 0.03 or trim_sensitivity > 0.03:
        judgment = "WEAK"
    else:
        judgment = "UNCLASSIFIED"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-16: Test combined regime weight + signal strength continuous function"
    if judgment == "ROBUST":
        next_exp = "10-KR-23-16: Optimize continuous weight function f(treasuryRatio, regime)"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-16: Investigate Risk-On Treasury signal decay in TEST"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save results
    result = {
        "experiment": "10-KR-23-15B: Risk-On Treasury signal strength",
        "decile_returns": decile_results,
        "monotonicity": {"TRAIN": mono_train, "VALID": mono_valid, "TEST": mono_test},
        "top_n_results": {k: {p: v for p, v in d.items()} for k, d in ro_weight_results.items()},
        "weight_results": {k: {p: v for p, v in d.items()} for k, d in weight_results.items()},
        "trim_results": {k: {p: v for p, v in d.items()} for k, d in trim_results.items()},
        "baseline_results": {k: {p: v for p, v in d.items()} for k, d in baseline_results.items()},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-ro-signal-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()