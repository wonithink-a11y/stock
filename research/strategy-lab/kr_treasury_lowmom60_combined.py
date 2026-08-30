#!/usr/bin/env python
"""10-KR-23-4: TreasuryRatio + LOWMOM60 Incremental Validation.

Tests if Quarterly TreasuryRatio adds incremental alpha to LOWMOM60 baseline.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-lowmom60-combined")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
TOP_N = 30
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS
MIN_TURNOVER = 100_000_000.0  # 1억원 - absolute threshold from LOWMOM60 baseline


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
    if not monthly:
        return {}
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


def jaccard(set1, set2):
    if not set1 and not set2:
        return 1.0
    if not set1 or not set2:
        return 0.0
    return len(set1 & set2) / len(set1 | set2)


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

    # Load treasuryRatio
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

    # Build treasury panel at monthly rebalance dates
    base = df[df["date"].isin(months)][["ticker", "date", "mom60", "turnover20",
                                         "close"]].copy()
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

    # Close price lookup for next-day entry (A4 has close, use next-day close)
    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}

    # Pre-filter liquid universe for LOWMOM60
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()
    print(f"  liquid universe (turnover20>=1e8): {liq['ticker'].nunique()} tickers, {len(liq)} rows")

    # === LOWMOM60 Baseline (Monthly, Top 30, Next-day entry) ===
    def run_lowmom60(period_dates):
        out = []
        for k, sd in enumerate(period_dates):
            if k + 1 >= len(period_dates):
                break
            this = liq[liq["date"] == sd].dropna(subset=["mom60"])
            if len(this) < TOP_N:
                continue
            this = this.sort_values("mom60").head(TOP_N)  # lowest mom60 = best
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
                        "turnover": 1.0, "roundtrips": 1.0, "holding_months": 1,
                        "picks": set(picks)})
        return out

    # === TreasuryRatio Quarterly 3M Hold (from 10-KR-23-3) ===
    # Top-Q (top 20%), no liquidity filter, quarterly rebal, 3M hold
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
            picks = this[this["q"] == 4]["ticker"].tolist()  # Top quintile
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
            out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                        "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3,
                        "picks": set(picks)})
        return out

    # === 50/50 Combined ===
    def run_combined(period_dates):
        # Monthly LOWMOM60 sleeve (top 30, liquidity filter) + Quarterly Treasury sleeve (top-Q, no liquidity filter)
        lowmom_sleeves = []  # list of (start_idx, picks)
        treas_sleeves = []   # list of (start_q_idx, picks)
        monthly_rets = []

        period_qdates = [d for d in qmonths if d in period_dates]
        q_idx_map = {d: i for i, d in enumerate(period_qdates)}

        for k, sd in enumerate(period_dates):
            # Add LOWMOM60 sleeve (monthly, top 30)
            this_low = liq[liq["date"] == sd].dropna(subset=["mom60"])
            if len(this_low) >= TOP_N:
                this_low = this_low.sort_values("mom60").head(TOP_N)
                lowmom_sleeves.append((k, set(this_low["ticker"].tolist())))

            # Add Treasury sleeve (quarterly, top-Q)
            if sd in q_idx_map:
                qk = q_idx_map[sd]
                this_tres = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
                if len(this_tres) >= MIN_NAMES:
                    this_tres = this_tres.copy()
                    this_tres["q"] = pd.qcut(this_tres["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
                    picks = this_tres[this_tres["q"] == 4]["ticker"].tolist()
                    if picks:
                        treas_sleeves.append((qk, set(picks)))

            # Remove expired sleeves
            lowmom_sleeves = [(si, sp) for (si, sp) in lowmom_sleeves if k - si < 1]
            current_q_idx = q_idx_map.get(sd, -1)
            treas_sleeves = [(si, sp) for (si, sp) in treas_sleeves if current_q_idx - si < 1]

            # Compute return for this month
            if not lowmom_sleeves and not treas_sleeves:
                continue

            ent_d = next((x for x in all_dates if x > sd), None)
            if ent_d is None or k + 1 >= len(period_dates):
                continue
            ext_d = period_dates[k + 1]
            ent = close_by_date[ent_d]
            ext = close_by_date[ext_d]

            sleeve_rets = []
            all_picks = set()
            lowmom_picks = set()
            treas_picks = set()

            # LOWMOM60 contributes 50%
            for _, picks in lowmom_sleeves:
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if rets:
                    sleeve_rets.append(0.5 * float(np.mean(rets)))
                    lowmom_picks.update(picks)
                    all_picks.update(picks)

            # Treasury contributes 50%
            for _, picks in treas_sleeves:
                rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                        if t in ent.index and t in ext.index and ent.loc[t] > 0]
                if rets:
                    sleeve_rets.append(0.5 * float(np.mean(rets)))
                    treas_picks.update(picks)
                    all_picks.update(picks)

            if not sleeve_rets:
                continue

            gr = float(np.sum(sleeve_rets))
            # Turnover: LOWMOM60 monthly (1.0 * 0.5), Treasury quarterly (1/3 * 0.5)
            monthly_rets.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                                 "turnover": 0.5 * 1.0 + 0.5 * (1.0/3.0),
                                 "roundtrips": 0.5 * 1.0 + 0.5 * (1.0/3.0),
                                 "holding_months": 1.5,
                                 "picks": all_picks,
                                 "lowmom_picks": lowmom_picks,
                                 "treas_picks": treas_picks})
        return monthly_rets

    # Run for each period
    results = {"LOWMOM60": {}, "TreasuryQuarterly": {}, "Combined_50_50": {}}
    overlap_data = {"LOWMOM60": {}, "TreasuryQuarterly": {}, "Combined_50_50": {}}

    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n=== Period: {p} ({len(period_dates)} months) ===")

        lowmom_rets = run_lowmom60(period_dates)
        treas_rets = run_treasury_quarterly(period_dates)
        comb_rets = run_combined(period_dates)

        results["LOWMOM60"][p] = profile(lowmom_rets)
        results["TreasuryQuarterly"][p] = profile(treas_rets)
        results["Combined_50_50"][p] = profile(comb_rets)

        # Overlap analysis
        lowmom_picks_all = set()
        treas_picks_all = set()
        for r in lowmom_rets:
            lowmom_picks_all.update(r.get("picks", set()))
        for r in treas_rets:
            treas_picks_all.update(r.get("picks", set()))

        # Monthly overlap
        monthly_overlaps = []
        for r in comb_rets:
            lm = r.get("lowmom_picks", set())
            tr = r.get("treas_picks", set())
            if lm or tr:
                monthly_overlaps.append(jaccard(lm, tr))
        avg_overlap = np.mean(monthly_overlaps) if monthly_overlaps else 0

        # Return correlation
        if lowmom_rets and treas_rets:
            min_len = min(len(lowmom_rets), len(treas_rets))
            low_ret = [r["ret"] for r in lowmom_rets[:min_len]]
            tr_ret = [r["ret"] for r in treas_rets[:min_len]]
            ret_corr = float(np.corrcoef(low_ret, tr_ret)[0, 1]) if min_len > 1 else 0
        else:
            ret_corr = 0

        overlap_data["LOWMOM60"][p] = {"avg_monthly_overlap": round(avg_overlap, 3),
                                         "return_corr_with_treasury": round(ret_corr, 3),
                                         "unique_tickers_lowmom": len(lowmom_picks_all),
                                         "unique_tickers_treasury": len(treas_picks_all)}

        print(f"  LOWMOM60: CAGR={results['LOWMOM60'][p].get('cagrNet',0):.2%} "
              f"Sharpe={results['LOWMOM60'][p].get('sharpe',0):.3f} "
              f"Turnover={results['LOWMOM60'][p].get('avgAnnualTurnover',0):.1f}x")
        print(f"  TreasuryQuarterly: CAGR={results['TreasuryQuarterly'][p].get('cagrNet',0):.2%} "
              f"Sharpe={results['TreasuryQuarterly'][p].get('sharpe',0):.3f} "
              f"Turnover={results['TreasuryQuarterly'][p].get('avgAnnualTurnover',0):.1f}x")
        print(f"  Combined_50_50: CAGR={results['Combined_50_50'][p].get('cagrNet',0):.2%} "
              f"Sharpe={results['Combined_50_50'][p].get('sharpe',0):.3f} "
              f"Turnover={results['Combined_50_50'][p].get('avgAnnualTurnover',0):.1f}x")
        print(f"  Overlap (Jaccard): {avg_overlap:.3f}, Return Corr: {ret_corr:.3f}")

    # Incremental analysis
    print("\n=== INCREMENTAL: Combined - LOWMOM60 ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        c = results["Combined_50_50"][p]
        b = results["LOWMOM60"][p]
        inc = {
            "cagrDiff": round(c.get("cagrNet", 0) - b.get("cagrNet", 0), 4),
            "sharpeDiff": round(c.get("sharpe", 0) - b.get("sharpe", 0), 4) if c.get("sharpe") and b.get("sharpe") else None,
            "mddDiff": round(c.get("mdd", 0) - b.get("mdd", 0), 4),
            "grossCagrDiff": round(c.get("grossCAGR", 0) - b.get("grossCAGR", 0), 4) if c.get("grossCAGR") and b.get("grossCAGR") else None,
            "netCagrDiff": round(c.get("cagrNet", 0) - b.get("cagrNet", 0), 4),
            "turnoverDiff": round(c.get("avgAnnualTurnover", 0) - b.get("avgAnnualTurnover", 0), 2),
        }
        print(f"  {p}: CAGR={inc['cagrDiff']:.2%} Sharpe={inc['sharpeDiff']:.3f} "
              f"MDD={inc['mddDiff']:.2%} GrossCAGR={inc['grossCagrDiff']:.2%} "
              f"Turnover={inc['turnoverDiff']:.1f}x")
        results[f"Incremental_{p}"] = inc

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    inc_train = results["Incremental_TRAIN"]
    inc_valid = results["Incremental_VALID"]
    inc_test = results["Incremental_TEST"]

    cagr_signs = [inc_train["cagrDiff"], inc_valid["cagrDiff"], inc_test["cagrDiff"]]
    all_positive = all(x > 0 for x in cagr_signs)
    all_negative = all(x < 0 for x in cagr_signs)
    test_only = cagr_signs[2] > 0 and (cagr_signs[0] <= 0 or cagr_signs[1] <= 0)

    if all_positive and inc_train["sharpeDiff"] > 0 and inc_valid["sharpeDiff"] > 0 and inc_test["sharpeDiff"] > 0:
        judgment = "PASS"
    elif test_only:
        judgment = "WEAK"
    else:
        judgment = "REJECT"

    print(f"TRAIN inc CAGR: {inc_train['cagrDiff']:.2%}, Sharpe: {inc_train['sharpeDiff']:.3f}, MDD: {inc_train['mddDiff']:.2%}")
    print(f"VALID inc CAGR: {inc_valid['cagrDiff']:.2%}, Sharpe: {inc_valid['sharpeDiff']:.3f}, MDD: {inc_valid['mddDiff']:.2%}")
    print(f"TEST inc CAGR:  {inc_test['cagrDiff']:.2%}, Sharpe: {inc_test['sharpeDiff']:.3f}, MDD: {inc_test['mddDiff']:.2%}")
    print(f"\n>>> JUDGMENT: {judgment} <<<")

    if judgment == "PASS":
        next_exp = "10-KR-23-5: Optimize TreasuryRatio + LOWMOM60 weight (not 50/50 fixed)"
    elif judgment == "WEAK":
        next_exp = "10-KR-23-5: Investigate why Treasury helps only in TEST (regime?)"
    else:
        next_exp = "10-KR-23-5: Test TreasuryRatio with other baselines (PBR, REV20)"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-4: TreasuryRatio + LOWMOM60 incremental validation",
        "results": results,
        "overlap": overlap_data,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-lowmom60-combined-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()