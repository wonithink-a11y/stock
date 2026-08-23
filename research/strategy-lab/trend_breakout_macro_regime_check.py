#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TREND-BREAKOUT-v1 — macro regime 축별 조건부 성과 검증 (2026-08).

pbr_macro_rate_regime_check.py가 검증한 방법론(월별 수익을 "trailing 126거래일
변화"의 부호(hiking>0 / not-hiking<=0)로 분류해 평균수익·기여율을 비교)을 아직
한 번도 적용한 적 없는 Strategy Lab 전략 **trend_breakout_v1**에 그대로 적용한다
— 새 설계·임계값 결정 없음, 이미 검증된 패턴의 반복.

방법: pbr_vs_ew_monthly_mtm.py의 schedule_with_monthly_mtm()과 동일한 구성
(run_smoke()의 resolved를 그대로 받아 월말 종가 시가평가 스냅샷만 추가)으로
trend_breakout_v1의 월별 MTM 수익률을 만들고,
market_regime_features.parquet의 10개 축 전부에 trailing 126거래일 변화
(`col - col.shift(126)`, threshold >0)로 hiking/not-hiking 분류를 적용해
월평균수익·기여율·연도별 breakdown을 본다.

**day-loop는 engine/runner.py::_schedule_portfolio()의 현재 논리를 그대로
복제한다**(same-bar 재시도 + 2026-08-22 exit_symbols_queued 가드 포함).
pbr_vs_ew_monthly_mtm.py의 사본은 이 가드가 반영되기 전 버전이라 동일심볼
청산+재진입 체인이 same-bar 스탑까지 겹치는 날에 exits 큐에 같은 심볼이 두 번
들어가 process_day()에서 KeyError가 난다(trend_breakout_v1 실측, 001770).
기존 스크립트는 수정 금지이므로 이 스크립트 안에 엔진 현재 논리 기준으로
복제했다 — 원본 파일 무변경.

TRAIL_DAYS=126·>0 사전 고정(재최적화 없음), 정규화 없음, production 코드·정책
무변경, 새 회귀 없음 - 순수 진단.

  python trend_breakout_macro_regime_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import annual_returns_mtm, curve_metrics  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
STRATEGY_ID = "trend_breakout_v1"
TRAIL_DAYS = 126  # ~6개월 거래일, 사전 고정(pbr 조사와 동일, 재최적화 없음)
REGIME_PARQUET = os.path.join(REPO_ROOT, "research", "strategy-lab", "data",
                              "market-regime", "market_regime_features.parquet")


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


def schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end):
    """pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm과 동일 구성(월말 종가 MTM
    스냅샷 추가)의 day-loop 복제. 차이 한 가지: engine/runner.py::_schedule_
    portfolio()의 **현재** 논리를 따라 exit_symbols_queued 가드(2026-08-22 수정,
    runner.py docstring 참조)를 포함한다 — 동일심볼 청산+재진입 체인이 same-bar
    스탑까지 겹치는 날에 같은 심볼의 청산이 exits 큐에 두 번 들어가는 것을 막는다.
    그 외 로직·same-bar 재시도·월말 스냅샷 규칙은 원본 사본과 동일."""
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
        exit_symbols_queued = set()  # runner.py 2026-08-22 guard: symbol당 하루 1회만 큐잉
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
            # else: 슬롯을 못 얻은 체결 없는 청산 - 닫을 것이 없다(engine과 동일).
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

AXES = [
    ("usFedFundsRate", "미국 연방기금금리(6개월 변화)"),
    ("usTreasury10y", "미국 10년물 금리(6개월 변화)"),
    ("usNasdaq", "나스닥 지수(6개월 변화)"),
    ("krKospi", "KOSPI 지수(6개월 변화)"),
    ("krTreasury3y", "한국 국고채 3년물 금리(6개월 변화)"),
    ("krCorpAA3y", "한국 회사채 AA- 3년물 금리(6개월 변화)"),
    ("krCpi", "한국 CPI(6개월 변화)"),
    ("krLeadingCyclical", "한국 선행순환지수(6개월 변화)"),
    ("krCoincidentCyclical", "한국 일반순환지수(6개월 변화)"),
    ("krCreditSpreadBp", "한국 신용스프레드(bp, 6개월 변화, 확대=긴축)"),
]


def monthly_snapshots(strategy_id):
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    return snapshots


def monthly_returns(snapshots):
    dates = [d for d, _ in snapshots[1:]]  # t0 baseline row 제외
    eqs = [e for _, e in snapshots]
    rets = [eqs[i] / eqs[i - 1] - 1.0 for i in range(1, len(eqs))]
    return pd.DataFrame({"date": dates, "ret": rets})


def axis_features():
    """market_regime_features.parquet에서 10축 전부의 trailing 126거래일 변화를
    계산. pbr_macro_rate_regime_check.rate_regime_features()와 동일 패턴, 축만 확장.
    정규화·재최적화 없음 - 전 축 같은 창."""
    cols = ["date"] + [a for a, _ in AXES]
    df = pd.read_parquet(REGIME_PARQUET)[cols].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for axis, _ in AXES:
        df[axis + "Chg6m"] = df[axis] - df[axis].shift(TRAIL_DAYS)
    return df


def bucket_report(ret_df, regime_df, chg_col, label):
    """ret_df: [date, ret]. regime_df: [date, <chg_col>]. asof(backward) 조인 후
    hiking(변화>0)/not으로 나눠 합계·평균·기여율을 리포트. pbr 버전과 동일 구조."""
    left = ret_df.sort_values("date").copy()
    right = regime_df[["date", chg_col]].sort_values("date").copy()
    left["date"] = pd.to_datetime(left["date"])
    right["date"] = pd.to_datetime(right["date"])
    merged = pd.merge_asof(left, right, on="date", direction="backward")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged = merged.dropna(subset=[chg_col])
    hiking = merged[merged[chg_col] > 0]
    not_hiking = merged[merged[chg_col] <= 0]
    total_ret = merged["ret"].sum()
    hiking_ret = hiking["ret"].sum()
    return {
        "label": label,
        "months_total": int(len(merged)),
        "months_hiking": int(len(hiking)),
        "months_not_hiking": int(len(not_hiking)),
        "totalRetSum": round(float(total_ret), 5),
        "hikingRetSum": round(float(hiking_ret), 5),
        "notHikingRetSum": round(float(not_hiking["ret"].sum()), 5),
        "hikingSharePct": round(float(hiking_ret / total_ret * 100), 2) if total_ret != 0 else None,
        "hikingMeanMonthly": round(float(hiking["ret"].mean()), 5) if len(hiking) else None,
        "notHikingMeanMonthly": round(float(not_hiking["ret"].mean()), 5) if len(not_hiking) else None,
    }, merged


def year_hiking_breakdown(merged, chg_col):
    merged = merged.copy()
    merged["year"] = merged["date"].str.slice(0, 4)
    out = {}
    for y, g in merged.groupby("year"):
        out[y] = {
            "monthsHiking": int((g[chg_col] > 0).sum()),
            "monthsTotal": int(len(g)),
            "retSum": round(float(g["ret"].sum()), 5),
        }
    return out


def main():
    t0 = time.time()
    print("=== %s 월별 MTM 재현 (run_smoke + schedule_with_monthly_mtm 무변경 재사용) ===" % STRATEGY_ID)
    snapshots = monthly_snapshots(STRATEGY_ID)
    print("  스냅샷 %d개 (%.0fs)" % (len(snapshots), time.time() - t0))

    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    ret_df = monthly_returns(snapshots)
    print("  baseline ->", json.dumps(metrics, ensure_ascii=False))
    print("  월별수익 %d개월, 합계=%.4f(로그아님 단순합)" % (len(ret_df), ret_df["ret"].sum()))

    regime_df = axis_features()

    results, year_breakdowns = {}, {}
    for axis, label in AXES:
        chg_col = axis + "Chg6m"
        rep, merged = bucket_report(ret_df, regime_df, chg_col, label)
        results[chg_col] = rep
        year_breakdowns[chg_col] = year_hiking_breakdown(merged, chg_col)
        print("\n[%s]" % label)
        print("  전체 %d개월(hiking %d · not %d)"
              % (rep["months_total"], rep["months_hiking"], rep["months_not_hiking"]))
        print("  총수익합=%.4f, hiking구간 기여=%.4f(%s%%)"
              % (rep["totalRetSum"], rep["hikingRetSum"], rep["hikingSharePct"]))
        print("  hiking 월평균=%s vs not-hiking 월평균=%s"
              % (rep["hikingMeanMonthly"], rep["notHikingMeanMonthly"]))

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "context": "TREND-BREAKOUT-v1의 macro regime 축별 조건부 성과 검증 - "
                   "pbr_macro_rate_regime_check.py 방법론(trailing 126거래일 변화 부호 분류)을 "
                   "pbr_vs_ew_monthly_mtm.py의 월별 MTM 파이프라인 무변경 재사용으로 적용",
        "trailDays": TRAIL_DAYS,
        "period": [START, END],
        "strategyId": STRATEGY_ID,
        "monthlyCount": int(len(ret_df)),
        "baselineStats": metrics,
        "annualReturns": ann,
        "results": results,
        "yearBreakdown": year_breakdowns,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-24-trend-breakout-macro-regime")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "trend-breakout-macro-regime-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
