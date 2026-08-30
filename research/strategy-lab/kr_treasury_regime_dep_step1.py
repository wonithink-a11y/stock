#!/usr/bin/env python
"""10-KR-23-13 STEP 1: Regime-Dependent Performance Analysis.

Analyzes Treasury6M and LOWMOM60 performance by market regime.
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
    return {"n": n, "cagrNet": round(cn, 4),
            "sharpe": round(sh, 4) if sh is not None else None, "mdd": round(mdd, 4)}


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
    print(f"  Regimes: {regime_lut.value_counts().to_dict()}")

    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}

    # Liquid universe
    liq = m[m["turnover20"] >= MIN_TURNOVER].copy()

    def get_regime_for_entry(sd):
        ent_d = next((x for x in all_dates if x > sd), None)
        if ent_d is None:
            return None
        return regime_lut.get(ent_d, None)

    # === Run strategies by period and regime ===
    regimes = ["Risk-On", "Neutral", "Risk-Off"]
    results = {"LOWMOM60": {p: {r: [] for r in regimes} for p in ["TRAIN", "VALID", "TEST"]},
               "Treasury6M": {p: {r: [] for r in regimes} for p in ["TRAIN", "VALID", "TEST"]}}

    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        print(f"\n=== Period: {p} ({len(period_dates)} months) ===")

        # LOWMOM60 monthly
        for k, sd in enumerate(period_dates):
            if k + 1 >= len(period_dates):
                break
            regime = get_regime_for_entry(sd)
            if regime not in regimes:
                continue
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
            results["LOWMOM60"][p][regime].append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr})

        # Treasury6M quarterly (6M hold = 2 quarters)
        rebal_dates = [d for d in qmonths if d in period_dates]
        for k, sd in enumerate(rebal_dates):
            if k + 2 >= len(rebal_dates):
                break
            regime = get_regime_for_entry(sd)
            if regime not in regimes:
                continue
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
            ext_d = rebal_dates[k + 2]  # 6M = 2 quarters
            ent = close_by_date[ent_d]
            ext = close_by_date[ext_d]
            rets = [ext.loc[t] / ent.loc[t] - 1.0 for t in picks
                    if t in ent.index and t in ext.index and ent.loc[t] > 0]
            if not rets:
                continue
            gr = float(np.mean(rets))
            results["Treasury6M"][p][regime].append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr})

    # === Analyze by regime ===
    print("\n=== REGIME PERFORMANCE SUMMARY ===")
    summary = {}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        summary[p] = {}
        for strategy in ["LOWMOM60", "Treasury6M"]:
            summary[p][strategy] = {}
            for r in regimes:
                rets = results[strategy][p][r]
                prof = profile(rets)
                summary[p][strategy][r] = prof
                n = prof.get("n", 0)
                cagr = prof.get("cagrNet")
                sharpe = prof.get("sharpe")
                small_sample = " [SMALL SAMPLE]" if n < 5 else ""
                cagr_str = f"{cagr:.2%}" if cagr is not None else "NA"
                sharpe_str = f"{sharpe:.3f}" if sharpe is not None else "NA"
                print(f"  {strategy} {p} {r}: n={n} CAGR={cagr_str} Sharpe={sharpe_str}{small_sample}")

    # === Treasury vs LOWMOM60 comparison by regime ===
    print("\n=== TREASURY6M vs LOWMOM60 BY REGIME ===")
    treasury_better = {p: {r: False for r in regimes} for p in ["TRAIN", "VALID", "TEST"]}
    
    for p in ["TRAIN", "VALID", "TEST"]:
        print(f"\n{p}:")
        for r in regimes:
            lm = summary[p]["LOWMOM60"][r]
            tr = summary[p]["Treasury6M"][r]
            lm_n = lm.get("n", 0)
            tr_n = tr.get("n", 0)
            lm_cagr = lm.get("cagrNet")
            tr_cagr = tr.get("cagrNet")
            lm_sharpe = lm.get("sharpe")
            tr_sharpe = tr.get("sharpe")
            
            better = False
            if lm_cagr is not None and tr_cagr is not None and tr_n >= 3:
                better = tr_cagr > lm_cagr
                treasury_better[p][r] = better
            
            lm_str = f"CAGR={lm_cagr:.2%} Sharpe={lm_sharpe:.3f}" if lm_cagr else "NA"
            tr_str = f"CAGR={tr_cagr:.2%} Sharpe={tr_sharpe:.3f}" if tr_cagr else "NA"
            better_str = "Treasury" if better else ("LOWMOM60" if lm_cagr is not None and tr_cagr is not None else "?")
            small = " [SMALL]" if tr_n < 5 else ""
            print(f"  {r}: LOWMOM60 {lm_str} (n={lm_n}) | Treasury6M {tr_str} (n={tr_n}) -> {better_str}{small}")

    # === Overall assessment ===
    print("\n=== REGIME-DEPENDENT PATTERN ASSESSMENT ===")
    
    # Check if any regime consistently favors Treasury across periods
    for r in regimes:
        print(f"\n{r}:")
        for p in ["TRAIN", "VALID", "TEST"]:
            tr = summary[p]["Treasury6M"][r]
            lm = summary[p]["LOWMOM60"][r]
            tr_cagr = tr.get("cagrNet")
            lm_cagr = lm.get("cagrNet")
            tr_n = tr.get("n", 0)
            if tr_cagr is not None and lm_cagr is not None:
                diff = tr_cagr - lm_cagr
                print(f"  {p}: ΔCAGR={diff:+.2%} (Treas n={tr_n})")
            else:
                print(f"  {p}: Insufficient data (Treas n={tr_n})")

    # Sample size warning
    print("\n=== SAMPLE SIZE WARNING ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        for r in regimes:
            tr_n = summary[p]["Treasury6M"][r].get("n", 0)
            lm_n = summary[p]["LOWMOM60"][r].get("n", 0)
            if tr_n < 5 or lm_n < 5:
                print(f"  [SMALL] {p} {r}: Treasury n={tr_n}, LOWMOM60 n={lm_n}")

    # Next step decision
    print("\n=== NEXT STEP DECISION ===")
    # Check if there's a regime where Treasury consistently outperforms with adequate samples
    consistent_treasury = False
    for r in regimes:
        wins = 0
        valid_periods = 0
        for p in ["TRAIN", "VALID", "TEST"]:
            tr_n = summary[p]["Treasury6M"][r].get("n", 0)
            lm_n = summary[p]["LOWMOM60"][r].get("n", 0)
            if tr_n >= 5 and lm_n >= 5:
                valid_periods += 1
                tr_cagr = summary[p]["Treasury6M"][r].get("cagrNet")
                lm_cagr = summary[p]["LOWMOM60"][r].get("cagrNet")
                if tr_cagr is not None and lm_cagr is not None and tr_cagr > lm_cagr:
                    wins += 1
        if valid_periods >= 2 and wins == valid_periods:
            consistent_treasury = True
            print(f"  {r}: Treasury consistently better in {wins}/{valid_periods} periods (n>=5)")

    if consistent_treasury:
        next_step = "YES - Proceed to STEP 2: Test regime-dependent fixed weights (e.g., 70/30 in Treasury-favored regime)"
        decision = "PROCEED"
    else:
        next_step = "NO - No regime shows consistent Treasury superiority with adequate samples"
        decision = "STOP"

    print(f"\nDecision: {decision}")
    print(f"Next: {next_step}")

    result = {
        "experiment": "10-KR-23-13 STEP 1: Regime-dependent performance analysis",
        "summary": {p: {s: {r: prof for r, prof in summary[p][s].items()} for s in summary[p]} for p in summary},
        "treasury_better": treasury_better,
        "decision": decision,
        "next_step": next_step,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-regime-dep-step1-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()