#!/usr/bin/env python
"""PBR 저PBR-고PBR spread가 절대 유동성 기준을 단계적으로 올려도(1억/3억/5억/10억)
유지되는지 확인 - turnover20 rolling tercile은 그 자체가 강한 예측변수였음이
확정됐으므로(2026-08-21-c) 쓰지 않는다. 기존 확정 파라미터(top-30·월별 리밸런싱)는
그대로, 유동성 임계값만 단계적으로 올려 IC·spread·비용반영 성과를 비교한다.
전체 2016-01~2026-08 기간(파라미터 재튜닝 없음), 순수 진단.

  python pbr_liquidity_tier_spread_check.py
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
TOP_N = 30
TIERS = {
    "ge_1e8": 100_000_000.0,
    "ge_3e8": 300_000_000.0,
    "ge_5e8": 500_000_000.0,
    "ge_10e8": 1_000_000_000.0,
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


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    fr = pd.Series(factor_vals).rank()
    rr = pd.Series(fwd_rets).rank()
    return float(np.corrcoef(fr, rr)[0, 1])


def period_ic(sub):
    monthly_ics = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        if len(g) < 15:
            continue
        ic = rank_ic((-g["pbr"]).values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    if not monthly_ics:
        return {"meanMonthlyIC": None, "icTstat": None, "icMonthsUsed": 0}
    ic_mean = float(np.mean(monthly_ics))
    ic_std = float(np.std(monthly_ics))
    ic_tstat = (ic_mean / (ic_std / np.sqrt(len(monthly_ics)))) if ic_std > 0 else None
    return {"meanMonthlyIC": round(ic_mean, 4),
            "icTstat": round(ic_tstat, 2) if ic_tstat is not None else None,
            "icMonthsUsed": len(monthly_ics)}


def monthly_series(sub, selector):
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
    return {"monthsTraded": n_months, "avgN": round(mdf["n"].mean(), 1),
            "totalReturn": round(eq - 1, 4), "cagr": round(cagr, 4) if cagr is not None else None,
            "maxDD": round(maxdd, 4), "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "avgMonthlyRet": round(float(mdf["ret"].mean()), 4)}


def spread_stats(low_rets, high_rets):
    low_by_m = {m: r for m, r, _ in low_rets}
    high_by_m = {m: r for m, r, _ in high_rets}
    common = sorted(set(low_by_m) & set(high_by_m))
    if not common:
        return None
    spread_rets = [low_by_m[m] - high_by_m[m] for m in common]
    mdf = pd.DataFrame({"ret": spread_rets})
    eq = 1.0
    for r in mdf["ret"]:
        eq *= (1 + r)
    n_months = len(mdf)
    n_years = n_months / 12.0
    cagr = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = mdf["ret"].std(ddof=1) if len(mdf) > 1 else 0.0
    sharpe = (mdf["ret"].mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    return {"monthsTraded": n_months, "avgMonthlySpread": round(float(mdf["ret"].mean()), 4),
            "cagr": round(cagr, 4) if cagr is not None else None,
            "sharpe": round(sharpe, 4) if sharpe is not None else None,
            "winRateMonths": round(float((mdf["ret"] > 0).mean()), 3)}


def main():
    pbr_lookup = load_valuation_panel()
    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-liquidity-tier-spread-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    print(f"panel rows (pre-liquidity-filter)={len(df)}")

    results = {}
    for tier_name, threshold in TIERS.items():
        sub = df[df["turnover20"] >= threshold]
        low_rets = monthly_series(sub, lambda g: g.sort_values("pbr", ascending=True).head(TOP_N))
        high_rets = monthly_series(sub, lambda g: g.sort_values("pbr", ascending=False).head(TOP_N))

        block = {
            "minTurnover": threshold,
            "eligibleRows": len(sub),
            "avgEligiblePerMonth": round(len(sub) / max(sub["entry_date"].nunique(), 1), 1),
            "ic": period_ic(sub),
            "lowPBR_top30": curve_stats(low_rets),
            "highPBR_control_top30": curve_stats(high_rets),
            "lowMinusHighPBR_spread": spread_stats(low_rets, high_rets),
        }
        results[tier_name] = block
        print(f"\n=== {tier_name} (>= {threshold:.0f}) ===")
        print(json.dumps(block, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-pbr-liquidity-tier-spread-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-liquidity-tier-spread-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "저PBR-고PBR spread가 절대 유동성 임계값을 1억->3억->5억->10억으로 "
                       "올려도 유지되는지 확인. turnover20 rolling tercile 미사용(그 자체가 "
                       "강한 예측변수였음이 확정됨, 2026-08-21-c). top-30·월별 리밸런싱 "
                       "그대로, 전체 2016-01~2026-08 기간, 파라미터 재튜닝 없음.",
            "period": f"{START} ~ {END}", "costBps": COST_RT_BPS, "topN": TOP_N,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
