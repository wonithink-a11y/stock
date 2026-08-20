#!/usr/bin/env python
"""REV20 트레이드 디버그 — backtest 로직과 robustness 로직이 왜 다른 total을 내는지 확인.

차이 가설:
1. backtest는 entry_map이 (ticker,t) -> t 이후 첫 거래일 open (searchsorted side=right),
   robustness는 open.iloc[i+1] (i = t의 정확한 행). 만약 t가 그 ticker에 없으면 backtest는
   팩터 계산에서도 스킵된다(build_rank_table의 pos.get(t)). 차이는 없어야 한다.
2. backtest build_rank_table은 rebalance_dates 전체(마지막 포함)를 쓰고,
   robustness는 rebalance_dates[:-1]를 쓴다. 마지막 달 차이만 있을 뿐.
3. 가장 큰 의심: backtest는 진입가를 entry_map[(ticker, t)] = t의 다음 거래일 open으로 쓰는데
   robustness도 동일. 다만 backtest build_trades에서 'chosen'은 rank_dfs 기준 t 시점 팩터,
   robustness는 rows에 이미 t+1 open 진입가를 저장. 근본 로직은 같아야 한다.

각 달의 선택 종목·수익률을 직접 출력해 어느 달이 갈리는지 확인한다.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import strategy_candidate_backtest as S  # noqa: E402
from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = S.monthly_rebalance_dates(calendar, START, END)
    entry_map = S.build_entry_map(bars_by_ticker, rebalance_dates)
    rank_dfs = {f: S.build_rank_table(bars_by_ticker, rebalance_dates, f) for f in S.FACTOR_FUNCS}

    trades = S.build_trades(rank_dfs, rebalance_dates, entry_map, "REV20", {"factor": "rev20", "ascending": False})
    df_t = pd.DataFrame(trades)
    # 월별 수익률
    months = sorted(df_t["entry_date"].unique())
    bt_monthly = {}
    for m in months:
        sub = df_t[df_t["entry_date"] == m]
        rets = sub["exit_price"] / sub["entry_price"] - 1 - S.COST_RT_BPS / 1e4
        bt_monthly[m] = rets.mean()

    # robustness식 재현: 같은 bars로 i+1 진입가
    rob_monthly = {}
    rev_tab = rank_dfs["rev20"]
    for k, t in enumerate(rebalance_dates[:-1]):
        nxt_date = rebalance_dates[k + 1]
        sub = rev_tab[rev_tab["date"] == t].sort_values("factor", ascending=False).head(30)
        if sub.empty:
            continue
        rets_list = []
        for r in sub.itertuples():
            bars = bars_by_ticker[r.ticker]
            idx = bars.index.astype(str)
            pos = {d: i for i, d in enumerate(idx)}
            i = pos.get(t)
            j = pos.get(nxt_date)
            if i is None or j is None:
                continue
            ep = float(bars["open"].iloc[i + 1]) if i + 1 < len(idx) else None
            xp = float(bars["open"].iloc[j + 1]) if j + 1 < len(idx) else None
            if ep is None or xp is None or ep <= 0:
                continue
            rets_list.append(xp / ep - 1 - S.COST_RT_BPS / 1e4)
        if rets_list:
            rob_monthly[t] = float(pd.Series(rets_list).mean())

    print(f"backtest months={len(bt_monthly)}, robustness months={len(rob_monthly)}")
    print("| month | backtest | robustness | diff |")
    for m in sorted(set(bt_monthly) | set(rob_monthly)):
        b = bt_monthly.get(m)
        r = rob_monthly.get(m)
        if b is None or r is None:
            print(f"| {m} | {b if b is not None else '-'} | {r if r is not None else '-'} | (한쪽 없음) |")
        else:
            print(f"| {m} | {b:.5f} | {r:.5f} | {b - r:.5f} |")


if __name__ == "__main__":
    main()