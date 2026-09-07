#!/usr/bin/env python
"""08_ey_final_robustness.py — Earnings Yield 최종 Robustness 검증.

설계: 사용자 최종 지시문 (EY를 KEEP/HOLD/REJECT로 확정하는 검증).

목적: 현재 EY(TEST top-decile net CAGR 10.79% / Sharpe 0.653 / MDD -14.4% /
WinRate 54.8% / n=31 / IC t=3.64)가
  1) A/B/C (원 EY / PBR-resid / Size+PBR-resid) — TRAIN-고정 직교화로 실제 portfolio 성과가
     IC 유의와 함께 남는지, 아니면 IC만 유의하고 portfolio alpha 가 사라지는지.
  2) 업종 집중도 / 업종중립(PIT) / 특정 업종 TEST 지배 여부.
  3) 연도별 + rolling 24/36개월 + benchmark(EW) 대비 초과수익.
  4) 비용(30/50/65bps, 사전 고정) robustness.
  5) turnover 분포 + 비용-성과 감소가 turnover 때문인지.
결과적으로 독립적·견고한 투자 알파인지 최종 판정한다.

규칙 (지시문 그대로, §8 금지 사항 준수):
  - EY 정의 그대로(panel earnings_yield = 1/per, per>0, PIT). 튜닝 없음.
  - TRAIN/VALID/TEST, monthly rebalance, universe(dv20>=1e8), top-decile EW 고정.
  - residualization 은 TRAIN 에서만 fit → VALID/TEST 에 TRAIN-고정 계수 적용.
  - TEST 결과로 조건 변경 없음. 좋은 구간/업종 선택·제거 없음.
  - 비용 수준 30/50/65bps 사전 고정, 새 값 선택 없음.

산출: reports/2026-09-06-ey-final-robustness/ey-final-robustness.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-06-ey-final-robustness")
PANEL = os.path.join(fd.LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
COST_LEVELS = [30, 50, 65]  # bps round-trip (사전 고정)
ROLL_WINDOWS = [24, 36]

SIZE_COL = "dv20_log"
SIGNAL = "earnings_yield"
TARGET = "fwd1m"


def load_base():
    df = pd.read_parquet(PANEL).copy()
    return df[df["liquid"]].copy()


def monthly_spearman(a, b):
    r = a.corr(b, method="spearman")
    return None if pd.isna(r) else float(r)


def ic_series(sub, sig, tgt=TARGET):
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


def add_residual_fixed(base, controls, sig=SIGNAL):
    """TRAIN-고정 직교화 잔차. TRAIN 월에서 컨트롤 계수 중앙값을 fit, 전월에 고정 적용.

    반환 sub에 'ey_res_<controls>_fixed' 컬럼 추가. (월별 자기 단면 OLS는 미사용 —
    지시문 'TRAIN에서만 fit' 실행.)
    """
    sub = base.dropna(subset=[sig] + list(controls) + [TARGET]).copy()
    months = sorted(sub["date"].unique())
    resid_fx = pd.Series(np.nan, index=sub.index, dtype=float)

    train_month_slopes = []
    train_months = [d for d in months if fd.period_of(d) == "TRAIN"]
    month_design = {}

    for d in months:
        g = sub[sub["date"] == d]
        if len(g) < fd.MIN_NAMES:
            continue
        X = g[sig].rank().to_numpy(dtype=float)
        C = np.column_stack([g[c].rank().to_numpy(dtype=float) for c in controls])
        keep = [i for i in range(C.shape[1]) if np.std(C[:, i]) > 0]
        if not keep:
            resid_fx.loc[g.index] = X - X.mean()
            continue
        Ck = C[:, keep]
        A = np.column_stack([np.ones(len(g)), Ck])
        try:
            beta, *_ = np.linalg.lstsq(A, X, rcond=None)
            resid = X - A @ beta
        except np.linalg.LinAlgError:
            continue
        resid_fx.loc[g.index] = resid
        month_design[d] = (g.index, keep, A)
        if d in train_months:
            train_month_slopes.append(beta[1:])

    if train_month_slopes and len(train_month_slopes) >= 3:
        arr = np.array(train_month_slopes)
        fixed_beta_ctl = np.median(arr, axis=0)
        for d, (gidx, keep, A) in month_design.items():
            resid_fx.loc[gidx] = (sub.loc[gidx, sig].rank().to_numpy(dtype=float)
                                  - A[:, 1:] @ fixed_beta_ctl)

    col = "ey_res_" + "_".join(controls) + "_fixed"
    sub[col] = resid_fx
    return sub


def cs_corr(sub, a, b, min_n=fd.MIN_NAMES):
    recs = []
    for d, g in sub.groupby("date", sort=True):
        gg = g[[a, b]].dropna()
        if len(gg) < min_n or gg[a].nunique() <= 1 or gg[b].nunique() <= 1:
            continue
        v = monthly_spearman(gg[a], gg[b])
        if v is not None:
            recs.append((d, v))
    return summarize_ic(recs)


def month_top_names(sub, sig):
    """월별 상위 decile 종목 집합 + 당월 리턴. (당월 단면 결정, 미래 미사용)"""
    out = []
    for d, g in sub.groupby("date", sort=True):
        gg = g.dropna(subset=[sig]).copy()
        if len(gg) < fd.MIN_NAMES or gg[sig].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg[sig].rank(method="first"), 10, labels=False) + 1
        top = gg.loc[gg["dec"] == 10]
        out.append((d, set(top["ticker"]), float(top[TARGET].mean()), top))
    return out


def portfolio_stats(monthly_nets):
    if not monthly_nets or len(monthly_nets) == 0:
        return None
    ps = fd.port_stats([v for _, v in monthly_nets])
    wins = sum(1 for _, v in monthly_nets if v > 0)
    return {
        "nMonths": ps["nMonths"], "cagr": ps["cagr"], "sharpe": ps["sharpe"],
        "mdd": ps["mdd"], "meanMonthlyNet": ps["meanMonthlyNet"],
        "winRate": round(wins / len(monthly_nets), 4),
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    base = load_base()
    print(f"panel base(liquid) {len(base)} rows, {base['ticker'].nunique()} tk, "
          f"{base['date'].nunique()} months", flush=True)

    sub_ey = base.dropna(subset=[SIGNAL, TARGET]).copy()
    print(f"EY coverage rows {len(sub_ey)}", flush=True)

    results = {
        "factor": "earnings_yield",
        "generatedAt": pd.Timestamp.utcnow().isoformat(),
        "purpose": "EY 최종 robustness — A/B/C 독립성(통제후 portfolio alive?), 업종, 연도/rolling, 비용, turnover",
        "eyDefinition": "panel earnings_yield = 1/per (per>0, valuation-panel PIT)",
        "sizeProxy": "dv20_log (log 20일 평균 거래대금) - 프로젝트 표준",
        "splits": ["ALL", "TRAIN", "VALID", "TEST"],
        "costBps": COST_LEVELS,
        "rollWindows": ROLL_WINDOWS,
        "residualization": "TRAIN에서만 fit(월별 계수 중앙값), VALID/TEST에 고정 적용",
    }

    # ---------- 실제 포트 라인 (gross top-decile 계열을 분할/비용/rolling/turnover 에 재사용) ----------
    # 각 시그널: ALL 기간 상위 decile EW gross 월 리턴 계열 (date 정렬)
    def build_series(sub, sig):
        recs = month_top_names(sub, sig)
        dates = [d for d, _, _, _ in recs]
        gross = [r for _, _, r, _ in recs]
        names = [s for _, s, _, _ in recs]
        bench = []
        for d, _n, _r, _t in recs:
            bb = sub_ey[sub_ey["date"] == d][TARGET]
            bench.append(float(bb.mean()) if len(bb) else np.nan)
        return pd.Series(gross, index=pd.to_datetime(dates)), \
               pd.Series(bench, index=pd.to_datetime(dates)), \
               names

    # ---------- 1. A/B/C: EY / PBR-resid / Size+PBR-resid (TRAIN-고정) ----------
    print("=== 1. A/B/C portfolio (TRAIN-fixed residual) ===", flush=True)
    pbr_panel = add_residual_fixed(sub_ey.copy(), ["pbr"])
    both_panel = add_residual_fixed(sub_ey.copy(), ["pbr", SIZE_COL])
    size_panel = add_residual_fixed(sub_ey.copy(), [SIZE_COL])

    variants = [
        ("A_rawEY", "earnings_yield", sub_ey),
        ("B_eyResPbr_fixed", "ey_res_pbr_fixed", pbr_panel),
        ("C_eyResSizePbr_fixed", "ey_res_pbr_dv20_log_fixed", both_panel),
        ("S_eyResSize_fixed", "ey_res_dv20_log_fixed", size_panel),
    ]

    abc = {}
    for label, sig, panel in variants:
        css, bs, name_list = build_series(panel, sig)
        ic_recs = ic_series(panel, sig)
        abc[label] = {"ic": summarize_ic(ic_recs),
                      "crossSectionalCorr_PBR_fixed": None}
        # 교차단면 상관 (raw 신호 vs PBR)
        if "raw" in label:
            abc[label]["crossSectionalCorr_EY_PBR"] = cs_corr(panel, "earnings_yield", "pbr")
        per = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            mask = [fd.period_of(str(d.date())) == p for d in css.index]
            nets = [(k, float(css.iloc[k]) - 30 / 10000) for k, use in enumerate(mask) if use]
            per[p] = portfolio_stats(nets)
        abc[label]["portfolio"] = per
        # IC t 분할
        icper = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            ss = panel if p == "ALL" else panel[panel["period"] == p]
            icper[p] = summarize_ic(ic_series(ss, sig))
        abc[label]["ic_by_split"] = icper
        # A/B/C 모두에 benchmark excess (TEST 초점) — EW benchmark 는 동일 유니버스
        excess_per = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            mask = [fd.period_of(str(d.date())) == p for d in css.index]
            exc = [(k, float(css.iloc[k]) - float(bs.iloc[k])) for k, use in enumerate(mask) if use]
            excess_per[p] = portfolio_stats(exc)
        abc[label]["excessEW_by_split"] = excess_per
        print(f"  {label}: TEST ic_t={icper['TEST']['t']} "
              f"port CAGR={per['TEST']['cagr'] if per['TEST'] else None} "
              f"Sh={per['TEST']['sharpe'] if per['TEST'] else None}", flush=True)

    results["abcPortfolio"] = abc

    # IC 유의 vs portfolio 유지 판별용 키 요약
    summary = {}
    for label, sig, panel in variants:
        r = abc[label]
        summary[label] = {
            "TEST_icT": r["ic_by_split"]["TEST"]["t"],
            "TEST_icMean": r["ic_by_split"]["TEST"]["mean"],
            "TEST_portCagr": (r["portfolio"]["TEST"]["cagr"] if r["portfolio"]["TEST"] else None),
            "TEST_portSharpe": (r["portfolio"]["TEST"]["sharpe"] if r["portfolio"]["TEST"] else None),
            "TEST_excessCagr": (r["excessEW_by_split"]["TEST"]["cagr"] if r["excessEW_by_split"]["TEST"] else None),
        }
    results["abcSummary"] = {k: summary[k] for k in summary}

    # ---------- 2. Size / PBR / Size+PBR 교차단면 상관 & 잔차 IC (TRAIN-고정) ----------
    print("=== 2. Controls cross-correlation ===", flush=True)
    controls_out = {"residIC_fixed": {}, "crossSectionalCorr": {}}
    for ctl, panel, col in [("Size", size_panel, "ey_res_dv20_log_fixed"),
                            ("PBR", pbr_panel, "ey_res_pbr_fixed"),
                            ("SizePBR", both_panel, "ey_res_pbr_dv20_log_fixed")]:
        ric = {}
        for p in ["ALL", "TRAIN", "VALID", "TEST"]:
            ss = panel if p == "ALL" else panel[panel["period"] == p]
            ric[p] = summarize_ic(ic_series(ss, col))
        controls_out["residIC_fixed"][ctl] = ric
        ctl_col = {"Size": SIZE_COL, "PBR": "pbr", "SizePBR": "pbr"}[ctl]
        controls_out["crossSectionalCorr"][ctl] = cs_corr(sub_ey, SIGNAL, ctl_col)
    results["controlsIndependence"] = controls_out
    print("  done", flush=True)

    # ---------- 3. 업종 집중도 / 업종중립(PIT) / 특정 업종 TEST 지배 ----------
    print("=== 3. Industry ===", flush=True)
    # (a) top-decile 업종 집중도 (전체 + TEST)
    def sector_share(recs):
        cnt, tot = {}, 0
        for _, _, _, top in recs:
            for s, c in top["sector"].fillna("NA").value_counts().items():
                cnt[str(s)] = cnt.get(str(s), 0) + int(c)
                tot += int(c)
        sh = {s: round(c / tot, 4) for s, c in cnt.items()}
        return {"totalSelections": tot, "nSectors": len(cnt),
                "topSectors": [{"sector": s, "share": sh[s]} for s in sorted(sh, key=lambda x: -sh[x])[:6]]}

    recs_all = month_top_names(sub_ey, SIGNAL)
    recs_test = [(d, s, r, t) for d, s, r, t in recs_all if fd.period_of(str(d)) == "TEST"]
    ind = {"topDecileSectorShare": {"ALL": sector_share(recs_all), "TEST": sector_share(recs_test)}}

    # 특정 1-2개 업종이 TEST 성과를 지배하는지: TEST 기간 업종별 EW 리턴 & 기여
    test_top = pd.concat([t for _, _, _, t in recs_test])
    test_top["sector"] = test_top["sector"].fillna("NA")
    sec_stats = []
    for s, g in test_top.groupby("sector"):
        n = len(g)
        ew = float(g[TARGET].mean())
        cum = float(np.prod(1 + g[TARGET].to_numpy())
                    ** (12 / len(g)) - 1) if len(g) else None
        sec_stats.append({"sector": s, "nNames": int(n), "ewMeanFwd": round(ew, 5), "cagr": round(cum, 4) if cum is not None else None})
    sec_stats.sort(key=lambda x: -(x["nNames"]))
    ind["testSectorContribution"] = sec_stats[:8]
    results["industry"] = ind

    # 업종중립 EY (panel 에 PIT 구축된 sector_rel_earnings_yield) vs raw
    sec_panel = sub_ey.dropna(subset=["sector_rel_earnings_yield"]).copy()
    ind_neq = {}
    for p in ["ALL", "TRAIN", "VALID", "TEST"]:
        ss = sec_panel if p == "ALL" else sec_panel[sec_panel["period"] == p]
        raw_port = portfolio_stats([(d, r - 30 / 10000) for d, r in _raw_series(ss)])
        rel_port = portfolio_stats([(d, r - 30 / 10000) for d, r in _sector_rel_series(ss)])
        ind_neq[p] = {
            "n": int(len(ss)),
            "rawEY_ic": summarize_ic(ic_series(ss, SIGNAL)),
            "sectorRelEY_ic": summarize_ic(ic_series(ss, "sector_rel_earnings_yield")),
            "rawEY_port": raw_port,
            "sectorRelEY_port": rel_port,
        }
    results["industryNeutral"] = ind_neq
    print("  done", flush=True)

    # ---------- 4. 연도별 + rolling + benchmark excess ----------
    print("=== 4. Yearly & rolling ===", flush=True)
    css, bs, _ = build_series(sub_ey, SIGNAL)
    # 연도별
    yearly = {}
    for d, r in css.items():
        yearly.setdefault(str(d.year), []).append((d, float(r) - 30 / 10000, float(bs.loc[d])))
    yearly_stats = {}
    for y, m in sorted(yearly.items()):
        port = [v for _, v, _ in m]
        exc = [v - b for _, v, b in m]
        yearly_stats[y] = {
            "nMonths": len(m),
            "meanMonthlyNet": round(float(np.mean(port)), 5),
            "cagr": (float(np.prod([1 + v for v in port])) ** (12 / len(m)) - 1) if len(m) else None,
            "benchCagr": (float(np.prod([1 + b for _, _, b in m])) ** (12 / len(m)) - 1) if len(m) else None,
            "excessCagr": (float(np.prod([1 + e for e in exc])) ** (12 / len(m)) - 1) if len(m) else None,
            "bench_meanM": round(float(np.mean([b for _, _, b in m])), 5),
            "posMonths": sum(1 for v in port if v > 0),
        }
    results["yearly"] = yearly_stats

    # rolling (24/36개월): 포트 CAGR + benchmark excess CAGR (net 30bps)
    rolling = {}
    months_dates = list(css.index)
    for W in ROLL_WINDOWS:
        win = []
        for i in range(W - 1, len(months_dates)):
            segd = months_dates[i - W + 1:i + 1]
            segp = [float(css.loc[d]) - 30 / 10000 for d in segd]
            sege = [float(css.loc[d]) - float(bs.loc[d]) for d in segd]
            start = str(segd[0].date()); end = str(segd[-1].date())
            cagr_p = float(np.prod([1 + v for v in segp]) ** (12 / W) - 1)
            cagr_e = float(np.prod([1 + v for v in sege]) ** (12 / W) - 1)
            win.append({"start": start, "end": end, "cagr": round(cagr_p, 4),
                        "excessCagr": round(cagr_e, 4)})
        pos_w = sum(1 for w in win if w["cagr"] > 0)
        pos_e = sum(1 for w in win if w["excessCagr"] > 0)
        rolling[str(W)] = {
            "nWindows": len(win),
            "posCagrRatio": round(pos_w / len(win), 3) if win else None,
            "posExcessRatio": round(pos_e / len(win), 3) if win else None,
            "windows": win,
            "bestCagr": max(w["cagr"] for w in win) if win else None,
            "worstCagr": min(w["cagr"] for w in win) if win else None,
        }
    results["rolling"] = rolling
    print("  rolling done", flush=True)

    # ---------- 5. 비용 robustness (30/50/65bps, 미래/결과 기반 선택 없음) ----------
    print("=== 5. Cost ===", flush=True)
    gross = [float(r) for r in css]
    cost = {}
    for cbps in COST_LEVELS:
        nets = [(i, g - cbps / 10000) for i, g in enumerate(gross)]
        cost[f"roundtrip_{cbps}bps"] = portfolio_stats(nets)
    results["cost"] = cost
    # 구간별(특히 TEST) 비용 민감도 — 고정 rule(월 전량 왕복) 그대로
    cost_by_split = {}
    split_of = [fd.period_of(str(d.date())) for d in css.index]
    for p in ["TRAIN", "VALID", "TEST"]:
        cost_by_split[p] = {}
        for cbps in COST_LEVELS:
            nets = [(i, g - cbps / 10000) for i, (g, sp) in enumerate(zip(gross, split_of)) if sp == p]
            cost_by_split[p][f"rt_{cbps}bps"] = portfolio_stats(nets)
    results["costBySplit"] = cost_by_split
    print("  cost by split done", flush=True)

    # ---------- 6. Turnover ----------
    print("=== 6. Turnover ===", flush=True)
    name_sets = [s for _, s, _, _ in recs_all]
    sizes = [len(s) for s in name_sets]
    tos = []
    for k in range(1, len(name_sets)):
        prev, cur = name_sets[k - 1], name_sets[k]
        if len(prev) == 0 or len(cur) == 0:
            continue
        kept = len(prev & cur)
        turn = 1 - kept / len(prev)
        tos.append((k, round(turn, 4)))
    to_v = [t for _, t in tos]
    q = lambda a: round(float(np.percentile(to_v, a)), 4)
    turnover_out = {
        "nObservations": len(to_v),
        "nMonths": len(to_v) + 1,
        "mean": round(float(np.mean(to_v)), 4),
        "p25": q(25), "p50": q(50), "p75": q(75), "p95": q(95),
        "max": round(float(np.max(to_v)), 4),
        "min": round(float(np.min(to_v)), 4),
        "topDecileMeanNames": round(float(np.mean(sizes)), 2),
    }
# 비용 증가로 인한 성과 감소가 turnover 때문인지: CAGR 감소폭을 turnover 와 함께 제시
    cost30 = cost["roundtrip_30bps"]["cagr"]; cost50 = cost["roundtrip_50bps"]["cagr"]
    cost65 = cost["roundtrip_65bps"]["cagr"]
    # turnover-aware net: 월별 비용 = cost_bps/10000 × 당월 turnover(실제 교체분만).
    # 첫 달은 기존 명단 없음 → turnover 1.0(초기 매수) 가정.
    gross_arr = gross
    turn_arr = [1.0] + [t for _, t in tos]
    ta = {}
    for cbps in COST_LEVELS:
        nets = [(i, g - cbps / 10000 * turn_arr[i]) for i, g in enumerate(gross_arr)]
        ta[f"rt_{cbps}bps"] = portfolio_stats(nets)
    turnover_out["costSensitivityContext"] = {
        "ALL_net30_CAGR": cost30, "ALL_net50_CAGR": cost50, "ALL_net65_CAGR": cost65,
        "dCagr_30to50": round(cost50 - cost30, 4),
        "dCagr_30to65": round(cost65 - cost30, 4),
        "costPerMonthlyTurnover": round(30 / 10000 * turnover_out["mean"], 5),
        "turnoverAware": {
            "fixedConvention_fullTurnoverPerMonth": "월 전량(100%) 교체 가정 비용 — 기존 프로젝트 rule",
            "measuredTurnoverMean": turnover_out["mean"],
            "note": "고정 rule은 월 100% 교체를 가정하나 실측 turnover 는 15~16% — turnover-aware 비용은 약 1/6",
        },
        "turnoverAware_netCagr_30": ta["rt_30bps"]["cagr"],
        "turnoverAware_netCagr_50": ta["rt_50bps"]["cagr"],
        "turnoverAware_netCagr_65": ta["rt_65bps"]["cagr"],
    }
    results["turnover"] = turnover_out
    print("  turnover done", flush=True)

    # ---------- 7. 경제적/통계적 독립성 종합 (YES/NO) ----------
    r = summary
    s = results
    def yesno(cond):
        return "YES" if cond else "NO"

    b = r["B_eyResPbr_fixed"]; c = r["C_eyResSizePbr_fixed"]
    nq = results["industryNeutral"]
    ver = {
        "Size_controlled_signal_kept(Q1)":
            yesno(r["S_eyResSize_fixed"]["TEST_icT"] is not None and r["S_eyResSize_fixed"]["TEST_icT"] >= 2
                  and r["S_eyResSize_fixed"]["TEST_portCagr"] is not None
                  and r["S_eyResSize_fixed"]["TEST_portCagr"] > 0.03),
        "PBR_controlled_portfolio_alpha_kept(Q2)":
            yesno(b["TEST_icT"] is not None and b["TEST_icT"] >= 2 and b["TEST_portCagr"] is not None
                  and b["TEST_portCagr"] > 0.03),
        "SizePBR_controlled_portfolio_alpha_kept(Q3)":
            yesno(c["TEST_icT"] is not None and c["TEST_icT"] >= 2 and c["TEST_portCagr"] is not None
                  and c["TEST_portCagr"] > 0.03),
        "Industry_neutral_signal_kept(Q4)":
            yesno(nq["TEST"]["sectorRelEY_ic"]["t"] >= 2),
        "Not_overly_dependent_on_few_years(Q5)":
            yesno(rolling["24"]["posCagrRatio"] and rolling["24"]["posCagrRatio"] >= 0.5
                  and rolling["36"]["posCagrRatio"] and rolling["36"]["posCagrRatio"] >= 0.5),
        "Economic_alpha_under_realistic_cost(Q6)":
            yesno(cost["roundtrip_65bps"]["cagr"] is not None and cost["roundtrip_65bps"]["cagr"] > 0),
    }
    results["yesNo"] = ver
    results["executionTime_s"] = round(time.time() - t0, 1)

    out_path = os.path.join(OUT_DIR, "ey-final-robustness.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


def _raw_series(sub):
    out = []
    for d, g in sub.groupby("date", sort=True):
        gg = g.dropna(subset=[SIGNAL]).copy()
        if len(gg) < fd.MIN_NAMES or gg[SIGNAL].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg[SIGNAL].rank(method="first"), 10, labels=False) + 1
        out.append((d, float(gg.loc[gg["dec"] == 10, TARGET].mean())))
    return out


def _sector_rel_series(sub):
    out = []
    for d, g in sub.groupby("date", sort=True):
        gg = g.dropna(subset=["sector_rel_earnings_yield"]).copy()
        if len(gg) < fd.MIN_NAMES or gg["sector_rel_earnings_yield"].nunique() <= 1:
            continue
        gg["dec"] = pd.qcut(gg["sector_rel_earnings_yield"].rank(method="first"), 10, labels=False) + 1
        out.append((d, float(gg.loc[gg["dec"] == 10, TARGET].mean())))
    return out


if __name__ == "__main__":
    main()
