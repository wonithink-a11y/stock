#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TREND-BREAKOUT-v1 · 5DC-v1A-P — 미국10Y "순수 노출조절" 오버레이 backtest.
`pbr_exposure_overlay_vs_baseline_mtm.py`(2026-08-24)와 완전히 같은 방법론을
그대로 재사용한다 - 구성(어떤 종목을 들고 있나)은 baseline과 100% 동일하게
두고, 이미 계산된 baseline 월간수익률에 exposure_frac(scalar)만 곱한다.

배경(사용자 지시, 2026-08-24 낮): overnight macro regime 조사(job3,
findings/trend-breakout-macro-regime-check-2026-08.md·5dc-v1a-p-macro-
regime-check-2026-08.md)에서 두 전략 다 "미국10Y 상승기(hiking)에 손실이
집중"되는 상관관계가 나왔다 - TREND-BREAKOUT 기여율 76.6%, 5DC 기여율
87.8%, 둘 다 ex-2022에도 방향 유지. 그런데 PBR에서 이미 "상관관계가 있다"
와 "타이밍 필터로 쓰면 이득이다"는 다른 질문임을 두 번 확인했다(이진
필터·연속 비중축소 둘 다 기각, 순수 노출 오버레이로 봐야 진짜 효과가
드러남 - `pbr-exposure-overlay-vs-ranking-cut-2026-08.md`). 이 스크립트는
그 분리검증을 이 두 후보에도 적용한다.

**부호 반전**: PBR·LOWMOM60은 hiking 구간에 유리해 exposure_frac이 클수록
비중을 키웠다. TREND-BREAKOUT·5DC는 정반대로 hiking 구간에 불리하다는
게 이미 findings로 확정돼 있으므로, 여기서는 `1 - exposure_of(date)`로
방향만 뒤집는다 - 새로운 임계값·정규화를 만드는 게 아니라 이미 검증된
축의 부호를 그 전략 자신의 상관관계 방향에 맞추는 것뿐이다(축·threshold·
TRAIL_DAYS·p10/p90 전부 build_pbr_sizing_selection.py와 완전히 동일,
재최적화 없음).

  python trendbreakout_5dc_exposure_overlay_vs_baseline_mtm.py
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


def build_overlay(snapshots, exposure_of, invert):
    """snapshots: [(date, equity_baseline), ...]. invert=True면 1-exposure_frac
    사용(hiking에 불리한 전략용). 구간 (i-1 -> i)의 노출은 구간 시작일(i-1)의
    정보로 결정(PIT)."""
    overlay = [snapshots[0]]
    exposures = []
    for i in range(1, len(snapshots)):
        date_prev, eq_prev_base = snapshots[i - 1]
        date_cur, eq_cur_base = snapshots[i]
        r = eq_cur_base / eq_prev_base - 1.0
        frac = exposure_of(date_prev)
        if frac is None:
            frac = 0.0  # axis 커버리지 이전 - PBR 오버레이와 동일 취급
        if invert:
            frac = 1.0 - frac
        eq_overlay_prev = overlay[-1][1]
        eq_overlay_cur = eq_overlay_prev * (1 + frac * r)
        overlay.append((date_cur, eq_overlay_cur))
        exposures.append((date_cur, frac))
    return overlay, exposures


def build_constant_exposure(snapshots, constant_frac):
    """대조군 - macro 조건 없이 매 구간 동일한 상수 노출만 적용. 동적
    오버레이의 개선이 "타이밍"이 아니라 단순 "평균 노출 축소(디레버리징)"
    효과인지 가르기 위한 것 - 평균 노출을 동적 버전과 정확히 맞춘다."""
    overlay = [snapshots[0]]
    for i in range(1, len(snapshots)):
        _, eq_prev_base = snapshots[i - 1]
        date_cur, eq_cur_base = snapshots[i]
        r = eq_cur_base / eq_prev_base - 1.0
        eq_overlay_prev = overlay[-1][1]
        eq_overlay_cur = eq_overlay_prev * (1 + constant_frac * r)
        overlay.append((date_cur, eq_overlay_cur))
    return overlay


def exposure_by_year(exposures):
    by_year = {}
    for d, f in exposures:
        by_year.setdefault(d[:4], []).append(f)
    return {y: round(sum(v) / len(v), 3) for y, v in sorted(by_year.items())}


def run_one(strategy_id, invert, label):
    t0 = time.time()
    snaps = baseline_snapshots(strategy_id)
    base_metrics = curve_metrics(snaps)
    base_ann = annual_returns_mtm(snaps)
    print("  %s baseline: %d monthly snapshots (%.0fs)" % (strategy_id, len(snaps), time.time() - t0))

    rate_df = load_rate_axis()
    exposure_of = exposure_lookup(rate_df)
    overlay_snaps, exposures = build_overlay(snaps, exposure_of, invert)
    overlay_metrics = curve_metrics(overlay_snaps)
    overlay_ann = annual_returns_mtm(overlay_snaps)

    avg_exposure = round(sum(f for _, f in exposures) / len(exposures), 3)
    exp_by_year = exposure_by_year(exposures)

    # 대조군: macro 조건 없이 같은 평균노출을 상수로 걸었을 때 - 동적 오버레이의
    # 개선이 "타이밍"인지 그냥 "평균 노출 축소(디레버리징)"인지 가른다.
    const_snaps = build_constant_exposure(snaps, avg_exposure)
    const_metrics = curve_metrics(const_snaps)
    calmar_const = round(const_metrics["cagr"] / abs(const_metrics["mdd"]), 4) if const_metrics["mdd"] != 0 else None

    cagr_gap = round(overlay_metrics["cagr"] - base_metrics["cagr"], 4)
    sharpe_gap = None
    if base_metrics["sharpe"] is not None and overlay_metrics["sharpe"] is not None:
        sharpe_gap = round(overlay_metrics["sharpe"] - base_metrics["sharpe"], 4)
    calmar_base = round(base_metrics["cagr"] / abs(base_metrics["mdd"]), 4) if base_metrics["mdd"] != 0 else None
    calmar_overlay = round(overlay_metrics["cagr"] / abs(overlay_metrics["mdd"]), 4) if overlay_metrics["mdd"] != 0 else None
    timing_value_cagr = round(overlay_metrics["cagr"] - const_metrics["cagr"], 4)
    timing_value_sharpe = None
    if overlay_metrics["sharpe"] is not None and const_metrics["sharpe"] is not None:
        timing_value_sharpe = round(overlay_metrics["sharpe"] - const_metrics["sharpe"], 4)

    print("\n[%s] baseline              : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (label, base_metrics["cagr"], base_metrics["mdd"], base_metrics["sharpe"], calmar_base))
    print("[%s] overlay(macro 노출조절): CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (label, overlay_metrics["cagr"], overlay_metrics["mdd"], overlay_metrics["sharpe"], calmar_overlay))
    print("[%s] 대조군(상수 %.3f 노출)  : CAGR=%.4f MDD=%.4f Sharpe=%s Calmar=%s"
          % (label, avg_exposure, const_metrics["cagr"], const_metrics["mdd"], const_metrics["sharpe"], calmar_const))
    print("  CAGR gap(overlay-baseline)=%.4f, 평균노출=%.3f" % (cagr_gap, avg_exposure))
    print("  ** 순수 타이밍가치(overlay-대조군): CAGR=%.4f, Sharpe=%s **" % (timing_value_cagr, timing_value_sharpe))
    print("  연도별 평균노출:", exp_by_year)

    return {
        "strategyId": strategy_id, "invertExposure": invert,
        "baseline": {"resultTable": base_metrics, "calmar": calmar_base, "annualReturns": base_ann},
        "constantExposureControl": {"constantFrac": avg_exposure, "resultTable": const_metrics, "calmar": calmar_const},
        "timingValue_overlayMinusConstant": {"cagr": timing_value_cagr, "sharpe": timing_value_sharpe},
        "overlay": {"resultTable": overlay_metrics, "calmar": calmar_overlay, "annualReturns": overlay_ann,
                    "avgExposureFrac": avg_exposure, "exposureFracByYear": exp_by_year},
        "cagrGap_overlayMinusBaseline": cagr_gap, "sharpeGap_overlayMinusBaseline": sharpe_gap,
    }


def main():
    print("=== TREND-BREAKOUT-v1 / 5DC-v1A-P 미국10Y 노출 오버레이(구성 baseline과 동일) vs baseline ===")
    result_tb = run_one("trend_breakout_v1", invert=True, label="TREND-BREAKOUT-v1")
    result_5dc = run_one("5dc_v1a_p", invert=True, label="5DC-v1A-P")

    out = {"period": "%s ~ %s" % (START, END),
           "method": "monthly MTM equity curve, exposure overlay (composition unchanged), "
                     "exposure_frac inverted (1-frac) - hiking hurts both strategies per "
                     "2026-08-24 macro regime findings",
           "trend_breakout_v1": result_tb, "5dc_v1a_p": result_5dc}
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-24-trendbreakout-5dc-exposure-overlay-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "trendbreakout-5dc-exposure-overlay-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": out},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
