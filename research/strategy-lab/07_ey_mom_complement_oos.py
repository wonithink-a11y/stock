#!/usr/bin/env python
"""07_ey_mom_complement_oos.py — earnings_yield × LOWMOM60 complement OOS.

설계 문서: 07_earnings_yield_momentum_complement_oos_2026-09.md

목적: earnings_yield(검증된 value 축)가 이 프로젝트에서 검증·사용 가능한
모멘텀 정의(LOWMOM60 = 저모멘텀 롱, kr-market-breadth-rs REJECT + LOWMOM60
후보C가 확립한 방향)와 결합될 때 동일 value 신호의 중복인지, 서로 다른
정보인지 검증한다.

핵심 규칙 (설계 문서 그대로):
  - earnings_yield = 1/per (per>0, valuation-panel PIT) — 기본 축 고정.
  - momentum = LOWMOM60 = mom6m(=60세션) 오름차순, 저모멘텀이 좋은 방향.
    기존 프로젝트에서 검증된 정의만 사용, 신규 정의 발명 없음.
  - 기본 결합 = 동일가중 rank composite (월별 cross-sectional pct rank 평균).
  - TRAIN/VALID/TEST 시간분할 유지 (2022-06-30 / 2024-01-01).
  - 전체기간 최고 조합 사후 선택 안 함. 결합 규칙은 사전 고정(튜닝 없음).
  - PIT·수정주가·데이터 계약 유지 (factor_discovery_kr.py 재사용).

모든 지표는 factor_discovery_kr.decile_analysis()를 그대로 재사용해 실제
계산한다(만든 수치 아님). 추가로 turnover proxy(월별 decile-10 명단 교체율)를
계산해 결합으로 인한 turnover 증가가 성과를 잠식하는지 본다.
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-06-ey-mom-complement-oos")
MOM_WINDOW = 126  # mom6m = 60세션 (~6개월), LOWMOM60의 mom60과 동일 창 및 factor_discovery mom6m과 동일


def build_base():
    t0 = time.time()
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(fd.A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["mom6m"] = df["close"] / df["close"].groupby(df["ticker"]).shift(MOM_WINDOW) - 1
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["liquid"] = df["dv20"] >= fd.LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = fd.monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # forward 1-month return: factor_discovery_kr.py와 동일 규약.
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {months[i]: months[i + 1] for i in range(len(months) - 1)}
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[i + 1]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd1m"] = fwd
    base = base.dropna(subset=["fwd1m"])
    base = base[base["fwd1m"] > -1].copy()
    print(f"  with fwd1m {len(base)} rows ({time.time()-t0:.0f}s)", flush=True)

    market_map = fd.load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(fd.period_of)
    base["lowmom"] = -base["mom6m"]  # 저모멘텀=좋은 방향 (검증된 LOWMOM60 방향)
    n_pre = len(base)
    base = base[base["liquid"]].copy()
    print(f"  liquidity gate dv20>=1e8: {n_pre} -> {len(base)} rows", flush=True)

    print("loading valuation-panel (per) ...", flush=True)
    vdf = fd.load_panel(fd.VALUATION_PANEL, ["per"])
    base["per"] = [fd.panel_lookup(vdf, t, d, "per") for t, d in zip(base["ticker"], base["date"])]
    base["earnings_yield"] = np.where((base["per"].notna()) & (base["per"] > 0),
                                      1.0 / base["per"], np.nan)
    print(f"  base ready ({time.time()-t0:.0f}s)", flush=True)
    return base


def rank_composite(sub):
    """동일가중 rank composite: 월별 cross-sectional pct rank(earnings_yield)와
    pct rank(lowmom)의 평균. 두 축 모두 '높을수록 좋음' 방향으로 맞춘다.
    결합 규칙은 사전 고정(튜닝 없음)."""
    def _rank(g):
        ey = g["earnings_yield"].rank(pct=True)
        lm = g["lowmom"].rank(pct=True)
        return (ey + lm) / 2.0
    return sub.groupby("date", group_keys=False).apply(_rank)


def top_decile_churn(sub, f, months):
    """월별 decile-10 명단의 교체율 proxy: 이번 달과 다음 달 decile-10(최상위)
    종목 집합의 Jaccard 거리. f 기반 월별 cross-sectional qcut decile 계산."""
    churns = []
    prev_set = None
    for m in sorted(months):
        g = sub[sub["date"] == m].dropna(subset=[f])
        if len(g) < fd.MIN_NAMES or g[f].nunique() <= 1:
            prev_set = None
            continue
        g2 = g.copy()
        g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
        cur = set(g2.loc[g2["dec"] == 10, "ticker"])
        if prev_set is not None and len(prev_set) > 0 and len(cur) > 0:
            inter = len(prev_set & cur)
            union = len(prev_set | cur)
            churns.append(1.0 - inter / union if union else 0.0)
        prev_set = cur
    return {"nMonths": len(churns),
            "meanChurn": round(float(np.mean(churns)), 4) if churns else None}


def top_decile_stats(res):
    """decile_analysis의 longTopDecile.net(월별 포트)에서 WINRATE(양수 개월 비율) 추가."""
    net = res["longTopDecile"]["net"]
    if not net:
        return None
    return net


def top_decile_winrate(sub, f):
    """상위 decile(10) 종목 EW 평균 월수익이 양수인 개월 비율 (WINRATE)."""
    wins = 0
    n = 0
    for ddate, g in sub.groupby("date"):
        g2 = g.dropna(subset=[f]).copy()
        if len(g2) < fd.MIN_NAMES or g2[f].nunique() <= 1:
            continue
        g2["dec"] = pd.qcut(g2[f].rank(method="first"), 10, labels=False) + 1
        top = g2.loc[g2["dec"] == 10, "fwd1m"]
        if len(top) == 0:
            continue
        n += 1
        if top.mean() > 0:
            wins += 1
    return {"nMonths": n, "winRate": round(wins / n, 4) if n else None}


def analyze(sub, f):
    if sub.empty:
        return None
    res = fd.decile_analysis(sub, f)
    if res is None:
        return None
    months = sorted(sub["date"].unique())
    res["topDecileChurn"] = top_decile_churn(sub, f, months)
    res["topDecileWinRate"] = top_decile_winrate(sub, f)
    return res


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    base = build_base()

    need_all = ["earnings_yield", "lowmom", "fwd1m"]
    sub_all = base.dropna(subset=need_all).copy()
    print(f"both-axis coverage (EY & LOWMOM60): {len(sub_all)}/{len(base)} "
          f"({len(sub_all) / len(base) * 100:.1f}%)", flush=True)

    # composite: 동일가중 rank (사전 고정 규칙) — 월별 계산
    sub_all["composite"] = rank_composite(sub_all)

    results = {
        "factor": "earnings-yield-momentum-complement-oos",
        "generatedAt": pd.Timestamp.utcnow().isoformat(),
        "purpose": "earnings_yield × LOWMOM60 결합이 EY 단독 대비 incremental 정보를 주는지",
        "momentumDef": "LOWMOM60 = -mom6m(-60세션), 저모멘텀이 좋은 방향 (검증된 방향 재사용)",
        "compositeRule": "equal-weight rank composite, 사전 고정(튜닝 없음)",
        "trainEnd": "2022-06-30", "validEnd": "2024-01-01",
        "splits": {},
    }

    for split in ["ALL", "TRAIN", "VALID", "TEST"]:
        sub = sub_all if split == "ALL" else sub_all[sub_all["period"] == split]
        split_res = {}
        for label, f in [("ey_only", "earnings_yield"),
                         ("lowmom60_only", "lowmom"),
                         ("ey_lowmom60_composite", "composite")]:
            res = analyze(sub, f)
            if res is None:
                split_res[label] = None
                continue
            top = res["longTopDecile"]["net"]
            spr = res["spread"] or {}
            split_res[label] = {
                "n": res["n"], "nMonths": res["nMonths"],
                "ic": res["ic"], "decileSlopeSpearman": res["decileSlopeSpearman"],
                "spread": spr,
                "longTopDecile_net": top,
                "topDecileChurn": res["topDecileChurn"],
                "topDecileWinRate": res["topDecileWinRate"],
            }
            print(f"[{split}] {label}: n={res['n']} m={res['nMonths']} "
                  f"slope={res['decileSlopeSpearman']} spread_t={spr.get('t')} "
                  f"ic_t={res['ic'].get('t')} | topNet cagr={top.get('cagr')} "
                  f"sharpe={top.get('sharpe')} mdd={top.get('mdd')} "
                  f"win={res['topDecileWinRate'].get('winRate')} "
                  f"churn={res['topDecileChurn'].get('meanChurn')}", flush=True)
        results["splits"][split] = split_res

    # 판정 관점: 두 축 decile slope가 composite에서 모두 살아있는지 —
    # EY decile 내 lowmom slope, lowmom decile 내 EY slope (ALL, 각 split)
    print("=== second-axis slope within first-axis deciles (ALL) ===", flush=True)
    second_axis = {}
    tmp = sub_all.dropna(subset=["earnings_yield", "lowmom", "fwd1m"])
    for outer, outer_good in [("ey", "earnings_yield"), ("lowmom", "lowmom")]:
        inner = "lowmom" if outer == "ey" else "earnings_yield"
        slopes = []
        pooled = {d: [] for d in range(1, 11)}
        for ddate, g in tmp.groupby("date"):
            if len(g) < fd.MIN_NAMES or g[outer_good].nunique() <= 1:
                continue
            g2 = g.copy()
            g2["dec"] = pd.qcut(g2[outer_good].rank(method="first"), 10, labels=False) + 1
            for dec_i, gv in g2.groupby("dec"):
                pooled[int(dec_i)].extend(gv["fwd1m"].tolist())
            # inner-axis IC within outer decile 10 (겹침: 내부 서브그룹에서도 slope 살아있는지)
            topd = g2[g2["dec"] == 10]
            if len(topd) > 2 and topd[inner].nunique() > 1:
                r = spearman(topd[inner], topd["fwd1m"])
                if not np.isnan(r):
                    slopes.append(float(r))
        sa = np.array(slopes, dtype=float) if slopes else np.array([])
        second_axis[outer] = {
            "outerFactor": outer, "innerFactor": inner,
            "innerIC_withinOuterTopDecile": {
                "nMonths": len(slopes),
                "mean": round(float(sa.mean()), 6) if len(sa) else None,
                "t": round(float(sa.mean() / (sa.std(ddof=1) / np.sqrt(len(sa)))), 3)
                    if len(sa) > 1 and sa.std(ddof=1) > 0 else None,
            },
        }
        print(f"  {outer} decile에 {inner} slope(내부 IC): mean={second_axis[outer]['innerIC_withinOuterTopDecile']['mean']} "
              f"t={second_axis[outer]['innerIC_withinOuterTopDecile']['t']} "
              f"m={len(slopes)}", flush=True)
    results["withinDecileSecondAxisSlope"] = second_axis

    out_path = os.path.join(OUT_DIR, "ey-mom-complement-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


def spearman(a, b):
    from scipy.stats import spearmanr
    r = spearmanr(a, b)
    return r.statistic


if __name__ == "__main__":
    main()
