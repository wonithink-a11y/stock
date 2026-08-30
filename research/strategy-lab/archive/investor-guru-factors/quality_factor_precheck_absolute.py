#!/usr/bin/env python
"""Lynch PEG · Buffett ROE 팩터 재검증(절대 유동성 임계값).

2026-08-21 "투자대가 방법론 타당성 조사"가 turnover20 rolling tercile을
유동성 통제변수로 쓰는 테스트베드 자체에 결함(그 자체가 강한 방향성
예측변수)이 있음을 확정한 뒤, PBR·LOWMOM60은 절대임계값(turnover20>=1억원)
으로 재검증해 결과가 뒤집혔다(PBR -1.48%→+7.06%, LOWMOM60 -11.8%→+13.90%,
CLAUDE.md "투자대가 방법론 타당성 조사" 절 참고). **그런데 그 결함을 원래
드러낸 당사자인 Lynch PEG·Buffett ROE 자신은 그 이후 한 번도 재검증되지
않았다** — `lynch_garp_factor_precheck.py`·`buffett_quality_factor_precheck.py`
둘 다 직접 확인 결과 여전히 옛 tercile_filter 로직 그대로다(2026-08-28).
PBR·LOWMOM60이 뒤집힌 선례가 있으니 이 둘도 뒤집힐 수 있다 — 새 factor
mining이 아니라 이미 있는 방법론 버그를 이미 있는 후보에 적용하는 재검증
이라 과적합 위험이 낮다(growth screen 원인분석과 같은 성격, 사용자 승인
없이 착수 - "새로운 신호를 찾아봐" 지시, 2026-08-28).

per_factor_precheck.py(PER 재검증)와 완전히 같은 방법론 - 절대임계값
(turnover20>=1억원), decile IC 진단. 기존 패널(valuation-panel.jsonl의
per+epsGrowthRate로 peg 계산, quality-panel.jsonl의 roe) 그대로 재사용 -
새 계산·API 호출 없음.

  python quality_factor_precheck_absolute.py
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
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
QUALITY_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                              "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
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


def load_peg_lookup():
    rows = [json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["per", "epsGrowthRate"])
    df = df[(df["per"] > 0) & (df["epsGrowthRate"] > 0)]
    df["peg"] = df["per"] / df["epsGrowthRate"]
    return df.set_index(["ticker", "asOf"])["peg"].to_dict()


def load_roe_lookup():
    rows = [json.loads(line) for line in open(QUALITY_PANEL, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["roe"])
    return df.set_index(["ticker", "asOf"])["roe"].to_dict()


def build_panel(bars_by_ticker, rebalance_dates, factor_lookup, factor_name):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            val = factor_lookup.get((ticker, t))
            if val is None:
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
                "ticker": ticker, "entry_date": t, factor_name: float(val),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, factor_name, direction, top_n=TOP_N, cost_bps=COST_RT_BPS, liquidity_filter=None):
    months = sorted(df["entry_date"].unique())
    month_rets = []
    for m in months:
        g = df[df["entry_date"] == m]
        if liquidity_filter == "high":
            g = g[g["turnover20"] >= MIN_TURNOVER]
        elif liquidity_filter == "low":
            g = g[g["turnover20"] < MIN_TURNOVER]
        g = g.sort_values(factor_name, ascending=(direction == "low")).head(top_n)
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


def decile_ic(df, factor_name, best_direction):
    """best_direction='low'면 D1(팩터값 최저)이 '좋다'는 가설 방향(PEG),
    'high'면 D10(팩터값 최고)이 좋다는 가설 방향(ROE) - 스프레드는 항상
    "가설이 맞는 방향 - 틀린 방향"으로 부호를 통일해 t-stat을 직접 비교
    가능하게 한다."""
    spreads = []
    for m, g in df.groupby("entry_date"):
        if len(g) < 30:
            continue
        g = g.copy()
        g["decile"] = pd.qcut(g[factor_name].rank(method="first"), 10, labels=False) + 1
        d1 = g[g["decile"] == 1]["ret"].mean()
        d10 = g[g["decile"] == 10]["ret"].mean()
        if pd.notna(d1) and pd.notna(d10):
            spread = (d1 - d10) if best_direction == "low" else (d10 - d1)
            spreads.append(spread)
    sp = pd.Series(spreads)
    t = sp.mean() / (sp.std() / (len(sp) ** 0.5)) if len(sp) > 1 and sp.std() > 0 else None
    return {"nMonths": len(sp), "meanSpread(bestDecile-worstDecile)": round(float(sp.mean()), 5) if len(sp) else None,
            "t": round(float(t), 2) if t is not None else None}


def run_factor(name, factor_lookup, direction, calendar, a2a, rebalance_dates):
    tickers = sorted({t for t, _ in factor_lookup.keys()})
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash=f"{name}-precheck-absolute")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"[{name}] bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    df = build_panel(bars_by_ticker, rebalance_dates, factor_lookup, name)
    print(f"[{name}] panel rows={len(df)}")

    results = {
        f"{direction}{name}_no_filter": run_backtest(df, name, direction, liquidity_filter=None),
        f"{direction}{name}_high_liquidity_absoluteThreshold": run_backtest(df, name, direction, liquidity_filter="high"),
        f"{direction}{name}_low_liquidity_absoluteThreshold_control": run_backtest(df, name, direction, liquidity_filter="low"),
    }
    for rname, r in results.items():
        print(f"  {rname} -> {json.dumps(r, ensure_ascii=False)}")
    ic = decile_ic(df, name, direction)
    print(f"  decile IC (bestDirection={direction}):", json.dumps(ic, ensure_ascii=False))
    return {"panelRows": len(factor_lookup), "results": results, "decileIC": ic}


def main():
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    out = {}
    print("=== Lynch PEG (저PEG=GARP 가설, direction=low) ===")
    out["peg"] = run_factor("peg", load_peg_lookup(), "low", calendar, a2a, rebalance_dates)

    print("\n=== Buffett ROE (고ROE 가설, direction=high) ===")
    out["roe"] = run_factor("roe", load_roe_lookup(), "high", calendar, a2a, rebalance_dates)

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-28-quality-factor-precheck-absolute")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "quality-factor-precheck-absolute.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "2026-08-21 tercile 테스트베드 결함 확정 이후 PBR·LOWMOM60만 절대"
                       "임계값으로 재검증됐고 Lynch PEG·Buffett ROE는 미착수였던 것을 재검증"
                       "(2026-08-28, 'PBR/A5-3 재검증 선례가 뒤집혔으니 이 둘도 뒤집힐 수 "
                       "있다'는 가설). 절대 유동성 임계값(turnover20>=1억원), top-30, 30bps.",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "minTurnover": MIN_TURNOVER, "factors": out,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
