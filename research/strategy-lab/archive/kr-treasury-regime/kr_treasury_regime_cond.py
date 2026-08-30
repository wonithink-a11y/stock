#!/usr/bin/env python
"""10-KR-23-5: TreasuryRatio Regime Conditionality.

Tests if TreasuryRatio's performance and complementarity to LOWMOM60 varies by market regime.
"""
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
REGIME_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "regime_labels.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-regime-cond")

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
        return {"n": len(monthly), "cagrNet": None, "sharpe": None, "mdd": None,
                "avgAnnualTurnover": None, "totalRoundTrips": None, "avgHoldingMonths": None,
                "grossCAGR": None, "costDrag": None, "avgMonthlyRet": None, "winRate": None, "monthlyVol": None}
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
    win_rate = float(np.mean(mr > 0)) if len(mr) > 0 else 0
    avg_ret = float(mr.mean()) if len(mr) > 0 else 0
    vol = float(mr.std(ddof=1)) if len(mr) > 1 else 0
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
            "costDrag": round(cn - gross_cagr, 4) if gross_cagr is not None else None,
            "avgMonthlyRet": round(avg_ret, 4),
            "winRate": round(win_rate, 4),
            "monthlyVol": round(vol, 4)}


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

    # Load regime lookup
    print("Loading regime labels...")
    regime_lut = load_regime_lookup()
    print(f"  regime labels: {len(regime_lut)} dates")
    print(f"  regimes: {regime_lut.value_counts().to_dict()}")

    # Close price lookup
    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}

    # Liquid universe for LOWMOM60
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()

    # Get regime for each rebalance date (entry date = next trading day after rebal)
    def get_regime_for_entry(sd):
        ent_d = next((x for x in all_dates if x > sd), None)
        if ent_d is None:
            return None
        return regime_lut.get(ent_d, None)

    # === LOWMOM60 Baseline ===
    def run_lowmom60(period_dates):
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
            regime = get_regime_for_entry(sd)
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                        "turnover": 1.0, "roundtrips": 1.0, "holding_months": 1,
                        "regime": regime, "month": sd})
        return out

    # === TreasuryQuarterly 3M Hold ===
    def run_treasury_quarterly(period_dates):
        out = []
        rebal_dates = [d for d in qmonths if d in period_dates]
        for k, sd in enumerate(rebal_dates):
            if k + 1 >= len(rebal_dates):
                break
            this = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
            if len(this) < MIN_NAMES:
                continue
            this = this.copy()
            this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
            picks = this[this["q"] == 4]["ticker"].tolist()
            if not picks:
                continue
            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None:
                continue
            ext_d = rebal_dates[k + 1]
            ent = close_by_date[ent_d]
            ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets:
                continue
            gr = float(np.mean(rets))
            regime = get_regime_for_entry(sd)
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                        "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3,
                        "regime": regime, "month": sd})
        return out

    results = {"LOWMOM60": {}, "TreasuryQuarterly": {}}
    regime_stats = {}

    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n=== Period: {p} ({len(period_dates)} months) ===")

        lowmom_rets = run_lowmom60(period_dates)
        treas_rets = run_treasury_quarterly(period_dates)

        # Group by regime
        for regime in ["Risk-On", "Neutral", "Risk-Off"]:
            key = f"{p}_{regime}"
            lowmom_regime = [r for r in lowmom_rets if r.get("regime") == regime]
            treas_regime = [r for r in treas_rets if r.get("regime") == regime]
            
            regime_stats[key] = {
                "LOWMOM60": profile(lowmom_regime),
                "TreasuryQuarterly": profile(treas_regime),
            }
            
            # Incremental
            l = regime_stats[key]["LOWMOM60"]
            t = regime_stats[key]["TreasuryQuarterly"]
            inc = {}
            l_cagr = l.get("cagrNet")
            t_cagr = t.get("cagrNet")
            l_sharpe = l.get("sharpe")
            t_sharpe = t.get("sharpe")
            l_mdd = l.get("mdd")
            t_mdd = t.get("mdd")
            if l_cagr is not None and t_cagr is not None:
                inc = {
                    "cagrDiff": round(t_cagr - l_cagr, 4),
                    "sharpeDiff": round((t_sharpe or 0) - (l_sharpe or 0), 4),
                    "mddDiff": round((t_mdd or 0) - (l_mdd or 0), 4),
                }
            regime_stats[key]["Incremental"] = inc

            l_cagr_str = f"{l_cagr:.2%}" if l_cagr is not None else "NA"
            l_sharpe_str = f"{l_sharpe:.3f}" if l_sharpe is not None else "NA"
            t_cagr_str = f"{t_cagr:.2%}" if t_cagr is not None else "NA"
            t_sharpe_str = f"{t_sharpe:.3f}" if t_sharpe is not None else "NA"
            print(f"  {regime}: LOWMOM60 CAGR={l_cagr_str} Sharpe={l_sharpe_str} n={l.get('n',0)}")
            print(f"  {regime}: Treasury  CAGR={t_cagr_str} Sharpe={t_sharpe_str} n={t.get('n',0)}")
            if inc:
                print(f"  {regime}: Inc CAGR={inc['cagrDiff']:.2%} Sharpe={inc['sharpeDiff']:.3f} MDD={inc['mddDiff']:.2%}")

        # Overall period results (for reference)
        results["LOWMOM60"][p] = profile(lowmom_rets)
        results["TreasuryQuarterly"][p] = profile(treas_rets)

    # Summary table
    print("\n=== REGIME SUMMARY TABLE ===")
    print(f"{'Period':8s} {'Regime':10s} | {'LOWMOM60 CAGR':>12s} {'LOWMOM60 Sharpe':>14s} {'Treas CAGR':>12s} {'Treas Sharpe':>13s} | {'Inc CAGR':>10s} {'Inc Sharpe':>10s} {'Inc MDD':>8s}")
    print("-" * 110)
    for p in ["TRAIN", "VALID", "TEST"]:
        for regime in ["Risk-On", "Neutral", "Risk-Off"]:
            key = f"{p}_{regime}"
            s = regime_stats[key]
            l = s["LOWMOM60"]
            t = s["TreasuryQuarterly"]
            inc = s["Incremental"]
            if l.get("n", 0) > 0 and t.get("n", 0) > 0:
                l_cagr = l.get("cagrNet")
                l_sharpe = l.get("sharpe")
                t_cagr = t.get("cagrNet")
                t_sharpe = t.get("sharpe")
                inc_cagr = inc.get("cagrDiff")
                inc_sharpe = inc.get("sharpeDiff")
                inc_mdd = inc.get("mddDiff")
                print(f"{p:8s} {regime:10s} | "
                      f"{(f'{l_cagr:.2%}' if l_cagr is not None else 'NA'):>12s} "
                      f"{(f'{l_sharpe:.3f}' if l_sharpe is not None else 'NA'):>14s} "
                      f"{(f'{t_cagr:.2%}' if t_cagr is not None else 'NA'):>12s} "
                      f"{(f'{t_sharpe:.3f}' if t_sharpe is not None else 'NA'):>13s} | "
                      f"{(f'{inc_cagr:.2%}' if inc_cagr is not None else 'NA'):>10s} "
                      f"{(f'{inc_sharpe:.3f}' if inc_sharpe is not None else 'NA'):>10s} "
                      f"{(f'{inc_mdd:.2%}' if inc_mdd is not None else 'NA'):>8s}")

    # Key analysis
    print("\n=== KEY ANALYSIS ===")
    
    # 1. Treasury strength by regime across periods
    print("\n1. TreasuryQuarterly CAGR by regime across periods:")
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        vals = []
        for p in ["TRAIN", "VALID", "TEST"]:
            v = regime_stats[f"{p}_{regime}"]["TreasuryQuarterly"].get("cagrNet")
            vals.append(f"{v:.2%}" if v is not None else "NA")
        print(f"  {regime}: TRAIN={vals[0]} VALID={vals[1]} TEST={vals[2]}")

    # 2. LOWMOM60 strength by regime across periods
    print("\n2. LOWMOM60 CAGR by regime across periods:")
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        vals = []
        for p in ["TRAIN", "VALID", "TEST"]:
            v = regime_stats[f"{p}_{regime}"]["LOWMOM60"].get("cagrNet")
            vals.append(f"{v:.2%}" if v is not None else "NA")
        print(f"  {regime}: TRAIN={vals[0]} VALID={vals[1]} TEST={vals[2]}")

    # 3. Incremental by regime across periods
    print("\n3. Incremental (Treasury - LOWMOM60) by regime across periods:")
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        vals = []
        for p in ["TRAIN", "VALID", "TEST"]:
            v = regime_stats[f"{p}_{regime}"]["Incremental"].get("cagrDiff")
            vals.append(f"{v:.2%}" if v is not None else "NA")
        print(f"  {regime}: TRAIN={vals[0]} VALID={vals[1]} TEST={vals[2]}")

    # 4. TEST effect concentration
    print("\n4. TEST regime contribution:")
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        s = regime_stats[f"TEST_{regime}"]["TreasuryQuarterly"]
        cagr = s.get("cagrNet")
        n = s.get("n", 0)
        cagr_str = f"{cagr:.2%}" if cagr is not None else "NA"
        print(f"  {regime}: CAGR={cagr_str} n={n}")

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    # Check if Treasury outperforms consistently in same regime across TRAIN/VALID/TEST
    regime_consistency = {}
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        incs = []
        for p in ["TRAIN", "VALID", "TEST"]:
            v = regime_stats[f"{p}_{regime}"]["Incremental"].get("cagrDiff")
            incs.append(v if v is not None else -999)
        all_pos = all(x > 0 for x in incs)
        all_neg = all(x < 0 for x in incs)
        regime_consistency[regime] = {"incs": incs, "all_pos": all_pos, "all_neg": all_neg}
        incs_str = [f"{x:.2%}" if x != -999 else "NA" for x in incs]
        print(f"  {regime}: incs={incs_str} all_pos={all_pos} all_neg={all_neg}")

    # Check if TEST Treasury strength is regime-concentrated
    test_incs = []
    for r in ["Risk-On", "Neutral", "Risk-Off"]:
        v = regime_stats[f"TEST_{r}"]["Incremental"].get("cagrDiff")
        test_incs.append(v if v is not None else 0)
    max_test_inc = max(test_incs)
    test_concentrated = max_test_inc > 0.03 and sum(1 for x in test_incs if x > 0.01) <= 1

    # Check if TRAIN/VALID weakness is regime-concentrated
    train_valid_weak = False
    for regime in ["Risk-On", "Neutral", "Risk-Off"]:
        train_inc = regime_stats[f"TRAIN_{regime}"]["Incremental"].get("cagrDiff", 0)
        valid_inc = regime_stats[f"VALID_{regime}"]["Incremental"].get("cagrDiff", 0)
        if train_inc is not None and valid_inc is not None and train_inc < -0.02 and valid_inc < -0.02:
            train_valid_weak = True
            print(f"  TRAIN/VALID both weak in {regime}")

    any_consistent_regime = any(v["all_pos"] for v in regime_consistency.values())
    
    if any_consistent_regime and not test_concentrated:
        judgment = "PASS"
    elif test_concentrated and not any_consistent_regime:
        judgment = "REJECT"
    else:
        judgment = "WEAK"

    print(f"\n  Consistent regime with Treasury>LOWMOM60 across splits: {any_consistent_regime}")
    print(f"  TEST strength concentrated in single regime: {test_concentrated}")
    print(f"  TRAIN/VALID weakness concentrated: {train_valid_weak}")
    print(f"\n>>> JUDGMENT: {judgment} <<<")

    if judgment == "PASS":
        next_exp = "10-KR-23-6: Build regime-conditional combined strategy (not fixed 50/50)"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-6: Test TreasuryRatio with other baselines (PBR, REV20)"
    else:
        next_exp = "10-KR-23-6: TreasuryRatio not suitable for combination; test standalone with timing"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-5: TreasuryRatio regime conditionality",
        "regime_stats": regime_stats,
        "period_results": results,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-regime-cond-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()