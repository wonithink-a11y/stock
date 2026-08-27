#!/usr/bin/env python
"""DD252(skip-1m) Arm A — Baseline full backtest (Gross → Net 30bps) + BM1.

수정된(교차-cohort 슬롯 캡 적용) strategies/dd252_v1_cohort/selection.json을
그대로 쓴다 - MERGED 패널·6-cohort/120세션·top-30, 설계 그대로(findings/
dd252-strategy-design-2026-08.md §10 1~2단계: Gross → Net). run_smoke()는
비용을 rule.PARAMS["cost"]에서 읽으므로, policy.json을 두 번 고쳐 쓰는 대신
인메모리로 cost만 오버라이드한 rule_module 두 벌(gross=0bps, net=30bps)을
만들어 run_smoke()를 각각 한 번씩 호출한다(pbr paramsweep류와 동일 패턴) -
같은 selection·같은 체결타이밍, cost만 다르다.

BM1(§9): "자격 유니버스(같은 필터) 전체 동일가중 월 mtm" - DD252 Arm A의
자격(MERGED, 히스토리>=273세션, dd_252_skip1m 유효, 유동성 필터 없음) 전체를
매달 동일가중·월간 리밸런스로 담는 벤치마크. gross만 계산(벤치마크는 비용
가정을 안 지운다 - §9 "핵심 판정은 전략-BM1 순액 기준"). run_smoke()가 이미
로드한 MERGED bars를 재사용해 추가 I/O 없이 계산.

production 변경 없음, 커밋 없음(사용자 지시) - 결과만 보고.

  python run_dd252_cohort_full_backtest.py
"""
import copy
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import _month_end_dates, curve_metrics, annual_returns_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
DD252_DIR = os.path.join(STRATEGY_LAB_DIR, "strategies", "dd252_v1_cohort")
START, END = "2016-01-01", "2026-08-14"
N_COHORTS = 6
TOTAL_CAPITAL = 100_000_000.0
COHORT_CAPITAL = TOTAL_CAPITAL / N_COHORTS
MAX_POSITIONS_PER_COHORT = 30
MIN_HISTORY = 273
COST_VARIANTS = [("gross", 0.0, 0.0), ("net30bps", 15.0, 15.0)]


def make_rule_module(params, selection_by_ticker):
    hold_col = "dd252HoldSessions"
    fallback_max_holding = params["risk"]["maxHoldingSessions"]
    reward_risk = params["risk"]["rewardRisk"]
    stop_multiple = 100.0
    selection = {t: {e["date"]: e["holdSessions"] for e in entries}
                 for t, entries in selection_by_ticker.items()}

    def compute_features(bars):
        features = bars.copy()
        features[hold_col] = float("nan")
        return features

    def generate_signals(symbol, features):
        from engine.signals.schema import Signal
        dates = selection.get(symbol, {})
        out = []
        for d, hold_sessions in dates.items():
            ts = pd.Timestamp(d)
            if ts in features.index:
                features.loc[ts, hold_col] = hold_sessions
                out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
        return out

    def risk_spec_for(features_row):
        from engine.signals.schema import RiskSpec
        close = float(features_row["close"])
        huge_stop_distance = close * stop_multiple
        hold = features_row.get(hold_col)
        max_holding = int(hold) if hold is not None and not pd.isna(hold) else fallback_max_holding
        return RiskSpec(stop_distance=huge_stop_distance, reward_risk=reward_risk,
                         max_holding_sessions=max_holding)

    return types.SimpleNamespace(
        PARAMS=params, compute_features=compute_features,
        generate_signals=generate_signals, risk_spec_for=risk_spec_for)


def schedule_cohort(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end):
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
    trade_log = []  # (date, "buy"/"sell", dollarAmount)

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

        pre_open = set(portfolio.open_positions.keys())
        portfolio.process_day(date, exits_today, candidates_today)
        for sym, exit_fill, shares in exits_today:
            trade_log.append((date, "sell", exit_fill.fill_price * shares))
        for sym in portfolio.open_positions:
            if sym not in pre_open:
                pos = portfolio.open_positions[sym]
                trade_log.append((date, "buy", pos["cost_basis"]))

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])
                for sym, exit_fill, shares in same_bar_exits_admitted:
                    trade_log.append((date, "sell", exit_fill.fill_price * shares))

        if date in month_ends:
            closes_today = {}
            for sym in portfolio.open_positions:
                c = close_lookup.get(sym, {}).get(date)
                if c is not None:
                    closes_today[sym] = c
            snapshots.append((date, portfolio.equity(closes_today)))

    return portfolio, snapshots, trade_log


def run_dd252_variant(selection_by_ticker, entry_bps, exit_bps, cohort_lookup, base_params):
    params = copy.deepcopy(base_params)
    params["cost"]["entryCostBps"] = entry_bps
    params["cost"]["exitCostBps"] = exit_bps
    params["cost"]["roundTripBps"] = entry_bps + exit_bps
    rule = make_rule_module(params, selection_by_ticker)

    t0 = time.time()
    base = run_smoke("dd252_v1_cohort_backtest", START, END, REPO_ROOT, rule_module=rule)
    resolved, bars_by_ticker, calendar = base["resolved"], base["bars_by_ticker"], base["calendar"]
    print(f"  run_smoke (entry={entry_bps}bps): resolved={len(resolved)} ({time.time()-t0:.0f}s)")

    resolved_by_cohort = {c: [] for c in range(N_COHORTS)}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        c = cohort_lookup.get((order.symbol, order.signal_date))
        if c is not None:
            resolved_by_cohort[c].append(item)

    portfolio_cfg = PortfolioConfig(initial_capital=COHORT_CAPITAL, max_positions=MAX_POSITIONS_PER_COHORT,
                                     equal_weight=True, fractional_shares=False, tie_break="ticker_ascending")

    cohort_snapshots, all_trade_logs, closed_total = {}, [], 0
    for c in range(N_COHORTS):
        portfolio, snapshots, trade_log = schedule_cohort(
            resolved_by_cohort[c], portfolio_cfg, bars_by_ticker, calendar, START, END)
        cohort_snapshots[c] = snapshots
        all_trade_logs.extend(trade_log)
        closed_total += len(portfolio.closed_positions)

    n_snap = min(len(cohort_snapshots[c]) for c in range(N_COHORTS))
    combined = []
    for i in range(n_snap):
        d = cohort_snapshots[0][i][0]
        total_eq = sum(cohort_snapshots[c][i][1] for c in range(N_COHORTS))
        combined.append((d, total_eq))

    metrics = curve_metrics(combined)
    ann = annual_returns_mtm(combined)

    # 월별 회전율(1-way): 그 달 매수액 합 / 그 시점 총자본
    equity_by_date = {d: e for d, e in combined}
    monthly_buy = {}
    for d, side, amt in all_trade_logs:
        if side == "buy":
            ym = d[:7]
            monthly_buy[ym] = monthly_buy.get(ym, 0.0) + amt
    turnovers = []
    for d, e in combined:
        ym = d[:7]
        if ym in monthly_buy and e > 0:
            turnovers.append(monthly_buy[ym] / e)
    avg_monthly_turnover = float(np.mean(turnovers)) if turnovers else None

    return {"resultTable": metrics, "annualReturns": ann, "closedPositionCount": closed_total,
            "avgMonthlyTurnoverOneWay": round(avg_monthly_turnover, 4) if avg_monthly_turnover else None,
            "monthsWithTrades": len(turnovers)}, bars_by_ticker, calendar


def build_bm1(bars_by_ticker, calendar, min_history=MIN_HISTORY):
    """BM1: DD252 Arm A와 같은 자격 유니버스(히스토리>=273, dd 유효) 전체를
    매달 동일가중·월간 리밸런스로 담는 gross EW 벤치마크."""
    def monthly_rebalance_dates(calendar, start, end):
        days = calendar.sessions_between(start, end)
        out, seen = [], set()
        for d in days:
            ym = d[:7]
            if ym not in seen:
                seen.add(ym)
                out.append(d)
        return out

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    monthly_returns = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < min_history:
            continue
        close, open_ = bars["close"], bars["open"]
        idx = close.index.astype(str)
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or pd.isna(dd.iloc[i]):
                continue
            entry_i = i + 1
            next_t = rebalance_dates[k + 1]
            j = pos.get(next_t)
            if entry_i >= len(idx) or j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[entry_i]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            monthly_returns.setdefault(t, []).append(exit_price / entry_price - 1.0)

    snapshots = [(START, TOTAL_CAPITAL)]
    equity = TOTAL_CAPITAL
    for k, t in enumerate(rebalance_dates[:-1]):
        rets = monthly_returns.get(t)
        if not rets:
            continue
        equity *= (1.0 + float(np.mean(rets)))
        snapshots.append((rebalance_dates[k + 1], equity))

    metrics = curve_metrics(snapshots)
    ann = annual_returns_mtm(snapshots)
    return {"resultTable": metrics, "annualReturns": ann,
            "monthsUsed": len(monthly_returns), "avgNamesPerMonth":
            round(float(np.mean([len(v) for v in monthly_returns.values()])), 1) if monthly_returns else None}


def main():
    t0 = time.time()
    with open(os.path.join(DD252_DIR, "policy.json"), encoding="utf-8") as f:
        base_params = json.load(f)
    with open(os.path.join(DD252_DIR, "selection.json"), encoding="utf-8") as f:
        sel_data = json.load(f)
    selection_by_ticker = sel_data["selection"]
    cohort_lookup = {}
    for ticker, entries in selection_by_ticker.items():
        for e in entries:
            cohort_lookup[(ticker, e["date"])] = e["cohort"]
    print(f"selection: {sel_data['tickersEverSelected']} tickers, {sel_data['rebalanceMonths']} months")

    results = {}
    bars_by_ticker_ref, calendar_ref = None, None
    for label, entry_bps, exit_bps in COST_VARIANTS:
        print(f"\n=== {label} (entry={entry_bps}bps, exit={exit_bps}bps) ===")
        res, bars_by_ticker, calendar = run_dd252_variant(
            selection_by_ticker, entry_bps, exit_bps, cohort_lookup, base_params)
        results[label] = res
        bars_by_ticker_ref, calendar_ref = bars_by_ticker, calendar
        m = res["resultTable"]
        print(f"  CAGR={m['cagr']:.4f} MDD={m['mdd']:.4f} Sharpe={m['sharpe']} "
              f"turnover(1-way,monthly avg)={res['avgMonthlyTurnoverOneWay']} ({time.time()-t0:.0f}s)")

    print("\n=== BM1 (EW, same eligible universe, gross) ===")
    bm1 = build_bm1(bars_by_ticker_ref, calendar_ref)
    m = bm1["resultTable"]
    print(f"  CAGR={m['cagr']:.4f} MDD={m['mdd']:.4f} Sharpe={m['sharpe']} "
          f"avgNames/month={bm1['avgNamesPerMonth']} ({time.time()-t0:.0f}s)")

    gross_cagr, net_cagr = results["gross"]["resultTable"]["cagr"], results["net30bps"]["resultTable"]["cagr"]
    bm1_cagr = bm1["resultTable"]["cagr"]
    comparison = {
        "costDragCagr_grossMinusNet": round(gross_cagr - net_cagr, 4),
        "cagrGapVsBM1_gross": round(gross_cagr - bm1_cagr, 4),
        "cagrGapVsBM1_net": round(net_cagr - bm1_cagr, 4),
    }
    print("\n", json.dumps(comparison, indent=2))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-27-dd252-arm-a-full-backtest")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dd252-arm-a-full-backtest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "DD252 Arm A(baseline) full backtest, Gross->Net(30bps), vs BM1(EW same "
                       "eligible universe, gross). findings/dd252-strategy-design-2026-08.md §10. "
                       "cross-cohort slot-cap fix applied (사용자 지시 2026-08-27). "
                       "production 변경·커밋 없음.",
            "period": f"{START} ~ {END}", "totalCapital": TOTAL_CAPITAL, "nCohorts": N_COHORTS,
            "dd252": results, "bm1": bm1, "comparison": comparison,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
