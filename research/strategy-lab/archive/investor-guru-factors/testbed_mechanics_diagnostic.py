#!/usr/bin/env python
"""테스트베드 설계 진단: 지금까지 시도한 7개 가설(5DC·TREND-BREAKOUT·LOWMOM60·
REV20·PBR·PEG·ROE)이 경제적 근거가 전부 다른데도 하나같이 "저유동성에서만
플러스, 고유동성에서 반전/소멸"이라는 같은 모양으로 죽었다(사용자 질문:
"이렇게까지 유효한 검증이 없는 이유가 뭐일까"). 오늘 발견한 단서 하나:
전체 유니버스 동일가중 매수-보유 벤치마크(research/strategy-lab/reports/
2026-08-15-trend-breakout-v1-benchmark-analysis/universe_ew_benchmark.json,
2016-2026 CAGR +4.78%)보다 T3(turnover20 상위 tercile) 월별 리밸런싱
baseline(-5.77%)이 10.5%p나 나쁘다 — 팩터와 무관한 baseline 자체의 문제일
가능성.

이 스크립트는 그 원인을 둘로 가른다: (a) tercile로 유니버스를 좁히는 것
자체가 문제인가, (b) "월별 리밸런싱+거래비용" 메커니즘 자체가 매수-보유보다
구조적으로 나쁜가. tercile 제한 없이 전체 유니버스를 월별 리밸런싱하고,
비용 0bps/30bps 두 버전을 재서 벤치마크(+4.78%)와 비교한다.

  python testbed_mechanics_diagnostic.py
"""
import json
import os
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
BUY_HOLD_BENCHMARK_CAGR = 0.0478  # universe_ew_benchmark.json 2016~2026 체인 계산(본문 참고), 재계산 아님


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
        close, open_ = bars["close"], bars["open"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
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
            rows.append({"ticker": ticker, "entry_date": t, "ret": exit_price / entry_price - 1})
    return pd.DataFrame(rows)


def run_monthly_rebalance_ew(df, cost_bps):
    months = sorted(df["entry_date"].unique())
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    years = set()
    for m in months:
        g = df[df["entry_date"] == m]
        if g.empty:
            continue
        r = float(g["ret"].mean()) - cost_bps / 1e4
        eq *= (1 + r)
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
        years.add(m[:4])
    n_years = len(years)
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if n_years else None
    return {"monthsTraded": len(months), "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4)}


def main():
    tickers = load_universe_tickers()
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="testbed-mechanics-diagnostic")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"rows={len(df)}")

    results = {
        "fullUniverse_monthlyRebalanceEW_0bps": run_monthly_rebalance_ew(df, cost_bps=0.0),
        "fullUniverse_monthlyRebalanceEW_30bps": run_monthly_rebalance_ew(df, cost_bps=30.0),
        "buyHoldBenchmark_forReference": {"cagr": BUY_HOLD_BENCHMARK_CAGR,
                                           "source": "2026-08-15-trend-breakout-v1-benchmark-analysis/universe_ew_benchmark.json (재계산 아님, 2016-2026 체인)"},
        "T3_turnoverTercile_monthlyRebalanceEW_30bps_forReference": {"cagr": -0.0577,
                                                                       "source": "t3_roe_quality_strategy_backtest.py T3_baseline_no_filter"},
        "T1_turnoverTercile_monthlyRebalanceEW_30bps_forReference": {"cagr": 0.1197,
                                                                       "source": "meta_pattern_liquidity_check.py T1_bucket_equalWeight_all"},
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-testbed-mechanics-diagnostic")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "testbed-diagnostic.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "테스트베드 설계 진단 - tercile 선별이 문제인지, 월별 리밸런싱+"
                       "비용 메커니즘 자체가 문제인지 가른다. 세션인수인계-2026-08-21-c.md 후속.",
            "period": f"{START} ~ {END}",
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
