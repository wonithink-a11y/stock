#!/usr/bin/env python
"""T3(대형주) ROE decile 분석(t3_factor_decile_check.py, meanMonthlyIC=0.0626,
t=8.06)이 찾은 신호를 실제 롱 전략으로 구성해 CAGR을 잰다.

decile 분석이 보인 모양은 "최상위를 집중매수"가 아니라 "저ROE 하위분위가
확실히 나쁘다"였다(decile 9·10 평균 -0.8%~-1.1%/월, decile 1~4는 완만).
그래서 top-30 집중매수 대신 **하위분위를 배제한 넓은 바스켓**(동일가중)으로
구성한다 — 그래야 decile 분석이 실제로 측정한 신호의 모양과 전략 설계가
일치한다.

  python t3_roe_quality_strategy_backtest.py
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
QUALITY_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                              "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
COST_RT_BPS = 30.0
N_DECILES = 10


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


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


def run_equity_curve(monthly_avg_rets, cost_bps=COST_RT_BPS):
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    months_used = 0
    for r in monthly_avg_rets:
        eq *= (1 + r - cost_bps / 1e4)
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
        months_used += 1
    return eq, maxdd, months_used


def backtest_variant(t3, keep_deciles, label):
    """keep_deciles: 그 달 남길 decile 번호 집합(1=최고ROE). None이면 필터 없음(T3 baseline)."""
    months = sorted(t3["entry_date"].unique())
    monthly_rets, ns, years = [], [], set()
    for m in months:
        g = t3[t3["entry_date"] == m]
        if keep_deciles is not None:
            g = g[g["roe"].notna()]
            if len(g) < N_DECILES * 3:
                continue
            ranks = g["roe"].rank(ascending=False, method="first")
            deciles = pd.qcut(ranks, N_DECILES, labels=False, duplicates="drop") + 1
            g = g[deciles.isin(keep_deciles)]
        if g.empty:
            continue
        monthly_rets.append(float(g["ret"].mean()))
        ns.append(len(g))
        years.add(m[:4])
    eq, maxdd, months_used = run_equity_curve(monthly_rets)
    n_years = len(years)
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if n_years else None
    return {
        "label": label, "monthsTraded": months_used,
        "avgTickersPerMonth": round(sum(ns) / len(ns), 1) if ns else None,
        "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def main():
    qual = pd.DataFrame([json.loads(line) for line in open(QUALITY_PANEL, encoding="utf-8")])
    qual = qual[["ticker", "asOf", "roe"]]

    tickers = sorted(set(qual["ticker"]))
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="t3-roe-quality-strategy")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    month_rows = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"month_rows={len(month_rows)}")

    merged = month_rows.merge(qual, left_on=["ticker", "entry_date"],
                               right_on=["ticker", "asOf"], how="left")

    # T3 tercile — 그 달 가격 있는 전체 종목 기준(팩터 유효 여부와 무관), 기존 스크립트와 같은 basis
    parts = []
    for m, g_all in month_rows.groupby("entry_date"):
        q1, q2 = g_all["turnover20"].quantile([1 / 3, 2 / 3])
        t3_tickers = set(g_all.loc[g_all["turnover20"] >= q2, "ticker"])
        sub = merged[(merged["entry_date"] == m) & (merged["ticker"].isin(t3_tickers))]
        if len(sub):
            parts.append(sub)
    t3 = pd.concat(parts, ignore_index=True)
    print(f"T3-restricted rows={len(t3)}")

    results = {
        "T3_baseline_no_filter": backtest_variant(t3, None, "T3 전체(ROE 필터 없음)"),
        "T3_exclude_bottom3deciles": backtest_variant(t3, set(range(1, 8)), "T3, decile 8~10(저ROE) 배제"),
        "T3_exclude_bottom4deciles": backtest_variant(t3, set(range(1, 7)), "T3, decile 7~10(저ROE) 배제"),
        "T3_top4deciles_only": backtest_variant(t3, {1, 2, 3, 4}, "T3, decile 1~4(고ROE)만"),
        "T3_top5deciles_only": backtest_variant(t3, {1, 2, 3, 4, 5}, "T3, decile 1~5만"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-t3-roe-quality-strategy")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "t3-roe-strategy-backtest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "t3_factor_decile_check.py가 찾은 ROE 신호(하위분위 배제 모양)를 "
                       "실제 롱 전략으로 구성. 세션인수인계-2026-08-21-c.md §A안 후속.",
            "period": f"{START} ~ {END}", "costBps": COST_RT_BPS,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
