#!/usr/bin/env python
"""PBR·LOWMOM60(mom60) 두 후보가 top-30 하드컷이 아니라 decile 스프레드·IC로
봐도 고유동성(절대임계값, 중립성 검증됨) 구간에서 견고한지 정밀 확인 —
t3_factor_decile_check.py와 같은 방법론, 유동성 정의만 상대 tercile 대신
절대임계값(turnover20>=1억원)으로. 세션인수인계-2026-08-21-c.md §추가확인
(같은 세션 재후속) 다음 단계, 사용자 승인("go, 토큰 많지 않으면").

  python absolute_liquidity_decile_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
COST_RT_BPS = 30.0
N_DECILES = 10
MIN_TURNOVER = 100_000_000.0


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
    """(ticker, entry_date) -> ret, turnover20, mom60."""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        mom60 = close / close.shift(60) - 1
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
            m = mom60.iloc[i]
            if pd.isna(tv):
                continue
            rows.append({"ticker": ticker, "entry_date": t,
                         "ret": exit_price / entry_price - 1, "turnover20": float(tv),
                         "mom60": float(m) if not pd.isna(m) else None})
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    fr = pd.Series(factor_vals).rank()
    rr = pd.Series(fwd_rets).rank()
    return float(np.corrcoef(fr, rr)[0, 1])


def decile_analysis(merged, factor_col, ascending_is_good, cost_bps=COST_RT_BPS, label=""):
    months = sorted(merged["entry_date"].unique())
    decile_rets = {d: [] for d in range(1, N_DECILES + 1)}
    monthly_ics = []
    for m in months:
        g = merged[(merged["entry_date"] == m) & merged[factor_col].notna()]
        if len(g) < N_DECILES * 3:
            continue
        ranks = g[factor_col].rank(ascending=ascending_is_good, method="first")
        deciles = pd.qcut(ranks, N_DECILES, labels=False, duplicates="drop") + 1
        for d in range(1, deciles.max() + 1 if len(deciles) else 1):
            sel = g.loc[deciles == d, "ret"]
            if len(sel):
                decile_rets[d].append(float(sel.mean()) - cost_bps / 1e4)
        signed_factor = g[factor_col] if not ascending_is_good else -g[factor_col]
        ic = rank_ic(signed_factor.values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    decile_avg = {d: (round(float(np.mean(v)), 4) if v else None) for d, v in decile_rets.items()}
    top_bottom_spread = None
    if decile_avg.get(1) is not None and decile_avg.get(N_DECILES) is not None:
        top_bottom_spread = round(decile_avg[1] - decile_avg[N_DECILES], 4)
    ic_mean = round(float(np.mean(monthly_ics)), 4) if monthly_ics else None
    ic_tstat = (round(ic_mean / (np.std(monthly_ics) / np.sqrt(len(monthly_ics))), 2)
                if monthly_ics and np.std(monthly_ics) > 0 else None)
    return {
        "label": label, "monthsUsed": len(monthly_ics),
        "decileAvgMonthlyReturn": decile_avg, "topDecileMinusBottomDecile": top_bottom_spread,
        "meanMonthlyIC": ic_mean, "icTstat": ic_tstat,
    }


def main():
    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = load_universe_tickers()
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="absolute-liquidity-decile-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    month_rows = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"month_rows={len(month_rows)}")

    merged = month_rows.merge(val, left_on=["ticker", "entry_date"],
                               right_on=["ticker", "asOf"], how="left")

    high_liq = merged[merged["turnover20"] >= MIN_TURNOVER]
    print(f"high-liquidity rows={len(high_liq)}")

    results = {
        "pbr_lowIsGood_highLiquidity": decile_analysis(high_liq, "pbr", ascending_is_good=True, label="저PBR, 고유동성"),
        "mom60_lowIsGood_highLiquidity": decile_analysis(high_liq, "mom60", ascending_is_good=True, label="저모멘텀60, 고유동성"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-absolute-liquidity-decile-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "absolute-liquidity-decile-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR·LOWMOM60을 절대임계값(turnover20>=1억원) 고유동성 구간에서 "
                       "decile/IC로 정밀 재확인. 세션인수인계-2026-08-21-c.md 후속.",
            "period": f"{START} ~ {END}", "nDeciles": N_DECILES, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
