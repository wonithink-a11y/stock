#!/usr/bin/env python
"""메타패턴 조사: PBR·PEG·ROE 세 팩터(가치·성장·품질, 서로 다른 경제적 근거)가
전부 "저유동성 tercile(T1)에서만 플러스, 고유동성(T3)에서는 반전/소멸"로
수렴했다(2026-08-21, docs/control 인수인계 §추가확인·lynch_garp_factor_
precheck.py·buffett_quality_factor_precheck.py 실측). 사용자 승인 후 이
메타패턴 자체를 조사한다 — CAN SLIM으로 또 진행해 6번째로 같은 결론을
재확인하는 대신, "팩터가 하는 일이 있는가"부터 가른다.

방법: 팩터 순위를 아예 안 쓴다. 같은 유니버스·기간·turnover20 tercile 정의·
30bps 왕복비용·월별 리밸런싱으로 (a) T1/T3 버킷을 통째로 동일가중 매수하거나
(b) 버킷 안에서 무작위로 30종목을 뽑는(여러 시드 반복) 플라시보 백테스트를
돌린다. 이게 실측 팩터+T1 CAGR(PBR/PEG +4%대, ROE +8.68%)과 비슷한 규모로
나오면, 세 팩터가 측정한 건 팩터 알파가 아니라 "그 버킷에 들어간 것 자체"임을
뜻한다.

  python meta_pattern_liquidity_check.py
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
TOP_N = 30
COST_RT_BPS = 30.0
N_RANDOM_SEEDS = 20


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
    tickers = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            tickers.append(json.loads(line)["ticker"])
    return tickers


def build_month_rows(bars_by_ticker, rebalance_dates):
    """팩터 없이 (ticker, month) -> {ret, turnover20}만 만든다 — pbr/peg/roe
    precheck의 build_panel()과 진입/청산 규칙(신호월 다음 거래일 시가 진입,
    다음 리밸런싱월 다음 거래일 시가 청산)은 동일, factor lookup만 뺐다."""
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


def run_backtest(df, cost_bps=COST_RT_BPS, tercile_filter=None, mode="all", top_n=TOP_N, seed=None):
    """mode: 'all'(버킷 전체 동일가중) | 'random'(버킷에서 top_n 무작위 추출, seed 고정)."""
    rng = random.Random(seed)
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if tercile_filter:
            q1, q2 = g["turnover20"].quantile([1 / 3, 2 / 3])
            if tercile_filter == "T3":
                g = g[g["turnover20"] >= q2]
            elif tercile_filter == "T1":
                g = g[g["turnover20"] < q1]
        if mode == "random" and len(g) > top_n:
            g = g.loc[rng.sample(list(g.index), top_n)]
        if g.empty:
            continue
        month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean(), len(g)))
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
    bars_raw = a2a.load(tickers, START, END, universe_hash="meta-pattern-liquidity-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"rows={len(df)}")

    results = {
        "T1_bucket_equalWeight_all": run_backtest(df, tercile_filter="T1", mode="all"),
        "T3_bucket_equalWeight_all": run_backtest(df, tercile_filter="T3", mode="all"),
    }
    t1_cagrs, t3_cagrs = [], []
    for seed in range(N_RANDOM_SEEDS):
        r1 = run_backtest(df, tercile_filter="T1", mode="random", seed=seed)
        r3 = run_backtest(df, tercile_filter="T3", mode="random", seed=seed)
        if r1["cagr"] is not None:
            t1_cagrs.append(r1["cagr"])
        if r3["cagr"] is not None:
            t3_cagrs.append(r3["cagr"])
    results["T1_random30_meanCagr"] = round(sum(t1_cagrs) / len(t1_cagrs), 4) if t1_cagrs else None
    results["T1_random30_cagrRange"] = [round(min(t1_cagrs), 4), round(max(t1_cagrs), 4)] if t1_cagrs else None
    results["T3_random30_meanCagr"] = round(sum(t3_cagrs) / len(t3_cagrs), 4) if t3_cagrs else None
    results["T3_random30_cagrRange"] = [round(min(t3_cagrs), 4), round(max(t3_cagrs), 4)] if t3_cagrs else None

    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-meta-pattern-liquidity-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "meta-pattern-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR/PEG/ROE 세 팩터 모두 T1(저유동성)에서만 플러스, T3에서 "
                       "반전/소멸했다 - 팩터 순위 없이 T1/T3 버킷 자체를 사도 비슷한 "
                       "수익이 나는지 확인(무작위 30종목 추출 20회 반복 평균).",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "randomSeeds": N_RANDOM_SEEDS,
            "factorResultsForComparison": {
                "PEG_T1_cagr": 0.0408, "PEG_T3_cagr": -0.0202,
                "ROE_T1_cagr": 0.0868, "ROE_T3_cagr": -0.0766,
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
