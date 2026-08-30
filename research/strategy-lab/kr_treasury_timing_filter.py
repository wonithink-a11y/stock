#!/usr/bin/env python
"""10-KR-23-7: TreasuryRatio Quarterly with KOSPI 200D Trend Filter.

Baseline: TreasuryQuarterly (always invested)
Timing: TreasuryQuarterly + KOSPI 200D trend filter (invest only when KOSPI > SMA200)
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
KOSPI_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime", "krkospi_raw.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-29-kr-treasury-timing-filter-60d")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30
COST_BPS = 15.0
ROUNDTRIP_BPS = 2 * COST_BPS


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
    for n, col in [(5, "f5"), (20, "f20"), (60, "f60"), (120, "f120")]:
        df[col] = g.shift(-n) / df["close"] - 1.0
    df["turnover20"] = (df["close"] * df["total_volume"]).groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])
    close_by_date = {d: gd.set_index("ticker")["close"] for d, gd in df.groupby("date")}
    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    qmonths = quarterly_reb(all_dates)

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

    base = df[df["date"].isin(months)][["ticker", "date", "turnover20",
                                         "f5", "f20", "f60", "f120"]].copy()
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

    # Load KOSPI data
    print("Loading KOSPI data...")
    kospi = pd.read_parquet(KOSPI_PATH)
    kospi["date"] = kospi["date"].astype(str)
    kospi = kospi.sort_values("date").reset_index(drop=True)
    kospi_dates = kospi["date"].tolist()
    kospi_values = kospi["value"].tolist()
    kospi_idx = {d: i for i, d in enumerate(kospi_dates)}
    print(f"  KOSPI: {len(kospi)} rows, {kospi_dates[0]} to {kospi_dates[-1]}")

    # Pre-compute KOSPI 60D SMA for each quarterly rebalance date
    # SMA is computed using data strictly before Q_date
    sma_cache = {}
    for qd in qmonths:
        if qd not in kospi_idx:
            # Find closest prior trading day in KOSPI data
            prior = [d for d in kospi_dates if d <= qd]
            if not prior:
                sma_cache[qd] = None
                continue
            qd = prior[-1]
        idx = kospi_idx[qd]
        if idx < 60:
            # Not enough history -> allow by default
            sma_cache[qd] = -1  # Will always be > -1
            continue
        # Use 60 trading days strictly before Q_date
        sma = np.mean(kospi_values[idx-60:idx])
        close = kospi_values[idx]
        sma_cache[qd] = {"close": close, "sma60": sma, "allow": close > sma}

    # Run TreasuryQuarterly with and without timing filter
    results = {"Baseline": {}, "TimingFilter": {}}

    for p in ["TRAIN", "VALID", "TEST"]:
        period_dates = [d for d in months if period_of(d) == p]
        rebal_dates = [d for d in qmonths if d in period_dates]
        print(f"\n=== Period: {p} ({len(rebal_dates)} quarters) ===")

        for variant in ["Baseline", "TimingFilter"]:
            out = []
            cash_months = 0
            invested_months = 0
            for k, sd in enumerate(rebal_dates):
                if k + 1 >= len(rebal_dates):
                    break
                # Check trend filter
                if variant == "TimingFilter":
                    trend_info = sma_cache.get(sd)
                    if trend_info is not None and isinstance(trend_info, dict):
                        if not trend_info["allow"]:
                            # Risk-Off: Treasury sleeve goes to cash (0 return)
                            out.append({"ret": 0.0, "gross_ret": 0.0,
                                        "turnover": 0.0, "roundtrips": 0.0, "holding_months": 3,
                                        "regime": "Risk-Off"})
                            cash_months += 1
                            continue
                    elif trend_info is None:
                        # No KOSPI data for this date -> skip (shouldn't happen)
                        pass
                    invested_months += 1

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
                out.append({"ret": gr - ROUNDTRIP_BPS / 10000, "gross_ret": gr,
                            "turnover": 1.0/3.0, "roundtrips": 1.0/3.0, "holding_months": 3,
                            "regime": "Risk-On" if variant == "TimingFilter" else "Always"})

            prof = profile(out)
            prof["cash_months"] = cash_months
            prof["invested_months"] = invested_months
            results[variant][p] = prof
            if prof.get("n", 0) > 1:
                print(f"  {variant}: CAGR={prof['cagrNet']:.2%} Sharpe={prof['sharpe']:.3f} "
                      f"MDD={prof['mdd']:.2%} n={prof['n']} "
                      f"cash={cash_months} invested={invested_months}")

    # Summary comparison
    print("\n=== COMPARISON: Baseline vs TimingFilter ===")
    for p in ["TRAIN", "VALID", "TEST"]:
        b = results["Baseline"][p]
        t = results["TimingFilter"][p]
        if b.get("n", 0) > 1 and t.get("n", 0) > 1:
            print(f"{p}:")
            print(f"  Baseline:     CAGR={b['cagrNet']:.2%} Sharpe={b['sharpe']:.3f} MDD={b['mdd']:.2%} n={b['n']}")
            print(f"  TimingFilter: CAGR={t['cagrNet']:.2%} Sharpe={t['sharpe']:.3f} MDD={t['mdd']:.2%} n={t['n']} "
                  f"(cash={t.get('cash_months',0)}/{t.get('invested_months',0)+t.get('cash_months',0)})")
            print(f"  Delta:        CAGR={t['cagrNet']-b['cagrNet']:+.2%} Sharpe={t['sharpe']-b['sharpe']:+.3f} "
                  f"MDD={t['mdd']-b['mdd']:+.2%}")

    # Final judgment
    print("\n=== FINAL JUDGMENT ===")
    deltas = {p: results["TimingFilter"][p].get("cagrNet", 0) - results["Baseline"][p].get("cagrNet", 0) for p in ["TRAIN", "VALID", "TEST"]}
    print(f"CAGR Delta: TRAIN={deltas['TRAIN']:+.2%} VALID={deltas['VALID']:+.2%} TEST={deltas['TEST']:+.2%}")
    
    all_positive = all(d > 0 for d in deltas.values())
    all_negative = all(d < 0 for d in deltas.values())
    mixed = not all_positive and not all_negative
    
    if all_positive:
        judgment = "PASS - Timing filter improves all periods"
    elif all_negative:
        judgment = "REJECT - Timing filter harms all periods"
    else:
        judgment = "WEAK - Mixed results across periods"

    print(f">>> JUDGMENT: {judgment} <<<")

    if judgment.startswith("PASS"):
        next_exp = "10-KR-23-8: Test combined LOWMOM60 + TreasuryQuarterly with trend filter"
    elif judgment.startswith("REJECT"):
        next_exp = "10-KR-23-8: Test TreasuryRatio with alternative timing (VIX, 60D MA)"
    else:
        next_exp = "10-KR-23-8: Analyze which regime drives mixed timing filter results"

    print(f"Next experiment suggestion: {next_exp}")

    result = {
        "experiment": "10-KR-23-8: TreasuryRatio with KOSPI 60D trend filter",
        "results": results,
        "judgment": judgment,
        "next_experiment": next_exp,
        "executionTime_s": round(time.time() - t0, 1)
    }
    out_path = os.path.join(OUT_DIR, "kr-treasury-timing-filter-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()