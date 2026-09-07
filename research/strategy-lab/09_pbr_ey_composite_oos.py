#!/usr/bin/env python
"""09_pbr_ey_composite_oos.py — PBR + Earnings Yield 50:50 Composite OOS.

설계: 사용자 지시문 (PBR+EY composite 최적화 아님, 사전 고정 50:50 검증).

목적: PBR 단독 / EY 단독 / PBR+EY 50:50 동일가중 rank composite 을 **완전 동일한
universe·split·rebalance·cost** 조건에서 비교해, composite 이 단일 팩터 대비 OOS
포트폴리오 성과·안정성을 개선하는지 검증한다. TEST 결과 보고 weight/topN 변경 없음.

정의 (최신 repo 정본 그대로):
  - universe = liquid(dv20>=1e8) ∩ pbr & earnings_yield 동시 존재 (교집합, 공정 비교).
    NOTE: 교집합(83,013행)은 full EY universe(83,088행)와 실질 동일 —
    EY canonical 정의 그대로이며 EY∩LOWMOM(13.32% 유니버스)과 혼용하지 않는다.
  - PBR = panel `pbr` (valuation-panel PIT), 저PBR 좋음(오름차순) — 기존 pbr_value_v1 방향.
  - EY = panel `earnings_yield`(=1/per, per>0, valuation-panel PIT), 높을수록 좋음.
  - score_pbr = 1 - pbr.rank(pct=True)   (월별 단면, [0,1], 저PBR=1)
  - score_ey  = earnings_yield.rank(pct=True) (월별 단면, [0,1])
  - composite = 0.5*score_pbr + 0.5*score_ey  (50:50 사전 고정, weight sweep 없음)
  - top-N = 상위 decile EW 월 리밸런스 롱온리 (기존 cross-sectional 연구 기준 그대로)
  - fwd1m = 신호 다음 거래일 진입 → 다음 리밸런스월 첫 거래일 청산 (기존 그대로)
  - 3구간: TRAIN<=2022-06-30 < VALID<=2024-01-01 < TEST
  - 비용: 30bps 왕복 baseline, 50/65bps robustness (사전 고정, 월 전량 교체 rule
    + turnover-aware 병기). benchmark = 교집합 EW.

산출: reports/2026-09-06-pbr-ey-composite-oos/pbr-ey-composite-oos.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-06-pbr-ey-composite-oos")
PANEL = os.path.join(fd.LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
COST_LEVELS = [30, 50, 65]

TARGET = "fwd1m"
PBR = "pbr"
EY = "earnings_yield"


def monthly_spearman(a, b):
    r = a.corr(b, method="spearman")
    return None if pd.isna(r) else float(r)


def build_panel():
    df = pd.read_parquet(PANEL).copy()
    df = df[df["liquid"] & df[PBR].notna() & df[EY].notna()].copy()
    df["score_pbr"] = 1 - df.groupby("date")[PBR].rank(pct=True)
    df["score_ey"] = df.groupby("date")[EY].rank(pct=True)
    df["score_comp"] = 0.5 * df["score_pbr"] + 0.5 * df["score_ey"]
    return df


def ic_series(sub, sig):
    out = []
    for d, g in sub.groupby("date", sort=True):
        gg = g[[sig, TARGET]].dropna()
        if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
            continue
        v = monthly_spearman(gg[sig], gg[TARGET])
        if v is not None:
            out.append((d, v))
    return out


def summarize_ic(recs):
    if not recs:
        return {"nMonths": 0, "mean": None, "t": None}
    arr = np.array([v for _, v in recs], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    return {"nMonths": n, "mean": round(float(arr.mean()), 5),
            "t": round(t, 3) if t is not None else None}


def month_top(sub, sig):
    """월별 상위 decile 집합 + EW fwd1m(gross)."""
    recs = []
    for d, g in sub.groupby("date", sort=True):
        gg = g.dropna(subset=[sig, TARGET]).copy()
        if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg[sig].rank(method="first"), 10, labels=False) + 1
        top = gg.loc[gg["dec"] == 10]
        recs.append((d, set(top["ticker"]), float(top[TARGET].mean()), top))
    return recs


def portfolio_stats(nets):
    if not nets or len(nets) == 0:
        return None
    ps = fd.port_stats([v for _, v in nets])
    wins = sum(1 for _, v in nets if v > 0)
    return {"nMonths": ps["nMonths"], "cagr": ps["cagr"], "sharpe": ps["sharpe"],
            "mdd": ps["mdd"], "meanMonthlyNet": ps["meanMonthlyNet"],
            "winRate": round(wins / len(nets), 4)}


def strategy_block(panel, sig, recs, ew_series):
    """단일 전략의 구간별 성과 블록."""
    assert sig in {"score_pbr", "score_ey", "score_comp"}
    by_date = {d: (names, r, top) for d, names, r, top in recs}
    dates = sorted(by_date.keys())
    gross = {d: by_date[d][1] for d in dates}
    bench = {d: float(ew_series.loc[d]) for d in dates if d in ew_series.index}
    ic = summarize_ic(ic_series(panel, sig))
    out = {"ic": ic}
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ds = [d for d in dates if fd.period_of(str(d)) == p]
        nets30 = [(i, gross[d] - 30 / 10000) for i, d in enumerate(ds)]
        exc = [(i, gross[d] - bench[d]) for i, d in enumerate(ds) if d in bench]
        exc_arr = np.array([v for _, v in exc], dtype=float)
        t_ex = float(exc_arr.mean() / (exc_arr.std(ddof=1) / np.sqrt(len(exc_arr)))) if len(exc_arr) > 1 and exc_arr.std(ddof=1) > 0 else None
        bm_series = [bench[d] for d in ds if d in bench]
        out[p] = {
            "nMonths": len(ds),
            "portfolio30": portfolio_stats(nets30),
            "excessEW": {
                "nMonths": len(exc),
                "meanMonthly": round(float(exc_arr.mean()), 5) if len(exc_arr) else None,
                "t": round(t_ex, 3) if t_ex is not None else None,
                "cagr": (float(np.prod([1 + v for _, v in exc])) ** (12 / len(exc)) - 1) if len(exc) else None,
                "posRatio": round(float((exc_arr > 0).mean()), 4) if len(exc_arr) else None,
            },
            "benchEW": {
                "meanMonthly": round(float(np.mean(bm_series)), 5) if bm_series else None,
                "cagr": (float(np.prod([1 + v for v in bm_series])) ** (12 / len(bm_series)) - 1) if bm_series else None,
            },
        }
    # cost robustness (분할별 30/50/65 + TEST 초점)
    cost_split = {}
    for cbps in COST_LEVELS:
        cost_split[str(cbps)] = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            ds = [d for d in dates if fd.period_of(str(d)) == p]
            nets = [(i, gross[d] - cbps / 10000) for i, d in enumerate(ds)]
            cost_split[str(cbps)][p] = portfolio_stats(nets)
    out["costBySplit"] = cost_split
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    panel = build_panel()
    print(f"joint(liquid & pbr & ey) {len(panel)} rows, {panel['ticker'].nunique()} tk, "
          f"{panel['date'].nunique()} months", flush=True)
    print(panel.groupby("period").size(), flush=True)

    ew_series = panel.groupby("date")[TARGET].mean().sort_index()
    n_cross = panel.groupby("date")[TARGET].count().mean()

    results = {
        "factor": "pbr_ey_composite_oos",
        "generatedAt": pd.Timestamp.utcnow().isoformat(),
        "purpose": "PBR+EY 50:50 composite — PBR/EY 단독 대비 OOS 개선 검증 (최적화 아님)",
        "universe": "liquid(dv20>=1e8) ∩ (pbr & earning_yield 존재) 교집합 — full EY universe(83,088)와 실질 동일, EY∩LOWMOM 미사용",
        "eyDefinition": "panel earnings_yield = 1/per (per>0, valuation-panel PIT)",
        "pbrDefinition": "panel pbr (valuation-panel PIT), 저PBR 좋음(오름차순)",
        "composite": "0.5*(1 - pbr_rank_pct) + 0.5*ey_rank_pct (50:50 사전 고정)",
        "topN": "상위 decile EW 월 리밸런스 롱온리",
        "splits": ["ALL", "TRAIN", "VALID", "TEST"],
        "costBps": COST_LEVELS,
        "avgCrossSectionNames": round(float(n_cross), 1),
    }

    variants = [
        ("PBR_only", "score_pbr"),
        ("EY_only", "score_ey"),
        ("PBR_EY_comp", "score_comp"),
    ]

    # strategy blocks
    for label, sig in variants:
        recs = month_top(panel, sig)
        blk = strategy_block(panel, sig, recs, ew_series)
        results[label] = blk
        # churn & names per month
        name_sets = [s for _, s, _, _ in recs]
        sizes = [len(s) for s in name_sets]
        tos = []
        for k in range(1, len(name_sets)):
            prev, cur = name_sets[k - 1], name_sets[k]
            if len(prev) == 0 or len(cur) == 0:
                continue
            tos.append(1 - len(prev & cur) / len(prev))
        to_arr = np.array(tos)
        blk["turnover"] = {
            "nObs": int(len(to_arr)),
            "mean": round(float(to_arr.mean()), 4),
            "p25": round(float(np.percentile(to_arr, 25)), 4),
            "p50": round(float(np.percentile(to_arr, 50)), 4),
            "p75": round(float(np.percentile(to_arr, 75)), 4),
            "p95": round(float(np.percentile(to_arr, 95)), 4),
            "max": round(float(to_arr.max()), 4),
            "avgTopNames": round(float(np.mean(sizes)), 2),
        }
        # turnover-aware net (cost × 실측 turnover, 기존 rule 병기)
        ta = {}
        for cbps in COST_LEVELS:
            turn_arr = [1.0] + list(to_arr)
            nets = [(i, recs[i][2] - cbps / 10000 * turn_arr[i]) for i in range(len(recs))]
            ta[str(cbps)] = portfolio_stats(nets)
        blk["turnoverAwareNet"] = ta
        print(f"  {label}: TEST icT={blk['ic']['t']} TEST_p30 cagr={blk['TEST']['portfolio30']['cagr']}"
              f" sh={blk['TEST']['portfolio30']['sharpe']} excess_t={blk['TEST']['excessEW']['t']}", flush=True)

    # ---------- factor complementarity ----------
    print("=== complementarity ===", flush=True)
    rank_corr = []
    for d, g in panel.groupby("date", sort=True):
        v = monthly_spearman(g["score_pbr"], g["score_ey"])
        if v is not None:
            rank_corr.append((d, v))
    results["rankCorr_pbr_ey"] = summarize_ic(rank_corr)

    def jaccard(a, b):
        if not a or not b:
            return None
        return len(a & b) / len(a | b)

    ov = {"mean_overlap": {}, "by_split": {}}
    rec_sets = {label: {d: names for d, names, _, _ in month_top(panel, sig)}
                for label, sig in variants}
    pairs = [("PBR_only", "EY_only"), ("PBR_only", "PBR_EY_comp"), ("EY_only", "PBR_EY_comp")]
    for la, lb in pairs:
        ds = sorted(set(rec_sets[la].keys()) & set(rec_sets[lb].keys()))
        js = [j for j in (jaccard(rec_sets[la][d], rec_sets[lb][d]) for d in ds) if j is not None]
        ov["mean_overlap"][f"{la}_vs_{lb}"] = round(float(np.mean(js)), 4) if js else None
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            pds = [d for d in ds if fd.period_of(str(d)) == p]
            pjs = [j for j in (jaccard(rec_sets[la][d], rec_sets[lb][d]) for d in pds) if j is not None]
            ov["by_split"][f"{la}_vs_{lb}"] = ov["by_split"].get(f"{la}_vs_{lb}", {})
            ov["by_split"][f"{la}_vs_{lb}"][p] = round(float(np.mean(pjs)), 4) if pjs else None
    comp = rec_sets["PBR_EY_comp"]
    for sname in ["score_pbr", "score_ey"]:
        ss = rec_sets["PBR_only"] if sname == "score_pbr" else rec_sets["EY_only"]
        ds = sorted(set(comp.keys()) & set(ss.keys()))
        fracs = [len(comp[d] & ss[d]) / len(comp[d]) for d in ds]
        ov[f"comp_share_with_{sname}"] = round(float(np.mean(fracs)), 4) if fracs else None
    results["overlap"] = ov
    print(f"  rankCorr mean={results['rankCorr_pbr_ey']['mean']} t={results['rankCorr_pbr_ey']['t']}", flush=True)
    print(f"  overlap: {ov['mean_overlap']} compShare={ov['comp_share_with_score_pbr']}/{ov['comp_share_with_score_ey']}", flush=True)

    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "pbr-ey-composite-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()