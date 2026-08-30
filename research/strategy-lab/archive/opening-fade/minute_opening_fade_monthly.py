#!/usr/bin/env python
"""오더닝 페이드 Q5-Q1 스프레드의 월별 분해 ([RESEARCH HYPOTHESIS]) - 실험 4.

배경: PBR에서 "전체 기간 우위의 98.6%가 단 한 해(2022)"를 나중에 발견한 전례처럼,
minute-opening-fade의 250일 합산 스프레드가 특정 몇 달에 지배되는지 확인한다.

방법: minute_opening_fade_study와 동일한 정의(r05 5분위, 결과=09:05→종가,
날짜 동일가중 벤치마크). 월별 스프레드 = 그 달 날짜들의 (Q5평균초과 − Q1평균초과)
날짜 동일가중 평균. 상위 기여월(가장 음(-)인 월) 2개/3개 제외 후 나머지 기간
스프레드의 부호 유지 여부를 확인한다. threshold 튜닝 없음.

  python minute_opening_fade_monthly.py
"""
import glob
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from minute_opening_fade_study import day_frame  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MINUTE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-opening-fade-monthly")


def main():
    t0 = time.time()
    date_dirs = sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*")))
    chunks, n_days = [], 0
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is None or fr.empty:
            continue
        chunks.append(fr)
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {n_days} days ({time.time()-t0:.0f}s)", flush=True)
    df = pd.concat(chunks, ignore_index=True)
    print(f"ticker-days={len(df)}, days={n_days} ({time.time()-t0:.0f}s)", flush=True)

    base = df[df["p0900"].notna() & df["p0905"].notna() & df["p1530"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["r05"] = base["p0905"] / base["p0900"] - 1
    base["rclose"] = base["p1530"] / base["p0905"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
    base["month"] = base["date"].str[:7]

    bench = base.groupby("date")["rclose"].mean().rename("bench")
    dq = base.merge(bench, on="date")
    dq["excess"] = dq["rclose"] - dq["bench"]

    rows = []
    for month, gm in dq.groupby("month"):
        q1 = gm[gm["q"] == 1].groupby("date")["excess"].mean()
        q5 = gm[gm["q"] == 5].groupby("date")["excess"].mean()
        spread_dates = (q5 - q1).dropna()
        rows.append({
            "month": month,
            "nDates": int(len(spread_dates)),
            "avgTickersPerDayQ": round(float(gm.groupby("date").size().mean()), 1),
            "q1MeanExcessBp": round(float(q1.mean()) * 100, 3),
            "q5MeanExcessBp": round(float(q5.mean()) * 100, 3),
            "spreadQ5mQ1Bp": round(float((q5 - q1).mean()) * 100, 3),
        })
    monthly = pd.DataFrame(rows).sort_values("month")

    overall_spread = float(monthly["spreadQ5mQ1Bp"].mean())
    ranked = monthly.sort_values("spreadQ5mQ1Bp")  # 가장 음(-)인 월부터
    excl2 = ranked.iloc[2:]
    excl3 = ranked.iloc[3:]
    robustness = {
        "overallSpreadBp_dateEqualWeight": round(overall_spread, 3),
        "topContributionMonths": list(ranked.iloc[:3]["month"]),
        "excludeTop2_remainingSpreadBp": round(float(excl2["spreadQ5mQ1Bp"].mean()), 3),
        "excludeTop2_monthsKept": int(len(excl2)),
        "excludeTop3_remainingSpreadBp": round(float(excl3["spreadQ5mQ1Bp"].mean()), 3),
        "excludeTop3_monthsKept": int(len(excl3)),
    }
    print("monthly:")
    print(monthly.to_string(index=False), flush=True)
    print("robustness:", json.dumps(robustness, ensure_ascii=False), flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "purpose": "오더닝 페이드 Q5-Q1 스프레드(09:05->close)의 월별 분해 + "
                       "상위 기여월 제외 후 부호 유지 검증",
            "definitions": "minute_opening_fade_study.py와 동일; 스프레드=월 내 날짜 동일가중 "
                           "(Q5평균초과 - Q1평균초과)",
            "diagnostics": {"days": int(n_days), "tickerDaysValid": int(len(dq))},
            "monthly": rows,
            "robustness": robustness,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
