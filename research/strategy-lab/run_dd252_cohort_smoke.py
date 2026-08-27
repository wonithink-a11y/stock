#!/usr/bin/env python
"""DD252(skip-1m) Arm A — 6-cohort 격리 회계 SMOKE 검증.

사용자 지시(2026-08-27): "기존 run_smoke의 단순 maxHoldingSessions 방식은
사용하지 말 것 - LOWMOM60 패턴의 custom runner/cohort accounting 사용."
engine의 Portfolio는 max_positions 하나를 공유하는 단일 자금 풀이라 "6개
cohort가 각자 1/6 자금을 격리해서 쓴다"를 표현할 수 없다 - 이 스크립트는
run_smoke()를 **한 번만** 호출해 신호·체결(PIT·상장폐지 강제청산 포함)을
얻은 뒤, `resolved` 거래를 (symbol, signal_date)로 selection.json의 cohort
태그와 대조해 6그룹으로 나누고, **cohort마다 완전히 독립된 Portfolio
인스턴스**(initial_capital=총액/6, max_positions=30)로 각각 스케줄링한다.
engine/portfolio/portfolio.py는 무변경 - 이미 검증된 단일 Portfolio 클래스를
6번 별도 인스턴스화해서 쓸 뿐이다.

산출: 6개 cohort 월별 시가평가(MTM) 곡선을 합산한 전체 포트폴리오 성과 +
교차-cohort 격리·PIT·현금 회계 sanity check.

production 변경 없음, 커밋 없음(사용자 지시) - 결과만 보고.

  python run_dd252_cohort_smoke.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import _month_end_dates, curve_metrics, annual_returns_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
SELECTION_PATH = os.path.join(STRATEGY_LAB_DIR, "strategies", "dd252_v1_cohort", "selection.json")
START, END = "2016-01-01", "2026-08-14"
N_COHORTS = 6
TOTAL_CAPITAL = 100_000_000.0
COHORT_CAPITAL = TOTAL_CAPITAL / N_COHORTS
MAX_POSITIONS_PER_COHORT = 30


def load_cohort_lookup():
    with open(SELECTION_PATH, encoding="utf-8") as f:
        data = json.load(f)
    lookup = {}
    for ticker, entries in data["selection"].items():
        for e in entries:
            lookup[(ticker, e["date"])] = e["cohort"]
    return lookup, data


def schedule_cohort(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end):
    """schedule_with_monthly_mtm()의 축자적 복제(pbr_vs_ew_monthly_mtm.py) - 이
    cohort가 받은 resolved 부분집합만으로 독립 Portfolio를 굴린다."""
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
        portfolio.process_day(date, exits_today, candidates_today)

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


def session_count(calendar, entry_date, exit_date):
    return len(calendar.sessions_between(entry_date, exit_date))


def check_no_cross_cohort_overlap(resolved_by_cohort):
    """같은 종목이 서로 다른 cohort에서 동시에 보유되지 않았는지 - 선정 단계
    자체 기록이 아니라 엔진이 실제로 만든 체결(entry/exit fill)로 재검증한다."""
    by_symbol = {}
    for c, items in resolved_by_cohort.items():
        for item in items:
            _, order, entry_fill, exit_fill, _, _ = item
            by_symbol.setdefault(order.symbol, []).append((order.order_date, exit_fill.fill_date, c))
    violations = []
    for symbol, intervals in by_symbol.items():
        intervals.sort()
        for i in range(len(intervals)):
            e1, x1, c1 = intervals[i]
            for j in range(i + 1, len(intervals)):
                e2, x2, c2 = intervals[j]
                if e2 > x1:
                    break  # sorted by entry - no further overlap possible
                if c1 != c2:
                    violations.append({"symbol": symbol, "cohortA": c1, "rangeA": [e1, x1],
                                        "cohortB": c2, "rangeB": [e2, x2]})
    return violations


def main():
    t0 = time.time()
    cohort_lookup, sel_meta = load_cohort_lookup()
    print(f"selection.json: {sel_meta['tickersEverSelected']} tickers, "
          f"{sel_meta['rebalanceMonths']} months, avgSelected/mo={sel_meta['avgSelectedPerMonth']}, "
          f"crossCohortDedupSkips={sel_meta['totalCrossCohortDedupSkips']}")

    base = run_smoke("dd252_v1_cohort", START, END, REPO_ROOT)
    resolved, bars_by_ticker, calendar, diag = base["resolved"], base["bars_by_ticker"], base["calendar"], base["diag"]
    print(f"run_smoke: runClass={diag['runClass']}, universeCoverage={diag.get('universeCoverage')}, "
          f"signalCount={diag.get('signalCount')}, resolved={len(resolved)} ({time.time()-t0:.0f}s)")

    resolved_by_cohort = {c: [] for c in range(N_COHORTS)}
    unresolved = 0
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        c = cohort_lookup.get((order.symbol, order.signal_date))
        if c is None:
            unresolved += 1
            continue
        resolved_by_cohort[c].append(item)
    print(f"cohort split: {[len(resolved_by_cohort[c]) for c in range(N_COHORTS)]}, unresolved(no cohort tag)={unresolved}")

    portfolio_cfg = PortfolioConfig(initial_capital=COHORT_CAPITAL, max_positions=MAX_POSITIONS_PER_COHORT,
                                     equal_weight=True, fractional_shares=False, tie_break="ticker_ascending")

    cohort_snapshots = {}
    cohort_diag = {}
    for c in range(N_COHORTS):
        portfolio, snapshots = schedule_cohort(resolved_by_cohort[c], portfolio_cfg, bars_by_ticker, calendar, START, END)
        cohort_snapshots[c] = snapshots
        holds = [session_count(calendar, p["entry_date"], p["exit"].fill_date) for p in portfolio.closed_positions]
        cohort_diag[c] = {
            "closedPositionCount": len(portfolio.closed_positions),
            "openPositionCountAtEnd": len(portfolio.open_positions),
            "avgHoldSessions": round(sum(holds) / len(holds), 1) if holds else None,
            "minHoldSessions": min(holds) if holds else None,
            "maxHoldSessions": max(holds) if holds else None,
            "finalCash": portfolio.cash,
        }
        print(f"  cohort {c}: closed={cohort_diag[c]['closedPositionCount']} "
              f"openAtEnd={cohort_diag[c]['openPositionCountAtEnd']} "
              f"avgHold={cohort_diag[c]['avgHoldSessions']} cash={portfolio.cash:.0f} ({time.time()-t0:.0f}s)")

    n_snap = min(len(cohort_snapshots[c]) for c in range(N_COHORTS))
    combined = []
    for i in range(n_snap):
        d = cohort_snapshots[0][i][0]
        assert all(cohort_snapshots[c][i][0] == d for c in range(N_COHORTS)), \
            f"cohort snapshot dates misaligned at index {i}"
        total_eq = sum(cohort_snapshots[c][i][1] for c in range(N_COHORTS))
        combined.append((d, total_eq))

    metrics = curve_metrics(combined)
    ann = annual_returns_mtm(combined)
    print(f"\nCOMBINED (6 cohorts summed): CAGR={metrics['cagr']:.4f} MDD={metrics['mdd']:.4f} "
          f"Sharpe={metrics['sharpe']} finalEquity={metrics['finalEquity']}")

    overlap_violations = check_no_cross_cohort_overlap(resolved_by_cohort)
    print(f"\ncross-cohort overlap violations: {len(overlap_violations)}")
    if overlap_violations:
        for v in overlap_violations[:5]:
            print("  VIOLATION:", v)

    max_positions_violation = [c for c in range(N_COHORTS)
                                if cohort_diag[c]["openPositionCountAtEnd"] > MAX_POSITIONS_PER_COHORT]
    negative_cash = [c for c in range(N_COHORTS) if cohort_diag[c]["finalCash"] < 0]

    report = {
        "period": f"{START} ~ {END}", "totalCapital": TOTAL_CAPITAL, "nCohorts": N_COHORTS,
        "cohortCapitalEach": COHORT_CAPITAL, "maxPositionsPerCohort": MAX_POSITIONS_PER_COHORT,
        "runSmokeDiag": {k: diag.get(k) for k in ("runClass", "universeMode", "signalCount", "universeCoverage")},
        "selectionMeta": {k: sel_meta.get(k) for k in
                          ("rebalanceMonths", "avgSelectedPerMonth", "totalCrossCohortDedupSkips", "tickersEverSelected")},
        "resolvedUnresolvedCohortTag": unresolved,
        "perCohort": cohort_diag,
        "combined": {"resultTable": metrics, "annualReturns": ann},
        "sanityChecks": {
            "crossCohortOverlapViolations": len(overlap_violations),
            "overlapViolationExamples": overlap_violations[:10],
            "cohortsExceedingMaxPositionsAtEnd": max_positions_violation,
            "cohortsWithNegativeFinalCash": negative_cash,
        },
    }

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-27-dd252-cohort-smoke")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dd252-cohort-smoke.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "context":
                   "DD252 Arm A - 6-cohort 격리 회계 SMOKE. findings/dd252-strategy-design-2026-08.md "
                   "§10 1단계(Gross 백테스트). production 변경·커밋 없음.",
                   "report": report}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
