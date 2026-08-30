#!/usr/bin/env python
"""10-KR-23-13 STEP 2: Regime-Dependent Fixed Weights Backtest.

Tests three fixed weight schemes across market regimes.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-regime-dep")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0


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


def profile(monthly):
    if not monthly or len(monthly) < 2:
        return {"n": len(monthly) if monthly else 0}
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

    # Weight schemes
    schemes = {
        "50_50": {"Risk-On": 0.5, "Neutral": 0.5, "Risk-Off": 0.5},
        "70_30": {"Risk-On": 0.7, "Neutral": 0.5, "Risk-Off": 0.3},
        "30_70": {"Risk-On": 0.3, "Neutral": 0.5, "Risk-Off": 0.7},
    }

    # Run for each scheme
    results = {name: {} for name in schemes}

    for scheme_name, weights in schemes.items():
        print(f"\n=== Scheme: {scheme_name} ===")
        
        for p in ["TRAIN", "VALID", "TEST"]:
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}
            
            lowmom_sleeves = []
            treas_sleeves = []
            monthly_rets = []

            for k, sd in enumerate(period_dates):
                regime = get_regime_for_entry(sd)
                if regime not in weights:
                    continue
                w_treas = weights[regime]
                w_lowmom = 1.0 - w_treas

                # Add LOWMOM60 sleeve
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))

                # Add Treasury sleeve (quarterly, 6M hold = 2 quarters)
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
                        lowmom_ret = w_lowmom * float(np.mean(rets))

                # Treasury sleeve return
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

            prof = profile(monthly_rets)
            results[scheme_name][p] = prof
            if prof.get("n", 0) > 1:
                print(f"  {p}: CAGR={prof['cagrNet']:.2%} Sharpe={prof['sharpe']:.3f} "
                      f"MDD={prof['mdd']:.2%} Turnover={prof['avgAnnualTurnover']:.1f}x n={prof['n']}")

    # LOWMOM60 baseline
    print("\n=== LOWMOM60 Baseline ===")
    lowmom_results = {}
    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        out = []
        for k, sd in enumerate(period_dates):
            if k + 1 >= len(period_dates):
                break
            this = liq[liq["date"] == sd].dropna(subset=["mom60"])
            if len(this) < TOP_N:
                continue
            this = this.sort_values("mom60").head(TOP_N)
            picks = this["ticker"].tolist()
            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None:
                continue
            ext_d = period_dates[k + 1]
            ent = close_by_date[ent_d]
            ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets:
                continue
            gr = float(np.mean(rets))
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                        "turnover": 1.0, "roundtrips": 1.0, "holding_months": 1})
        lowmom_results[p] = profile(out)
        if lowmom_results[p].get("n", 0) > 1:
            print(f"  {p}: CAGR={lowmom_results[p]['cagrNet']:.2%} Sharpe={lowmom_results[p]['sharpe']:.3f} MDD={lowmom_results[p]['mdd']:.2%}")

    # Comparison table
    print("\n=== COMPARISON TABLE ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p}:")
        lm = lowmom_results[p]
        for scheme_name in schemes:
            r = results[scheme_name][p]
            if r.get("n", 0) > 1 and lm.get("n", 0) > 1:
                inc_cagr = r.get("cagrNet", 0) - lm.get("cagrNet", 0)
                inc_sharpe = (r.get("sharpe", 0) or 0) - (lm.get("sharpe", 0) or 0)
                inc_mdd = r.get("mdd", 0) - lm.get("mdd", 0)
                print(f"  {scheme_name}: CAGR={r['cagrNet']:.2%} (inc={inc_cagr:+.2%}) "
                      f"Sharpe={r['sharpe']:.3f} (inc={inc_sharpe:+.3f}) "
                      f"MDD={r['mdd']:.2%} (inc={inc_mdd:+.2%}) "
                      f"Turnover={r['avgAnnualTurnover']:.1f}x n={r['n']}")

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    # Check consistency: 70/30 vs 50/50 incremental vs LOWMOM60
    inc_70_50 = {p: results["70_30"][p].get("cagrNet", 0) - results["50_50"][p].get("cagrNet", 0) for p in ["TRAIN", "VALID", "TEST"]}
    inc_30_50 = {p: results["30_70"][p].get("cagrNet", 0) - results["50_50"][p].get("cagrNet", 0) for p in ["TRAIN", "VALID", "TEST"]}
    
    print(f"70/30 vs 50/50 CAGR Delta: TRAIN={inc_70_50['TRAIN']:+.2%} VALID={inc_70_50['VALID']:+.2%} TEST={inc_70_50['TEST']:+.2%}")
    print(f"30/70 vs 50/50 CAGR Delta: TRAIN={inc_30_50['TRAIN']:+.2%} VALID={inc_30_50['VALID']:+.2%} TEST={inc_30_50['TEST']:+.2%}")

    # Check if 70/30 improves over 50/50 in all periods
    improves_70 = all(v > 0 for v in inc_70_50.values())
    worsens_70 = all(v < 0 for v in inc_70_50.values())
    
    # Check if 30/70 improves over 50/50 in all periods
    improves_30 = all(v > 0 for v in inc_30_50.values())
    worsens_30 = all(v < 0 for v in inc_30_50.values())

    if improves_70:
        judgment = "PASS - 70/30 improves over 50/50 in all periods"
    elif worsens_70:
        judgment = "REJECT - 70/30 harms vs 50/50 in all periods"
    elif improves_30:
        judgment = "PASS - 30/70 improves over 50/50 in all periods"
    elif worsens_30:
        judgment = "REJECT - 30/70 harms vs 50/50 in all periods"
    else:
        judgment = "UNCLASSIFIED - Mixed results across periods"

    print(f"\n>>> JUDGMENT: {judgment} <<<")

    # Sample size warnings
    print("\n=== SAMPLE SIZE WARNINGS ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        for r in ["Risk-On", "Neutral", "Risk-Off"]:
            # Count treasury quarters in this period/regime
            count = 0
            period_dates = [d for d in months if period_of(d) == p]
            period_qdates = [d for d in qmonths if d in period_dates]
            for sd in period_qdates:
                regime = get_regime_for_entry(sd)
                if regime == r:
                    count += 1
            if count < 3:
                print(f"  [SMALL] {p} {r}: {count} Treasury quarters")

    next_exp = "10-KR-23-14: Test continuous weight (linear in signal strength) within regime"
    if judgment.startswith("PASS"):
        next_exp = "10-KR-23-14: Optimize regime weights (not just 70/30/30/70)"
    elif judgment.startswith("REJECT"):
        next_exp = "10-KR-23-14: Test alternative regime definitions"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-13 STEP 2: Regime-dependent fixed weights",
        "results": results,
        "lowmom60_baseline": lowmom_results,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-regime-dep-step2-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()