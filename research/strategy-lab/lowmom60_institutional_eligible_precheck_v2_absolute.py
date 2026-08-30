#!/usr/bin/env python
"""lowmom60_institutional_eligible_precheck.py 재검토(v2) — 원래 스크립트는
"매달 거래대금 상위 tercile(T3)"로 대형주를 정의했는데, 이 tercile 방식이
그 자체로 강한 예측변수임이 확정됐다(테스트베드 결함, 세션인수인계-
2026-08-21-c.md §추가확인). absolute_turnover_filter_validation.py로 검증한
**절대 거래대금 임계값**(turnover20>=1억원, gap -0.68%p로 중립 확인)으로
tercile을 대체해 "ChatGPT 저모멘텀+기관수급 후보 A/B/C 채택 불가" 결론이
여전히 성립하는지 재검토한다. mom60·top30·cost 로직은 원본과 완전히 동일,
유동성 필터 정의만 바꿨다.

  python lowmom60_institutional_eligible_precheck_v2_absolute.py
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
MIN_TURNOVER = 100_000_000.0  # 1억원 — rev20/lowmom60 원래 robustness와 동일 임계


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


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, liquidity_filter=None):
    """liquidity_filter: None(무필터) | 'high'(turnover20>=1억원) | 'low'(<1억원, 대조군)."""
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if liquidity_filter == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif liquidity_filter == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        g = g.sort_values("mom60").head(top_n)
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
        "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates)
    print(f"panel rows={len(df)}")

    results = {
        "baseline_no_filter": run_backtest(df, liquidity_filter=None),
        "high_liquidity_absoluteThreshold": run_backtest(df, liquidity_filter="high"),
        "low_liquidity_absoluteThreshold_control": run_backtest(df, liquidity_filter="low"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-chatgpt-momentum-supplydemand-candidates")
    out_path = os.path.join(out_dir, "lowmom60_institutional_eligible_precheck_v2_absolute.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "lowmom60_institutional_eligible_precheck.py 재검토(v2) - "
                       "원본이 쓴 T3 상대 tercile을 절대 임계값(1억원, 중립성 검증됨: "
                       "absolute_turnover_filter_validation.py gap -0.68%p)으로 대체.",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER,
            "v1_tercile_result_forComparison": {"T3_top_liquidity_tercile_cagr": -0.118,
                                                  "source": "lowmom60_institutional_eligible_precheck.json (오염된 방식)"},
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
