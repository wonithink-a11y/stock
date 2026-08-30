#!/usr/bin/env python
"""REV20 결합 견고성 검증 — 비용 × 유동성 × 가격 필터 동시 적용 (DEEPSEEK-1).

재사용: lowmom60_survivorship.run_backtest() 의 팩터/필터 로직을 그대로 따른다.
headline 수치는 run_backtest()를 직접 호출해 기존 저장 JSON(lowmom60_survivorship.json)
수치 재현을 먼저 확인한다. 그 다음 동일 panel 로직을 로컬에 재구현해
  (a) 필터 통과 후보 수(n_selected_rows), (b) 미충족 월 수(underfilled),
  (c) 연도별 성과·연도별 최고/최저 기여 종목, (d) 월 수익률 분포(불안정 vs 체계적 전환)
를 분해해 minPrice 전환 손실의 원인을 구분한다.

production 경로(lib/·scripts/·config/·정책)는 건드리지 않는다.
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from lowmom60_survivorship import (  # noqa: E402
    REPO_ROOT, START, END, TOP_N, INITIAL_CAPITAL,
    load_a2b, monthly_rebalance_dates, run_backtest,
)

OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                       "2026-08-18-strategy-candidates")


def build_panel(bars_by_ticker, rebalance_dates, factor="rev20"):
    """lowmom60_survivorship.run_backtest()의 panel 구성과 동일."""
    if factor == "rev20":
        ffn = lambda df: -(df["close"] / df["close"].shift(20) - 1)
    else:
        ffn = lambda df: df["close"] / df["close"].shift(60) - 1
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close = bars["close"]
        open_ = bars["open"]
        vol = bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        fv = ffn(bars)
        turnover20 = (close * vol).rolling(20).mean()
        avgclose20 = close.rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            m = fv.iloc[i]
            if pd.isna(m):
                continue
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue  # 상장폐지 등 → 미진입
            ep = float(open_.iloc[i + 1])
            xp = float(open_.iloc[j + 1])
            if ep <= 0 or xp <= 0:
                continue
            rows.append({
                "ticker": ticker, "entry_date": t, "factor": float(m),
                "ret": xp / ep - 1,
                "turnover20": float(turnover20.iloc[i]) if not pd.isna(turnover20.iloc[i]) else 0.0,
                "avgclose20": float(avgclose20.iloc[i]) if not pd.isna(avgclose20.iloc[i]) else 0.0,
            })
    return pd.DataFrame(rows)


def analyze(panel, factor="rev20", ascending=False,
            min_turnover=0, min_price=0, cost_bps=30.0):
    """run_backtest()와 같은 선택/수익 로직 + 원인 분해 지표."""
    sub = panel[(panel["turnover20"] >= min_turnover) & (panel["avgclose20"] >= min_price)]
    months = sorted(sub["entry_date"].unique())
    selected = []
    month_rets = []
    underfilled = []
    for m in months:
        g = sub[sub["entry_date"] == m].sort_values("factor", ascending=ascending).head(TOP_N)
        if g.empty:
            continue
        if len(g) < TOP_N:
            underfilled.append((m, int(len(g))))
        selected.append(g)
        month_rets.append((m, (g["ret"] - cost_bps / 1e4).mean()))
    port = pd.concat(selected) if selected else pd.DataFrame()
    mdf = pd.DataFrame(month_rets, columns=["month", "ret"])
    eq = INITIAL_CAPITAL
    curve = []
    peak = eq
    maxdd = 0.0
    for _, r in mdf.iterrows():
        eq *= (1 + r["ret"])
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
        curve.append((r["month"], eq))
    eq_df = pd.DataFrame(curve, columns=["month", "equity"])
    years = eq_df["month"].str[:4]
    n_years = len(years.unique())
    total = eq_df["equity"].iloc[-1] / INITIAL_CAPITAL - 1
    cagr = (eq_df["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / n_years) - 1 if n_years else None
    yearly = {}
    for y, g in eq_df.groupby(years):
        yearly[y] = round(float(g["equity"].iloc[-1] / g["equity"].iloc[0] - 1), 4)

    yearly_detail = {}
    if not port.empty:
        port = port.copy()
        port["year"] = port["entry_date"].str[:4]
        for y, g in port.groupby("year"):
            byt = g.groupby("ticker")["ret"].agg(["count", "sum"]).sort_values("sum", ascending=False)
            yearly_detail[y] = {
                "n_selected": int(len(g)),
                "n_tickers": int(byt.shape[0]),
                "top_contrib": {
                    "ticker": byt.index[0], "count": int(byt.iloc[0]["count"]),
                    "sum_ret": round(float(byt.iloc[0]["sum"]), 4),
                },
                "bottom_contrib": {
                    "ticker": byt.index[-1], "count": int(byt.iloc[-1]["count"]),
                    "sum_ret": round(float(byt.iloc[-1]["sum"]), 4),
                },
            }

    monthly = {
        "n_months": int(len(mdf)),
        "n_pos": int((mdf["ret"] > 0).sum()),
        "n_neg": int((mdf["ret"] < 0).sum()),
        "mean": round(float(mdf["ret"].mean()), 6),
        "median": round(float(mdf["ret"].median()), 6),
        "std": round(float(mdf["ret"].std()), 6),
        "min": round(float(mdf["ret"].min()), 6),
        "max": round(float(mdf["ret"].max()), 6),
        "worst_month": str(mdf.loc[mdf["ret"].idxmin(), "month"]),
    }
    return {
        "n_selected_rows": int(len(sub)),
        "n_portfolio_rows": int(len(port)) if not port.empty else 0,
        "n_unique_tickers": int(port["ticker"].nunique()) if not port.empty else 0,
        "n_underfilled_months": len(underfilled),
        "underfilled_examples": underfilled[:10],
        "totalReturn": round(float(total), 4),
        "cagr": round(float(cagr), 4) if cagr else None,
        "maxDrawdown": round(float(maxdd), 4),
        "finalEquity": round(float(eq_df["equity"].iloc[-1]), 0),
        "yearly": yearly,
        "monthly": monthly,
        "yearly_detail": yearly_detail,
    }


def load_universe_bars():
    universe_a1a = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    universe_merged = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    a1a_tickers = {e.ticker for e in universe_a1a.entries}
    bars_a1a = a2a.load(a1a_tickers, START, END, universe_hash=universe_a1a.universe_hash)
    bars_a1a = {t: _drop_suspension_rows(df) for t, df in bars_a1a.items()}

    a1b_tickers = {e.ticker for e in universe_merged.entries if e.source == "A1B"}
    bars_a1b = load_a2b(a1b_tickers)
    merged = dict(bars_a1a)
    merged.update(bars_a1b)
    return rebalance_dates, bars_a1a, merged


def main():
    rebalance_dates, bars_a1a, merged = load_universe_bars()
    out = {"config": {"topN": TOP_N, "start": START, "end": END,
                      "turnoverUnit": "원/일 (close*volume 20D 평균)",
                      "method": "월 리밸런스 top-30, t+1 open 진입/청산, 상장폐지 종목은 다음 리밸런스 이후 거래 없으면 미진입"}}

    # ── 0. 재현 확인: run_backtest()로 기존 저장 JSON 수치 재현 ──
    repro = {
        "REV20_A1A_ONLY_30bps": run_backtest(bars_a1a, rebalance_dates, factor="rev20", ascending=False),
        "REV20_A1A_ONLY_150bps": run_backtest(bars_a1a, rebalance_dates, factor="rev20", ascending=False, cost_bps=150),
        "REV20_A1A_ONLY_turnover10M": run_backtest(bars_a1a, rebalance_dates, factor="rev20", ascending=False, min_turnover=10_000_000),
        "REV20_MERGED_30bps": run_backtest(merged, rebalance_dates, factor="rev20", ascending=False),
        "REV20_MERGED_minPrice5000": run_backtest(merged, rebalance_dates, factor="rev20", ascending=False, min_price=5000),
    }
    for k, r in repro.items():
        print(f"[repro] {k}: cagr={r['cagr']} total={r['totalReturn']} mdd={r['maxDrawdown']} "
              f"n_months={r['n_months']} n_rows={r['n_selected_rows']}")
    out["reproduction"] = {k: {kk: r[kk] for kk in ("cagr", "totalReturn", "maxDrawdown", "n_months", "n_selected_rows")}
                           for k, r in repro.items()}

    # ── panel 구축 (REV20·LOWMOM60) ──
    print("\nBuilding REV20 panel (merged)...")
    panel_rev = build_panel(merged, rebalance_dates, factor="rev20")
    print(f"REV20 panel rows={len(panel_rev)}")
    print("Building LOWMOM60 panel (merged)...")
    panel_mom = build_panel(merged, rebalance_dates, factor="mom60")
    print(f"LOWMOM60 panel rows={len(panel_mom)}")

    # 로컬 analyze()가 run_backtest()와 일치하는지 한 번 교차검증
    a_base = analyze(panel_rev, factor="rev20", ascending=False, cost_bps=30.0)
    print(f"[cross-check] analyze vs run_backtest baseline MERGED: "
          f"cagr {a_base['cagr']} vs {repro['REV20_MERGED_30bps']['cagr']}, "
          f"n_rows {a_base['n_selected_rows']} vs {repro['REV20_MERGED_30bps']['n_selected_rows']}")

    # ── REV20 결합 검증 항목 ──
    rev = {}
    # 항목 1: cost 60/90 단독 (MERGED, 필터 없음)
    for cb in (60, 90):
        rev[f"cost{cb}bps"] = analyze(panel_rev, cost_bps=cb)
    # 항목 2: minTurnover 단독 (MERGED) — 1천만/5천만/1억/3억
    for mt, label in ((10_000_000, "turnover10M"), (50_000_000, "turnover50M"),
                      (100_000_000, "turnover100M"), (300_000_000, "turnover300M")):
        rev[label] = analyze(panel_rev, min_turnover=mt)
    # 항목 3: cost60 + turnover1억
    rev["cost60_turnover100M"] = analyze(panel_rev, min_turnover=100_000_000, cost_bps=60)
    # 항목 4: cost60 + turnover1억 + minPrice5000
    rev["cost60_turnover100M_minPrice5000"] = analyze(panel_rev, min_turnover=100_000_000, min_price=5000, cost_bps=60)
    # 항목 5 원인 분해용: minPrice 스윕 (cost30, 필터 없음) + minPrice 단독 MERGED 재확인
    for mp in (1000, 2000, 3000, 5000):
        rev[f"minPrice{mp}"] = analyze(panel_rev, min_price=mp)
    # 월 수익률 분포: raw(비용 0) 기준 minPrice 0 vs 5000 — 체계적 전환 vs 통계 불안정 구분
    rev["_raw_base"] = analyze(panel_rev, cost_bps=0)
    rev["_raw_minPrice5000"] = analyze(panel_rev, min_price=5000, cost_bps=0)
    rev["_raw_turnover100M"] = analyze(panel_rev, min_turnover=100_000_000, cost_bps=0)
    rev["_raw_turnover100M_minPrice5000"] = analyze(panel_rev, min_turnover=100_000_000, min_price=5000, cost_bps=0)
    out["REV20"] = rev

    # ── 항목 6: LOWMOM60 결합 조건 짧은 재확인 ──
    mom = {
        "baseline_MERGED_30bps": analyze(panel_mom, factor="mom60", ascending=True, cost_bps=30.0),
        "cost60_turnover100M": analyze(panel_mom, factor="mom60", ascending=True, min_turnover=100_000_000, cost_bps=60),
        "cost60_turnover100M_minPrice5000": analyze(panel_mom, factor="mom60", ascending=True,
                                                     min_turnover=100_000_000, min_price=5000, cost_bps=60),
    }
    out["LOWMOM60"] = mom

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "rev20_combined_robustness.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== REV20 요약 ===")
    for k, r in rev.items():
        if k.startswith("_"):
            continue
        print(f"{k:38s} cagr={r['cagr']!s:>8} total={r['totalReturn']!s:>8} mdd={r['maxDrawdown']!s:>8} "
              f"n_rows={r['n_selected_rows']:>7} uniq={r['n_unique_tickers']:>5} underfilled={r['n_underfilled_months']}")
    print("\n=== LOWMOM60 요약 ===")
    for k, r in mom.items():
        print(f"{k:38s} cagr={r['cagr']!s:>8} total={r['totalReturn']!s:>8} mdd={r['maxDrawdown']!s:>8} "
              f"n_rows={r['n_selected_rows']:>7} underfilled={r['n_underfilled_months']}")
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()