#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PBR 미국10Y hiking 강도 - "순수 노출조절" 오버레이 backtest. 사용자 지시
(2026-08-23): build_pbr_sizing_selection.py(매달 top-K PBR랭킹 컷)는 비중을
줄이는 과정에서 **어느 종목을 들고 있는지(구성)까지 함께 바뀌었다** - 2022년
사례(exposure_frac 0.905로 거의 풀비중인데도 오히려 악화)가 그 증거. 이
스크립트는 **구성은 baseline(pbr_value_v1)과 100% 동일하게 두고, 매달 실현된
수익률에 exposure_frac(scalar)만 곱하는 오버레이**로 두 효과를 분리한다.

방법: pbr_value_v1의 월별 MTM 스냅샷(schedule_with_monthly_mtm, 무변경
재사용 - 종목 선정·리밸런싱·체결·비용 전부 baseline과 완전히 동일)에서
월간 수익률 r(t)를 구하고,

    equity_overlay(t) = equity_overlay(t-1) * (1 + exposure_frac(t-1 시점) * r(t))

로 재구성한다. exposure_frac은 build_pbr_sizing_selection.py의 exposure_lookup
(같은 p10/p90 정규화, 같은 TRAIL_DAYS=126)을 **그대로 import해서 재사용** -
새 정규화 기준을 만들지 않아 두 방법이 "같은 축, 다른 메커니즘"으로 정확히
비교된다. 그 구간의 exposure는 구간 시작 시점(전월말)의 정보로만 결정 -
미래 수익률을 보고 그 달의 노출을 정하지 않는다(PIT).

axis 커버리지 이전(2016년 초 warmup) 구간은 build_pbr_sizing_selection.py와
동일하게 exposure=0으로 처리(그 스크립트가 그 구간 전체를 selection에서
제외한 것과 동일 효과).

공용 engine(engine/portfolio/portfolio.py 등)은 전혀 안 건드린다 - 이미
계산된 equity 곡선 위에서 하는 순수 후처리 재구성이라 Research Lab 스크립트
범위를 벗어나지 않는다. selection.json도 새로 안 만든다(baseline 그대로).

  python pbr_exposure_overlay_vs_baseline_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402
    annual_returns_mtm, curve_metrics, schedule_with_monthly_mtm,
)
from build_pbr_sizing_selection import load_rate_axis, exposure_lookup  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def baseline_snapshots(strategy_id):
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    return snapshots


def build_overlay(snapshots, exposure_of):
    """snapshots: [(date, equity_baseline), ...] - baseline과 구성 100% 동일.
    구간 (i-1 -> i)의 노출은 구간 시작일(i-1)의 정보로 결정(PIT)."""
    overlay = [snapshots[0]]
    exposures = []
    for i in range(1, len(snapshots)):
        date_prev, eq_prev_base = snapshots[i - 1]
        date_cur, eq_cur_base = snapshots[i]
        r = eq_cur_base / eq_prev_base - 1.0
        frac = exposure_of(date_prev)
        if frac is None:
            frac = 0.0  # axis 커버리지 이전 - build_pbr_sizing_selection.py의
            # "no_axis -> 전량 제외"와 동일 취급(그 구간은 완전 비중0)
        eq_overlay_prev = overlay[-1][1]
        eq_overlay_cur = eq_overlay_prev * (1 + frac * r)
        overlay.append((date_cur, eq_overlay_cur))
        exposures.append((date_cur, frac))
    return overlay, exposures


def exposure_by_year(exposures):
    by_year = {}
    for d, f in exposures:
        by_year.setdefault(d[:4], []).append(f)
    return {y: round(sum(v) / len(v), 3) for y, v in sorted(by_year.items())}


def main():
    t0 = time.time()
    print("=== PBR 순수노출 오버레이(구성 baseline과 동일) vs baseline, monthly MTM, %s~%s ===" % (START, END))
    snaps = baseline_snapshots("pbr_value_v1")
    base_metrics = curve_metrics(snaps)
    base_ann = annual_returns_mtm(snaps)
    print("  baseline: %d monthly snapshots (%.0fs)" % (len(snaps), time.time() - t0))

    rate_df = load_rate_axis()
    exposure_of = exposure_lookup(rate_df)
    overlay_snaps, exposures = build_overlay(snaps, exposure_of)
    overlay_metrics = curve_metrics(overlay_snaps)
    overlay_ann = annual_returns_mtm(overlay_snaps)

    avg_exposure = round(sum(f for _, f in exposures) / len(exposures), 3)
    exp_by_year = exposure_by_year(exposures)

    cagr_gap = round(overlay_metrics["cagr"] - base_metrics["cagr"], 4)
    sharpe_gap = None
    if base_metrics["sharpe"] is not None and overlay_metrics["sharpe"] is not None:
        sharpe_gap = round(overlay_metrics["sharpe"] - base_metrics["sharpe"], 4)
    calmar_base = round(base_metrics["cagr"] / abs(base_metrics["mdd"]), 4) if base_metrics["mdd"] != 0 else None
    calmar_overlay = round(overlay_metrics["cagr"] / abs(overlay_metrics["mdd"]), 4) if overlay_metrics["mdd"] != 0 else None

    print("\n[결과]")
    print("  baseline(구성=노출 100%%) : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (base_metrics["cagr"], base_metrics["mdd"], base_metrics["sharpe"], calmar_base))
    print("  overlay(구성 동일,노출만 조절) : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (overlay_metrics["cagr"], overlay_metrics["mdd"], overlay_metrics["sharpe"], calmar_overlay))
    print("  CAGR gap = %.4f, Sharpe gap = %s" % (cagr_gap, sharpe_gap))
    print("  평균 exposure_frac = %.3f" % avg_exposure)
    print("  연도별 평균 exposure_frac:", exp_by_year)

    result = {
        "period": "%s ~ %s" % (START, END), "method": "monthly MTM equity curve, exposure overlay (composition unchanged)",
        "baseline": {"resultTable": base_metrics, "calmar": calmar_base, "annualReturns": base_ann},
        "overlay": {"resultTable": overlay_metrics, "calmar": calmar_overlay, "annualReturns": overlay_ann,
                    "avgExposureFrac": avg_exposure, "exposureFracByYear": exp_by_year},
        "cagrGap_overlayMinusBaseline": cagr_gap, "sharpeGap_overlayMinusBaseline": sharpe_gap,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-23-pbr-exposure-overlay-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-exposure-overlay-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "PBR 노출조절 오버레이(구성 baseline과 100% 동일, exposure_frac만 곱함) "
                              "- build_pbr_sizing_selection.py(랭킹컷)와 구성효과/노출효과 분리 비교용",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
