#!/usr/bin/env python
"""10-KR-23-12 STEP 2: Dynamic Weighting Backtest.

Tests Candidate A (Dispersion Ratio) and Candidate B (Spread Ratio) vs 50/50 baseline.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-dynamic-weight")

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

    # Build treasury panel at monthly dates
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

    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}

    # Liquid universe for LOWMOM60
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()

    # Pre-compute signal strength metrics at each rebalance date
    print("Computing signal strength metrics...")
    
    # Monthly mom60 metrics
    mom60_std_by_month = {}
    mom60_spread_by_month = {}
    for sd in months:
        this = liq[liq["date"] == sd].dropna(subset=["mom60"])
        if len(this) < TOP_N:
            mom60_std_by_month[sd] = np.nan
            mom60_spread_by_month[sd] = np.nan
            continue
        mom60_std_by_month[sd] = this["mom60"].std()
        # top30 - bottom30 spread
        mom60_sorted = this.sort_values("mom60")
        top30 = mom60_sorted.head(TOP_N)["mom60"]
        bot30 = mom60_sorted.tail(TOP_N)["mom60"]
        mom60_spread_by_month[sd] = top30.mean() - bot30.mean()
    
    # Quarterly treasury metrics
    treas_std_by_q = {}
    treas_spread_by_q = {}
    for sd in qmonths:
        this = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
        if len(this) < MIN_NAMES:
            treas_std_by_q[sd] = np.nan
            treas_spread_by_q[sd] = np.nan
            continue
        treas_std_by_q[sd] = this["treasuryRatio"].std()
        this = this.copy()
        this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
        top_q = this[this["q"] == 4]["treasuryRatio"]
        bot_q = this[this["q"] == 0]["treasuryRatio"]
        treas_spread_by_q[sd] = top_q.mean() - bot_q.mean()

    # Align quarterly treasury metrics to monthly dates (carry forward)
    # For each monthly date, find most recent quarterly date <= monthly date
    q_dates_sorted = sorted(qmonths)
    treas_std_aligned = {}
    treas_spread_aligned = {}
    for sd in months:
        prior_q = [d for d in q_dates_sorted if d <= sd]
        if prior_q:
            qd = prior_q[-1]
            treas_std_aligned[sd] = treas_std_by_q.get(qd, np.nan)
            treas_spread_aligned[sd] = treas_spread_by_q.get(qd, np.nan)
        else:
            treas_std_aligned[sd] = np.nan
            treas_spread_aligned[sd] = np.nan

    # Run strategies for each period
    results = {"50_50_Baseline": {}, "Candidate_A": {}, "Candidate_B": {}}

    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n=== Period: {p} ({len(period_dates)} months) ===")

        for variant in ["50_50_Baseline", "Candidate_A", "Candidate_B"]:
            lowmom_sleeves = []
            treas_sleeves = []  # (start_quarter_idx, picks)
            monthly_rets = []

            period_qdates = [d for d in qmonths if d in period_dates]
            q_idx_map = {d: i for i, d in enumerate(period_qdates)}

            for k, sd in enumerate(period_dates):
                # Determine weights for this month
                if variant == "50_50_Baseline":
                    w_treas = 0.5
                    w_lowmom = 0.5
                elif variant == "Candidate_A":
                    # Dispersion Ratio
                    t_std = treas_std_aligned.get(sd, np.nan)
                    m_std = mom60_std_by_month.get(sd, np.nan)
                    if np.isnan(t_std) or np.isnan(m_std) or (t_std + m_std) == 0:
                        w_treas = 0.5
                        w_lowmom = 0.5
                    else:
                        w_treas = t_std / (t_std + m_std)
                        w_lowmom = m_std / (t_std + m_std)
                elif variant == "Candidate_B":
                    # Spread Ratio
                    t_spread = treas_spread_aligned.get(sd, np.nan)
                    m_spread = mom60_spread_by_month.get(sd, np.nan)
                    if np.isnan(t_spread) or np.isnan(m_spread) or (t_spread + m_spread) == 0:
                        w_treas = 0.5
                        w_lowmom = 0.5
                    else:
                        w_treas = t_spread / (t_spread + m_spread)
                        w_lowmom = m_spread / (t_spread + m_spread)

                # Add LOWMOM60 sleeve (monthly, 1M)
                this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
                if len(this_low) >= TOP_N:
                    this_low = this_low.sort_values("mom60").head(TOP_N)
                    lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))

                # Add Treasury sleeve (quarterly, 6M = 2 quarters)
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
                lowmom_picks = set()
                for _, picks in lowmom_sleeves:
                    rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                            if t in ent.index and t in ext.index and ent.loc[t] > 0]
                    if rets:
                        lowmom_ret = w_lowmom * float(np.mean(rets))
                        lowmom_picks.update(picks)

                # Treasury sleeve return
                treas_ret = 0.0
                treas_picks = set()
                for _, picks in treas_sleeves:
                    rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                            if t in ent.index and t in ext.index and ent.loc[t] > 0]
                    if rets:
                        treas_ret = w_treas * float(np.mean(rets))
                        treas_picks.update(picks)

                combined_ret = lowmom_ret + treas_ret
                net_ret = combined_ret - ROUNDTRIP_BPS / 10000

                monthly_rets.append({"ret": net_ret, "gross_ret": combined_ret,
                                     "turnover": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "roundtrips": w_lowmom * 1.0 + w_treas * (1.0/6.0),
                                     "holding_months": w_lowmom * 1.0 + w_treas * 6.0,
                                     "w_lowmom": w_lowmom, "w_treas": w_treas})

            prof = profile(monthly_rets)
            results[variant][p] = prof
            if prof.get("n", 0) > 1:
                print(f"  {variant}: CAGR={prof['cagrNet']:.2%} Sharpe={prof['sharpe']:.3f} "
                      f"MDD={prof['mdd']:.2%} Turnover={prof['avgAnnualTurnover']:.1f}x n={prof['n']}")

    # Summary comparison
    print("\n=== COMPARISON: 50/50 vs Candidate A vs Candidate B ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        b = results["50_50_Baseline"][p]
        a = results["Candidate_A"][p]
        c = results["Candidate_B"][p]
        if b.get("n", 0) > 1 and a.get("n", 0) > 1 and c.get("n", 0) > 1:
            print(f"\n{p}:")
            print(f"  50/50:      CAGR={b['cagrNet']:.2%} Sharpe={b['sharpe']:.3f} MDD={b['mdd']:.2%} Turnover={b['avgAnnualTurnover']:.1f}x")
            print(f"  Cand_A:     CAGR={a['cagrNet']:.2%} Sharpe={a['sharpe']:.3f} MDD={a['mdd']:.2%} Turnover={a['avgAnnualTurnover']:.1f}x")
            print(f"  Cand_B:     CAGR={c['cagrNet']:.2%} Sharpe={c['sharpe']:.3f} MDD={c['mdd']:.2%} Turnover={c['avgAnnualTurnover']:.1f}x")
            print(f"  A-50/50:    CAGR={a['cagrNet']-b['cagrNet']:+.2%} Sharpe={a['sharpe']-b['sharpe']:+.3f} MDD={a['mdd']-b['mdd']:+.2%}")
            print(f"  B-50/50:    CAGR={c['cagrNet']-b['cagrNet']:+.2%} Sharpe={c['sharpe']-b['sharpe']:+.3f} MDD={c['mdd']-b['mdd']:+.2%}")

    # Incremental vs LOWMOM60 (need LOWMOM60 baseline)
    print("\n=== INCREMENTAL vs LOWMOM60 Baseline ===")
    # Run LOWMOM60 standalone
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
            print(f"  LOWMOM60 {p}: CAGR={lowmom_results[p]['cagrNet']:.2%} Sharpe={lowmom_results[p]['sharpe']:.3f} MDD={lowmom_results[p]['mdd']:.2%}")

    # Incremental
    print("\n=== INCREMENTAL: Combined - LOWMOM60 ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        lm = lowmom_results[p]
        for variant in ["50_50_Baseline", "Candidate_A", "Candidate_B"]:
            c = results[variant][p]
            if lm.get("n", 0) > 1 and c.get("n", 0) > 1:
                inc = {
                    "cagrDiff": round(c.get("cagrNet", 0) - lm.get("cagrNet", 0), 4),
                    "sharpeDiff": round((c.get("sharpe", 0) or 0) - (lm.get("sharpe", 0) or 0), 4),
                    "mddDiff": round(c.get("mdd", 0) - lm.get("mdd", 0), 4),
                }
                print(f"  {variant} {p}: CAGR={inc['cagrDiff']:.2%} Sharpe={inc['sharpeDiff']:.3f} MDD={inc['mddDiff']:.2%}")

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    # Candidate A vs 50/50
    a_vs_b = {p: results["Candidate_A"][p].get("cagrNet", 0) - results["50_50_Baseline"][p].get("cagrNet", 0) for p in ["TRAIN", "VALID", "TEST"]}
    b_vs_b = {p: results["Candidate_B"][p].get("cagrNet", 0) - results["50_50_Baseline"][p].get("cagrNet", 0) for p in ["TRAIN", "VALID", "TEST"]}
    
    print(f"Candidate A vs 50/50 CAGR Delta: TRAIN={a_vs_b['TRAIN']:+.2%} VALID={a_vs_b['VALID']:+.2%} TEST={a_vs_b['TEST']:+.2%}")
    print(f"Candidate B vs 50/50 CAGR Delta: TRAIN={b_vs_b['TRAIN']:+.2%} VALID={b_vs_b['VALID']:+.2%} TEST={b_vs_b['TEST']:+.2%}")

    # Judgment criteria
    a_all_pos = all(v > 0 for v in a_vs_b.values())
    a_all_neg = all(v < 0 for v in a_vs_b.values())
    b_all_pos = all(v > 0 for v in b_vs_b.values())
    b_all_neg = all(v < 0 for v in b_vs_b.values())

    if a_all_pos and b_all_pos:
        judgment = "PASS - Both candidates improve over 50/50 in all periods"
    elif a_all_neg and b_all_neg:
        judgment = "REJECT - Both candidates harm vs 50/50 in all periods"
    elif (a_all_pos or b_all_pos) and not (a_all_neg or b_all_neg):
        judgment = "WEAK - Mixed: one candidate helps, other harms"
    else:
        judgment = "UNCLASSIFIED - No consistent pattern across candidates/periods"

    print(f"\n>>> JUDGMENT: {judgment} <<<")

    if judgment.startswith("PASS"):
        next_exp = "10-KR-23-13: Optimize dynamic weighting parameters (smoothing, clipping)"
    elif judgment.startswith("REJECT"):
        next_exp = "10-KR-23-13: Test alternative signal-strength definitions"
    elif judgment.startswith("WEAK"):
        next_exp = "10-KR-23-13: Analyze why Candidate A/B diverge and refine"
    else:
        next_exp = "10-KR-23-13: Dynamic weighting not robust; test regime-dependent fixed weights"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-12 STEP 2: Dynamic weighting backtest",
        "results": results,
        "lowmom60_baseline": lowmom_results,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-dynamic-weight-step2-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()