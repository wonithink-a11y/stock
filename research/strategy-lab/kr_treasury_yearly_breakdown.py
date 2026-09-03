#!/usr/bin/env python
"""kr_treasury_yearly_breakdown.py — TreasuryRatio 신호를 연도별로 쪼개서
승률·평균수익률·Q5-Q1 스프레드를 본다.

배경: 이 프로젝트가 PBR에서 겪은 패턴 - 전체기간·TEST구간 합산으로는 신호가
강해 보여도 실은 특정 연도 하나(2022년, 로그초과수익의 98.6%)에 몰려 있었다.
TreasuryRatio도 TEST(2024-01~2026-08)가 유독 강했으니 같은 방식으로
연도별 분해를 먼저 봐야 한다.

데이터 파이프라인은 kr_treasury_signal_decay_nw.py와 동일(재현성 보장),
집계만 연도 단위로 바꾼다. 승률은 "그 달 Q5(top) 선행수익률이 양수였던
달의 비율"과 "Q5가 Q1(bottom)을 이긴 달의 비율" 둘 다 낸다.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-09-02-kr-treasury-yearly")

MIN_NAMES = 30


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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print("Loading A4...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_volume", "fwd_d20", "fwd_d60", "fwd_d120"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

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

    horizons = {"3M": "fwd_d20", "6M": "fwd_d60", "9M": "fwd_d120"}
    monthly_rows = []  # 연도별 집계 전에 월별 원자료를 먼저 쌓는다(재사용·검증 용이)
    for sd in months:
        this = m[m["date"] == sd].dropna(subset=["treasuryRatio"])
        if len(this) < MIN_NAMES or this["treasuryRatio"].nunique() <= 1:
            continue
        this = this.copy()
        this["q"] = pd.qcut(this["treasuryRatio"].rank(method="first"), 5, labels=False, duplicates="drop")
        rec = {"date": sd, "year": sd[:4], "n": len(this)}
        for h_name, h_col in horizons.items():
            sub = this.dropna(subset=[h_col])
            if sub.empty or sub["q"].nunique() < 5:
                rec[f"{h_name}_q5"] = None
                rec[f"{h_name}_q1"] = None
                continue
            q5 = sub.loc[sub["q"] == 4, h_col].mean()
            q1 = sub.loc[sub["q"] == 0, h_col].mean()
            rec[f"{h_name}_q5"] = float(q5) if pd.notna(q5) else None
            rec[f"{h_name}_q1"] = float(q1) if pd.notna(q1) else None
        monthly_rows.append(rec)
    monthly_df = pd.DataFrame(monthly_rows)
    print(f"  monthly signal rows: {len(monthly_df)}", flush=True)

    yearly = {}
    print(f"\n{'Year':6s} | {'nMon':4s} | "
          + " | ".join(f"{h}_Q5avg  {h}_Q5win%  {h}_Q5>Q1%" for h in horizons))
    for year, g in monthly_df.groupby("year"):
        yearly[year] = {"nMonths": len(g)}
        line = f"{year:6s} | {len(g):4d} | "
        parts = []
        for h_name in horizons:
            q5 = g[f"{h_name}_q5"].dropna()
            q1 = g[f"{h_name}_q1"].dropna()
            paired = g.dropna(subset=[f"{h_name}_q5", f"{h_name}_q1"])
            q5_mean = float(q5.mean()) if len(q5) else None
            q5_winrate = float((q5 > 0).mean()) if len(q5) else None
            beat_rate = float((paired[f"{h_name}_q5"] > paired[f"{h_name}_q1"]).mean()) if len(paired) else None
            yearly[year][h_name] = {
                "n": int(len(q5)), "q5Mean": round(q5_mean, 4) if q5_mean is not None else None,
                "q5WinRate": round(q5_winrate, 3) if q5_winrate is not None else None,
                "q5BeatQ1Rate": round(beat_rate, 3) if beat_rate is not None else None,
                "q1Mean": round(float(q1.mean()), 4) if len(q1) else None,
            }
            parts.append(f"{q5_mean*100 if q5_mean is not None else float('nan'):>7.2f}%  "
                          f"{q5_winrate*100 if q5_winrate is not None else float('nan'):>6.1f}%  "
                          f"{beat_rate*100 if beat_rate is not None else float('nan'):>6.1f}%")
        print(line + " | ".join(parts), flush=True)

    out_path = os.path.join(OUT_DIR, "kr-treasury-yearly-breakdown.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"purpose": "TreasuryRatio Q5(top20%) 연도별 승률·평균수익률·Q5>Q1 비율 - "
                              "PBR 2022년 집중 사례와 같은 방식으로 특정 연도 쏠림 확인",
                   "yearly": yearly, "executionTime_s": round(time.time() - t0, 1)},
                  f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
