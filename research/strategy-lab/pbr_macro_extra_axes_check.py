#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PBR-EW 월별 초과수익 — 미검증 macro 6축 확장 검증 (2026-08).

배경: pbr_macro_rate_regime_check.py(2026-08-23)가 usTreasury10y·krTreasury3y·
krCreditSpreadBp 3축만 검증했다. market_regime_features.parquet에는 아직 안 쓴
축이 6개 더 있다(usFedFundsRate·usNasdaq·krKospi·krCpi·krLeadingCyclical·
krCoincidentCyclical). 이 스크립트는 원본과 **완전히 같은 방법론**을 그 6축에
그대로 적용한다 — 새 설계·임계값 결정 없음, 이미 검증된 패턴의 축 확장 반복.

방법: 원본과 동일하게 pbr_vs_ew_monthly_mtm.py의 schedule_with_monthly_mtm을
무변경 재사용해 월별 MTM 초과수익(PBR-EW)을 재현하고, 각 축의 trailing
126거래일(~6개월) 변화(col - col.shift(126), threshold >0)로 버킷을 나눠
합계·평균·연도별 breakdown을 본다. TRAIL_DAYS=126 사전고정(재최적화 없음),
production 코드·정책 무변경.

  python pbr_macro_extra_axes_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
TRAIL_DAYS = 126  # ~6개월 거래일, 사전 고정(pbr_macro_rate_regime_check와 동일, 재최적화 없음)
REGIME_PARQUET = os.path.join(REPO_ROOT, "research", "strategy-lab", "data",
                              "market-regime", "market_regime_features.parquet")

EXTRA_AXES = [
    ("usFedFundsRate", "미국 연방기금금리(6개월 변화)"),
    ("usNasdaq", "나스닥 지수(6개월 변화)"),
    ("krKospi", "KOSPI 지수(6개월 변화)"),
    ("krCpi", "한국 CPI(6개월 변화)"),
    ("krLeadingCyclical", "한국 선행순환지수(6개월 변화)"),
    ("krCoincidentCyclical", "한국 일반순환지수(6개월 변화)"),
]


def monthly_snapshots(strategy_id):
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    return snapshots


def monthly_returns(snapshots):
    dates = [d for d, _ in snapshots[1:]]  # t0 baseline row 제외
    eqs = [e for _, e in snapshots]
    rets = [eqs[i] / eqs[i - 1] - 1.0 for i in range(1, len(eqs))]
    return pd.DataFrame({"date": dates, "ret": rets})


def extra_axis_features():
    """market_regime_features.parquet에서 미검증 6축의 trailing 126거래일 변화를
    계산. 사전고정 규칙 — 원본 3축 조사와 같은 창(col - col.shift(TRAIL_DAYS))."""
    cols = ["date"] + [c for c, _ in EXTRA_AXES]
    df = pd.read_parquet(REGIME_PARQUET)[cols].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for col, _ in EXTRA_AXES:
        df[col + "Chg6m"] = df[col] - df[col].shift(TRAIL_DAYS)
    return df


def bucket_report(excess_df, regime_df, chg_col, label):
    """excess_df: [date, excess]. regime_df: [date, <chg_col>]. asof 조인 후
    up(변화>0)/not으로 나눠 합계·평균·기여율을 리포트 — 원본 bucket_report와
    동일 로직."""
    left = excess_df.sort_values("date").copy()
    right = regime_df[["date", chg_col]].sort_values("date").copy()
    left["date"] = pd.to_datetime(left["date"])
    right["date"] = pd.to_datetime(right["date"])
    merged = pd.merge_asof(left, right, on="date", direction="backward")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged = merged.dropna(subset=[chg_col])
    hiking = merged[merged[chg_col] > 0]
    not_hiking = merged[merged[chg_col] <= 0]
    total_excess = merged["excess"].sum()
    hiking_excess = hiking["excess"].sum()
    return {
        "label": label,
        "months_total": int(len(merged)),
        "months_up": int(len(hiking)),
        "months_not_up": int(len(not_hiking)),
        "totalExcessSum": round(float(total_excess), 5),
        "upExcessSum": round(float(hiking_excess), 5),
        "notUpExcessSum": round(float(not_hiking["excess"].sum()), 5),
        "upSharePct": round(float(hiking_excess / total_excess * 100), 2) if total_excess != 0 else None,
        "upMeanMonthly": round(float(hiking["excess"].mean()), 5) if len(hiking) else None,
        "notUpMeanMonthly": round(float(not_hiking["excess"].mean()), 5) if len(not_hiking) else None,
    }, merged


def year_breakdown(merged, chg_col):
    merged = merged.copy()
    merged["year"] = merged["date"].str.slice(0, 4)
    out = {}
    for y, g in merged.groupby("year"):
        out[y] = {
            "monthsUp": int((g[chg_col] > 0).sum()),
            "monthsTotal": int(len(g)),
            "excessSum": round(float(g["excess"].sum()), 5),
        }
    return out


def main():
    t0 = time.time()
    print("=== PBR-EW 월별 MTM 재현 (pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용) ===")
    pbr_snap = monthly_snapshots("pbr_value_v1")
    ew_snap = monthly_snapshots("ew_benchmark_liquid_v1")
    print("  PBR 스냅샷 %d개, EW 스냅샷 %d개 (%.0fs)" % (len(pbr_snap), len(ew_snap), time.time() - t0))

    pbr_ret = monthly_returns(pbr_snap)
    ew_ret = monthly_returns(ew_snap)
    merged_ret = pbr_ret.merge(ew_ret, on="date", suffixes=("_pbr", "_ew"))
    merged_ret["excess"] = merged_ret["ret_pbr"] - merged_ret["ret_ew"]
    print("  월별 초과수익(PBR-EW) %d개월, 합계=%.4f(로그아님 단순합)"
          % (len(merged_ret), merged_ret["excess"].sum()))

    regime_df = extra_axis_features()

    results = {}
    year_breakdowns = {}
    for col, label in EXTRA_AXES:
        chg_col = col + "Chg6m"
        rep, merged = bucket_report(merged_ret[["date", "excess"]], regime_df, chg_col, label)
        results[chg_col] = rep
        year_breakdowns[chg_col] = year_breakdown(merged, chg_col)
        print("\n[%s]" % label)
        print("  전체 %d개월(up %d · not %d)"
              % (rep["months_total"], rep["months_up"], rep["months_not_up"]))
        print("  총초과수익=%.4f, up구간 기여=%.4f(%.1f%%)"
              % (rep["totalExcessSum"], rep["upExcessSum"], rep["upSharePct"] or 0))
        print("  up 월평균=%.5f vs not-up 월평균=%.5f"
              % (rep["upMeanMonthly"] or 0, rep["notUpMeanMonthly"] or 0))

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": "PBR-EW 월별 초과수익의 미검증 macro 6축 확장 검증 - "
                   "pbr_macro_rate_regime_check.py와 동일 방법론의 축 확장 반복",
        "trailDays": TRAIL_DAYS,
        "period": [START, END],
        "monthlyExcessCount": int(len(merged_ret)),
        "results": results,
        "yearBreakdown": year_breakdowns,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-24-pbr-macro-extra-axes")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-macro-extra-axes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
