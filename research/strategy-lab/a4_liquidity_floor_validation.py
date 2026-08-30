#!/usr/bin/env python
"""A4 패널 — liquidity floor(절대 거래대금 하한)가 LOWMOM60·REV20 효과를 어떻게
바꾸는지 검증. 앞선 a4_liquidity_factor_check.py의 후속으로, 새 팩터 발굴이 아니라
기존 결과의 investability 제약 적용판이다.

floor: 전체 / amt20>=1억 / >=3억 / >=5억 (amt20 = 20거래일 평균 거래대금, PIT).
  - 1억은 이 저장소의 기존 운영 관례(turnover20>=1억, docs/data/factors/lowmom60.json).
  - 3억/5억은 기관 규모 진입 가능성 탐침. 최고 성과 threshold를 고르는 방식으로
    쓰지 않는다 — 표본 감소·경제적 의미를 함께 본다.

측정 (floor 유니버스 내부, 월말 cross-section):
  - 표본: 월평균 종목수, 고유 종목수, <100종목 월 비율, 유지율(전체 대비)
  - 신호 spread: mom60/rev20 5분위 Q1(low)−Q5(high) 월평균, NW t, 연도별
  - Rank IC (원부호: 음수 = 낮을수록 고수익)
  - floor 유니버스 자체 EW 평균 fwd return (ALL 대비 감소분 = 저유동성 프리미엄 포기액)
  - 보조: ge_1e8 내부를 잔여 유동성 절반으로 다시 나눠 mom60/rev20 spread 비교
    (하한 적용 후에도 상대적 저유동성 기울기가 남는지)

factor 조합 백테스트는 하지 않는다(이번 단계 제외).
출력: findings/a4-liquidity-floor/{a4_liquidity_floor_results.json, study.md}

  python a4_liquidity_floor_validation.py
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from a4_liquidity_factor_check import (  # noqa: E402
    HORIZONS, NW_LAGS, load_month_end_panel, newey_west_t, plain_t)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "a4-liquidity-floor")
FLOORS = {"ALL": None, "ge_1e8": 1e8, "ge_3e8": 3e8, "ge_5e8": 5e8}
SIGNALS = ["mom60", "rev20"]
MIN_NAMES_Q = 30   # 분위 계산 최소 종목
MIN_NAMES_IC = 100


def quintile_spread(g, sig, fwd):
    gg = g[[sig, fwd]].dropna()
    if len(gg) < MIN_NAMES_Q:
        return None
    q = pd.qcut(gg[sig].rank(method="first"), 5, labels=False) + 1
    m = gg.groupby(q)[fwd].mean()
    return float(m[1] - m[5])


def spread_stats(sp_df, h):
    s = sp_df["spread"]
    lag = NW_LAGS[h]
    return {
        "months": int(len(s)),
        "meanMonthlySpread": round(float(s.mean()), 4),
        "tstat_NW" if lag else "tstat": newey_west_t(s, lag) if lag else plain_t(s),
        "winRateMonths": round(float((s > 0).mean()), 3),
        "yearlyMeanSpread": {y: round(float(v), 4) for y, v in
                             s.groupby(sp_df["date"].str[:4]).mean().items()},
    }


def rank_ic_stats(panel, sig, fwd):
    ics = []
    for _, g in panel.groupby("date"):
        gg = g[[sig, fwd]].dropna()
        if len(gg) < MIN_NAMES_IC:
            continue
        ics.append(gg[sig].rank().corr(gg[fwd].rank()))
    s = pd.Series(ics)
    return {"months": int(len(s)), "icMean": round(float(s.mean()), 4)}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    panel = load_month_end_panel()

    results = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": "liquidity floor(abs amt20)별 LOWMOM60·REV20 생존 여부. "
                   "threshold 선정은 성과 채택이 아니라 경제성·표본 감소 평가 목적.",
        "pit": {"signalAt": "month-end t까지 정보만 사용",
                 "fwdReturn": "close[t+n]/close[t]-1 — 당일 수익률 미포함",
                 "floorVar": "amt20 = 20거래일 평균 거래대금(t 포함 backward rolling)"},
        "floors": {}, "universeReturn": {}, "withinFloorLiquiditySplit_ge1e8": {},
        "amt20Distribution": {},
    }

    # ── floor별 유니버스 통계 ──
    base_n = panel.groupby("date")["amt20"].count()
    for fname, thr in FLOORS.items():
        sub = panel if thr is None else panel[panel["amt20"] >= thr]
        n_by_m = sub.groupby("date").size().reindex(base_n.index).fillna(0)
        results["floors"][fname] = {
            "thresholdKrw": thr,
            "avgNamesPerMonth": round(float(n_by_m.mean()), 1),
            "minNamesMonth": int(n_by_m.min()),
            "pctMonthsUnder100Names": round(float((n_by_m < 100).mean()), 3),
            "distinctTickers": int(sub["ticker"].nunique()),
            "retentionVsAll": round(float(n_by_m.sum() / base_n.sum()), 3),
        }

    # ── amt20 월말 분포 (threshold 경제성 참고) ──
    q = panel.groupby("date")["amt20"].quantile([0.25, 0.5, 0.75, 0.9]).unstack()
    results["amt20Distribution"] = {
        f"p{int(k*100)}": {"medianAcrossMonths": round(float(q[k].median()), 0),
                            "p10AcrossMonths": round(float(q[k].quantile(0.1)), 0)}
        for k in [0.25, 0.5, 0.75, 0.9]}

    # ── floor별 EW 유니버스 수익 (저유동성 프리미엄 포기액) ──
    for h in HORIZONS:
        results["universeReturn"][h] = {}
        for fname in FLOORS:
            sub = panel if FLOORS[fname] is None else panel[panel["amt20"] >= FLOORS[fname]]
            m = sub.groupby("date")[f"fwd_{h}"].mean()
            results["universeReturn"][h][fname] = {
                "months": int(len(m)),
                "meanMonthlyRet": round(float(m.mean()), 4)}

    # ── floor별 신호 spread + IC ──
    for fname, thr in FLOORS.items():
        sub = panel if thr is None else panel[panel["amt20"] >= FLOORS[fname]]
        blk = {}
        for sig in SIGNALS:
            sb = {}
            for h in HORIZONS:
                sps = [(d, quintile_spread(g, sig, f"fwd_{h}"))
                       for d, g in sub.groupby("date")]
                sp_df = pd.DataFrame([{"date": d, "spread": v}
                                      for d, v in sps if v is not None])
                row = spread_stats(sp_df, h) if len(sp_df) else {"months": 0}
                ic = rank_ic_stats(sub, sig, f"fwd_{h}")
                row.update({"rawRankIC": ic["icMean"], "icMonths": ic["months"],
                             "directionNote": "spread>0 = low신호 우위(Q1-Q5)"})
                sb[h] = row
            blk[sig] = sb
        results["floors"][fname]["signals"] = blk

    # ── 보조: ge_1e8 내부 잔여 유동성 절반 분할 (상대적 저유동성 기울기 잔존?) ──
    fl = panel[panel["amt20"] >= 1e8].dropna(subset=["amt20"]).copy()
    fl["liq_half"] = fl.groupby("date")["amt20"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 2,
                          labels=["lowerHalf", "upperHalf"]))
    for sig in SIGNALS:
        results["withinFloorLiquiditySplit_ge1e8"][sig] = {}
        for half in ["lowerHalf", "upperHalf"]:
            sub = fl[fl["liq_half"] == half]
            row = {}
            for h in ["d20", "d60"]:
                sps = [(d, quintile_spread(g, sig, f"fwd_{h}"))
                       for d, g in sub.groupby("date")]
                sp_df = pd.DataFrame([{"date": d, "spread": v}
                                      for d, v in sps if v is not None])
                row[h] = spread_stats(sp_df, h) if len(sp_df) else {"months": 0}
            results["withinFloorLiquiditySplit_ge1e8"][sig][half] = row

    path = os.path.join(OUT_DIR, "a4_liquidity_floor_results.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    print("saved:", path)
    print(json.dumps(results["floors"], ensure_ascii=False, indent=1)[:3500])


if __name__ == "__main__":
    main()
