#!/usr/bin/env python
"""kr_treasury_signal_decay_nw.py — kr_treasury_signal_decay.py의 IC t-stat을
Newey-West(HAC) 보정으로 재계산.

배경: 원본(archive/kr-treasury-regime/kr_treasury_signal_decay.py)의 ic_t는
매달 계산한 스피어만 IC를 독립표본처럼 취급한 naive t(mean/(std/sqrt(n)))였다.
fwd_d60(6M)·fwd_d120(9M) 선행수익률을 매달 겹치게 계산했으니 인접 관측치가
심하게 자기상관돼 있다(9M은 인접 두 달이 9개월 중 8개월을 공유) - DD252
팩터에서 이미 한 번 걸러낸 것과 같은 함정. 데이터 로딩·TreasuryRatio 계산은
원본과 완전히 동일(재현성 보장), t-stat만 statsmodels HAC로 교체한다.

lag 선택: 표준 관례대로 horizon(개월)-1을 기본으로 쓴다(3M→2, 6M→5, 9M→8,
Hansen-Hodrick 스타일). 데이터 기반 규칙(Newey-West 1994, 4*(n/100)^(2/9))도
같이 계산해 lag 선택 자체가 결론을 바꾸는지 확인한다.
"""
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A3C_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3c")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-09-02-kr-treasury-signal-decay-nw")

TRAIN_END = "2022-06-30"
VALID_END = "2024-01-01"
MIN_NAMES = 30


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
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


def nw_t(series, maxlags):
    """평균이 0인지 HAC(Newey-West) 표준오차로 검정 - 상수항만 있는 OLS의 HAC t값."""
    x = np.asarray(series, dtype=float)
    n = len(x)
    if n < 3:
        return None
    maxlags = max(0, min(maxlags, n - 2))
    model = sm.OLS(x, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return float(model.tvalues[0]), maxlags


def nw_lag_datadriven(n):
    return int(np.floor(4 * (n / 100) ** (2 / 9)))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_volume", "fwd_d20", "fwd_d60", "fwd_d120"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    df["turnover20"] = (df["close"] * df["total_volume"]).groupby(df["ticker"]).transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    df = df.dropna(subset=["turnover20"])

    print("Loading raw A3c (treasuryRatio)...", flush=True)
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

    base = df[df["date"].isin(months)][["ticker", "date", "turnover20", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
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
    print(f"  treasuryRatio merged: {len(m)} rows ({time.time()-t0:.0f}s)", flush=True)

    horizons = {"3M": ("fwd_d20", 3), "6M": ("fwd_d60", 6), "9M": ("fwd_d120", 9)}
    results = {}

    print(f"\n{'Period':6s} | {'Horizon':5s} | {'IC_mean':>8s} | {'naive_t':>8s} | "
          f"{'NW_t(k-1)':>10s} | {'lag':>4s} | {'NW_t(datadrv)':>13s} | {'lag2':>4s} | {'n':>4s}")
    print("-" * 100)
    for p in ["TRAIN", "VALID", "TEST"]:
        dates = [d for d in months if period_of(d) == p]
        results[p] = {}
        for h_name, (h_col, h_months) in horizons.items():
            recs = []
            for sd in dates:
                this = m[m["date"] == sd].dropna(subset=["treasuryRatio", h_col])
                if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
                    continue
                r = spearmanr(this["treasuryRatio"], this[h_col])
                if not np.isnan(r.statistic):
                    recs.append(float(r.statistic))
            if not recs:
                results[p][h_name] = {"n": 0}
                continue
            v = np.array(recs)
            n = len(v)
            naive_t = float(v.mean() / (v.std(ddof=1) / np.sqrt(n))) if v.std(ddof=1) > 0 else None
            lag1 = h_months - 1
            nw_t1, used_lag1 = nw_t(v, lag1)
            lag2 = nw_lag_datadriven(n)
            nw_t2, used_lag2 = nw_t(v, lag2)
            results[p][h_name] = {
                "n": n, "ic_mean": round(float(v.mean()), 6),
                "naive_t": round(naive_t, 3) if naive_t is not None else None,
                "nw_t_horizonMinus1": round(nw_t1, 3), "lag_horizonMinus1": used_lag1,
                "nw_t_datadriven": round(nw_t2, 3), "lag_datadriven": used_lag2,
            }
            r = results[p][h_name]
            print(f"{p:6s} | {h_name:5s} | {r['ic_mean']:>8.4f} | {r['naive_t']:>8.2f} | "
                  f"{r['nw_t_horizonMinus1']:>10.2f} | {r['lag_horizonMinus1']:>4d} | "
                  f"{r['nw_t_datadriven']:>13.2f} | {r['lag_datadriven']:>4d} | {n:>4d}", flush=True)

    out_path = os.path.join(OUT_DIR, "kr-treasury-signal-decay-nw-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"purpose": "naive t-stat -> Newey-West(HAC) 재계산, "
                              "kr_treasury_signal_decay.py 재현성 확인 겸용",
                   "results": results, "executionTime_s": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
