#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""earnings_yield 팩터 2021년 집중 현상 — 금리 regime 조건부 가설 검증 (2026-08).

배경: findings/factor-earnings-yield-2021-concentration-2026-08.md가 초과
로그수익의 89.2%가 2021년 단 한 해에서 나옴을 확인했다(exit_date 귀속
방식이라는 한계가 있는 채로). PBR이 2022년 집중 현상을 usTreasury10y
(미국 10년물, trailing 6개월 변화)로 검증한 것과 같은 방법론
(pbr_macro_rate_regime_check.py)을 earnings_yield에도 적용한다.

pbr_vs_ew_monthly_mtm.py의 검증된 함수(schedule_with_monthly_mtm 등)를
**무변경 재사용**(strategy_id만 factor_earnings_yield_v1로 교체) - 이건
동시에 2021-concentration 문서가 남긴 한계(연도별 수익률이 exit_date
귀속 방식이라 정밀 MTM 곡선으로 검증한 게 아님)도 해소한다. 진짜 월별
시가평가 곡선으로 연도별 수익률을 다시 계산해 exit_date 귀속과 비교한다.

threshold 재최적화 없음(6개월·126거래일은 PBR 검증 때 사전 고정된 값
그대로 재사용), production 코드·정책 무변경, 새 회귀 없음 - 순수 진단.

  python factor_earnings_yield_macro_rate_regime_check.py
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, annual_returns_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
TRAIL_DAYS = 126  # PBR 검증과 동일 - 재최적화 없음
STRATEGY_ID = "factor_earnings_yield_v1"
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
    dates = [d for d, _ in snapshots[1:]]
    eqs = [e for _, e in snapshots]
    rets = [eqs[i] / eqs[i - 1] - 1.0 for i in range(1, len(eqs))]
    return pd.DataFrame({"date": dates, "ret": rets})


def rate_regime_features():
    df = pd.read_parquet(REGIME_PARQUET)[
        ["date", "usTreasury10y", "krTreasury3y", "krCreditSpreadBp"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("usTreasury10y", "krTreasury3y", "krCreditSpreadBp"):
        df[col + "Chg6m"] = df[col] - df[col].shift(TRAIL_DAYS)
    return df


def bucket_report(excess_df, regime_df, chg_col, label):
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
    print("=== earnings_yield-EW 월별 MTM 재현 (pbr_vs_ew_monthly_mtm.py 함수 무변경 재사용) ===")
    ey_snap = monthly_snapshots(STRATEGY_ID)
    ew_snap = monthly_snapshots("ew_benchmark_liquid_v1")
    print("  earnings_yield 스냅샷 %d개, EW 스냅샷 %d개 (%.0fs)" % (len(ey_snap), len(ew_snap), time.time() - t0))

    # exit_date 귀속(run_factor_backtest.py) vs 진짜 MTM 연도별 비교 - 2021-concentration
    # 문서가 남긴 한계 해소.
    ey_annual_mtm = annual_returns_mtm(ey_snap)
    ew_annual_mtm = annual_returns_mtm(ew_snap)
    print("\n=== MTM 기준 연도별 수익률 (exit_date 귀속 방식과 비교) ===")
    years_mtm = sorted(set(ey_annual_mtm) & set(ew_annual_mtm))
    ey_log_mtm = {y: math.log(1 + ey_annual_mtm[y]) for y in years_mtm}
    ew_log_mtm = {y: math.log(1 + ew_annual_mtm[y]) for y in years_mtm}
    excess_log_mtm = {y: ey_log_mtm[y] - ew_log_mtm[y] for y in years_mtm}
    total_excess_mtm = sum(excess_log_mtm.values())
    for y in years_mtm:
        share = excess_log_mtm[y] / total_excess_mtm * 100 if total_excess_mtm else float("nan")
        print("  %s  ey=%+.2f%%  ew=%+.2f%%  excessLog=%+.4f  share=%+.1f%%" %
              (y, ey_annual_mtm[y] * 100, ew_annual_mtm[y] * 100, excess_log_mtm[y], share))
    print("  총 초과 로그수익(MTM)=%.4f, 2021 비중=%.1f%%" %
          (total_excess_mtm, (excess_log_mtm.get(2021, 0) / total_excess_mtm * 100) if total_excess_mtm else 0))

    pbr_ret = monthly_returns(ey_snap)
    ew_ret = monthly_returns(ew_snap)
    merged_ret = pbr_ret.merge(ew_ret, on="date", suffixes=("_ey", "_ew"))
    merged_ret["excess"] = merged_ret["ret_ey"] - merged_ret["ret_ew"]
    print("\n  월별 초과수익(ey-EW) %d개월, 합계=%.4f(로그아님 단순합)"
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
        "context": "earnings_yield 2021 집중 현상의 금리regime 조건부 가설 검증 - "
                   "pbr_macro_rate_regime_check.py와 동일 방법론(strategy_id만 교체)",
        "trailDays": TRAIL_DAYS,
        "period": [START, END],
        "annualReturnsMtm": {"earnings_yield": ey_annual_mtm, "ew_benchmark": ew_annual_mtm},
        "excessLogReturnByYearMtm": excess_log_mtm,
        "totalExcessLogReturnMtm": total_excess_mtm,
        "monthlyExcessCount": int(len(merged_ret)),
        "results": results,
        "yearBreakdown": year_breakdowns,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-30-factor-earnings-yield-macro-rate-regime")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "factor-earnings-yield-macro-rate-regime-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
