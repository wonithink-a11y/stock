#!/usr/bin/env python
"""Lynch GARP/PEG 팩터가 실제로 초과수익을 내는지, 유동성과 무관하게 남는지
사전 점검 (투자대가 방법론 타당성 조사, 2026-08-21 사용자 승인 "추천 순서대로:
Lynch -> Buffett -> CAN SLIM 축약판").

a5_valuation_factor_precheck.py(pbr)와 완전히 같은 골격 — 다른 것은 팩터
정의(peg = per/epsGrowthRate, epsGrowthRate<=0이면 PEG 정의 불가라 표본에서
제외. lib/scoringEngine.js:162-177의 운영 정의와 동일 조건)뿐이다. 패널은
scripts/build-a5-valuation-panel.js가 만든 valuation-panel.jsonl을 그대로
재사용(2026-08-21에 epsGrowthRate·debtRatio 필드 추가, mergerSpinoff 이력
종목은 패널 생성 단계에서 이미 제외됨).

  python lynch_garp_factor_precheck.py
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
END = "2026-08-14"
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


def load_garp_panel():
    """peg = per/epsGrowthRate, epsGrowthRate>0·per>0일 때만 정의(운영 scoringEngine.js와
    동일 조건) — 이익 역성장 종목은 PEG 자체가 성립하지 않아 표본에서 제외한다."""
    rows = []
    with open(PANEL_PATH, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["per", "epsGrowthRate"])
    df = df[(df["per"] > 0) & (df["epsGrowthRate"] > 0)]
    df["peg"] = df["per"] / df["epsGrowthRate"]
    # to_dict("index"): (ticker,asOf) -> {"peg":..,"debtRatio":..}. 주의 —
    # df.set_index(...)[["peg","debtRatio"]]로 DataFrame을 만들면 .get((t,d))가
    # 인덱스가 아니라 컬럼명을 찾아 전부 None이 된다(Series의 .get과 다름) —
    # 실측으로 발견(panel rows=0).
    return df.set_index(["ticker", "asOf"])[["peg", "debtRatio"]].to_dict("index")


def build_panel(bars_by_ticker, rebalance_dates, garp_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            row = garp_lookup.get((ticker, t))
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
                "ticker": ticker, "entry_date": t, "peg": float(row["peg"]),
                "debtRatio": row["debtRatio"] if pd.notna(row["debtRatio"]) else None,
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, tercile_filter=None,
                  direction="low", max_debt_ratio=None):
    """direction: 'low'(저PEG 매수, GARP 가설) | 'high'(고PEG 매수, 대조군).
    max_debt_ratio: 지정하면 그 값 이하(재무건전성 필터, 린치의 "합리적 부채"
    조건 근사)만 후보로 남긴다."""
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
        if max_debt_ratio is not None:
            g = g[g["debtRatio"].notna() & (g["debtRatio"] <= max_debt_ratio)]
        g = g.sort_values("peg", ascending=(direction == "low")).head(top_n)
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
    garp_lookup = load_garp_panel()
    print(f"garp panel: {len(garp_lookup)} (ticker,asOf) rows with peg")

    tickers = sorted({t for t, _ in garp_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="lynch-garp-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, garp_lookup)
    print(f"panel rows={len(df)}")

    median_debt = df["debtRatio"].median()
    results = {
        "lowPEG_no_filter": run_backtest(df, direction="low", tercile_filter=None),
        "highPEG_control_no_filter": run_backtest(df, direction="high", tercile_filter=None),
        "lowPEG_T3_top_liquidity_tercile": run_backtest(df, direction="low", tercile_filter="T3"),
        "lowPEG_T1_bottom_liquidity_tercile": run_backtest(df, direction="low", tercile_filter="T1"),
        "lowPEG_plus_belowMedianDebt_no_filter": run_backtest(df, direction="low", tercile_filter=None, max_debt_ratio=median_debt),
        "lowPEG_plus_belowMedianDebt_T3": run_backtest(df, direction="low", tercile_filter="T3", max_debt_ratio=median_debt),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-lynch-garp-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "peg-factor-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "투자대가 방법론 타당성 조사 - Lynch GARP/PEG를 Strategy Lab에 "
                       "결합하기 전 사전 점검. 저PEG 매수가 초과수익을 내는지, 유동성 "
                       "상/하위 tercile에서도 남는지, 부채비율 중앙값 이하 필터를 얹으면 "
                       "달라지는지. mergerSpinoff 공시 이력 종목은 패널 생성 단계에서 "
                       "이미 제외됨(a5-valuation-precheck coverage-summary.json 참고).",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "panelRows": len(garp_lookup), "medianDebtRatio": round(float(median_debt), 1),
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
