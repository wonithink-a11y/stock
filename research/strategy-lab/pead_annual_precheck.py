#!/usr/bin/env python
"""PEAD(실적발표 후 드리프트) precheck — 착수 전 데이터 재확인에서 블로커
발견: 세션인수인계-2026-08-26.md와 findings/github-literature-return-
enhancement-candidates-2026-08.md가 "데이터 매핑 확인됨(A3b·A3d·
pitSelector.js)"이라 적어 뒀지만, 실제로 A3b(`data/backfill/fundamentals/
a3b/`)를 열어보면 fiscalYear 하나당 레코드 1건뿐인 **연간(annual) EPS만
있다** - reprtCode 필드 자체가 없다(A3c의 발행주식수는 reprtCode
11011~11014로 분기 커버리지가 있는 것과 대조적). A3d는 분할·병합 등 기업
행위 데이터로 실적발표와 무관하다. 즉 Eom·Hahn·Sohn(2019)이 실측한 표준
PEAD(분기 SUE, 발표 후 며칠~몇 주 드리프트)는 **이 프로젝트 데이터로 재현
불가능** - 이전 세션의 "데이터 매핑 타당" 판정은 파일 존재만 확인했지
분기 단위 여부를 확인하지 않은 오류였다(이 발견 자체가 이 스크립트의
1차 결과물).

그래도 완전히 막다른 골목은 아니다 - A3b의 연간 EPS로 "연간 SUE"(Foster/
Olsen/Shevlin 1984의 seasonal random walk 모델: SUE = deps_t / std(deps
과거 최대4년), 애널리스트 컨센서스 없이 과거 실적만으로 계산 가능한
정의)를 계산해, 연차보고서 공시일(availableFrom) 직후 수익률 드리프트가
있는지 cross-sectional decile/IC로 정찰한다. 표준 분기 PEAD보다 증거가
약하다는 걸 전제하고 보는 참고용 결과다 - 통과해도 "표준 PEAD 채택"이
아니라 "연간 버전이라도 신호가 있는지" 답만 준다.

  python pead_annual_precheck.py
"""
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3b")
START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
COST_RT_BPS = 30.0
HORIZONS = [20, 60]  # 세션수 - T+20(약 1개월)·T+60(약 3개월)
N_DECILES = 10
MIN_PRIOR_DEPS = 2  # SUE 분모(과거 deps 표준편차) 계산에 필요한 최소 관측치


def load_a3b():
    rows = []
    for fname in sorted(os.listdir(A3B_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3B_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df["availableFrom"] = pd.to_datetime(df["availableFrom"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    return df


def compute_annual_sue(df):
    """corp-year 패널에 deps(전년대비 EPS 변화)·SUE(deps/과거 deps 표준편차)를
    붙인다. 직전 연도가 실제로 fiscalYear-1이 아니면(결측 연도 있으면) deps를
    계산하지 않는다 - 결측을 이어붙여 계산하면 다년치 변화를 1년 변화로
    오인한다."""
    df = df.sort_values(["ticker", "fiscalYear"]).reset_index(drop=True)
    out = []
    for ticker, g in df.groupby("ticker"):
        g = g.sort_values("fiscalYear").reset_index(drop=True)
        eps = g["eps"].astype(float).values
        fy = g["fiscalYear"].values
        deps = np.full(len(g), np.nan)
        for i in range(1, len(g)):
            if fy[i] - fy[i - 1] == 1:
                deps[i] = eps[i] - eps[i - 1]
        g = g.copy()
        g["deps"] = deps
        # 과거(현재 제외) deps의 표준편차 - shift(1)로 당해 deps를 분모에서 뺀다
        g["priorDepsStd"] = g["deps"].shift(1).rolling(4, min_periods=MIN_PRIOR_DEPS).std()
        g["priorDepsCount"] = g["deps"].shift(1).rolling(4, min_periods=1).count()
        out.append(g)
    merged = pd.concat(out, ignore_index=True)
    merged["sue"] = merged["deps"] / merged["priorDepsStd"]
    return merged


def build_events(sue_df, bars_by_ticker, calendar):
    """announcement별로 진입가(공시 다음 거래일 시가)·turnover20·T+20/T+60 원시
    수익률(수수료 전)을 계산."""
    rows = []
    for _, r in sue_df.dropna(subset=["sue", "priorDepsStd"]).iterrows():
        if r["priorDepsStd"] == 0 or r["priorDepsCount"] < MIN_PRIOR_DEPS:
            continue
        ticker = r["ticker"]
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        avail = r["availableFrom"]
        after = idx[idx >= avail]
        if len(after) == 0:
            continue
        entry_date = after[0]
        i = idx.get_loc(entry_date)
        if i + 1 >= len(idx):
            continue
        entry_i = i + 1
        entry_price = float(open_.iloc[entry_i])
        if entry_price <= 0 or entry_i < 20:
            continue
        turnover20 = float((close * vol).iloc[max(0, entry_i - 20):entry_i].mean())
        row = {"ticker": ticker, "availableFrom": avail, "entryDate": idx[entry_i],
               "sue": float(r["sue"]), "turnover20": turnover20}
        ok = True
        for h in HORIZONS:
            exit_i = entry_i + h
            if exit_i >= len(idx):
                ok = False
                break
            row[f"ret_t{h}"] = float(open_.iloc[exit_i]) / entry_price - 1
        if ok:
            rows.append(row)
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    fr = pd.Series(factor_vals).rank()
    rr = pd.Series(fwd_rets).rank()
    return float(np.corrcoef(fr, rr)[0, 1])


def decile_analysis(events, ret_col, cost_bps=COST_RT_BPS):
    events = events.copy()
    events["month"] = events["availableFrom"].str.slice(0, 7)
    months = sorted(events["month"].unique())
    decile_rets = {d: [] for d in range(1, N_DECILES + 1)}
    monthly_ics = []
    for m in months:
        g = events[events["month"] == m]
        if len(g) < N_DECILES * 2:
            continue
        ranks = g["sue"].rank(ascending=False, method="first")  # SUE 높을수록 좋다는 가정 - decile1=최고SUE
        try:
            deciles = pd.qcut(ranks, N_DECILES, labels=False, duplicates="drop") + 1
        except ValueError:
            continue
        for d in range(1, int(deciles.max()) + 1 if len(deciles) else 1):
            sel = g.loc[deciles == d, ret_col]
            if len(sel):
                decile_rets[d].append(float(sel.mean()) - cost_bps / 1e4)
        ic = rank_ic(g["sue"].values, g[ret_col].values)
        if ic is not None:
            monthly_ics.append(ic)
    decile_avg = {d: (round(float(np.mean(v)), 4) if v else None) for d, v in decile_rets.items()}
    spread = None
    if decile_avg.get(1) is not None and decile_avg.get(N_DECILES) is not None:
        spread = round(decile_avg[1] - decile_avg[N_DECILES], 4)
    ic_mean = round(float(np.mean(monthly_ics)), 4) if monthly_ics else None
    ic_tstat = (round(ic_mean / (np.std(monthly_ics) / np.sqrt(len(monthly_ics))), 2)
                if monthly_ics and np.std(monthly_ics) > 0 else None)
    return {"monthsUsed": len(monthly_ics), "decileAvgReturn": decile_avg,
            "topMinusBottomDecile": spread, "meanMonthlyIC": ic_mean, "icTstat": ic_tstat}


def main():
    t0 = time.time()
    a3b = load_a3b()
    print(f"A3b loaded: {len(a3b)} corp-year records, {a3b['ticker'].nunique()} tickers")
    sue_df = compute_annual_sue(a3b)
    n_valid_sue = sue_df["sue"].notna().sum()
    print(f"SUE computable: {n_valid_sue}/{len(sue_df)} corp-years "
          f"(최소 {MIN_PRIOR_DEPS}개 과거 deps 필요)")

    tickers = sorted(a3b["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pead-annual-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    events = build_events(sue_df, bars_by_ticker, calendar)
    print(f"events with full T+{max(HORIZONS)} forward return: {len(events)}")

    eligible = events[events["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (turnover20>={MIN_TURNOVER:,.0f}): {len(eligible)}")

    results = {}
    for h in HORIZONS:
        results[f"t{h}_allEvents"] = decile_analysis(events, f"ret_t{h}")
        results[f"t{h}_eligibleLiquidity"] = decile_analysis(eligible, f"ret_t{h}")
        for k in [f"t{h}_allEvents", f"t{h}_eligibleLiquidity"]:
            r = results[k]
            print(f"  {k}: IC={r['meanMonthlyIC']} t={r['icTstat']} "
                  f"top-bottom={r['topMinusBottomDecile']} months={r['monthsUsed']}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pead-annual-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pead-annual-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PEAD 착수 전 재확인 - A3b가 연간 EPS만 있어 표준(분기) SUE는 "
                       "재현 불가(1차 발견). 연간 SUE(Foster/Olsen/Shevlin 1984 seasonal "
                       "random walk)로 정찰만 수행. findings/github-literature-return-"
                       "enhancement-candidates-2026-08.md ②(PEAD) 후속.",
            "nCorpYears": len(a3b), "nValidSue": int(n_valid_sue), "nEvents": len(events),
            "nEligible": len(eligible), "minTurnover": MIN_TURNOVER, "costBps": COST_RT_BPS,
            "horizons": HORIZONS, "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nsaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
