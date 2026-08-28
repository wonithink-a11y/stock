#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fear -> Position Sizing — panic-recovery 9종 전부 기각 후 사용자가 제안한
후속 방향(findings/panic-recovery-family-rejection-2026-08.md §5): 이진
진입/청산 대신 공포 정도에 비례해 비중을 연속 조절한다("Buy&Hold의 복리
효과 자체는 포기하지 않는 구조").

착수 전 확인된 필수 조건 그대로 적용 — 이 구조는 이미 5번(PBR·
TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60·PBR-combined) 테스트한 "노출도
오버레이"와 같아서, **순수 오버레이 vs 같은 평균노출 상수 대조군**으로
타이밍가치와 디레버리징효과를 분리한다(pbr_combined_exposure_overlay_
vs_baseline_mtm.py와 완전히 같은 방법론, build_overlay/build_constant_
exposure를 그대로 재사용 - 새로 안 짠다).

기존 5개와의 유일한 차이: 매크로 국면 신호로 *다른* 전략의 비중을 조절한
게 아니라, 자산 *자기 자신*의 공포 percentile로 그 자산 자체의 비중을
조절한다. 공포 신호는 stress_score_rebound_check.py의 4축 expanding-window
percentile(drawdown·RSI저·MA200이탈·VIX, 전부 PIT-safe)을 그대로 재사용 -
그 스크립트가 쓴 0/1 threshold(score>=3) 대신 4축 평균을 연속값(0~1)으로
써서 "정도에 비례"를 구현한다. 자산은 panic-recovery 연구의 주 표본
Nasdaq100(1986~2026, 최장 표본) 하나로 우선 확인한다.

  python fear_position_sizing_overlay.py
"""
import json
import os
import time

import numpy as np
import pandas as pd

from stress_score_rebound_check import build_features, WARMUP
from pbr_vs_ew_monthly_mtm import curve_metrics, annual_returns_mtm
from pbr_combined_exposure_overlay_vs_baseline_mtm import (
    build_overlay, build_constant_exposure, exposure_by_year,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market-regime")
FEAR_AXES = ["drawdown_pct", "rsi_low_pct", "ma200_dev_pct", "vol_pct"]


def build_monthly_snapshots(df):
    """일별 (date,value) -> 월별 (date,equity) MTM 스냅샷. 시작 equity=1.0."""
    df = df.set_index("date")
    month_last = df.groupby(df.index.to_period("M")).tail(1)
    base = float(month_last["value"].iloc[0])
    snaps = [(d.strftime("%Y-%m-%d"), float(v) / base) for d, v in month_last["value"].items()]
    return snaps


def monthly_fear_lookup(df):
    """일별 4축 평균 percentile(연속 0~1, "공포 정도") -> 월말 시점 값을
    exposure_of(date_prev)에서 그대로 찾을 수 있도록 date->frac 딕셔너리로."""
    df = df.copy()
    df["fear"] = df[FEAR_AXES].mean(axis=1)
    df = df.set_index("date")
    month_last = df.groupby(df.index.to_period("M")).tail(1)
    lookup = {d.strftime("%Y-%m-%d"): (float(f) if not pd.isna(f) else None)
              for d, f in month_last["fear"].items()}
    return lookup


def main():
    t0 = time.time()
    print("=== Fear -> Position Sizing 오버레이 (Nasdaq100, 1986~2026) vs 상수노출 대조군 ===")
    vix = pd.read_parquet(f"{DATA_DIR}/vixcls_raw.parquet")
    vix["date"] = pd.to_datetime(vix["date"])

    raw = pd.read_parquet(f"{DATA_DIR}/usnasdaq100_raw.parquet").rename(columns={"usableFromDate": "date"})
    raw["date"] = pd.to_datetime(raw["date"])
    feat = build_features(raw, vix=vix, use_own_vol=False)
    feat = feat.dropna(subset=FEAR_AXES).reset_index(drop=True)
    print(f"feature rows (post-WARMUP={WARMUP}): {len(feat)}, "
          f"{feat['date'].min().date()} ~ {feat['date'].max().date()}")

    snaps_all = build_monthly_snapshots(raw[["date", "value"]])
    fear_lookup = monthly_fear_lookup(feat)
    # WARMUP 이전 구간(fear 계산 불가) 스냅샷은 오버레이 비교에서 제외 -
    # baseline·overlay·대조군을 정확히 같은 구간으로 맞춘다.
    first_valid = min(fear_lookup)
    snaps = [(d, e) for d, e in snaps_all if d >= first_valid]
    print(f"monthly snapshots used: {len(snaps)} ({snaps[0][0]} ~ {snaps[-1][0]}) ({time.time()-t0:.0f}s)")

    def exposure_of(date_prev):
        return fear_lookup.get(date_prev)

    base_metrics = curve_metrics(snaps)
    base_ann = annual_returns_mtm(snaps)

    overlay_snaps, exposures = build_overlay(snaps, exposure_of)
    overlay_metrics = curve_metrics(overlay_snaps)
    overlay_ann = annual_returns_mtm(overlay_snaps)
    avg_exposure = round(sum(f for _, f in exposures) / len(exposures), 3)
    exp_by_year = exposure_by_year(exposures)

    const_snaps = build_constant_exposure(snaps, avg_exposure)
    const_metrics = curve_metrics(const_snaps)

    calmar = lambda m: round(m["cagr"] / abs(m["mdd"]), 4) if m["mdd"] != 0 else None
    calmar_base, calmar_overlay, calmar_const = calmar(base_metrics), calmar(overlay_metrics), calmar(const_metrics)

    timing_value_cagr = round(overlay_metrics["cagr"] - const_metrics["cagr"], 4)
    timing_value_sharpe = (round(overlay_metrics["sharpe"] - const_metrics["sharpe"], 4)
                            if overlay_metrics["sharpe"] is not None and const_metrics["sharpe"] is not None else None)
    timing_value_mdd = round(overlay_metrics["mdd"] - const_metrics["mdd"], 4)
    timing_value_calmar = (round(calmar_overlay - calmar_const, 4)
                            if calmar_overlay is not None and calmar_const is not None else None)

    print(f"\nbaseline(Buy&Hold, 노출100%): CAGR={base_metrics['cagr']:.4f} MDD={base_metrics['mdd']:.4f} "
          f"Sharpe={base_metrics['sharpe']} Calmar={calmar_base}")
    print(f"overlay(공포비례 사이징, 평균노출={avg_exposure}): CAGR={overlay_metrics['cagr']:.4f} "
          f"MDD={overlay_metrics['mdd']:.4f} Sharpe={overlay_metrics['sharpe']} Calmar={calmar_overlay}")
    print(f"대조군(상수 {avg_exposure} 노출): CAGR={const_metrics['cagr']:.4f} MDD={const_metrics['mdd']:.4f} "
          f"Sharpe={const_metrics['sharpe']} Calmar={calmar_const}")
    print(f"\n** 순수 타이밍가치(overlay-대조군): CAGR={timing_value_cagr}, MDD={timing_value_mdd}, "
          f"Sharpe={timing_value_sharpe}, Calmar={timing_value_calmar} **")
    print("연도별 평균노출(공포 정도):", exp_by_year)

    result = {
        "asset": "Nasdaq100", "period": f"{snaps[0][0]} ~ {snaps[-1][0]}",
        "fearSignal": "mean(drawdown_pct,rsi_low_pct,ma200_dev_pct,vol_pct), expanding PIT-safe percentile",
        "baseline": {"resultTable": base_metrics, "calmar": calmar_base, "annualReturns": base_ann},
        "constantExposureControl": {"constantFrac": avg_exposure, "resultTable": const_metrics, "calmar": calmar_const},
        "timingValue_overlayMinusConstant": {"cagr": timing_value_cagr, "mdd": timing_value_mdd,
                                              "sharpe": timing_value_sharpe, "calmar": timing_value_calmar},
        "overlay": {"resultTable": overlay_metrics, "calmar": calmar_overlay, "annualReturns": overlay_ann,
                    "avgExposureFrac": avg_exposure, "exposureFracByYear": exp_by_year},
        "cagrGap_overlayMinusBaseline": round(overlay_metrics["cagr"] - base_metrics["cagr"], 4),
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-fear-position-sizing-overlay")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "fear-position-sizing-overlay.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "panic-recovery-family-rejection-2026-08.md §5 후속 - 이진 진입/청산 "
                              "대신 공포 percentile로 비중을 연속 조절. 이 프로젝트가 5번(PBR·"
                              "TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60·PBR-combined) 반복한 순수 오버레이"
                              "+상수노출 대조군 방법론을 그대로 적용해 타이밍가치와 디레버리징효과를 분리.",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
