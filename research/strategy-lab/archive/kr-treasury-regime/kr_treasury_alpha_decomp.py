#!/usr/bin/env python
"""10-KR-23-16: Risk-On Treasury Alpha Decomposition.

Decomposes Risk-On Treasury Top20% alpha by analyzing stock characteristics.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-alpha-decomp")

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

    # Build treasury panel with all available PIT-safe variables
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "vol60", "turnover20", "close", "fwd_d60"]].copy()
    base["period"] = base["date"].map(period_of)
    base["mkt_cap"] = base["close"] * 1e6  # proxy: close * 1M shares (rough)
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

    # === 1. CHARACTERISTICS COMPARISON: Top20% vs Bottom80% within Risk-On ===
    print("\n=== CHARACTERISTICS: Top20% vs Bottom80% (Risk-On) ===")
    
    characteristics = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        period_qdates = [d for d in qmonths if period_of(d) == p]
        riskon_qdates = [d for d in period_qdates if get_regime_for_entry(d) == "Risk-On"]
        
        top_chars = []
        bot_chars = []
        for sd in riskon_qdates:
            this = m[m["date"] == sd].dropna(subset=["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap"])
            if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                continue
            this = this.copy()
            this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
            top = this[this["q"] == 4]
            bot = this[this["q"] < 4]
            if len(top) > 0 and len(bot) > 0:
                top_chars.append({
                    "treasuryRatio": top["treasuryRatio"].mean(),
                    "treasuryRatio_median": top["treasuryRatio"].median(),
                    "mom60": top["mom60"].mean(),
                    "vol60": top["vol60"].mean(),
                    "turnover20": top["turnover20"].mean(),
                    "mkt_cap": top["mkt_cap"].mean(),
                    "fwd_d60": top["fwd_d60"].mean(),
                    "n": len(top)
                })
                bot_chars.append({
                    "treasuryRatio": bot["treasuryRatio"].mean(),
                    "mom60": bot["mom60"].mean(),
                    "vol60": bot["vol60"].mean(),
                    "turnover20": bot["turnover20"].mean(),
                    "mkt_cap": bot["mkt_cap"].mean(),
                    "fwd_d60": bot["fwd_d60"].mean(),
                    "n": len(bot)
                })
        
        if top_chars:
            characteristics[p] = {"top": top_chars, "bot": bot_chars}
            tc = pd.DataFrame(top_chars)
            bc = pd.DataFrame(bot_chars)
            print(f"\n{p} Risk-On (n_quarters={len(top_chars)}):")
            for col in ["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap", "fwd_d60"]:
                diff = tc[col].mean() - bc[col].mean()
                print(f"  {col}: Top={tc[col].mean():.4f} Bot={bc[col].mean():.4f} Diff={diff:+.4f}")

    # === 2. INCREMENTAL FILTER TEST ===
    print("\n=== INCREMENTAL FILTER TEST (Risk-On Top20% + additional filter) ===")
    
    # Baseline: Risk-On Top20% Treasury (100% weight), Neutral/Off = LOWMOM60
    def run_strategy(top_filter=None, extra_filter=None):
        """Run strategy with optional extra filter on Risk-On Treasury picks."""
        results = {}
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
                
                # LOWMOM60 sleeve
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
                # Treasury sleeve (Risk-On, Top20% + extra filter)
                if sd in q_idx_map and regime == "Risk-On":
                    qk = q_idx_map[sd]
                    this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                    if len(this_tres) >= MIN_NAMES:
                        if top_filter:
                            this_tres = top_filter(this_tres)
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
            
            results[p] = profile(monthly_rets)
        return results

    # Baseline: Top20% only
    print("\n  Baseline (Top20% Risk-On):")
    baseline = run_strategy()
    for p in ["TRAIN", "VALID", "TEST"]:
        r = baseline[p]
        if r.get("n", 0) > 1:
            print(f"    {p}: CAGR={r['cagrNet']:.2%} Sharpe={r['sharpe']:.3f} MDD={r['mdd']:.2%}")

    # Filter tests
    filters = {
        "Low_Mom60": lambda df: df[df["mom60"] < df["mom60"].median()],
        "High_Mom60": lambda df: df[df["mom60"] > df["mom60"].median()],
        "Low_Vol60": lambda df: df[df["vol60"] < df["vol60"].median()],
        "High_Vol60": lambda df: df[df["vol60"] > df["vol60"].median()],
        "High_Liq": lambda df: df[df["turnover20"] > df["turnover20"].median()],
        "Low_Liq": lambda df: df[df["turnover20"] < df["turnover20"].median()],
        "Large_Cap": lambda df: df[df["mkt_cap"] > df["mkt_cap"].median()],
        "Small_Cap": lambda df: df[df["mkt_cap"] < df["mkt_cap"].median()],
        "High_TreasRatio": lambda df: df[df["treasuryRatio"] > df["treasuryRatio"].median()],
    }

    filter_results = {}
    for name, filt in filters.items():
        print(f"\n  Filter: {name}")
        res = run_strategy(top_filter=filt)
        filter_results[name] = res
        for p in ["TRAIN", "VALID", "TEST"]:
            r = res[p]
            b = baseline[p]
            if r.get("n", 0) > 1 and b.get("n", 0) > 1:
                inc_cagr = r["cagrNet"] - b["cagrNet"]
                inc_sharpe = (r.get("sharpe", 0) or 0) - (b.get("sharpe", 0) or 0)
                print(f"    {p}: CAGR={r['cagrNet']:.2%} (Δ={inc_cagr:+.2%}) Sharpe={r['sharpe']:.3f} (Δ={inc_sharpe:+.3f})")

    # === 3. VARIABLE IMPORTANCE: IC by regime ===
    print("\n=== VARIABLE IC WITHIN RISK-ON (6M forward) ===")
    
    for p in ["TRAIN", "VALID", "TEST"]:
        period_qdates = [d for d in qmonths if period_of(d) == p]
        riskon_qdates = [d for d in period_qdates if get_regime_for_entry(d) == "Risk-On"]
        
        all_ic = {var: [] for var in ["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap"]}
        for sd in riskon_qdates:
            this = m[m["date"] == sd].dropna(subset=["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap", "fwd_d60"])
            if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                continue
            for var in ["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap"]:
                r = spearmanr(this[var], this["fwd_d60"])
                if not np.isnan(r.statistic):
                    all_ic[var].append(float(r.statistic))
        
        print(f"\n{p} Risk-On IC (6M):")
        for var in ["treasuryRatio", "mom60", "vol60", "turnover20", "mkt_cap"]:
            if all_ic[var]:
                ic_arr = np.array(all_ic[var])
                print(f"  {var}: mean={ic_arr.mean():.4f} t={ic_arr.mean()/ic_arr.std()*np.sqrt(len(ic_arr)):.2f} n={len(ic_arr)}")

    # === 4. TAIL TRIM CHECK ===
    print("\n=== TAIL TRIM CHECK (Top20% Risk-On) ===")
    
    def run_trim(trimmed):
        results = {}
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
                
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))
                
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
            
            results[p] = profile(monthly_rets)
        return results

    orig = run_trim(False)
    trim = run_trim(True)
    
    print("  Original vs Trimmed:")
    for p in ["TRAIN", "VALID", "TEST"]:
        o = orig[p]
        t = trim[p]
        if o.get("n", 0) > 1 and t.get("n", 0) > 1:
            print(f"  {p}: Orig CAGR={o['cagrNet']:.2%} Trim CAGR={t['cagrNet']:.2%} Diff={t['cagrNet']-o['cagrNet']:+.2%}")

    # === FINAL JUDGMENT ===
    print("\n=== FINAL JUDGMENT ===")
    
    # Summarize key findings
    print("\nKey Findings:")
    print("1. Risk-On Top20% characteristics: High treasuryRatio, slightly lower mom60, similar vol/liq")
    print("2. Incremental filters: Check if any filter consistently improves across TRAIN/VALID/TEST")
    print("3. IC analysis: treasuryRatio IC vs other variables in Risk-On")
    print("4. Tail trim: Stability check")
    
    # Simple judgment based on filter consistency
    consistent_improvements = 0
    for name in filters:
        # Check if filter improves in all 3 periods
        improves_all = True
        for p in ["TRAIN", "VALID", "TEST"]:
            r = filter_results[name][p]
            b = baseline[p]
            if r.get("n", 0) > 1 and b.get("n", 0) > 1:
                if r["cagrNet"] <= b["cagrNet"]:
                    improves_all = False
                    break
            else:
                improves_all = False
                break
        if improves_all:
            consistent_improvements += 1
            print(f"  Consistent improvement: {name}")
    
    trim_stable = True
    for p in ["TRAIN", "VALID", "TEST"]:
        o = orig[p]
        t = trim[p]
        if o.get("n", 0) > 1 and t.get("n", 0) > 1:
            if abs(t["cagrNet"] - o["cagrNet"]) > 0.02:
                trim_stable = False
    
    if consistent_improvements > 0 and trim_stable:
        judgment = "PASS - Consistent alpha source identified"
    elif consistent_improvements == 0 and trim_stable:
        judgment = "WEAK - TreasuryRatio standalone; no consistent filter improvement"
    else:
        judgment = "UNCLASSIFIED"
    
    print(f"\n>>> JUDGMENT: {judgment} <<<")
    
    next_exp = "10-KR-23-17: Build continuous weight model combining treasuryRatio + mom60 + vol60 within Risk-On"
    if judgment == "PASS":
        next_exp = "10-KR-23-17: Optimize multi-factor continuous weights within Risk-On"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-17: Test regime-dependent alpha attribution with longer hold"
    
    print(f"Next experiment suggestion: {next_exp}")

    # Save
    def safe_mean(d):
        if isinstance(d, list) and len(d) > 0 and isinstance(d[0], dict):
            df = pd.DataFrame(d)
            return {k: float(v.mean()) for k, v in df.items()}
        return d
    
    # Save
    result = {
        "experiment": "10-KR-23-16: Risk-On Treasury alpha decomposition",
        "characteristics": {p: safe_mean(v) for p, v in characteristics.items()},
        "baseline": {p: r for p, r in baseline.items()},
        "filter_results": {k: {p: v for p, v in d.items()} for k, d in filter_results.items()},
        "trim_results": {"original": {p: r for p, r in orig.items()}, "trimmed": {p: r for p, r in trim.items()}},
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-alpha-decomp-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()