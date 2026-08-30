#!/usr/bin/env python
"""PBR 저PBR/고유동성 후보의 OOS(구간분리) 검증 — 설계구간(2016-01~2022-12)에서
확정한 파라미터(top-30·월별 리밸런싱·거래대금>=1억원 절대임계값, 재튜닝 없이
그대로)를 2023 / 2024(밸류업 정책 regime) / 2025~2026 세 개별 구간에 적용해
IC·CAGR·MDD·Sharpe·거래수의 부호·크기가 유지되는지 확인한다. 하나로 묶지 않고
구간별로 분리 보고해 2024 이후 효과가 구조적인지 특정 regime 의존인지 가른다.
top-20/top-40은 순수 민감도 확인용 — 재튜닝도 최적값 선택도 하지 않는다.

turnover20 rolling과 월별 리밸런싱 스케줄은 전체 2016-01~2026-08 연속 구간에서
한 번만 계산한 뒤 entry_date로 기간을 나눈다 — 구간별로 따로 로드하면 각 구간
초반 20일의 rolling이 워밍업 부족으로 왜곡된다.

production 코드·PBR 정책(config/policies 등)은 미변경. 결과 산출만, Paper
Trading 승격 판단은 하지 않는다.

  python pbr_oos_regime_check.py
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
DESIGN_TOP_N = 30
SENSITIVITY_TOP_NS = [20, 40]

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
    """entry_date/ret/pbr/turnover20 per (ticker, month) over the FULL period -
    same as a5_valuation_factor_precheck_v2_absolute.py's build_panel, unchanged."""
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
    """Rank IC on the whole high-liquidity cross-section each month - independent
    of top_n, same method as absolute_liquidity_decile_check.py's decile_analysis."""
    months = sorted(sub["entry_date"].unique())
    monthly_ics = []
    for m in months:
        g = sub[sub["entry_date"] == m]
        if len(g) < 15:
            continue
        ic = rank_ic((-g["pbr"]).values, g["ret"].values)  # low pbr good -> sign-flip so +IC = good
        if ic is not None:
            monthly_ics.append(ic)
    if not monthly_ics:
        return {"meanMonthlyIC": None, "icTstat": None, "icMonthsUsed": 0}
    ic_mean = float(np.mean(monthly_ics))
    ic_std = float(np.std(monthly_ics))
    ic_tstat = (ic_mean / (ic_std / np.sqrt(len(monthly_ics)))) if ic_std > 0 else None
    return {
        "meanMonthlyIC": round(ic_mean, 4),
        "icTstat": round(ic_tstat, 2) if ic_tstat is not None else None,
        "icMonthsUsed": len(monthly_ics),
    }


def period_strategy_metrics(sub, top_n):
    months = sorted(sub["entry_date"].unique())
    month_rets = []
    trade_count = 0
    for m in months:
        g = sub[sub["entry_date"] == m].sort_values("pbr", ascending=True).head(top_n)
        if g.empty:
            continue
        month_rets.append((m, float((g["ret"] - COST_RT_BPS / 1e4).mean())))
        trade_count += len(g)
    if not month_rets:
        return None
    mdf = pd.DataFrame(month_rets, columns=["month", "ret"])
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
        "monthsTraded": n_months,
        "avgTickersPerMonth": round(trade_count / n_months, 1),
        "tradeCount": trade_count,
        "totalReturn": round(eq - 1, 4),
        "cagr": round(cagr, 4) if cagr is not None else None,
        "maxDD": round(maxdd, 4),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
    }


def main():
    pbr_lookup = load_valuation_panel()
    print(f"valuation panel: {len(pbr_lookup)} (ticker,asOf) rows with pbr")

    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-oos-regime-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    print(f"panel rows (full period, pre-liquidity-filter)={len(df)}")

    df_hi = df[df["turnover20"] >= MIN_TURNOVER]
    print(f"high-liquidity (>= {MIN_TURNOVER:.0f}) rows={len(df_hi)}")

    results = {}
    for period_name, (p_start, p_end) in PERIODS.items():
        sub = df_hi[(df_hi["entry_date"] >= p_start) & (df_hi["entry_date"] <= p_end)]
        period_block = {"period": f"{p_start} ~ {p_end}", "ic": period_ic(sub)}
        for top_n in [DESIGN_TOP_N] + SENSITIVITY_TOP_NS:
            tag = "top30_confirmedParams" if top_n == DESIGN_TOP_N else f"top{top_n}_sensitivityOnly"
            period_block[tag] = period_strategy_metrics(sub, top_n)
        results[period_name] = period_block
        print(f"\n=== {period_name} ({p_start} ~ {p_end}) ===")
        print(json.dumps(period_block, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-pbr-oos-regime-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-oos-regime-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "설계구간(2016-01~2022-12)에서 확정한 파라미터(top-30, 월별 리밸런싱, "
                       "turnover20>=1억원)를 재튜닝 없이 2023/2024(밸류업 regime)/2025-2026에 "
                       "그대로 적용한 OOS 구간분리 검증. top-20/40은 민감도 확인용, 선택 대상 아님. "
                       "세션인수인계-2026-08-21-c.md 후속, PBR 엔진 겹침판정 수정(runner.py) 이후.",
            "costBps": COST_RT_BPS, "minTurnover": MIN_TURNOVER,
            "designTopN": DESIGN_TOP_N, "sensitivityTopNs": SENSITIVITY_TOP_NS,
            "fullPeriodPanelRows": len(df), "fullPeriodHighLiquidityRows": len(df_hi),
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
