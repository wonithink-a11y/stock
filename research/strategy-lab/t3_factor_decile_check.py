#!/usr/bin/env python
"""A안: T3(고유동성/대형주) 전용으로 좁혀 PBR·PEG·ROE 중 뭐라도 실제 신호가
있는지 정밀 재검토 (docs/control/세션인수인계-2026-08-21-c.md §"다음 세션이
고를 두 방향" (A), 사용자 승인).

지금까지 T3는 top 30·단일 팩터·월별 리밸런싱이라는 좁은 설정에서만 봤고
전부 마이너스였다(PBR -1.48%, PEG -2.02%, ROE -7.66%). top-30 하드컷은
노이즈에 취약하다 — 이 스크립트는 T3 안에서 decile 스프레드·IC(랭크상관,
research/strategy-lab의 slot-marginal 연구가 쓴 것과 같은 척도)로 더 정밀하게
본다. 전체 분포에 단조성이 있는지가 top-30보다 신뢰도 높은 질문이다.
팩터 조합(품질+가치, 그린블라트 정신 — "싸고 좋은 기업")도 하나 추가로 본다.

패널은 기존 precheck가 만든 것 재사용(valuation-panel.jsonl, quality-panel.
jsonl) — 새 조인·PIT 로직 없음. IC는 scipy 없이 순위의 피어슨 상관(=스피어만
상관과 동치)으로 계산한다.

  python t3_factor_decile_check.py
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
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
QUALITY_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                              "2026-08-21-buffett-quality-precheck", "quality-panel.jsonl")
START = "2016-01-01"
END = "2026-08-14"
COST_RT_BPS = 30.0
N_DECILES = 10


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_panel(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))
    return pd.DataFrame(rows)


def build_month_rows(bars_by_ticker, rebalance_dates):
    """(ticker, entry_date) -> ret, turnover20. 팩터 없이 가격만."""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
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
            if pd.isna(tv):
                continue
            rows.append({"ticker": ticker, "entry_date": t,
                         "ret": exit_price / entry_price - 1, "turnover20": float(tv)})
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    """순위의 피어슨 상관 = 스피어만 상관(scipy 불필요)."""
    if len(factor_vals) < 5:
        return None
    fr = pd.Series(factor_vals).rank()
    rr = pd.Series(fwd_rets).rank()
    return float(np.corrcoef(fr, rr)[0, 1])


def decile_analysis(merged, factor_col, ascending_is_good, cost_bps=COST_RT_BPS, label=""):
    """T3 제한(호출부에서 이미 적용됨) 안에서 매달 factor_col로 decile을 나누고
    decile별 평균 수익률(비용 반영)·월별 IC를 모은다."""
    months = sorted(merged["entry_date"].unique())
    decile_rets = {d: [] for d in range(1, N_DECILES + 1)}
    monthly_ics = []
    for m in months:
        g = merged[(merged["entry_date"] == m) & merged[factor_col].notna()]
        if len(g) < N_DECILES * 3:  # decile당 최소 3종목 못 채우면 그 달은 건너뜀
            continue
        # decile 1 = "좋다"고 믿는 쪽(ascending_is_good=True면 낮은 값이 decile1)
        ranks = g[factor_col].rank(ascending=ascending_is_good, method="first")
        deciles = pd.qcut(ranks, N_DECILES, labels=False, duplicates="drop") + 1
        for d in range(1, deciles.max() + 1 if len(deciles) else 1):
            sel = g.loc[deciles == d, "ret"]
            if len(sel):
                decile_rets[d].append(float(sel.mean()) - cost_bps / 1e4)
        # IC: factor를 "좋은 방향이 큰 값"으로 통일해서 forward return과 상관
        signed_factor = g[factor_col] if not ascending_is_good else -g[factor_col]
        ic = rank_ic(signed_factor.values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    decile_avg = {d: (round(float(np.mean(v)), 4) if v else None) for d, v in decile_rets.items()}
    top_bottom_spread = None
    if decile_avg.get(1) is not None and decile_avg.get(N_DECILES) is not None:
        top_bottom_spread = round(decile_avg[1] - decile_avg[N_DECILES], 4)
    ic_mean = round(float(np.mean(monthly_ics)), 4) if monthly_ics else None
    ic_tstat = (round(ic_mean / (np.std(monthly_ics) / np.sqrt(len(monthly_ics))), 2)
                if monthly_ics and np.std(monthly_ics) > 0 else None)
    return {
        "label": label, "monthsUsed": len(monthly_ics),
        "decileAvgMonthlyReturn": decile_avg, "topDecileMinusBottomDecile": top_bottom_spread,
        "meanMonthlyIC": ic_mean, "icTstat": ic_tstat,
    }


def main():
    val = load_panel(VALUATION_PANEL)
    val = val.dropna(subset=["per", "epsGrowthRate"])
    val = val[(val["per"] > 0) & (val["epsGrowthRate"] > 0)]
    val["peg"] = val["per"] / val["epsGrowthRate"]
    val = val[["ticker", "asOf", "pbr", "peg"]]

    qual = load_panel(QUALITY_PANEL)[["ticker", "asOf", "roe"]]

    factors = val.merge(qual, on=["ticker", "asOf"], how="outer")
    print(f"factor rows: {len(factors)} (pbr={factors['pbr'].notna().sum()}, "
          f"peg={factors['peg'].notna().sum()}, roe={factors['roe'].notna().sum()})")

    # 그린블라트 정신 조합: 같은 달 안에서 -peg 백분위 + roe 백분위 (둘 다 있는 종목만)
    def add_composite(df):
        out = []
        for m, g in df.groupby("asOf"):
            both = g.dropna(subset=["peg", "roe"])
            if len(both) < N_DECILES * 3:
                continue
            pr = (-both["peg"]).rank(pct=True)
            rr = both["roe"].rank(pct=True)
            comp = (pr + rr) / 2
            out.append(pd.DataFrame({"ticker": both["ticker"], "asOf": m, "composite": comp}))
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["ticker", "asOf", "composite"])

    composite = add_composite(factors)
    factors = factors.merge(composite, on=["ticker", "asOf"], how="left")

    tickers = sorted(set(factors["ticker"]))
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    t0 = time.time()
    bars_raw = a2a.load(tickers, START, END, universe_hash="t3-factor-decile-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    month_rows = build_month_rows(bars_by_ticker, rebalance_dates)
    print(f"month_rows={len(month_rows)}")

    merged = month_rows.merge(factors, left_on=["ticker", "entry_date"],
                               right_on=["ticker", "asOf"], how="inner")

    # T3(유동성 상위 tercile) 제한 — 그 달 가격 데이터가 있는 전체 종목 기준
    # (기존 lynch/buffett precheck와 같은 basis: 팩터 유효 여부와 무관하게
    # 가격이 있는 전체 유니버스에서 tercile 경계를 정한다)
    def restrict_to_t3(df, month_rows_all):
        parts = []
        for m, g_all in month_rows_all.groupby("entry_date"):
            q1, q2 = g_all["turnover20"].quantile([1 / 3, 2 / 3])
            t3_tickers = set(g_all.loc[g_all["turnover20"] >= q2, "ticker"])
            sub = df[(df["entry_date"] == m) & (df["ticker"].isin(t3_tickers))]
            if len(sub):
                parts.append(sub)
        return pd.concat(parts, ignore_index=True) if parts else df.iloc[0:0]

    t3 = restrict_to_t3(merged, month_rows)
    print(f"T3-restricted rows={len(t3)}")

    results = {
        "pbr_lowIsGood": decile_analysis(t3, "pbr", ascending_is_good=True, label="저PBR"),
        "peg_lowIsGood": decile_analysis(t3, "peg", ascending_is_good=True, label="저PEG"),
        "roe_highIsGood": decile_analysis(t3, "roe", ascending_is_good=False, label="고ROE"),
        "composite_pegRoe_highIsGood": decile_analysis(t3, "composite", ascending_is_good=False,
                                                          label="저PEG+고ROE 조합(그린블라트 정신)"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-t3-factor-decile-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "t3-decile-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "A안 - T3(대형주/고유동성) 전용 정밀 재검토. top-30 하드컷 대신 "
                       "decile 스프레드+IC로 단조성 확인. 세션인수인계-2026-08-21-c.md 참고.",
            "period": f"{START} ~ {END}", "nDeciles": N_DECILES, "costBps": COST_RT_BPS,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
