#!/usr/bin/env python
"""A5-3 D4 pbr(저PBR 가치) 팩터가 실제로 초과수익을 내는지, 유동성과 무관하게
남는지 사전 점검.

배경(세션인수인계-2026-08-21-b.md §3, 사용자 승인 "mergerSpinoff 이력 종목
제외하고 진행") — Strategy Lab에 밸류에이션(peg/pbr)을 처음 결합하기 전,
scripts/build-a5-valuation-panel.js가 만든 종목×월별 pbr 패널(mergerSpinoff
공시 이력 종목 제외, 커버리지 72.0%)로 가장 단순한 질문부터 잰다: **매달
pbr이 낮은 종목을 사면 다음 달 초과수익이 나는가? 그 효과가 저유동성
종목에만 몰려 있지는 않은가?** (오늘 이 세션에서 LOWMOM60·REV20 둘 다 그
함정으로 채택 불가였다 — 같은 패턴 재발 여부부터 확인.)

lowmom60_robustness.py·lowmom60_institutional_eligible_precheck.py의 패널
구성·tercile 필터·백테스트 로직을 그대로 재사용한다 - 새 계약·새 엔진 없음,
engine/ 미변경, data/backfill/ 미변경.

  python a5_valuation_factor_precheck.py
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
    "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl",
)
START = "2016-01-01"
END = "2026-08-14"  # lowmom60_robustness.py와 동일 - 조건 고정
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


def load_valuation_panel():
    rows = []
    with open(PANEL_PATH, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["pbr"])
    df = df[df["pbr"] > 0]  # pbr<=0(음의 자본)은 가치주가 아니라 부실 신호 - 별도 취급 대상, 여기선 제외
    return df.set_index(["ticker", "asOf"])["pbr"]


def build_panel(bars_by_ticker, rebalance_dates, pbr_lookup):
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


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, tercile_filter=None, direction="low"):
    """direction: 'low'(저PBR 매수, 가치 가설) | 'high'(고PBR 매수, 대조군)."""
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if tercile_filter:
            q1, q2 = g["turnover20"].quantile([1 / 3, 2 / 3])
            if tercile_filter == "T3":
                g = g[g["turnover20"] >= q2]
            elif tercile_filter == "T1":
                g = g[g["turnover20"] < q1]
        g = g.sort_values("pbr", ascending=(direction == "low")).head(top_n)
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
    pbr_lookup = load_valuation_panel()
    print(f"valuation panel: {len(pbr_lookup)} (ticker,asOf) rows with pbr")

    tickers = sorted({t for t, _ in pbr_lookup.index})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="a5-valuation-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    print(f"panel rows={len(df)}")

    results = {
        "lowPBR_no_filter": run_backtest(df, direction="low", tercile_filter=None),
        "highPBR_control_no_filter": run_backtest(df, direction="high", tercile_filter=None),
        "lowPBR_T3_top_liquidity_tercile": run_backtest(df, direction="low", tercile_filter="T3"),
        "lowPBR_T1_bottom_liquidity_tercile": run_backtest(df, direction="low", tercile_filter="T1"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-a5-valuation-precheck")
    out_path = os.path.join(out_dir, "pbr-factor-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "A5-3 D4 pbr을 Strategy Lab에 결합하기 전 사전 점검 - "
                       "저PBR 매수가 초과수익을 내는지, 유동성 상/하위 tercile에서도 "
                       "남는지. mergerSpinoff 공시 이력 종목은 커버리지 붕괴(2.4%)로 "
                       "패널 생성 단계에서 이미 제외됨(coverage-summary.json 참고).",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "panelRows": len(pbr_lookup),
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
