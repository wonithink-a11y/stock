#!/usr/bin/env python
"""전략 후보 소규모 백테스트 — 팩터 검증(factor_deciles.json)에서 유망한 방향을
규칙 기반 전략으로 구체화해 CAGR/MDD/승률/손익비/연도별/regime별 성과를 확인한다.

전략(월 리밸런스, cross-sectional top-N, equal weight, LONG only):
  REV20      : 20D 수익률 하위 decile(급락) 종목 매수 — 단기 평균회귀
  LOWVOL     : 20D 변동성 하위 decile 종목 매수 — 저변동성 프리미엄
  REV20+LOWVOL : 급락 종목 중 변동성 낮은 종목 — 조합
  LOWMOM60   : 60D 모멘텀 하위(decile1) 종목 매수 — 저모멘텀
  MOM60      : 60D 모멘텀 상위(decile10) 종목 매수 — 추세(대조군, 음성 기대)
  EW-MARKET  : 전 종목 동일가중 — 벤치마크

메커니즘(PIT 준수):
  리밸런스일 t: t 종가까지의 데이터로 팩터 계산 → 순위 결정
  진입: t의 다음 거래일 시가(t+1 open). 청산: 다음 리밸런스 진입 시가에 전체 교체.
  look-ahead 없음(팩터는 t까지, 진입은 t+1 open).
  거래비용: roundTrip 30bps(5DC policy와 동일), slippage 0.

한계:
  A1A_ONLY survivorship. 신호일 종가 확인 후 다음날 시가 진입이라 시그널-진입 갭 리스크
  있음(갭상승/갭하락은 팩터가 잡지 못함). top-N=30, 월 1회.
"""
import json
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
COST_RT_BPS = 30.0  # round trip 진입+청산
INITIAL_CAPITAL = 100_000_000.0

FACTOR_FUNCS = {
    "rev20": lambda df: -(df["close"] / df["close"].shift(20) - 1),
    "vol20": lambda df: np.log(df["close"]).diff().rolling(20).std(),
    "mom60": lambda df: df["close"] / df["close"].shift(60) - 1,
}

# strategy: factor to rank on + ascending (True = lowest factor first)
STRATEGIES = {
    "REV20": {"factor": "rev20", "ascending": False},        # 20D 급락 종목 매수 (평균회귀)
    "LOWVOL": {"factor": "vol20", "ascending": True},        # 저변동성 종목 매수
    "LOWMOM60": {"factor": "mom60", "ascending": True},      # 저모멘텀 종목 매수 (역전)
    "MOM60": {"factor": "mom60", "ascending": False},        # 고모멘텀 (대조군, 음성 기대)
    "EW_MARKET": None,                                       # 전체 동일가중 벤치마크
}
# REV20+LOWVOL 조합: rev20 상위 20% 중 vol20 하위 50% 필터 → 그 안에서 rev20 순위
COMBO = "REV20+LOWVOL"


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def get_next_open(bars, after_date):
    """after_date 이후 첫 거래일의 시가. 없으면 None (장 마감/종료)."""
    idx = bars.index.astype(str)
    after = idx[idx > after_date]
    if after.empty:
        return None
    d = after[0]
    return d, float(bars.loc[bars.index.astype(str) == d, "open"].iloc[0])


def build_rank_table(bars_by_ticker, rebalance_dates, factor):
    """각 리밸런스일 t에 팩터값(t까지 backward)만 계산. (진입가/청산가는 entry_map 사용)"""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        f = FACTOR_FUNCS[factor](bars)
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
    return pd.DataFrame(rows)


def build_entry_map(bars_by_ticker, rebalance_dates):
    """(ticker, t) -> t 이후 첫 거래일 시가. searchsorted로 벡터화."""
    entry = {}
    for ticker, bars in bars_by_ticker.items():
        idx = bars.index.astype(str)
        opens = bars["open"].to_numpy()
        pos = np.searchsorted(idx, rebalance_dates, side="right")
        for k, t in enumerate(rebalance_dates):
            i = pos[k]
            if i < len(idx):
                entry[(ticker, t)] = float(opens[i])
    return entry


def build_rank_table(bars_by_ticker, rebalance_dates, factor):
    """각 리밸런스일 t에 팩터값(t까지 backward)만 계산. (진입가/청산가는 entry_map 사용)"""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        f = FACTOR_FUNCS[factor](bars)
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
    return pd.DataFrame(rows)


def build_trades(rank_dfs, rebalance_dates, entry_map, name, strategy, top_n=TOP_N):
    """strategy: None=EW_MARKET(전 종목 동일가중) / dict(factor, ascending) / COMBO."""
    trades = []
    for k, t in enumerate(rebalance_dates[:-1]):
        nxt_date = rebalance_dates[k + 1]
        if strategy is None:
            chosen = rank_dfs["rev20"][rank_dfs["rev20"]["date"] == t]
        else:
            factor = strategy["factor"]
            sub = rank_dfs[factor][rank_dfs[factor]["date"] == t]
            if sub.empty:
                continue
            if name == COMBO:
                # 조합: rev20 상위 20% 종목들 중에서 vol20 낮은 순 top_n
                rev = sub.sort_values("factor", ascending=False)
                rev_top = rev.head(max(1, int(len(rev) * 0.2)))
                vol = rank_dfs["vol20"][rank_dfs["vol20"]["date"] == t].set_index("ticker")
                vol_map = vol["factor"].to_dict()
                rev_top = rev_top.copy()
                rev_top["_vol"] = rev_top["ticker"].map(vol_map)
                rev_top = rev_top.dropna(subset=["_vol"]).sort_values("_vol", ascending=True)
                chosen = rev_top.head(top_n)
            else:
                chosen = sub.sort_values("factor", ascending=strategy["ascending"]).head(top_n)
        for r in chosen.itertuples():
            exit_price = entry_map.get((r.ticker, nxt_date))
            entry_price = entry_map.get((r.ticker, t))
            if entry_price is None or exit_price is None:
                continue
            trades.append({
                "ticker": r.ticker, "entry_date": t, "exit_date": nxt_date,
                "entry_price": entry_price, "exit_price": exit_price,
            })
    return trades


if __name__ == "__main__":
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"tickers={len(bars_by_ticker)}")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    print(f"rebalance_dates={len(rebalance_dates)}")

    # entry price map for all (ticker, date) — reuse across factors
    entry_map = build_entry_map(bars_by_ticker, rebalance_dates)

    rank_dfs = {}
    for factor in FACTOR_FUNCS:
        rank_dfs[factor] = build_rank_table(bars_by_ticker, rebalance_dates, factor)

    all_strategies = list(STRATEGIES.items()) + [(COMBO, {"factor": "rev20", "ascending": False})]
    results = {}
    for name, strategy in all_strategies:
        trades = build_trades(rank_dfs, rebalance_dates, entry_map, name, strategy)
        print(f"\n=== {name}: {len(trades)} trades ===")
        results[name] = {"n_trades": len(trades)}
        if not trades:
            continue

        df_t = pd.DataFrame(trades)
        # 월별 PnL (equal weight, top_n 슬롯)
        months = sorted(df_t["entry_date"].unique())
        monthly_ret = []
        for m in months:
            sub = df_t[df_t["entry_date"] == m]
            if sub.empty:
                continue
            rets = sub["exit_price"] / sub["entry_price"] - 1
            # cost: round trip 30bps per name
            rets = rets - COST_RT_BPS / 1e4
            monthly_ret.append((m, rets.mean()))
        mdf = pd.DataFrame(monthly_ret, columns=["month", "ret"])
        eq = INITIAL_CAPITAL
        curve = []
        for _, row in mdf.iterrows():
            eq *= (1 + row["ret"])
            curve.append((row["month"], eq))
        eq_df = pd.DataFrame(curve, columns=["month", "equity"])

        years = eq_df["month"].str[:4]
        yearly = {}
        for y, g in eq_df.groupby(years):
            start_eq = g["equity"].iloc[0]
            end_eq = g["equity"].iloc[-1]
            yearly[y] = {"start": round(float(start_eq), 0), "end": round(float(end_eq), 0),
                         "return": round(float(end_eq / start_eq - 1), 4)}
        n_years = len(years.unique())
        total_return = eq_df["equity"].iloc[-1] / INITIAL_CAPITAL - 1
        cagr = (eq_df["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years else None

        # win rate / profit factor (per-trade)
        raw_rets = df_t["exit_price"] / df_t["entry_price"] - 1 - COST_RT_BPS / 1e4
        wins = raw_rets[raw_rets > 0]
        losses = raw_rets[raw_rets < 0]
        win_rate = len(wins) / len(raw_rets) if len(raw_rets) else None
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else None

        # drawdown
        peak = eq_df["equity"].cummax()
        dd = eq_df["equity"] / peak - 1
        max_dd = dd.min()

        results[name].update({
            "totalReturn": round(float(total_return), 4),
            "cagr": round(float(cagr), 4) if cagr is not None else None,
            "maxDrawdown": round(float(max_dd), 4),
            "winRate": round(float(win_rate), 4) if win_rate is not None else None,
            "profitFactor": round(float(pf), 4) if pf is not None else None,
            "avgMonthlyRet": round(float(mdf["ret"].mean()), 5),
            "yearly": yearly,
            "finalEquity": round(float(eq_df["equity"].iloc[-1]), 0),
        })
        print(json.dumps(results[name], ensure_ascii=False, indent=2))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-18-strategy-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "backtest_top30.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")
