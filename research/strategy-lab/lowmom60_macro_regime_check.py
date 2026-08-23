#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""LOWMOM60+기관수급 후보 — macro regime 축별 조건부 성과 검증 (2026-08).

pbr_macro_rate_regime_check.py가 검증한 방법론(월별 수익을 "trailing 126거래일
변화"의 부호(hiking>0 / not-hiking<=0)로 분류해 평균수익·기여율을 비교)을
다른 팩터 후보인 LOWMOM60+기관수급에 적용한다. 백테스트 로직은
lowmom60_institutional_eligible_precheck_v2_absolute.py와 동일(top30,
turnover20>=1억원 절대 임계값, cost 30bps round-trip)이고, run_backtest()가
내부에서 만드는 월별 절대수익 시계열(mdf)만 반환하도록 복제했다.

threshold 재최적화 없음(TRAIL_DAYS=126·>0 사전 고정), production 코드·정책
무변경, 새 회귀 없음 - 순수 진단.

  python lowmom60_macro_regime_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"
TOP_N = 30
COST_RT_BPS = 30.0
MIN_TURNOVER = 100_000_000.0  # 1억원 — v2_absolute와 동일 임계
TRAIL_DAYS = 126  # ~6개월 거래일, 사전 고정(pbr_macro_rate_regime_check와 동일, 재최적화 없음)
REGIME_PARQUET = os.path.join(REPO_ROOT, "research", "strategy-lab", "data",
                              "market-regime", "market_regime_features.parquet")

AXES = [
    ("usFedFundsRate", "미국 연방기금금리(6개월 변화)"),
    ("usTreasury10y", "미국 10년물 금리(6개월 변화)"),
    ("usNasdaq", "나스닥 지수(6개월 변화)"),
    ("krKospi", "KOSPI 지수(6개월 변화)"),
    ("krTreasury3y", "한국 국고채 3년물 금리(6개월 변화)"),
    ("krCorpAA3y", "한국 회사채 AA- 3년물 금리(6개월 변화)"),
    ("krCpi", "한국 CPI(6개월 변화)"),
    ("krLeadingCyclical", "한국 선행순환지수(6개월 변화)"),
    ("krCoincidentCyclical", "한국 일반순환지수(6개월 변화)"),
    ("krCreditSpreadBp", "한국 신용스프레드(bp, 6개월 변화, 확대=긴축)"),
]


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def build_panel(bars_by_ticker, rebalance_dates):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        mom60 = close / close.shift(60) - 1
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            m = mom60.iloc[i]
            if pd.isna(m):
                continue
            entry_date = idx[i + 1]
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[i + 1]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            tv = turnover20.iloc[i]
            rows.append({
                "ticker": ticker, "entry_date": t, "mom60": float(m),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def monthly_returns_mdf(df, top_n=TOP_N, cost_bps=COST_RT_BPS):
    """run_backtest(liquidity_filter='high') 내부 루프와 동일, mdf만 반환."""
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        g = g[g["turnover20"] >= MIN_TURNOVER]
        g = g.sort_values("mom60").head(top_n)
        if g.empty:
            continue
        month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean(), len(g)))
    return pd.DataFrame(month_rets, columns=["month", "ret", "n"])


def backtest_stats(mdf):
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_years = len(mdf["month"].str[:4].unique())
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if n_years else None
    return {
        "monthsTraded": len(mdf),
        "avgTickersPerMonth": round(mdf["n"].mean(), 1) if len(mdf) else None,
        "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def rate_regime_features():
    """market_regime_features.parquet에서 축별 trailing 126거래일 변화를 계산.
    pbr_macro_rate_regime_check.rate_regime_features()와 동일 패턴, 축만 확장.
    정규화·재최적화 없음 - 전 축 같은 창."""
    cols = ["date"] + [a for a, _ in AXES]
    df = pd.read_parquet(REGIME_PARQUET)[cols].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for axis, _ in AXES:
        df[axis + "Chg6m"] = df[axis] - df[axis].shift(TRAIL_DAYS)
    return df


def bucket_report(ret_df, regime_df, chg_col, label):
    """ret_df: [date, ret]. regime_df: [date, <chg_col>]. asof(backward) 조인 후
    hiking(변화>0)/not으로 나눠 합계·평균·기여율을 리포트. pbr 버전과 동일 구조."""
    left = ret_df.sort_values("date").copy()
    right = regime_df[["date", chg_col]].sort_values("date").copy()
    left["date"] = pd.to_datetime(left["date"])
    right["date"] = pd.to_datetime(right["date"])
    merged = pd.merge_asof(left, right, on="date", direction="backward")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged = merged.dropna(subset=[chg_col])
    hiking = merged[merged[chg_col] > 0]
    not_hiking = merged[merged[chg_col] <= 0]
    total_ret = merged["ret"].sum()
    hiking_ret = hiking["ret"].sum()
    return {
        "label": label,
        "months_total": int(len(merged)),
        "months_hiking": int(len(hiking)),
        "months_not_hiking": int(len(not_hiking)),
        "totalRetSum": round(float(total_ret), 5),
        "hikingRetSum": round(float(hiking_ret), 5),
        "notHikingRetSum": round(float(not_hiking["ret"].sum()), 5),
        "hikingSharePct": round(float(hiking_ret / total_ret * 100), 2) if total_ret != 0 else None,
        "hikingMeanMonthly": round(float(hiking["ret"].mean()), 5) if len(hiking) else None,
        "notHikingMeanMonthly": round(float(not_hiking["ret"].mean()), 5) if len(not_hiking) else None,
    }, merged


def year_hiking_breakdown(merged, chg_col):
    merged = merged.copy()
    merged["year"] = merged["date"].str.slice(0, 4)
    out = {}
    for y, g in merged.groupby("year"):
        out[y] = {
            "monthsHiking": int((g[chg_col] > 0).sum()),
            "monthsTotal": int(len(g)),
            "retSum": round(float(g["ret"].sum()), 5),
        }
    return out


def main():
    t0 = time.time()
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    print("=== LOWMOM60+기관수급 월별 절대수익 재현 (v2_absolute 로직 복제) ===")
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates)
    print(f"panel rows={len(df)}")

    mdf = monthly_returns_mdf(df)
    stats = backtest_stats(mdf)
    print("baseline(high liquidity) ->", json.dumps(stats, ensure_ascii=False),
          f"({time.time()-t0:.0f}s)")
    print("  v2_absolute 참조치(high_liquidity): CAGR +13.90%, totalReturn +3.1854, "
          "maxDD -0.4265 (reports/2026-08-21-.../lowmom60_institutional_eligible_"
          "precheck_v2_absolute.json - 복제 검증용)")

    regime_df = rate_regime_features()

    results, year_breakdowns = {}, {}
    for axis, label in AXES:
        chg_col = axis + "Chg6m"
        rep, merged = bucket_report(mdf[["month", "ret"]].rename(columns={"month": "date"}),
                                    regime_df, chg_col, label)
        results[chg_col] = rep
        year_breakdowns[chg_col] = year_hiking_breakdown(merged, chg_col)
        print("\n[%s]" % label)
        print("  전체 %d개월(hiking %d · not %d)"
              % (rep["months_total"], rep["months_hiking"], rep["months_not_hiking"]))
        print("  총수익합=%.4f, hiking구간 기여=%.4f(%s%%)"
              % (rep["totalRetSum"], rep["hikingRetSum"], rep["hikingSharePct"]))
        print("  hiking 월평균=%s vs not-hiking 월평균=%s"
              % (rep["hikingMeanMonthly"], rep["notHikingMeanMonthly"]))

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": "LOWMOM60+기관수급 후보의 macro regime 축별 조건부 성과 검증 - "
                   "pbr_macro_rate_regime_check.py 방법론(trailing 126거래일 변화 부호 분류)을 "
                   "lowmom60_institutional_eligible_precheck_v2_absolute.py 백테스트에 적용",
        "trailDays": TRAIL_DAYS,
        "period": [START, END],
        "topN": TOP_N,
        "costBps": COST_RT_BPS,
        "minTurnover": MIN_TURNOVER,
        "monthlyCount": int(len(mdf)),
        "baselineStats": stats,
        "results": results,
        "yearBreakdown": year_breakdowns,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-24-lowmom60-macro-regime")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "lowmom60-macro-regime-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
