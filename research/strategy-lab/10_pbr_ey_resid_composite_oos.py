#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""10_pbr_ey_resid_composite_oos.py — PBR + (PBR로 잔차화한 EY) composite OOS.

배경: `09_pbr_ey_composite_oos.py`(2026-09-06)가 raw EY로 만든 50:50 composite을
REJECT했다 — PBR·EY rank 상관이 0.59로 높아 composite이 "새 정보"가 아니라
PBR을 희석시킬 뿐이었다(TEST CAGR 13.63%→11.98%, Sharpe 0.774→0.705). 그 문서의
"다음 단계 제안" §7-2: "PBR과 de-correlated된 EY 정의로 다시 composite을 평가하는
것이 의미 있는 후속"을 그대로 실행한다.

`add_residual_columns()`는 `07_ey_independence_oos.py`의 로직을 그대로 옮긴 것이다
(TRAIN에서만 fit한 계수로 EY를 PBR에 직교화 — 이 프로젝트가 라이브
factor_earnings_yield_v1에도 쓰는 것과 같은 TRAIN-고정 방식, 새로 설계 안 함).
숫자 로직을 바꾸지 않고 그대로 복사했다 — 모듈명이 숫자로 시작해 import가
안 되는 이 저장소의 관례(각 numbered 연구 스크립트가 독립 실행 가능) 그대로 따름.

그 잔차의 단면 rank를 EY 자리에 넣어 09와 완전히 같은 구조(50:50 고정,
top-decile EW, 3구간, 30/50/65bps)로 다시 돌린다 — 바뀌는 건 EY 정의 하나뿐이다.

사전 판정 기준(09와 동일, 그대로 재사용): composite TEST net30 CAGR·Sharpe가
PBR 단독(13.63%/0.774, 09 결과 그대로 인용 — 재실행 안 함)을 능가하거나 실질
동등이어야 KEEP. 아니면 REJECT.

  python 10_pbr_ey_resid_composite_oos.py
  python 10_pbr_ey_resid_composite_oos.py --selftest
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-18-pbr-ey-resid-composite-oos")
PANEL = os.path.join(fd.LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
TARGET = "fwd1m"
COST_LEVELS = [30, 50, 65]

PBR_ONLY_TEST_REF = {"cagr": 0.1363, "sharpe": 0.774,
                      "source": "pbr-ey-composite-oos-2026-09.md (09-06, 재실행 안 함)"}


def monthly_spearman(a, b):
    r = a.corr(b, method="spearman")
    return None if pd.isna(r) else float(r)


def summarize_ic(recs):
    if not recs:
        return {"nMonths": 0, "mean": None, "t": None}
    arr = np.array([v for _, v in recs], dtype=float)
    n = len(arr)
    sd = float(arr.std(ddof=1)) if n > 1 else 0.0
    t = float(arr.mean() / (sd / np.sqrt(n))) if sd > 0 else None
    return {"nMonths": n, "mean": round(float(arr.mean()), 5),
            "t": round(t, 3) if t is not None else None}


def add_residual_columns(base, controls):
    """07_ey_independence_oos.py의 (A) TRAIN-fit fixed residual 로직 그대로 복사.

    signal=earnings_yield를 controls(rank)에 월별 OLS로 직교화하되, 계수는
    TRAIN 월별 계수의 중앙값으로 고정해 VALID/TEST에 그대로 적용한다(lookahead 없음).
    """
    signal = "earnings_yield"
    sub = base.dropna(subset=[signal] + list(controls) + [TARGET]).copy()
    months = sorted(sub["date"].unique())
    resid_fx = pd.Series(np.nan, index=sub.index, dtype=float)
    train_month_slopes = []
    train_months = [d for d in months if fd.period_of(d) == "TRAIN"]
    per_month_cache = {}
    for d in months:
        g = sub[sub["date"] == d]
        if len(g) < fd.MIN_NAMES:
            continue
        X = g[signal].rank().to_numpy(dtype=float)
        C = np.column_stack([g[c].rank().to_numpy(dtype=float) for c in controls])
        keep = [i for i in range(C.shape[1]) if np.std(C[:, i]) > 0]
        if not keep:
            continue
        Ck = C[:, keep]
        A = np.column_stack([np.ones(len(g)), Ck])
        try:
            beta, *_ = np.linalg.lstsq(A, X, rcond=None)
        except np.linalg.LinAlgError:
            continue
        per_month_cache[d] = (g.index, A, X)
        if d in train_months:
            train_month_slopes.append(beta[1:])
    if train_month_slopes and len(train_month_slopes) >= 3:
        fixed_beta_ctl = np.median(np.array(train_month_slopes), axis=0)
        for d, (gidx, A, X) in per_month_cache.items():
            resid_fx.loc[gidx] = X - A[:, 1:] @ fixed_beta_ctl
    sub = sub.copy()
    sub["ey_res_pbr_fixed"] = resid_fx
    return sub


def month_top(sub, sig):
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
    if not nets:
        return None
    ps = fd.port_stats([v for _, v in nets])
    wins = sum(1 for _, v in nets if v > 0)
    return {"nMonths": ps["nMonths"], "cagr": ps["cagr"], "sharpe": ps["sharpe"],
            "mdd": ps["mdd"], "meanMonthlyNet": ps["meanMonthlyNet"],
            "winRate": round(wins / len(nets), 4)}


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


def strategy_block(panel, sig, recs, ew_series):
    by_date = {d: (names, r, top) for d, names, r, top in recs}
    dates = sorted(by_date.keys())
    gross = {d: by_date[d][1] for d in dates}
    bench = {d: float(ew_series.loc[d]) for d in dates if d in ew_series.index}
    ic = summarize_ic(ic_series(panel, sig))
    out = {"ic": ic}
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ds = [d for d in dates if fd.period_of(str(d)) == p]
        nets30 = [(i, gross[d] - 30 / 10000) for i, d in enumerate(ds)]
        out[p] = {"nMonths": len(ds), "portfolio30": portfolio_stats(nets30)}
    cost_split = {}
    for cbps in COST_LEVELS:
        cost_split[str(cbps)] = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            ds = [d for d in dates if fd.period_of(str(d)) == p]
            nets = [(i, gross[d] - cbps / 10000) for i, d in enumerate(ds)]
            cost_split[str(cbps)][p] = portfolio_stats(nets)
    out["costBySplit"] = cost_split
    return out


def annual_breakdown(recs, ew_series, cost_bps=30):
    """연도별 net 복리수익 + EW벤치마크 대비 초과 (portfolio-exit-policy 류와 같은 방식)."""
    out = {}
    for d, _, r, _ in recs:
        year = str(d)[:4]
        net = r - cost_bps / 10000
        bench = float(ew_series.loc[d]) if d in ew_series.index else None
        out.setdefault(year, {"net": [], "bench": []})
        out[year]["net"].append(net)
        if bench is not None:
            out[year]["bench"].append(bench)
    rows = {}
    for year, v in sorted(out.items()):
        net_cagr = float(np.prod([1 + x for x in v["net"]])) - 1
        bench_cagr = float(np.prod([1 + x for x in v["bench"]])) - 1 if v["bench"] else None
        rows[year] = {"nMonths": len(v["net"]), "cagr": round(net_cagr, 4),
                      "benchCagr": round(bench_cagr, 4) if bench_cagr is not None else None,
                      "excess": round(net_cagr - bench_cagr, 4) if bench_cagr is not None else None}
    return rows


def build_panel():
    df = pd.read_parquet(PANEL).copy()
    df = df[df["liquid"] & df["pbr"].notna() & df["earnings_yield"].notna()].copy()
    df = add_residual_columns(df, ["pbr"])
    df = df.dropna(subset=["ey_res_pbr_fixed"]).copy()
    df["score_pbr"] = 1 - df.groupby("date")["pbr"].rank(pct=True)
    df["score_ey"] = df.groupby("date")["ey_res_pbr_fixed"].rank(pct=True)
    df["score_comp"] = 0.5 * df["score_pbr"] + 0.5 * df["score_ey"]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    panel = build_panel()
    print(f"joint(liquid & pbr & ey_resid) {len(panel)} rows, {panel['ticker'].nunique()} tk, "
          f"{panel['date'].nunique()} months", flush=True)

    ew_series = panel.groupby("date")[TARGET].mean().sort_index()

    results = {
        "factor": "pbr_ey_resid_composite_oos",
        "generatedAt": pd.Timestamp.utcnow().isoformat(),
        "purpose": "PBR + (PBR로 잔차화한 EY) 50:50 composite — 09의 raw-EY composite REJECT 이후 "
                   "'de-correlated EY로 재설계하면 사는가' 후속 검증",
        "eyDefinition": "earnings_yield를 pbr에 TRAIN-고정 직교화한 잔차(07_ey_independence_oos.py "
                        "로직 그대로 복사, 재설계 안 함) — 단면 rank",
        "pbrOnlyTestRef": PBR_ONLY_TEST_REF,
        "composite": "0.5*(1-pbr_rank_pct) + 0.5*ey_resid_rank_pct (50:50 고정, 09와 동일 구조)",
    }

    variants = [("PBR_only", "score_pbr"), ("EYresid_only", "score_ey"), ("PBR_EYresid_comp", "score_comp")]
    for label, sig in variants:
        recs = month_top(panel, sig)
        blk = strategy_block(panel, sig, recs, ew_series)
        blk["annual"] = annual_breakdown(recs, ew_series)
        results[label] = blk
        print(f"  {label}: TEST icT={blk['ic']['t']} TEST_p30 cagr={blk['TEST']['portfolio30']['cagr']} "
              f"sh={blk['TEST']['portfolio30']['sharpe']}", flush=True)

    rank_corr = []
    for d, g in panel.groupby("date", sort=True):
        v = monthly_spearman(g["score_pbr"], g["score_ey"])
        if v is not None:
            rank_corr.append((d, v))
    results["rankCorr_pbr_eyresid"] = summarize_ic(rank_corr)
    print(f"  rankCorr(pbr, ey_resid) mean={results['rankCorr_pbr_eyresid']['mean']} "
          f"t={results['rankCorr_pbr_eyresid']['t']}", flush=True)

    comp_test = results["PBR_EYresid_comp"]["TEST"]["portfolio30"]
    pbr_test = PBR_ONLY_TEST_REF
    verdict = "KEEP" if (comp_test["cagr"] >= pbr_test["cagr"] and comp_test["sharpe"] >= pbr_test["sharpe"]) else "REJECT"
    results["verdict"] = verdict
    results["verdictNote"] = (
        f"comp TEST cagr={comp_test['cagr']:.4f} sharpe={comp_test['sharpe']:.4f} vs "
        f"PBR-only(09 인용) cagr={pbr_test['cagr']:.4f} sharpe={pbr_test['sharpe']:.4f}"
    )
    print(f"\n판정: {verdict} — {results['verdictNote']}", flush=True)

    results["executionTime_s"] = round(time.time() - t0, 1)
    out_path = os.path.join(OUT_DIR, "pbr-ey-resid-composite-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"저장: {out_path}", flush=True)


def _selftest():
    panel = build_panel()
    assert len(panel) > 1000, "패널이 비정상적으로 작음"
    assert "score_comp" in panel.columns
    assert panel["score_comp"].between(0, 1).all()
    corr = panel[["score_pbr", "score_ey"]].corr(method="spearman").iloc[0, 1]
    assert abs(corr) < 0.3, f"잔차화했는데도 PBR과 상관이 높음: {corr}"
    print(f"selftest OK — panel {len(panel)}행, score_comp∈[0,1], corr(pbr,ey_resid)={corr:.3f}(<0.3)")


if __name__ == "__main__":
    main()
