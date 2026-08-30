#!/usr/bin/env python
"""pbr_oos_regime_check.py가 낸 이상현상(2024: IC +0.110인데 top-30 CAGR -6.26%)의
원인을 분해한다 - 같은 4개 구간·같은 비용·같은 고유동성(turnover20>=1억원) 조건에서
저PBR top-30 / 고PBR 대조군(top-30) / 전체 유니버스 동일가중 / 저PBR-고PBR spread
네 가지를 나란히 비교한다. 파라미터 재튜닝·전략 수정 없음, 순수 진단.

가설: IC(순위상관)는 저PBR이 고PBR보다 상대적으로 나았다는 것만 말하고 절대수익
부호는 보장하지 않는다 - 2024가 시장 전체적으로 하락한 해였다면, 저PBR이 고PBR보다
덜 빠졌으면서도(양의 IC) 저PBR 바스켓 자체는 여전히 절대 손실(음의 CAGR)일 수 있다.

  python pbr_oos_decomposition.py
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
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
COST_RT_BPS = 30.0
MIN_TURNOVER = 100_000_000.0
TOP_N = 30

PERIODS = {
    "design_2016_2022": ("2016-01-01", "2022-12-31"),
    "oos_2023": ("2023-01-01", "2023-12-31"),
    "oos_2024_valueup_regime": ("2024-01-01", "2024-12-31"),
    "oos_2025_2026": ("2025-01-01", "2026-08-14"),
}


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_valuation_panel():
    rows = [json.loads(line) for line in open(PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["pbr"])
    df = df[df["pbr"] > 0]
    return df.set_index(["ticker", "asOf"])["pbr"].to_dict()


def build_panel(bars_by_ticker, rebalance_dates, pbr_lookup):
    """Unchanged from pbr_oos_regime_check.py / a5_valuation_factor_precheck_v2_absolute.py."""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            pbr = pbr_lookup.get((ticker, t))
            if pbr is None:
                continue
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
            rows.append({
                "ticker": ticker, "entry_date": t, "pbr": float(pbr),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def monthly_series(sub, selector):
    """selector(group_for_month) -> selected sub-DataFrame (or the group itself for EW-all).
    Returns list of (month, cost-adjusted mean return, n)."""
    out = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        sel = selector(g)
        if sel.empty:
            continue
        out.append((m, float((sel["ret"] - COST_RT_BPS / 1e4).mean()), len(sel)))
    return out


def curve_stats(month_rets):
    if not month_rets:
        return None
    mdf = pd.DataFrame(month_rets, columns=["month", "ret", "n"])
    eq, peak, maxdd = 1.0, 1.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_months = len(mdf)
    n_years = n_months / 12.0
    cagr = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = mdf["ret"].std(ddof=1) if len(mdf) > 1 else 0.0
    sharpe = (mdf["ret"].mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    return {
        "monthsTraded": n_months, "avgN": round(mdf["n"].mean(), 1),
        "totalReturn": round(eq - 1, 4), "cagr": round(cagr, 4) if cagr is not None else None,
        "maxDD": round(maxdd, 4), "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "avgMonthlyRet": round(float(mdf["ret"].mean()), 4),
    }


def spread_stats(low_rets, high_rets):
    low_by_m = {m: r for m, r, _ in low_rets}
    high_by_m = {m: r for m, r, _ in high_rets}
    common = sorted(set(low_by_m) & set(high_by_m))
    if not common:
        return None
    spread_rets = [(m, low_by_m[m] - high_by_m[m], None) for m in common]
    mdf = pd.DataFrame(spread_rets, columns=["month", "ret", "n"])
    eq = 1.0
    for r in mdf["ret"]:
        eq *= (1 + r)
    n_months = len(mdf)
    n_years = n_months / 12.0
    cagr = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = mdf["ret"].std(ddof=1) if len(mdf) > 1 else 0.0
    sharpe = (mdf["ret"].mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    win_rate = float((mdf["ret"] > 0).mean())
    return {
        "monthsTraded": n_months, "avgMonthlySpread": round(float(mdf["ret"].mean()), 4),
        "cagr": round(cagr, 4) if cagr is not None else None,
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "winRateMonths": round(win_rate, 3),
    }


def main():
    pbr_lookup = load_valuation_panel()
    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-oos-decomposition")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    df_hi = df[df["turnover20"] >= MIN_TURNOVER]
    print(f"high-liquidity rows={len(df_hi)}")

    results = {}
    for period_name, (p_start, p_end) in PERIODS.items():
        sub = df_hi[(df_hi["entry_date"] >= p_start) & (df_hi["entry_date"] <= p_end)]

        low_rets = monthly_series(sub, lambda g: g.sort_values("pbr", ascending=True).head(TOP_N))
        high_rets = monthly_series(sub, lambda g: g.sort_values("pbr", ascending=False).head(TOP_N))
        ew_rets = monthly_series(sub, lambda g: g)  # full high-liquidity universe that month, equal-weighted

        block = {
            "period": f"{p_start} ~ {p_end}",
            "lowPBR_top30": curve_stats(low_rets),
            "highPBR_control_top30": curve_stats(high_rets),
            "fullUniverse_EW_highLiquidity": curve_stats(ew_rets),
            "lowMinusHighPBR_spread": spread_stats(low_rets, high_rets),
        }
        results[period_name] = block
        print(f"\n=== {period_name} ({p_start} ~ {p_end}) ===")
        print(json.dumps(block, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-pbr-oos-decomposition")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-oos-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "pbr_oos_regime_check.py의 2024 이상현상(IC+0.110, top30 CAGR -6.26%) "
                       "원인 분해 - 저PBR top30/고PBR 대조군/전체유니버스EW/spread 비교. "
                       "파라미터 재튜닝 없음, 순수 진단.",
            "costBps": COST_RT_BPS, "minTurnover": MIN_TURNOVER, "topN": TOP_N,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
