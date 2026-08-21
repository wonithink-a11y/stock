#!/usr/bin/env python
"""LOWMOM60(60D 저모멘텀) 알파가 '기관 수급 신호가 유효한' 대형주(거래대금
상위 tercile, T3)에서도 살아남는지 사전 점검.

배경(2026-08-21, 사용자 승인 "①부터 진행해줘"): ChatGPT가 제안한 신규 후보
A/B/C(저모멘텀 + 기관/외국인 20D 순매수 + 유동성 필터)는 전부 저모멘텀을
기반으로 한다. 그런데 그 저모멘텀 신호는 이미 LOWMOM60이라는 이름으로
검증됐고(reports/2026-08-18-strategy-candidates/README.md §5.1)
"저가주(5,000원 미만) 의존 - minPrice≥5,000에서 -5.8%로 역전"이라는 결론이
나 있다. A4 연구(data/a4/A4-RESEARCH-HANDOFF.md §4)는 별개로 "기관·외국인
수급 신호는 거래대금 상위 tercile(T3, 대형주)에서만 유효"라고 밝힌다 - 즉
후보 A/B가 기관 수급 필터를 넣는 순간 사실상 대형주로 좁혀지는데, 이게
LOWMOM60의 알파를 이미 죽인 것과 같은 종류의 필터일 수 있다.

이 스크립트는 그 질문 하나만 잰다: **매달 거래대금 상위 tercile(T3) 안에서만
LOWMOM60을 골라도 알파가 남는가?** lowmom60_robustness.py의 패널 구성·백테스트
로직을 그대로 재사용한다(절대 임계값 필터 대신 매달 상대적 tercile 필터로만
바꿈) - 새 계약·새 엔진 없음, engine/ 미변경, data/backfill/ 미변경.

  python lowmom60_institutional_eligible_precheck.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def build_panel(bars_by_ticker, rebalance_dates):
    """lowmom60_robustness.py의 패널 구성과 동일 - mom60·turnover20·진출입가."""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        mom60 = close / close.shift(60) - 1
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            m = mom60.iloc[i]
            if pd.isna(m):
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
                "ticker": ticker, "entry_date": t, "mom60": float(m),
                "ret": exit_price / entry_price - 1,
                "turnover20": float(tv) if not pd.isna(tv) else 0.0,
            })
    return pd.DataFrame(rows)


def run_backtest(df, top_n=TOP_N, cost_bps=COST_RT_BPS, tercile_filter=None):
    """tercile_filter: None(무필터) | 'T3'(그 달 거래대금 상위 1/3만 후보로) |
    'T1'(하위 1/3, 대조군 - 소형주에서 알파가 몰려있다는 걸 다시 확인하는 용도)."""
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
        g = g.sort_values("mom60").head(top_n)
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
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)

    t0 = time.time()
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    df = build_panel(bars_by_ticker, rebalance_dates)
    print(f"panel rows={len(df)}")

    results = {
        "baseline_no_filter": run_backtest(df, tercile_filter=None),
        "T3_top_liquidity_tercile": run_backtest(df, tercile_filter="T3"),
        "T1_bottom_liquidity_tercile_control": run_backtest(df, tercile_filter="T1"),
    }
    for name, r in results.items():
        print(name, "->", json.dumps(r, ensure_ascii=False))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-21-chatgpt-momentum-supplydemand-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "lowmom60_institutional_eligible_precheck.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "ChatGPT 제안 후보 A/B/C(저모멘텀+기관수급) 착수 전 사전 점검 - "
                       "저모멘텀 알파가 기관수급 유효 구간(거래대금 상위 tercile)에서도 "
                       "남는지. lowmom60_robustness.py 패널·백테스트 로직 재사용, "
                       "절대임계 대신 매달 상대 tercile 필터로 변경.",
            "period": f"{START} ~ {END}", "topN": TOP_N, "costBps": COST_RT_BPS,
            "referenceBaseline_2026_08_18_report": {
                "cagr": 0.221, "totalReturn": 8.00, "note": "reports/2026-08-18-strategy-candidates/README.md §4 원 수치(2016-01-01~2026-08-14 근접 기간) - 재현 목적 아님, 규모감 비교용"
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
