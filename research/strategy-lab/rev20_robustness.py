#!/usr/bin/env python
"""REV20 전략의 견고성 검증 — LOWMOM60과 동일한 방법 (집중도·유동성·비용 민감도).

REV20(20D 최대 급락 종목 top30 월 리밸런스)이 CAGR 6.5%로 양호하지만 2016년 +83.5%
등 연도별 변동이 크다. 소수 종목 집중/저가주 의존 여부를 검증한다.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"
TOP_N = 30


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close = bars["close"]
        open_ = bars["open"]
        vol = bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        rev20 = -(close / close.shift(20) - 1)
        turnover20 = (close * vol).rolling(20).mean()
        avgclose20 = close.rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            m = rev20.iloc[i]
            if pd.isna(m):
                continue
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue
            entry_price = float(open_.iloc[i + 1])
            exit_price = float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            rows.append({
                "ticker": ticker, "entry_date": t, "rev20": float(m),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(turnover20.iloc[i]) if not pd.isna(turnover20.iloc[i]) else 0.0,
                "avgclose20": float(avgclose20.iloc[i]) if not pd.isna(avgclose20.iloc[i]) else 0.0,
            })
    df = pd.DataFrame(rows)
    print(f"panel rows={len(df)}")

    def run(min_turnover=0, min_price=0, cost_bps=30.0):
        sub = df[(df["turnover20"] >= min_turnover) & (df["avgclose20"] >= min_price)]
        months = sorted(sub["entry_date"].unique())
        month_rets = []
        for m in months:
            g = sub[sub["entry_date"] == m].sort_values("rev20", ascending=False).head(TOP_N)
            if g.empty:
                continue
            month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean()))
        mdf = pd.DataFrame(month_rets, columns=["month", "ret"])
        eq = 100_000_000.0
        final = eq
        peak = eq
        maxdd = 0.0
        for _, row in mdf.iterrows():
            final *= (1 + row["ret"])
            peak = max(peak, final)
            maxdd = min(maxdd, final / peak - 1)
        n_years = len(mdf["month"].str[:4].unique())
        cagr = (final / eq) ** (1 / n_years) - 1 if n_years else None
        # yearly
        yearly = {}
        for y, g in mdf.groupby(mdf["month"].str[:4]):
            eqs = [eq]
            for _, row in g.iterrows():
                eqs.append(eqs[-1] * (1 + row["ret"]))
            yearly[y] = round(eqs[-1] / eqs[0] - 1, 4)
        return {"months": len(mdf), "finalEquity": round(final, 0), "totalReturn": round(final / eq - 1, 4),
                "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4), "yearly": yearly}

    print("--- REV20 유동성/가격 필터 민감도 ---")
    for mt in (0, 1e7, 5e7, 1e8, 3e8):
        for mp in (0, 1000, 5000):
            r = run(min_turnover=mt, min_price=mp)
            print(f"  minTurnover={mt:>12,.0f} minPrice={mp:>5,}: total={r['totalReturn']:.4f} cagr={r['cagr']} mdd={r['maxDD']}")

    print("--- 거래비용 민감도 ---")
    for cb in (15, 30, 60, 90, 150):
        r = run(min_turnover=0, min_price=0, cost_bps=cb)
        print(f"  cost={cb:>3}bps: cagr={r['cagr']}")

    print("--- REV20 상위 15 기여 종목 ---")
    sub = df.sort_values("rev20", ascending=False).groupby("entry_date").head(TOP_N)
    contrib = sub.groupby("ticker")["ret"].agg(["count", "sum"]).sort_values("sum", ascending=False)
    print(contrib.head(15))
    print("unique tickers:", sub["ticker"].nunique())

    print("--- REV20 연도별 최고 기여 종목 ---")
    sub["year"] = sub["entry_date"].str[:4]
    for y, g in sub.groupby("year"):
        top = g.groupby("ticker")["ret"].sum().sort_values(ascending=False)
        if len(top):
            print(f"  {y}: {top.index[0]} sum_ret={top.iloc[0]:.2f} (n_top={len(g)})")

    print("--- 무비용/비용 반영 연도별 (기본) ---")
    print(run(min_turnover=0, min_price=0)["yearly"])


if __name__ == "__main__":
    main()
