#!/usr/bin/env python
"""오늘 확정한 결함(turnover20 rolling tercile이 중립적이지 않고 그 자체로
강한 예측변수)을 대체할 유동성 필터로, 이 프로젝트가 REV20/LOWMOM60 원래
robustness 검증에 쓴 **절대 거래대금 임계값**(turnover20 >= 고정 원화액,
rev20_combined_robustness.py·lowmom60_robustness.py 방식)이 같은 숨은
편향이 없는지 먼저 검증한다 (docs/control/세션인수인계-2026-08-21-c.md
후속, 사용자 승인 "go").

기준: testbed_mechanics_diagnostic.py가 이미 잰 "전체 유니버스, 무필터,
월별 리밸런싱, 30bps 비용" baseline(+2.94%, 매수-보유 벤치마크 +4.78% 대비
합리적 비용 드래그)에 얼마나 가까운가 — 절대임계값으로 나눈 고유동성
버킷이 이 정상 범위 안에 있으면 "중립적"으로 보고 재검토에 쓴다. 오늘의
T3(상대 tercile)처럼 벤치마크와 10%p 넘게 벌어지면 이것도 오염된 필터다.

  python absolute_turnover_filter_validation.py
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"
COST_RT_BPS = 30.0
MIN_TURNOVER = 100_000_000.0  # 1억원, rev20/lowmom60 robustness와 동일 임계
TOP_N = 30
N_RANDOM_SEEDS = 20
REFERENCE_FULL_UNIVERSE_CAGR = 0.0294  # testbed_mechanics_diagnostic.py, 30bps


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_universe_tickers():
    path = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line)["ticker"] for line in f]


def build_month_rows(bars_by_ticker, rebalance_dates):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
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
            if pd.isna(tv):
                continue
            rows.append({"ticker": ticker, "entry_date": t,
                         "ret": exit_price / entry_price - 1, "turnover20": float(tv)})
    return pd.DataFrame(rows)


def run_backtest(df, cost_bps=COST_RT_BPS, bucket=None, mode="all", top_n=TOP_N, seed=None):
    """bucket: 'high'(turnover20>=MIN_TURNOVER) | 'low' | None(전체)."""
    rng = random.Random(seed)
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if bucket == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif bucket == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        if mode == "random" and len(g) > top_n:
            g = g.loc[rng.sample(list(g.index), top_n)]
        if g.empty:
            continue
        month_rets.append((m, float(g["ret"].mean()) - cost_bps / 1e4, len(g)))
    mdf = pd.DataFrame(month_rets, columns=["month", "ret", "n"])
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_years = len(mdf["month"].str[:4].unique())
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if n_years else None
    return {
        "monthsTraded": len(mdf), "avgTickersPerMonth": round(mdf["n"].mean(), 1) if len(mdf) else None,
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def main():
    tickers = load_universe_tickers()
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="absolute-turnover-filter-validation")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"rows={len(df)}")

    results = {
        "high_bucket_equalWeight_all": run_backtest(df, bucket="high", mode="all"),
        "low_bucket_equalWeight_all": run_backtest(df, bucket="low", mode="all"),
    }
    high_cagrs, low_cagrs = [], []
    for seed in range(N_RANDOM_SEEDS):
        rh = run_backtest(df, bucket="high", mode="random", seed=seed)
        rl = run_backtest(df, bucket="low", mode="random", seed=seed)
        if rh["cagr"] is not None:
            high_cagrs.append(rh["cagr"])
        if rl["cagr"] is not None:
            low_cagrs.append(rl["cagr"])
    results["high_random30_meanCagr"] = round(sum(high_cagrs) / len(high_cagrs), 4) if high_cagrs else None
    results["high_random30_cagrRange"] = [round(min(high_cagrs), 4), round(max(high_cagrs), 4)] if high_cagrs else None
    results["low_random30_meanCagr"] = round(sum(low_cagrs) / len(low_cagrs), 4) if low_cagrs else None
    results["low_random30_cagrRange"] = [round(min(low_cagrs), 4), round(max(low_cagrs), 4)] if low_cagrs else None
    results["referenceFullUniverseCagr_30bps"] = REFERENCE_FULL_UNIVERSE_CAGR
    results["gapHighBucketVsReference"] = (round(results["high_bucket_equalWeight_all"]["cagr"] - REFERENCE_FULL_UNIVERSE_CAGR, 4)
                                            if results["high_bucket_equalWeight_all"]["cagr"] is not None else None)

    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-absolute-turnover-filter-validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "absolute-filter-validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "절대 거래대금 임계값(turnover20>=1억원) 필터가 오늘 확정한 상대 "
                       "tercile 결함과 같은 숨은 편향이 있는지 검증. 세션인수인계-"
                       "2026-08-21-c.md 후속.",
            "period": f"{START} ~ {END}", "minTurnover": MIN_TURNOVER, "costBps": COST_RT_BPS,
            "randomSeeds": N_RANDOM_SEEDS,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
