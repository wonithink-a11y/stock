#!/usr/bin/env python
"""전략 후보 regime별 성과 — A2a EW 지수 proxy로 월별 regime 분류(UP/DOWN/FLAT),
각 전략의 월별 수익률을 regime 조건부로 집계한다.

regime 정의: trailing 20d 누적수익률 >= +3% UP, <= -3% DOWN, else FLAT
(기존 perf_decomposition과 동일). EW 지수는 A1A 유니버스 일별 수익률 평균 복리.
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
UP_TH = 0.03
DOWN_TH = -0.03
COST_RT_BPS = 30.0
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


def build_ew_index(bars_by_ticker, calendar):
    """A1A 유니버스 일별 수익률 평균 복리 지수."""
    daily = defaultdict(list)
    for t, bars in bars_by_ticker.items():
        ret = bars["close"].pct_change()
        for d, v in ret.items():
            if pd.notna(v):
                daily[d.strftime("%Y-%m-%d")].append(v)
    dates = sorted(daily)
    idx = pd.Series(dates).map(lambda d: d)
    rets = pd.Series([float(np.mean(daily[d])) for d in dates], index=dates, dtype="float64")
    # 20d trailing cumulative
    cum = (1 + rets).cumprod()
    idx20 = pd.Series(cum.index)
    trailing20 = {}
    for i, d in enumerate(idx20):
        if i < 20:
            continue
        trailing20[d] = cum.iloc[i] / cum.iloc[i - 20] - 1
    return rets, trailing20


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    rets, trailing20 = build_ew_index(bars_by_ticker, calendar)

    # regime of each rebalance month entry_date (t) using trailing20[t]
    regime_of = {}
    for t in rebalance_dates:
        v = trailing20.get(t)
        if v is None:
            continue
        regime_of[t] = "UP" if v >= UP_TH else ("DOWN" if v <= DOWN_TH else "FLAT")

    # strategy trades: re-run the simple top-N monthly (reuse factor funcs inline)
    FACTOR_FUNCS = {
        "rev20": lambda df: -(df["close"] / df["close"].shift(20) - 1),
        "vol20": lambda df: np.log(df["close"]).diff().rolling(20).std(),
        "mom60": lambda df: df["close"] / df["close"].shift(60) - 1,
    }
    STRATEGIES = {
        "REV20": {"factor": "rev20", "ascending": False},
        "LOWMOM60": {"factor": "mom60", "ascending": True},
        "MOM60": {"factor": "mom60", "ascending": False},
        "EW_MARKET": None,
    }
    # factor tables
    rank_dfs = {}
    for fname, fn in FACTOR_FUNCS.items():
        rows = []
        for ticker, bars in bars_by_ticker.items():
            if bars.empty or len(bars) < 260:
                continue
            f = fn(bars)
            close = bars["close"]
            idx = close.index.astype(str)
            pos = {d: i for i, d in enumerate(idx)}
            for t in rebalance_dates:
                i = pos.get(t)
                if i is None:
                    continue
                v = f.iloc[i]
                if pd.isna(v):
                    continue
                rows.append({"ticker": ticker, "date": t, "factor": float(v)})
        rank_dfs[fname] = pd.DataFrame(rows)
    # entry price map
    entry_map = {}
    for ticker, bars in bars_by_ticker.items():
        idx = bars.index.astype(str)
        opens = bars["open"].to_numpy()
        pos = np.searchsorted(idx, rebalance_dates, side="right")
        for k, t in enumerate(rebalance_dates):
            i = pos[k]
            if i < len(idx):
                entry_map[(ticker, t)] = float(opens[i])

    out = {}
    for name, strategy in STRATEGIES.items():
        # monthly return series per strategy
        month_ret = {}
        for k, t in enumerate(rebalance_dates[:-1]):
            nxt_date = rebalance_dates[k + 1]
            if strategy is None:
                chosen = rank_dfs["rev20"][rank_dfs["rev20"]["date"] == t]
            else:
                sub = rank_dfs[strategy["factor"]][rank_dfs[strategy["factor"]]["date"] == t]
                if sub.empty:
                    continue
                chosen = sub.sort_values("factor", ascending=strategy["ascending"]).head(TOP_N)
            rets_list = []
            for r in chosen.itertuples():
                ep = entry_map.get((r.ticker, t))
                xp = entry_map.get((r.ticker, nxt_date))
                if ep is None or xp is None or ep <= 0:
                    continue
                rets_list.append(xp / ep - 1 - COST_RT_BPS / 1e4)
            if not rets_list:
                continue
            month_ret[t] = float(np.mean(rets_list))
        # regime conditional aggregation
        by_regime = defaultdict(list)
        for t, r in month_ret.items():
            rg = regime_of.get(t)
            if rg is None:
                continue
            by_regime[rg].append(r)
        agg = {}
        for rg in ("UP", "FLAT", "DOWN"):
            arr = by_regime.get(rg, [])
            if not arr:
                agg[rg] = {"months": 0}
                continue
            agg[rg] = {
                "months": len(arr),
                "avgMonthlyRet": round(float(np.mean(arr)), 5),
                "medianMonthlyRet": round(float(np.median(arr)), 5),
                "winRate": round(float(np.mean([1 if x > 0 else 0 for x in arr])), 4),
            }
        # cumulative by regime (compound)
        for rg in ("UP", "FLAT", "DOWN"):
            arr = by_regime.get(rg, [])
            if arr:
                cum = 1.0
                for x in arr:
                    cum *= (1 + x)
                agg[rg]["cumulative"] = round(float(cum - 1), 4)
        out[name] = agg
        print(f"=== {name} ===")
        for rg in ("UP", "FLAT", "DOWN"):
            print(f"  {rg}: {agg[rg]}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-18-strategy-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "regime_by_strategy.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
