#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LOWMOM60+기관수급 - 미국10Y "순수 노출조절" 오버레이 backtest, 상수노출
대조군 포함. `trendbreakout_5dc_exposure_overlay_vs_baseline_mtm.py`와 완전히
같은 분리검증 방법론(구성 baseline과 동일 + 상수노출 대조군으로 디레버리징
효과와 순수 타이밍효과를 분리)을 재사용한다.

배경: overnight macro regime 조사(job1, findings/lowmom60-macro-regime-
check-2026-08.md)가 "미국10Y 상승기에 유리"(hiking 기여율 74.66%, ex-2022
방향 유지)라는 상관관계를 찾았다. PBR·TREND-BREAKOUT-v1·5DC-v1A-P는 이미
"상관관계 발견 → 순수 오버레이+대조군으로 타이밍가치 분리" 절차를 거쳤는데
LOWMOM60만 빠져 있었다 - 이 스크립트로 그 세트를 완결한다.

**부호**: PBR과 같은 방향(hiking에 유리)이므로 반전 없음 - TREND-BREAKOUT·
5DC의 `1-frac`과 다르다(그 둘은 hiking에 불리해서 반전했다).

LOWMOM60은 PBR/TREND-BREAKOUT/5DC와 달리 engine의 Portfolio 클래스를 안 쓰고
`lowmom60_institutional_eligible_precheck_v2_absolute.py`가 직접 월별
수익률을 계산한다(top_n=30 오름차순 mom60, turnover20>=1억원, cost 30bps) -
원본 파일은 무변경, 그 파일의 `build_panel()`만 재사용하고 월별 반환값을
얻는 루프만 이 파일에 복제한다(원본의 `run_backtest()`는 집계만 반환하고
시계열 자체는 안 돌려주므로).

  python lowmom60_exposure_overlay_vs_baseline_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from pbr_vs_ew_monthly_mtm import curve_metrics, annual_returns_mtm  # noqa: E402
from build_pbr_sizing_selection import load_rate_axis, exposure_lookup  # noqa: E402
from trendbreakout_5dc_exposure_overlay_vs_baseline_mtm import (  # noqa: E402
    build_overlay, build_constant_exposure, exposure_by_year,
)
import lowmom60_institutional_eligible_precheck_v2_absolute as lm60  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INITIAL_CAPITAL = 100_000_000.0


def monthly_returns_high_liquidity(df):
    """lm60.run_backtest()의 내부 루프를 복제 - 집계만 반환하는 원본과 달리
    월별 (date, ret) 시계열 자체를 반환한다. top_n·cost_bps·liquidity_filter
    는 원본 v2_absolute의 검증된 값과 완전히 동일(재최적화 없음)."""
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        g = g[g["turnover20"] >= lm60.MIN_TURNOVER]
        g = g.sort_values("mom60").head(lm60.TOP_N)
        if g.empty:
            continue
        ret = (g["ret"] - lm60.COST_RT_BPS / 1e4).mean()
        month_rets.append((m, float(ret)))
    return month_rets


def returns_to_snapshots(month_rets):
    """pbr_vs_ew_monthly_mtm.py와 동일 관례 - t0(거래 시작 전) anchor 행을
    START 날짜로 먼저 넣고, 그 뒤로 월별 수익률을 복리 누적한다."""
    snapshots = [(lm60.START, INITIAL_CAPITAL)]
    eq = INITIAL_CAPITAL
    for date, ret in month_rets:
        eq *= (1 + ret)
        snapshots.append((date, eq))
    return snapshots


def main():
    t0 = time.time()
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(universe.tickers, lm60.START, lm60.END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(bdf) for t, bdf in bars_raw.items()}
    print("bars loaded: %d tickers (%.0fs)" % (len(bars_by_ticker), time.time() - t0))

    rebalance_dates = lm60.monthly_rebalance_dates(calendar, lm60.START, lm60.END)
    panel = lm60.build_panel(bars_by_ticker, rebalance_dates)
    month_rets = monthly_returns_high_liquidity(panel)
    print("monthly returns: %d months (%.0fs)" % (len(month_rets), time.time() - t0))

    snaps = returns_to_snapshots(month_rets)
    base_metrics = curve_metrics(snaps)
    base_ann = annual_returns_mtm(snaps)

    rate_df = load_rate_axis()
    exposure_of = exposure_lookup(rate_df)
    overlay_snaps, exposures = build_overlay(snaps, exposure_of, invert=False)
    overlay_metrics = curve_metrics(overlay_snaps)
    overlay_ann = annual_returns_mtm(overlay_snaps)

    avg_exposure = round(sum(f for _, f in exposures) / len(exposures), 3)
    exp_by_year = exposure_by_year(exposures)

    const_snaps = build_constant_exposure(snaps, avg_exposure)
    const_metrics = curve_metrics(const_snaps)

    calmar_base = round(base_metrics["cagr"] / abs(base_metrics["mdd"]), 4) if base_metrics["mdd"] != 0 else None
    calmar_overlay = round(overlay_metrics["cagr"] / abs(overlay_metrics["mdd"]), 4) if overlay_metrics["mdd"] != 0 else None
    calmar_const = round(const_metrics["cagr"] / abs(const_metrics["mdd"]), 4) if const_metrics["mdd"] != 0 else None
    timing_value_cagr = round(overlay_metrics["cagr"] - const_metrics["cagr"], 4)
    timing_value_sharpe = None
    if overlay_metrics["sharpe"] is not None and const_metrics["sharpe"] is not None:
        timing_value_sharpe = round(overlay_metrics["sharpe"] - const_metrics["sharpe"], 4)

    print("\n[LOWMOM60] baseline              : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (base_metrics["cagr"], base_metrics["mdd"], base_metrics["sharpe"], calmar_base))
    print("[LOWMOM60] overlay(macro 노출조절): CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (overlay_metrics["cagr"], overlay_metrics["mdd"], overlay_metrics["sharpe"], calmar_overlay))
    print("[LOWMOM60] 대조군(상수 %.3f 노출)  : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (avg_exposure, const_metrics["cagr"], const_metrics["mdd"], const_metrics["sharpe"], calmar_const))
    print("  평균노출=%.3f" % avg_exposure)
    print("  ** 순수 타이밍가치(overlay-대조군): CAGR=%.4f, Sharpe=%s **" % (timing_value_cagr, timing_value_sharpe))
    print("  연도별 평균노출:", exp_by_year)

    result = {
        "strategyId": "lowmom60_institutional_eligible_high_liquidity",
        "invertExposure": False,
        "baseline": {"resultTable": base_metrics, "calmar": calmar_base, "annualReturns": base_ann},
        "constantExposureControl": {"constantFrac": avg_exposure, "resultTable": const_metrics, "calmar": calmar_const},
        "timingValue_overlayMinusConstant": {"cagr": timing_value_cagr, "sharpe": timing_value_sharpe},
        "overlay": {"resultTable": overlay_metrics, "calmar": calmar_overlay, "annualReturns": overlay_ann,
                    "avgExposureFrac": avg_exposure, "exposureFracByYear": exp_by_year},
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-24-lowmom60-exposure-overlay-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "lowmom60-exposure-overlay-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
