#!/usr/bin/env python
"""Buffett Quality 팩터(고ROE + roeConsistency(5년 무적자) + 건전한 부채비율)가
실제로 초과수익을 내는지, 유동성과 무관하게 남는지 사전 점검 (투자대가 방법론
타당성 조사, Lynch GARP/PEG precheck 다음 단계 — 2026-08-21 사용자 승인).

핵심 차이(Lynch·PBR과 다른 경제적 근거): "싸다"가 아니라 "좋은 기업이다"가
매수 조건이다 — 가격(밸류에이션) 축을 아예 안 본다. lowmom60/pbr/peg
precheck와 같은 골격(월별 리밸런싱, turnover20 tercile 유동성 필터, 30bp
왕복비용)만 재사용한다.

  python buffett_quality_factor_precheck.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(
    REPO_ROOT, "research", "strategy-lab", "reports",
    "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl",
)
START = "2016-01-01"
END = "2026-08-14"
TOP_N = 30
COST_RT_BPS = 30.0
MAX_DEBT_RATIO = 200.0  # config/criteria의 warningThresholds.debtRatioHigh 기본값과 동일 기준


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_quality_panel():
    """quality 후보 = roe 있음 + roeConsistency>0(5년간 적자 없음, 최소 요건이라
    filter 아닌 eligibility) + debtRatio<=MAX_DEBT_RATIO. eligibility를 만족하지
    않는 종목도 패널엔 남기고 (roeConsistency<=0 등도) high-ROE 정렬 시 자연히
    최상위에서 밀려나지만, 대조군(direction='low')은 이 필터를 안 걸어 원본
    roe 분포를 그대로 본다."""
    rows = []
    with open(PANEL_PATH, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["roe"])
    df["qualityEligible"] = (df["roeConsistency"].fillna(-1) > 0) & (df["debtRatio"].fillna(MAX_DEBT_RATIO + 1) <= MAX_DEBT_RATIO)
    return df.set_index(["ticker", "asOf"])[["roe", "qualityEligible"]].to_dict("index")


def build_panel(bars_by_ticker, rebalance_dates, quality_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            row = quality_lookup.get((ticker, t))
            if row is None:
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
                "ticker": ticker, "entry_date": t, "roe": float(row["roe"]),
                "qualityEligible": bool(row["qualityEligible"]),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, tercile_filter=None,
                  direction="high", require_eligible=False):
    """direction: 'high'(고ROE 매수, Buffett 가설) | 'low'(저ROE 매수, 대조군).
    require_eligible: True면 roeConsistency>0·debtRatio<=200%인 종목만 후보."""
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if require_eligible:
            g = g[g["qualityEligible"]]
        if tercile_filter:
            q1, q2 = g["turnover20"].quantile([1 / 3, 2 / 3])
            if tercile_filter == "T3":
                g = g[g["turnover20"] >= q2]
            elif tercile_filter == "T1":
                g = g[g["turnover20"] < q1]
        g = g.sort_values("roe", ascending=(direction == "low")).head(top_n)
        if g.empty:
            continue
        month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean(), len(g)))
    mdf = pd.DataFrame(month_rets, columns=["month", "ret", "n"])
    eq, peak, maxdd = 100_000_000.0, 100_000_000.0, 0.0
    for _, row in mdf.iterrows():
        eq *= (1 + row["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_years = len(mdf["month"].str[:4].unique())
    cagr = (eq / 100_000_000.0) ** (1 / n_years) - 1 if n_years else None
    return {
        "monthsTraded": len(mdf), "avgTickersPerMonth": round(mdf["n"].mean(), 1) if len(mdf) else None,
        "finalEquity": round(eq, 0), "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def main():
    quality_lookup = load_quality_panel()
    print(f"quality panel: {len(quality_lookup)} (ticker,asOf) rows with roe")

    tickers = sorted({t for t, _ in quality_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="buffett-quality-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, quality_lookup)
    print(f"panel rows={len(df)}, quality-eligible rows={int(df['qualityEligible'].sum())}")

    results = {
        "highROE_no_filter": run_backtest(df, direction="high", tercile_filter=None),
        "lowROE_control_no_filter": run_backtest(df, direction="low", tercile_filter=None),
        "highROE_T3_top_liquidity_tercile": run_backtest(df, direction="high", tercile_filter="T3"),
        "highROE_T1_bottom_liquidity_tercile": run_backtest(df, direction="high", tercile_filter="T1"),
        "highROE_qualityEligible_no_filter": run_backtest(df, direction="high", tercile_filter=None, require_eligible=True),
        "highROE_qualityEligible_T3": run_backtest(df, direction="high", tercile_filter="T3", require_eligible=True),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-buffett-quality-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "quality-factor-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "투자대가 방법론 타당성 조사 - Buffett Quality(고ROE+5년무적자"
                       "+부채비율<=200%)를 Strategy Lab에 결합하기 전 사전 점검. "
                       "가격(밸류에이션) 축을 전혀 안 보고 품질만으로 초과수익이 "
                       "나는지, 유동성 상/하위 tercile에서도 남는지. FCF 미수집이라 "
                       "ROE/부채비율/이익안정성만으로 근사한 축소판.",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "maxDebtRatio": MAX_DEBT_RATIO, "panelRows": len(quality_lookup),
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
