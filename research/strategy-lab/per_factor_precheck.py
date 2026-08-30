#!/usr/bin/env python
"""저PER(밸류) 팩터 1차 정찰 — PBR 연구(a5_valuation_factor_precheck_v2_
absolute.py)와 완전히 같은 방법론을 PER에 적용한다. 사용자 지시(2026-08-28,
"PER을 완전히 별개 연구로") - PBR과는 독립된 신규 트랙.

기존 학습 그대로 재사용:
  - 상대 tercile(turnover20 T3) 대신 **절대 유동성 임계값**(turnover20>=1억원)
    사용 - 상대 tercile 자체가 강한 예측변수라는 테스트베드 결함이 이미
    확정됐다(세션인수인계-2026-08-21-c.md).
  - 저PER = 밸류라는 방향으로 오름차순 정렬, top-N.
  - PER<=0(적자 기업)은 "저평가"가 아니라 "이익이 없다"는 뜻이라 밸류
    순위에서 제외한다(PBR이 pbr>0으로 걸렀던 것과 동일 원칙).

데이터: reports/2026-08-21-a5-valuation-precheck/valuation-panel.jsonl
(이미 계산돼 있음 - resolver.js가 A2a 가격 + A3 순이익 + A3c 발행주식수로
만든 월별 PER 패널, 새 계산·API 호출 불필요).

production 변경 없음.
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
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
TOP_N = 30
COST_RT_BPS = 30.0
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


def load_valuation_panel():
    rows = [json.loads(line) for line in open(PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["per"])
    df = df[df["per"] > 0]  # 적자기업(PER<=0)은 "저평가"가 아니라 이익 자체가 없음 - 제외
    return df.set_index(["ticker", "asOf"])["per"].to_dict()


def build_panel(bars_by_ticker, rebalance_dates, per_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            per = per_lookup.get((ticker, t))
            if per is None:
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
                "ticker": ticker, "entry_date": t, "per": float(per),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, liquidity_filter=None, direction="low"):
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if liquidity_filter == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif liquidity_filter == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        g = g.sort_values("per", ascending=(direction == "low")).head(top_n)
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
    """월별 PER decile(1=최저PER) 대비 익월수익률 스프레드 - PBR 연구가 쓴
    것과 같은 진단(t=6.30 재확인용 관례)."""
    spreads = []
    for m, g in df.groupby("entry_date"):
        if len(g) < 30:
            continue
        g = g.copy()
        g["decile"] = pd.qcut(g["per"].rank(method="first"), 10, labels=False) + 1
        d1 = g[g["decile"] == 1]["ret"].mean()  # 최저PER
        d10 = g[g["decile"] == 10]["ret"].mean()  # 최고PER
        if pd.notna(d1) and pd.notna(d10):
            spreads.append(d1 - d10)
    import numpy as np
    sp = pd.Series(spreads)
    t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
    return {"nMonths": len(sp), "meanSpread(D1-D10)": round(float(sp.mean()), 5) if len(sp) else None,
            "t": round(float(t), 2) if t is not None else None}


def main():
    per_lookup = load_valuation_panel()
    print(f"valuation panel: {len(per_lookup)} (ticker,asOf) rows with per>0")

    tickers = sorted({t for t, _ in per_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="per-factor-precheck-v1")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates, per_lookup)
    print(f"panel rows={len(df)}")

    results = {
        "lowPER_no_filter": run_backtest(df, direction="low", liquidity_filter=None),
        "lowPER_high_liquidity_absoluteThreshold": run_backtest(df, direction="low", liquidity_filter="high"),
        "lowPER_low_liquidity_absoluteThreshold_control": run_backtest(df, direction="low", liquidity_filter="low"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    ic = decile_ic(df)
    print("decile IC (D1 저PER - D10 고PER):", json.dumps(ic, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-per-factor-precheck")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "per-factor-precheck-v1.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR 연구(a5_valuation_factor_precheck_v2_absolute.py)와 동일 방법론을 "
                       "PER에 적용 - 절대 유동성 임계값(1억원), PER<=0 제외, top-30, 30bps 비용.",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER, "panelRows": len(per_lookup),
            "results": results, "decileIC": ic,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
