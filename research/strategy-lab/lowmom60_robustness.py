#!/usr/bin/env python
"""LOWMOM60 결과의 견고성 검증 — 집중도·유동성·survivorship 민감도.

의문: LOWMOM60(60D 저모멘텀 상위 30종목 월 리밸런스)이 CAGR 22%/total +800%로
매우 크다. A1A_ONLY 유니버스는 상장폐지 종목을 제외하므로 '과거 하락한 종목 중
현재까지 살아남은' 종목만 선택된다 = survivorship이 저모멘텀 역전을 부풀리는 방향.
또한 소수의 초대형 반등 종목(테마주/정리매매 등)이 CAGR을 지배했을 수 있다.

검증 항목:
  1. LOWMOM60 선정 종목의 유동성 분포 (저유동성 필터 추가 시 결과 변화)
  2. 상위 10개 종목의 기여도 (집중도)
  3. 2016~2026 각 연도 최고 기여 종목
  4. 거래비용 민감도 (30/60/90bps)
  5. rev20 대비 과대한 이유 — 손익이 어느 종목에서 나는지
"""
import json
import os
import sys
from collections import defaultdict

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
COST_RT_BPS = 30.0


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

    # mom60 & 진입가 (t+1 open), 청산가 (다음 리밸런스 t+1 open), 20D avg turnover
    # (volume * close 대략 거래대금 proxy)
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close = bars["close"]
        open_ = bars["open"]
        vol = bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        mom60 = close / close.shift(60) - 1
        # avg daily turnover (원) proxy: close*volume 20D mean
        turnover20 = (close * vol).rolling(20).mean()
        # 평균 종가 (가격대 proxy)
        avgclose20 = close.rolling(20).mean()
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
            entry_price = float(open_.iloc[i + 1])
            exit_price = float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            rows.append({
                "ticker": ticker, "entry_date": t, "mom60": float(m),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(turnover20.iloc[i]) if not pd.isna(turnover20.iloc[i]) else 0.0,
                "avgclose20": float(avgclose20.iloc[i]) if not pd.isna(avgclose20.iloc[i]) else 0.0,
            })
    df = pd.DataFrame(rows)
    print(f"panel rows={len(df)}")

    # LOWMOM60 = mom60 하위 top30 (ascending)
    def run(min_turnover=0, min_price=0, cost_bps=COST_RT_BPS):
        sub = df[(df["turnover20"] >= min_turnover) & (df["avgclose20"] >= min_price)]
        months = sorted(sub["entry_date"].unique())
        month_rets = []
        for m in months:
            g = sub[sub["entry_date"] == m].sort_values("mom60").head(TOP_N)
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
        return {"months": len(mdf), "finalEquity": round(final, 0), "totalReturn": round(final / eq - 1, 4),
                "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4)}

    print("--- LOWMOM60 유동성/가격 필터 민감도 ---")
    for mt in (0, 1e7, 5e7, 1e8, 3e8):
        for mp in (0, 1000, 5000):
            r = run(min_turnover=mt, min_price=mp)
            print(f"  minTurnover={mt:>12,.0f} minPrice={mp:>5,}: {r}")

    print("--- 거래비용 민감도 ---")
    for cb in (15, 30, 60, 90, 150):
        print(f"  cost={cb:>3}bps: {run(min_turnover=0, min_price=0, cost_bps=cb)}")

    # 집중도: 최고 기여 종목
    print("--- LOWMOM60 상위 15 기여 종목 (총 기여) ---")
    sub = df.sort_values("mom60").groupby("entry_date").head(TOP_N)
    contrib = sub.groupby("ticker")["ret"].agg(["count", "sum"]).sort_values("sum", ascending=False)
    print(contrib.head(15))
    print("unique tickers in LOWMOM60:", sub["ticker"].nunique())

    # 연도별 최고 기여 종목
    print("--- 연도별 최고 기여 종목 ---")
    sub["year"] = sub["entry_date"].str[:4]
    for y, g in sub.groupby("year"):
        top = g.groupby("ticker")["ret"].sum().sort_values(ascending=False)
        if len(top):
            print(f"  {y}: {top.index[0]} sum_ret={top.iloc[0]:.2f} (n_top={len(g)})")


if __name__ == "__main__":
    main()
