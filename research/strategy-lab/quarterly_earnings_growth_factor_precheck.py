#!/usr/bin/env python
"""분기 이익성장률(QoQ YoY 단독분기 순이익 증가율) 팩터 — CAN SLIM의 "C"
(Current quarterly earnings growth)에 해당하는 축을 처음 테스트한다.

이 각도가 새로운 이유: `growth_screen_v1.py`(기각)는 **연간 3년 CAGR**
(자산·매출·영업이익)을 썼고, `build_quarterly_earnings_panel.py`(PEAD용,
2026-08-28 24,750 corp-year 전면수집 완료)는 **분기 실적 서프라이즈**
(SUE = 실적-기대치, event study)를 썼다. 이 스크립트는 그 사이 — "이번
분기 순이익이 전년동기 대비 몇 % 늘었나"를 **매달 재평가하는 횡단면
랭킹 팩터**로 쓴다(SUE처럼 발표 시점 이벤트가 아니라 PBR/PER처럼 매달
최신 알려진 값으로 순위를 매김). 오늘 전면수집이 끝난 분기 패널
(thstrm=이번분기 단독, frmtrm=전년동기 단독, 둘 다 누적아님 - 확인됨)이
있어 새 API 호출 없이 바로 테스트 가능하다(사용자 지시 2026-08-28,
"새로운 신호를 찾아봐").

방법론은 per_factor_precheck.py(PER)와 동일 - 절대 유동성 임계값
(turnover20>=1억원), top-30, 30bps, decile IC. PIT: 각 리밸런싱일에
그 시점까지 발표된 가장 최근 분기의 growth를 쓴다(carry-forward, 발표
후 180일 초과 정체 시 stale로 간주해 제외 - 분기 주기(~91일)의 2배).

  python quarterly_earnings_growth_factor_precheck.py
"""
import bisect
import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "quarterly-earnings", "quarterly-earnings-panel.jsonl")
START, END = "2016-01-01", "2026-08-14"
TOP_N = 30
COST_RT_BPS = 30.0
MIN_TURNOVER = 100_000_000.0
STALE_DAYS = 180
GROWTH_ABS_CAP = 5.0  # |growth|>500%는 frmtrm이 0에 가까운 분모 왜곡으로 보고 제외


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_growth_events():
    rows = [json.loads(line) for line in open(PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["thstrm", "frmtrm"])
    df = df[df["frmtrm"] > 0]  # 전년동기 흑자만 - 성장률이 부호까지 의미있게 정의되는 경우
    df["growth"] = df["thstrm"] / df["frmtrm"] - 1.0
    df = df[df["growth"].abs() <= GROWTH_ABS_CAP]
    df["availableFrom"] = pd.to_datetime(df["availableFrom"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    by_ticker = {}
    for tk, g in df.sort_values("availableFrom").groupby("ticker"):
        by_ticker[tk] = (g["availableFrom"].tolist(), g["growth"].tolist())
    return by_ticker


def growth_asof(by_ticker, ticker, as_of):
    ev = by_ticker.get(ticker)
    if not ev:
        return None
    dates, growths = ev
    i = bisect.bisect_right(dates, as_of) - 1
    if i < 0:
        return None
    d0 = date.fromisoformat(dates[i])
    d1 = date.fromisoformat(as_of)
    if (d1 - d0) > timedelta(days=STALE_DAYS):
        return None
    return growths[i]


def build_panel(bars_by_ticker, rebalance_dates, by_ticker):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            growth = growth_asof(by_ticker, ticker, t)
            if growth is None:
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
                "ticker": ticker, "entry_date": t, "growth": float(growth),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, liquidity_filter=None, direction="high"):
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if liquidity_filter == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif liquidity_filter == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        g = g.sort_values("growth", ascending=(direction == "low")).head(top_n)
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
        "totalReturn": round(eq / 100_000_000.0 - 1, 4),
        "cagr": round(cagr, 4) if cagr else None, "maxDD": round(maxdd, 4),
    }


def decile_ic(df):
    """D10(성장률 최고) - D1(최저) - 높을수록 좋다는 가설 방향으로 스프레드 고정."""
    spreads = []
    for m, g in df.groupby("entry_date"):
        if len(g) < 30:
            continue
        g = g.copy()
        g["decile"] = pd.qcut(g["growth"].rank(method="first"), 10, labels=False) + 1
        d1 = g[g["decile"] == 1]["ret"].mean()
        d10 = g[g["decile"] == 10]["ret"].mean()
        if pd.notna(d1) and pd.notna(d10):
            spreads.append(d10 - d1)
    sp = pd.Series(spreads)
    t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
    return {"nMonths": len(sp), "meanSpread(D10-D1)": round(float(sp.mean()), 5) if len(sp) else None,
            "t": round(float(t), 2) if t is not None else None}


def main():
    by_ticker = load_growth_events()
    print(f"tickers with growth events: {len(by_ticker)}")

    tickers = sorted(by_ticker.keys())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="qtr-earnings-growth-precheck")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, by_ticker)
    print(f"panel rows={len(df)}")

    results = {
        "highGrowth_no_filter": run_backtest(df, direction="high", liquidity_filter=None),
        "highGrowth_high_liquidity_absoluteThreshold": run_backtest(df, direction="high", liquidity_filter="high"),
        "highGrowth_low_liquidity_absoluteThreshold_control": run_backtest(df, direction="high", liquidity_filter="low"),
        "lowGrowth_control_no_filter": run_backtest(df, direction="low", liquidity_filter=None),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    ic = decile_ic(df)
    print("decile IC (D10 고성장 - D1 저성장):", json.dumps(ic, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-quarterly-earnings-growth-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "quarterly-earnings-growth-precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "분기 단독순이익 YoY 성장률(CAN SLIM 'C' 근사) 신규 팩터 1차 정찰 - "
                       "build_quarterly_earnings_panel.py(PEAD용, 오늘 전면수집 완료) 재사용, "
                       "새 API 호출 없음. PIT carry-forward, staleness cap 180일, "
                       "growth abs cap 500%(분모 왜곡 방지).",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER, "staleDays": STALE_DAYS, "growthAbsCap": GROWTH_ABS_CAP,
            "panelTickers": len(by_ticker),
            "results": results, "decileIC": ic,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
