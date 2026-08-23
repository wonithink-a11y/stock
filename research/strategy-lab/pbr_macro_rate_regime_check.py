#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PBR 2022년 집중 현상 — 금리인상 regime 조건부 가설 검증 (2026-08).

배경: pbr_vs_ew_monthly_mtm.py(2026-08-22, 실제 엔진 MTM)로 확정된 PBR-EW
CAGR 격차(+1.68%p)를 로그수익률로 연도분해하니 2022년 한 해가 98.6%를 차지했다
(세션인수인계-2026-08-22.md). 2022년은 전세계 금리인상기였고 저PBR/고PBR
버킷이 가치주/성장주 업종분할과 거의 일치했다(pbr_2022_decomposition.py) —
그런데 그때는 "금리" 축 자체가 없어 "정말 금리인상 regime 때문인가"를
직접 검증할 방법이 없었다. 이번에 Macro Regime Layer(2026-08-23,
findings/macro-regime-layer-backfill-report-2026-08.md)로 usTreasury10y·
krTreasury3y·krCreditSpreadBp가 생겨서 이 가설을 처음 직접 검증한다.

방법: pbr_vs_ew_monthly_mtm.py의 검증된 함수(schedule_with_monthly_mtm 등)를
**무변경 재사용**해 PBR·EW의 월별 MTM 스냅샷을 그대로 재현하고(신호·체결·비용·
스케줄링 전부 그 스크립트와 동일 코드 경로), 월별 초과수익(PBR-EW)을 계산한다.
각 월말 시점의 "trailing 6개월(126거래일) 금리 변화"를 market_regime_features
.parquet에서 가져와 hiking/not-hiking으로 분류하고, 초과수익이 hiking 구간에
집중되는지 본다.

threshold 재최적화 없음(6개월·126거래일은 사전 고정), production 코드·정책
무변경, 새 회귀 없음 - 순수 진단.

  python pbr_macro_rate_regime_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
TRAIL_DAYS = 126  # ~6개월 거래일, 사전 고정(재최적화 없음)
REGIME_PARQUET = os.path.join(REPO_ROOT, "research", "strategy-lab", "data",
                               "market-regime", "market_regime_features.parquet")


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


def rate_regime_features():
    """market_regime_features.parquet에서 trailing 126거래일 금리변화를 계산.
    사전고정 규칙(§ 재최적화 없음) - us10y/kr3y/creditSpread 셋 다 같은 창."""
    df = pd.read_parquet(REGIME_PARQUET)[
        ["date", "usTreasury10y", "krTreasury3y", "krCreditSpreadBp"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("usTreasury10y", "krTreasury3y", "krCreditSpreadBp"):
        df[col + "Chg6m"] = df[col] - df[col].shift(TRAIL_DAYS)
    return df


def bucket_report(excess_df, regime_df, chg_col, label):
    """excess_df: [date, excess]. regime_df: [date, <chg_col>]. asof 조인 후
    hiking(변화>0)/not으로 나눠 합계·평균·기여율을 리포트."""
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
        "months_hiking": int(len(hiking)),
        "months_not_hiking": int(len(not_hiking)),
        "totalExcessSum": round(float(total_excess), 5),
        "hikingExcessSum": round(float(hiking_excess), 5),
        "notHikingExcessSum": round(float(not_hiking["excess"].sum()), 5),
        "hikingSharePct": round(float(hiking_excess / total_excess * 100), 2) if total_excess != 0 else None,
        "hikingMeanMonthly": round(float(hiking["excess"].mean()), 5) if len(hiking) else None,
        "notHikingMeanMonthly": round(float(not_hiking["excess"].mean()), 5) if len(not_hiking) else None,
    }, merged


def year_hiking_breakdown(merged, chg_col):
    merged = merged.copy()
    merged["year"] = merged["date"].str.slice(0, 4)
    out = {}
    for y, g in merged.groupby("year"):
        out[y] = {
            "monthsHiking": int((g[chg_col] > 0).sum()),
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

    regime_df = rate_regime_features()

    results = {}
    year_breakdowns = {}
    for chg_col, label in [
        ("usTreasury10yChg6m", "미국 10년물 금리(6개월 변화)"),
        ("krTreasury3yChg6m", "한국 국고채 3년물 금리(6개월 변화)"),
        ("krCreditSpreadBpChg6m", "한국 신용스프레드(6개월 변화, 확대=긴축)"),
    ]:
        rep, merged = bucket_report(merged_ret[["date", "excess"]], regime_df, chg_col, label)
        results[chg_col] = rep
        year_breakdowns[chg_col] = year_hiking_breakdown(merged, chg_col)
        print("\n[%s]" % label)
        print("  전체 %d개월(hiking %d · not %d)"
              % (rep["months_total"], rep["months_hiking"], rep["months_not_hiking"]))
        print("  총초과수익=%.4f, hiking구간 기여=%.4f(%.1f%%)"
              % (rep["totalExcessSum"], rep["hikingExcessSum"], rep["hikingSharePct"] or 0))
        print("  hiking 월평균=%.5f vs not-hiking 월평균=%.5f"
              % (rep["hikingMeanMonthly"] or 0, rep["notHikingMeanMonthly"] or 0))

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": "PBR 2022 집중 현상의 금리regime 조건부 가설 검증 - "
                   "pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용 + Macro Regime Layer",
        "trailDays": TRAIL_DAYS,
        "period": [START, END],
        "monthlyExcessCount": int(len(merged_ret)),
        "results": results,
        "yearBreakdown": year_breakdowns,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-23-pbr-macro-rate-regime")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-macro-rate-regime-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
