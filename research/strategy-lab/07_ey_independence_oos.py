#!/usr/bin/env python
"""07_ey_independence_oos.py — Earnings Yield 독립성 & OOS robustness.

설계: 07_earnings_yield_independence_oos (사용자 지시문).

목적: EY(TEST CAGR 13.32% / Sharpe 0.780 / MDD -14.5% / WinRate 65.6% / n=32 /
IC t=3.55)가 (1) EY decile 단조성, (2) Size(거래대금 dv20_log) 독립성,
(3) PBR / Size+PBR 독립성, (4) 업종 집중도 / 업종중립, (5) 연도·국면, (6) 비용
에 걸쳐 독립적·견고한지 검증한다.

규칙 (지시문 그대로):
  - EY 정의 = panel 의 earnings_yield(1/per, per>0, PIT valuation-panel) 재사용.
    새 정의·튜닝 없음. TRAIN/VALID/TEST, monthly rebalance, universe(dv20>=1e8),
    cost 규약 일체 유지.
  - residualization 은 원칙상 "TRAIN 에서 fit → VALID/TEST 에 고정 적용". 두
    관례를 병기한다:
      (A) TRAIN-고정: 직교화 기울기(계수)를 TRAIN 월들에서만 fit(월별 계수의
          중앙값 채택)하고 그 고정 계수를 전월에 적용.
      (B) 월별(Fama-MacBeth): 매월 자기 단면에서 fit — 기존 프로젝트 표준.
    어떤 방식도 미래/TEST 정보를 사전이용하지 않는다(B는 동월 단면만 사용,
    미래 반영 없음).
  - 계산 안 한 값은 기록하지 않는다.

산출: reports/2026-09-06-ey-independence-oos/ey-independence-oos.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-06-ey-independence-oos")
PANEL = os.path.join(fd.LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
COST_LEVELS = [30, 50, 65]  # bps round-trip

SIZE_COL = "dv20_log"


def load_base():
    df = pd.read_parquet(PANEL)
    df = df.copy()
    df = df[df["liquid"]].copy()
    return df


def monthly_spearman(a, b):
    r = a.corr(b, method="spearman")
    return None if pd.isna(r) else float(r)


def ic_series(sub, sig, tgt="fwd1m"):
    """월별 Spearman IC 계열 (월 최소 표본/유니크 게이트)."""
    out = []
    for d, g in sub.groupby("date", sort=True):
        gg = g[[sig, tgt]].dropna()
        if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
            continue
        v = monthly_spearman(gg[sig], gg[tgt])
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


def add_residual_columns(base, controls):
    """base 에 시그널/컨트롤 rank 직교화 잔차 컬럼을 추가한다.

    - per-month(B): 매월 자기 단면에서 직교화 기울기 fit 후 잔차.
    - fixed(A): 기울기 계수를 TRAIN 월에서 fit(월별 계수 중앙값)하여 고정 적용.
    컨트롤은 rank 변환, 순차 직교화(크기가 작은 순으로) — 선형 OLS 한 번 행렬로.
    """
    signal = "earnings_yield"
    sub = base.dropna(subset=[signal] + list(controls) + ["fwd1m"]).copy()
    months = sorted(sub["date"].unique())

    # (B) per-month residual signal_rank - controls(rank) 직교화
    resid_pm = pd.Series(np.nan, index=sub.index, dtype=float)
    # (A) TRAIN-fit fixed residual
    resid_fx = pd.Series(np.nan, index=sub.index, dtype=float)

    fitted_slopes = None
    train_month_slopes = []
    train_months = [d for d in months if fd.period_of(d) == "TRAIN"]

    per_month_cache = {}
    for d in months:
        g = sub[sub["date"] == d]
        if len(g) < fd.MIN_NAMES:
            continue
        X = g[signal].rank().to_numpy(dtype=float)
        C = np.column_stack([g[c].rank().to_numpy(dtype=float) for c in controls])
        # drop constant controls
        keep = [i for i in range(C.shape[1]) if np.std(C[:, i]) > 0]
        if not keep:
            continue
        Ck = C[:, keep] if keep else np.empty((len(g), 0))
        if Ck.shape[1] == 0:
            resid_pm.loc[g.index] = X - X.mean()
            continue
        # per-month B: OLS X ~ Ck (+intercept), residual
        A = np.column_stack([np.ones(len(g)), Ck])
        try:
            beta, *_ = np.linalg.lstsq(A, X, rcond=None)
            resid = X - A @ beta
        except np.linalg.LinAlgError:
            continue
        resid_pm.loc[g.index] = resid
        per_month_cache[d] = (g.index, keep, np.column_stack([np.ones(len(g)), Ck]), X)
        if d in train_months:
            train_month_slopes.append(beta[1:])

    # (A) fixed slope = TRAIN 월별 계수(컨트롤 부분)의 중앙값
    if train_month_slopes and len(train_month_slopes) >= 3:
        arr = np.array(train_month_slopes)
        fixed_beta_ctl = np.median(arr, axis=0)
        for d, (gidx, keep, A, X) in per_month_cache.items():
            resid_fx.loc[gidx] = X - A[:, 1:] @ fixed_beta_ctl
    else:
        resid_fx = resid_pm.copy()  # TRAIN 계수 부족 시 per-month 로 폴백(명시)

    name_pm = "ey_res_" + "_".join(controls) + "_pm"
    name_fx = "ey_res_" + "_".join(controls) + "_fixed"
    sub = sub.copy()
    sub[name_pm] = resid_pm
    sub[name_fx] = resid_fx
    return sub


def cs_corr(sub, a, b, min_n=fd.MIN_NAMES):
    """월별 단면 Spearman 상관 계열 요약 (두 시그널 간)."""
    recs = []
    for d, g in sub.groupby("date", sort=True):
        gg = g[[a, b]].dropna()
        if len(gg) < min_n or gg[a].nunique() <= 1 or gg[b].nunique() <= 1:
            continue
        v = monthly_spearman(gg[a], gg[b])
        if v is not None:
            recs.append((d, v))
    return summarize_ic(recs)


def top_decile_monthly_net(sub, sig, cost_bps=30):
    """상위 decile(10) EW 월수익률 gross → net. (미래 미사용, 당월 단면 결정)"""
    months = []
    for d, g in sub.groupby("date", sort=True):
        gg = g.dropna(subset=[sig]).copy()
        if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg[sig].rank(method="first"), 10, labels=False) + 1
        top = gg.loc[gg["dec"] == 10, "fwd1m"]
        if len(top) == 0:
            continue
        months.append((d, float(top.mean()) - cost_bps / 10000))
    return months


def portfolio_stats(monthly_nets):
    if not monthly_nets:
        return None
    ps = fd.port_stats([v for _, v in monthly_nets])
    wins = sum(1 for _, v in monthly_nets if v > 0)
    return {
        "nMonths": ps["nMonths"], "cagr": ps["cagr"], "sharpe": ps["sharpe"],
        "mdd": ps["mdd"], "meanMonthlyNet": ps["meanMonthlyNet"],
        "winRate": round(wins / len(monthly_nets), 4),
    }


def industry_topdec_share(sub, sig, topk=6):
    """상위 decile 명단의 업종별 비중 (전체기간 + TEST)."""
    def _shares(ss):
        cnt = {}
        tot = 0
        for d, g in ss.groupby("date", sort=True):
            gg = g.dropna(subset=[sig]).copy()
            if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
                continue
            gg["dec"] = pd.qcut(gg[sig].rank(method="first"), 10, labels=False) + 1
            top = gg[gg["dec"] == 10]
            for s, c in top["sector"].fillna("NA").value_counts().items():
                cnt[s] = cnt.get(s, 0) + int(c)
                tot += int(c)
        sh = {s: round(c / tot, 4) for s, c in cnt.items()}
        top_list = sorted(sh.items(), key=lambda kv: -kv[1])[:topk]
        return {"totalSelections": tot, "nSectors": len(cnt),
                "topSectors": [{"sector": s, "share": sh} for s, sh in top_list]}
    return {"ALL": _shares(sub), "TEST": _shares(sub[sub["period"] == "TEST"])}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    base = load_base()
    print(f"panel base(liquid) {len(base)} rows, {base['ticker'].nunique()} tk, {base['date'].nunique()} months",
          flush=True)

    sub_ey = base.dropna(subset=["earnings_yield", "fwd1m"]).copy()
    print(f"EY coverage rows {len(sub_ey)}", flush=True)

    results = {
        "factor": "earnings_yield",
        "generatedAt": pd.Timestamp.utcnow().isoformat(),
        "purpose": "EY 독립성(oos) - Size/PBR/업종/연도/비용 robustness",
        "eyDefinition": "panel earnings_yield = 1/per (per>0, valuation-panel PIT)",
        "sizeProxy": "dv20_log (log 20일 평균 거래대금) - 프로젝트 표준",
        "splits": ["ALL", "TRAIN", "VALID", "TEST"],
        "costBps": COST_LEVELS,
    }

    # ---- 1. EY decile monotonicity ----
    print("=== 1. EY decile ===", flush=True)
    decile = {}
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ss = sub_ey if p == "ALL" else sub_ey[sub_ey["period"] == p]
        res = fd.decile_analysis(ss, "earnings_yield")
        if res is None:
            decile[p] = None
            continue
        dec = {int(k): v for k, v in res["deciles"].items()}
        decile[p] = {
            "n": res["n"], "nMonths": res["nMonths"],
            "decilesMeanFwd": {k: (v.get("mean") if isinstance(v, dict) else None) for k, v in dec.items()},
            "decileSlopeSpearman": res["decileSlopeSpearman"],
            "ic": res["ic"], "spread": res["spread"],
            "netSpread": res["netSpread"],
            "longTopDecile_net": res["longTopDecile"]["net"],
            "longBottomDecile_net": res["longBottomDecile"]["net"],
        }
        # monotonicity: 1->10 단조 여부 (감소 없이 증가)
        means = [v.get("mean") for k, v in sorted(dec.items())
                 if isinstance(v, dict) and v.get("mean") is not None]
        mono_inc = sum(1 for i in range(len(means) - 1) if means[i + 1] > means[i])
        decile[p]["monotonicIncreaseCount_1to10"] = mono_inc
        decile[p]["monotonicIncreaseRatio"] = round(mono_inc / (len(means) - 1), 3) if len(means) > 1 else None
        print(f"  {p}: slope={res['decileSlopeSpearman']} ic_t={res['ic'].get('t')} "
              f"monoRatio={decile[p]['monotonicIncreaseRatio']}", flush=True)
    results["decile"] = decile

    # ---- 2. Size 독립성 ----
    print("=== 2. Size independence ===", flush=True)
    size_panel = add_residual_columns(sub_ey.copy(), [SIZE_COL])
    size_indep = {
        "crossSectionalCorr_EY_Size": {},
        "residIC": {},
        "portfolio": {},
    }
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ss = size_panel if p == "ALL" else size_panel[size_panel["period"] == p]
        cc = cs_corr(ss, "earnings_yield", SIZE_COL)
        size_indep["crossSectionalCorr_EY_Size"][p] = cc
        ric = {}
        for v in ["_pm", "_fixed"]:
            col = "ey_res_dv20_log" + v
            ric[v] = summarize_ic(ic_series(ss, col))
        size_indep["residIC"][p] = ric
    # portfolio: raw vs residualized (TEST 초점, 전 구간도)
    for label, sig in [("ey_raw", "earnings_yield"),
                       ("ey_res_size_perMonth", "ey_res_dv20_log_pm"),
                       ("ey_res_size_trainFixed", "ey_res_dv20_log_fixed")]:
        pf = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            ss = size_panel if p == "ALL" else size_panel[size_panel["period"] == p]
            pf[p] = portfolio_stats(top_decile_monthly_net(ss, sig, 30))
        size_indep["portfolio"][label] = pf
    results["sizeIndependence"] = size_indep
    print("  done", flush=True)

    # ---- 3. PBR / Size+PBR 독립성 ----
    print("=== 3. PBR / Size+PBR independence ===", flush=True)
    pbr_panel = add_residual_columns(sub_ey.copy(), ["pbr"])
    both_panel = add_residual_columns(sub_ey.copy(), ["pbr", SIZE_COL])
    val_indep = {
        "crossSectionalCorr_EY_PBR": {},
        "residIC_pbr": {}, "residIC_size_pbr": {}, "portfolio": {},
    }
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ss = pbr_panel if p == "ALL" else pbr_panel[pbr_panel["period"] == p]
        ssb = both_panel if p == "ALL" else both_panel[both_panel["period"] == p]
        val_indep["crossSectionalCorr_EY_PBR"][p] = cs_corr(ss, "earnings_yield", "pbr")
        val_indep["residIC_pbr"][p] = {
            "perMonth": summarize_ic(ic_series(ss, "ey_res_pbr_pm")),
            "trainFixed": summarize_ic(ic_series(ss, "ey_res_pbr_fixed")),
        }
        val_indep["residIC_size_pbr"][p] = {
            "perMonth": summarize_ic(ic_series(ssb, "ey_res_pbr_dv20_log_pm")),
            "trainFixed": summarize_ic(ic_series(ssb, "ey_res_pbr_dv20_log_fixed")),
        }
    for label, sig in [("ey_res_pbr_perMonth", "ey_res_pbr_pm"),
                       ("ey_res_pbr_trainFixed", "ey_res_pbr_fixed"),
                       ("ey_res_size_pbr_perMonth", "ey_res_pbr_dv20_log_pm"),
                       ("ey_res_size_pbr_trainFixed", "ey_res_pbr_dv20_log_fixed")]:
        pf = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            pp = both_panel if ("pbr_dv20_log" in sig) else pbr_panel
            ss = pp if p == "ALL" else pp[pp["period"] == p]
            pf[p] = portfolio_stats(top_decile_monthly_net(ss, sig, 30))
        val_indep["portfolio"][label] = pf
    results["valueSizeIndependence"] = val_indep
    print("  done", flush=True)

    # ---- 4. 업종 집중도 / 업종중립 ----
    print("=== 4. Industry ===", flush=True)
    ind = {"topDecileSectorShare": industry_topdec_share(sub_ey, "earnings_yield", topk=6)}
    # 업종중립 EY(panel 의 sector_rel_earnings_yield) vs raw EY 비교
    sec_panel = sub_ey.dropna(subset=["sector_rel_earnings_yield"]).copy()
    ind["industryNeutral"] = {}
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ss = sec_panel if p == "ALL" else sec_panel[sec_panel["period"] == p]
        ind["industryNeutral"][p] = {
            "n": int(len(ss)),
            "rawEY_ic": summarize_ic(ic_series(ss, "earnings_yield")),
            "sectorRelEY_ic": summarize_ic(ic_series(ss, "sector_rel_earnings_yield")),
            "rawEY_port": portfolio_stats(top_decile_monthly_net(ss, "earnings_yield", 30)),
            "sectorRelEY_port": portfolio_stats(top_decile_monthly_net(ss, "sector_rel_earnings_yield", 30)),
        }
    # TEST 기여 상위 업종 (TEST 기간 중 상위 decile 에 많이 등장한 업종)
    results["industry"] = ind
    print("  done", flush=True)

    # ---- 5. 연도별 robustness ----
    print("=== 5. Yearly ===", flush=True)
    yearly = {}
    for d, g in sub_ey.groupby("date", sort=True):
        gg = g.dropna(subset=["earnings_yield"]).copy()
        if len(gg) < fd.MIN_NAMES or gg["earnings_yield"].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg["earnings_yield"].rank(method="first"), 10, labels=False) + 1
        top = gg.loc[gg["dec"] == 10, "fwd1m"]
        yearly.setdefault(d[:4], []).append((d, float(top.mean()) - 30 / 10000))
    yearly_stats = {}
    for y, m in sorted(yearly.items()):
        yearly_stats[y] = {
            "nMonths": len(m),
            "meanMonthlyNet": round(float(np.mean([v for _, v in m])), 5),
            "cagr": (float(np.prod([1 + v for _, v in m])) ** (12 / len(m)) - 1) if len(m) else None,
            "posMonths": sum(1 for _, v in m if v > 0),
        }
    results["yearly"] = yearly_stats
    print("  yearly done", flush=True)

    # ---- 6. 비용 robustness ----
    print("=== 6. Cost ===", flush=True)
    gross_top = []
    for d, g in sub_ey.groupby("date", sort=True):
        gg = g.dropna(subset=["earnings_yield"]).copy()
        if len(gg) < fd.MIN_NAMES or gg["earnings_yield"].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg["earnings_yield"].rank(method="first"), 10, labels=False) + 1
        top = gg.loc[gg["dec"] == 10, "fwd1m"]
        if len(top) == 0:
            continue
        gross_top.append((d, float(top.mean())))
    cost = {}
    for cbps in COST_LEVELS:
        nets = [(d, g - cbps / 10000) for d, g in gross_top]
        cost[f"roundtrip_{cbps}bps"] = portfolio_stats(nets)
    results["cost"] = cost
    print("  cost done", flush=True)

    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "ey-independence-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
