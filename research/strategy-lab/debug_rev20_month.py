#!/usr/bin/env python
"""2023-03-02 달 REV20 트레이드 종목·가격 비교 — backtest vs robustness."""
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
TARGET = "2023-03-02"


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
    sub_bt = df_t[df_t["entry_date"] == TARGET]
    print(f"backtest trades on {TARGET}: {len(sub_bt)}")
    nxt = rebalance_dates[rebalance_dates.index(TARGET) + 1]

    # robustness 방식: 같은 ticker set에 대해 open.iloc[i+1]
    rev = rank_dfs["rev20"]
    chosen = rev[rev["date"] == TARGET].sort_values("factor", ascending=False).head(30)
    print(f"chosen by factor: {len(chosen)}")
    merged = sub_bt.set_index("ticker")[["entry_price", "exit_price"]]
    rows = []
    for r in chosen.itertuples():
        bars = bars_by_ticker[r.ticker]
        idx = bars.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        i = pos.get(TARGET)
        j = pos.get(nxt)
        ep_rob = float(bars["open"].iloc[i + 1]) if (i is not None and i + 1 < len(idx)) else None
        xp_rob = float(bars["open"].iloc[j + 1]) if (j is not None and j + 1 < len(idx)) else None
        ep_bt = merged.loc[r.ticker, "entry_price"] if r.ticker in merged.index else None
        xp_bt = merged.loc[r.ticker, "exit_price"] if r.ticker in merged.index else None
        flag = "" if (ep_bt == ep_rob and xp_bt == xp_rob) else "  <-- DIFF"
        rows.append({"ticker": r.ticker, "factor": round(r.factor, 3),
                     "ep_bt": ep_bt, "ep_rob": ep_rob, "xp_bt": xp_bt, "xp_rob": xp_rob, "diff": flag.strip()})
    out = pd.DataFrame(rows)
    print(out.to_string())
    nd = out[out["diff"] == "<-- DIFF"]
    print(f"\ndiff rows: {len(nd)}")
    # 수익률 차이 계산
    bt_ret = (out["xp_bt"] / out["ep_bt"] - 1).mean() if out["xp_bt"].notna().all() else None
    rob_ret = (out["xp_rob"] / out["ep_rob"] - 1).mean() if out["xp_rob"].notna().all() else None
    print(f"backtest monthly ret (no cost): {bt_ret:.5f}, robustness: {rob_ret:.5f}")
    print(f"next rebalance: {nxt}")


if __name__ == "__main__":
    main()