#!/usr/bin/env python
"""역변동성 가중(inverse-volatility weighting) - Ox Alpha가 제안한 엔진 개선
2건(findings/github-literature-return-enhancement-candidates-2026-08.md,
"팩터가 아니라 실행 방식 개선이라 언제든 시도 가능") 중 첫 번째. 동일비중
대신 변동성이 낮은 종목에 더 큰 비중을 주는 방식이 pbr_value_v1_combined
(dropout+MAX제외, findings/pbr-combined-paramsweep-2026-08.md)에서 개선을
주는지 확인한다.

engine/portfolio/portfolio.py의 Portfolio.process_day()에 opt-in
`weights` 인자를 추가(기본 None - 기존 동일비중/전액현금 동작 완전
불변, 회귀 전체 재확인 완료)했다 - 오늘 동일비중이 배정했을 것과 같은
총 풀(len(selected) x cash/max_positions)을 가중치 비례로 재분배할 뿐,
청산·기존 보유는 손대지 않는다. 이 스크립트는 그 인자에 60일 변동성의
역수를 넘겨 비교한다.

  python run_pbr_combined_invvol_vs_equalweight_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402
    _month_end_dates, curve_metrics, annual_returns_mtm)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
VOL_WINDOW = 60


def build_vol_lookup(bars_by_ticker, window=VOL_WINDOW):
    """ticker -> {date_str: trailing daily-return std}. 결측(창 부족)이면
    없는 채로 둔다 - 가중치 계산 쪽에서 폴백(동일가중)으로 처리."""
    lookup = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        vol = bars["close"].pct_change().rolling(window, min_periods=window // 2).std()
        idx = bars.index.astype(str)
        lookup[ticker] = dict(zip(idx, vol.values))
    return lookup


def schedule_with_invvol_weighting(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end, vol_lookup):
    """pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm()의 축자적 복제 - 유일한
    차이는 process_day() 호출에 그날 신규 진입 후보들의 역변동성 weights를
    넘기는 것뿐(같은 exit/same-bar/월말 스냅샷 로직 그대로)."""
    portfolio = Portfolio(portfolio_cfg)
    close_lookup = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        idx = bars.index.astype(str)
        close_lookup[ticker] = dict(zip(idx, bars["close"].values))

    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    month_ends = set(_month_end_dates(calendar, start, end))
    event_dates = sorted(set(by_entry_date) | set(by_exit_date) | month_ends)
    snapshots = [(start, portfolio_cfg.initial_capital)]

    def weights_for(candidates, date):
        w = {}
        for order, _ in candidates:
            v = vol_lookup.get(order.symbol, {}).get(date)
            w[order.symbol] = 1.0 / v if v and v > 0 else None
        known = [x for x in w.values() if x is not None]
        fallback = float(np.median(known)) if known else 1.0
        return {k: (v if v is not None else fallback) for k, v in w.items()}

    for date in event_dates:
        exits_today, same_bar_exit_candidates = [], []
        exit_symbols_queued = set()
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        weights_today = weights_for(candidates_today, date) if candidates_today else None
        portfolio.process_day(date, exits_today, candidates_today, weights=weights_today)

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])

        if date in month_ends:
            closes_today = {}
            for sym in portfolio.open_positions:
                c = close_lookup.get(sym, {}).get(date)
                if c is not None:
                    closes_today[sym] = c
            snapshots.append((date, portfolio.equity(closes_today)))

    return portfolio, snapshots


def run_and_measure_invvol(strategy_id):
    t0 = time.time()
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    vol_lookup = build_vol_lookup(bars_by_ticker)
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_invvol_weighting(
        resolved, portfolio_cfg, bars_by_ticker, calendar, START, END, vol_lookup)
    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    print(f"  {strategy_id}(invvol): {len(portfolio.closed_positions)} closed ({time.time()-t0:.0f}s)")
    return {"resultTable": metrics, "annualReturns": ann,
            "closedPositionCount": len(portfolio.closed_positions)}


def main():
    print(f"=== pbr_value_v1_combined: 동일비중 vs 역변동성가중, monthly MTM, {START} ~ {END} ===")
    invvol = run_and_measure_invvol("pbr_value_v1_combined")

    # 동일비중 기준값은 findings/pbr-dropout-maxexcl-combined-2026-08.md에서
    # 이미 확정된 수치(재실행 없이 재사용 - 엔진의 weights=None 기본경로는
    # 이번 세션에서 무변경임을 회귀로 확인했다).
    equal_weight_baseline = {"cagr": 0.0687, "mdd": -0.1890, "sharpe": 0.6809, "closedPositionCount": 649}

    result = {
        "period": f"{START} ~ {END}", "method": "monthly mark-to-market equity curve",
        "pbr_value_v1_combined_equalWeight_reference": equal_weight_baseline,
        "pbr_value_v1_combined_invVolWeighted": invvol,
    }
    print("\n", json.dumps(result, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-invvol-vs-equalweight-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-invvol-vs-equalweight-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "Ox Alpha 엔진개선 제안(역변동성 가중)을 combined 전략에 적용 - "
                       "portfolio.py의 opt-in weights= 인자(기본 None, 기존 동작 불변) 사용. "
                       "findings/github-literature-return-enhancement-candidates-2026-08.md 후속.",
            "volWindow": VOL_WINDOW, "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
