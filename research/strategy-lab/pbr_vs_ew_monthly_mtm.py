#!/usr/bin/env python
"""PBR(top-30) vs EW(전체 적격종목) - 월별 시가평가(mark-to-market)로 CAGR·
MDD·Sharpe·연도별 수익률 재계산. pbr_vs_ew_same_engine.py가 쓴 실현손익
누적방식은 연속보유 병합 때문에 장기 보유 포지션의 손익이 마지막 청산일이
속한 해에 몰리는 왜곡이 있었다(2026-08-22 발견, EW 2026년 +53% 착시 - 실은
2016년부터 청산 없이 이어진 포지션들의 10년치 손익이 데이터 구간 끝에서
한꺼번에 실현된 것). 이 스크립트는 그 문제를 원천적으로 피한다 - 매월 말
실제 보유 중인 포지션을 그 시점 종가로 평가해 곡선을 만든다.

engine/runner.py의 _schedule_portfolio()를 수정 없이 그대로 복제해(로직 동일,
same-bar 재시도까지 포함) 월말 스냅샷만 추가했다 - run_smoke()가 이미 계산한
resolved(연속보유 병합 완료)를 재사용하므로 신호 재계산 없음, 스케줄링만
재실행. 두 전략 다 같은 방식으로 계산해 비교 자체가 공정하다. 기존 engine/
policy 파일은 미변경 - 진단 스크립트와 report만 신규 생성.

  python pbr_vs_ew_monthly_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"


def _build_close_lookup(bars_by_ticker):
    lookup = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        idx = bars.index.astype(str)
        lookup[ticker] = dict(zip(idx, bars["close"].values))
    return lookup


def _month_end_dates(calendar, start, end):
    sessions = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in reversed(sessions):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return sorted(out)


def schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end,
                              weight_fn=None):
    """Verbatim copy of engine/runner.py's _schedule_portfolio() day-loop
    (same-bar retry included, unmodified logic) with one addition: at each
    month-end trading date, snapshot portfolio.equity() using that date's
    close prices for whatever is currently open - independent of when any
    position's own exit event (possibly years later, post-merge) happens to
    fall.

    weight_fn: 선택. (order, entry_fill, risk_spec, atr) -> float 를 주면 그 날
    편입되는 종목들 사이의 상대 비중으로 쓴다(engine Portfolio.process_day 의
    opt-in weights 인자를 그대로 통과시킬 뿐, 이 함수는 비중을 해석하지 않는다).
    None(기본)이면 process_day 에 None 이 그대로 가서 기존 동일가중 동작과
    바이트 단위로 같다 - 2026-09-04 균등위험 사이징 검증에서 추가."""
    portfolio = Portfolio(portfolio_cfg)
    close_lookup = _build_close_lookup(bars_by_ticker)

    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    month_ends = set(_month_end_dates(calendar, start, end))
    event_dates = sorted(set(by_entry_date) | set(by_exit_date) | month_ends)

    snapshots = [(start, portfolio_cfg.initial_capital)]  # t0 baseline before any trading

    for date in event_dates:
        exits_today, same_bar_exit_candidates = [], []
        # engine/runner.py의 2026-08-22 수정(exit_symbols_queued 가드)을 그대로
        # 이식 - 같은 종목 exit+reentry 체인이 exits_today에 중복 큐잉되면
        # process_day()가 두 번째 pop에서 KeyError를 낸다(2026-08-24,
        # trend_breakout_v1 macro regime check 중 발견). 이 복제본은 그 수정
        # 이전에 만들어져 가드가 빠져 있었다.
        exit_symbols_queued = set()
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        entries_today = by_entry_date.get(date, [])
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in entries_today]
        weights = None
        if weight_fn is not None:
            weights = {order.symbol: weight_fn(order, entry_fill, risk_spec, atr)
                       for (_, order, entry_fill, _, risk_spec, atr) in entries_today}
        portfolio.process_day(date, exits_today, candidates_today, weights=weights)

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


def curve_metrics(snapshots):
    """CAGR/MDD/Sharpe from a monthly (date, equity) MTM curve."""
    eqs = [e for _, e in snapshots]
    peak, maxdd = eqs[0], 0.0
    for e in eqs:
        peak = max(peak, e)
        maxdd = min(maxdd, e / peak - 1)
    d0, d1 = snapshots[0][0], snapshots[-1][0]
    y0, y1 = int(d0[:4]) + (int(d0[5:7]) - 1) / 12, int(d1[:4]) + (int(d1[5:7]) - 1) / 12
    n_years = max(y1 - y0, 1 / 12)
    total_return = eqs[-1] / eqs[0] - 1
    cagr = (eqs[-1] / eqs[0]) ** (1 / n_years) - 1
    monthly_rets = [eqs[i] / eqs[i - 1] - 1 for i in range(1, len(eqs))]
    mr = np.array(monthly_rets)
    sharpe = (mr.mean() / mr.std(ddof=1) * np.sqrt(12)) if len(mr) > 1 and mr.std(ddof=1) > 0 else None
    return {
        "finalEquity": round(float(eqs[-1])), "totalReturn": round(float(total_return), 4),
        "cagr": round(float(cagr), 4), "mdd": round(float(maxdd), 4),
        "sharpe": round(float(sharpe), 4) if sharpe is not None else None,
    }


def annual_returns_mtm(snapshots):
    by_year_last = {}
    for d, e in snapshots:
        by_year_last[int(d[:4])] = e
    years = sorted(by_year_last)
    prev = snapshots[0][1]
    out = {}
    for y in years:
        out[y] = round(float(by_year_last[y] / prev - 1), 4)
        prev = by_year_last[y]
    return out


def run_and_measure(strategy_id):
    t0 = time.time()
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    print(f"  {strategy_id}: {len(portfolio.closed_positions)} closed, "
          f"{len(portfolio.open_positions)} still open at end, {len(snapshots)} monthly snapshots "
          f"({time.time()-t0:.0f}s)")
    return {"resultTable": metrics, "annualReturns": ann,
            "closedPositionCount": len(portfolio.closed_positions),
            "openPositionCountAtEnd": len(portfolio.open_positions),
            "monthlySnapshotCount": len(snapshots)}


def main():
    print(f"=== PBR vs EW, monthly MTM, {START} ~ {END} ===")
    pbr = run_and_measure("pbr_value_v1")
    ew = run_and_measure("ew_benchmark_liquid_v1")
    cagr_gap = round(pbr["resultTable"]["cagr"] - ew["resultTable"]["cagr"], 4)

    result = {"period": f"{START} ~ {END}", "method": "monthly mark-to-market equity curve",
              "pbr_value_v1": pbr, "ew_benchmark_liquid_v1": ew, "pbrMinusEW_cagrGap": cagr_gap}
    print("\n", json.dumps(result, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-22-pbr-vs-ew-monthly-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-vs-ew-monthly-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR vs EW 월별 시가평가(MTM) 재계산 - pbr_vs_ew_same_engine.py의 "
                       "실현손익 누적방식이 연속보유 병합 장기포지션의 손익을 마지막 청산일이 "
                       "속한 해에 몰아 왜곡하는 문제(2026-08-22 발견, EW 2026년 +53% 착시)를 "
                       "피하기 위해 매월 말 종가로 시가평가. _schedule_portfolio() 로직은 "
                       "무수정 복제, engine/policy 파일 변경 없음.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
