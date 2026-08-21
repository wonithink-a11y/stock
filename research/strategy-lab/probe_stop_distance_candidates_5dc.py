#!/usr/bin/env python
"""5DC-v1A-P / TREND-BREAKOUT-v1 공유 리스크 계약 결함(docs/control/세션인수인계-
2026-08-16.md §6) — 후보 stop_distance 공식들을 5DC-v1A-P 자체 데이터(A1A_ONLY,
2026-08-14 동결 baseline과 동일 universe/기간)로 재시뮬레이션해 same-bar STOP
집중도와 집계 지표가 후보별로 어떻게 달라지는지 잰다.

RESEARCH ONLY. engine/*, strategies/*/policy.json, rule.py 전부 미변경 —
risk_spec_for()를 이 스크립트 안에서만 오버라이드한다. data/backfill/에 아무것도
안 쓴다. 저장은 research/strategy-lab/reports/에만 한다.

  python probe_stop_distance_candidates_5dc.py

후보:
  C0_ORIGINAL_2xATR   현재 계약 그대로 (sanity check — 동결 baseline과 일치해야 함)
  C1_2p5xATR          배수만 2.0 -> 2.5로 키움 (동적 사이징 유지)
  C2_3xATR            배수만 2.0 -> 3.0
  C3_FIXED_MEDIAN     stop_distance/entry의 (이 실행 자체에서 관측한) 중앙값으로 고정
  C4_CAP_P75          2xATR 유지하되 stop_distance/entry를 75백분위에서 상한
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.fastBars import FastBars  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.execution.executor import CostModel, build_order, simulate_trade  # noqa: E402
from engine.metrics.metrics import cagr, max_drawdown, sharpe, trade_stats  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.runner import load_strategy  # noqa: E402


def _drop_suspension_rows(bars):
    return bars[~((bars["open"] == 0) & (bars["high"] == 0) & (bars["low"] == 0))]


def _schedule_portfolio(resolved, portfolio, portfolio_cfg):
    """run_5dc_v1a_p_merged.py의 _schedule_portfolio와 동일(같은 same-bar 계약)."""
    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)
    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    for date in event_dates:
        exits_today, same_bar_candidates = [], []
        for item in by_exit_date.get(date, []):
            _, order, _, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)
        if same_bar_candidates:
            admitted = [(sym, ex, portfolio.open_positions[sym]["shares"])
                        for sym, ex in same_bar_candidates if sym in portfolio.open_positions]
            if admitted:
                portfolio.process_day(date, admitted, [])


def run_one_candidate(name, stop_distance_fn, repo_root, start, end, rule, universe,
                       bars_by_ticker, calendar):
    """stop_distance_fn(row, atr_t) -> stop_distance. 신호 생성까지는 후보와
    무관해 매번 다시 계산하지만(코드 단순성 우선, 신호 자체는 몇 초 내), 비싼
    bar 로딩은 호출부에서 한 번만 한다."""
    params = rule.PARAMS
    cost_model = CostModel(
        entry_cost_bps=params["cost"]["entryCostBps"],
        exit_cost_bps=params["cost"]["exitCostBps"],
        slippage_bps=params["cost"]["slippageBps"],
    )
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"],
    )
    portfolio = Portfolio(portfolio_cfg)

    all_signals = []
    features_by_ticker, fast_bars_by_ticker = {}, {}
    for symbol, bars in bars_by_ticker.items():
        try:
            features = rule.compute_features(bars)
        except Exception:
            continue
        features_by_ticker[symbol] = features
        fast_bars_by_ticker[symbol] = FastBars(bars)
        for sig in rule.generate_signals(symbol, features):
            all_signals.append(sig)

    resolved = []
    exit_type_counts = Counter()
    for sig in all_signals:
        features = features_by_ticker[sig.symbol]
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index:
            continue
        row = features.loc[ts]
        if pd.isna(row["atr"]):
            continue
        atr_t = float(row["atr"])
        stop_distance = stop_distance_fn(row, atr_t)
        risk_spec = type(rule.risk_spec_for(row))(
            stop_distance=stop_distance, reward_risk=params["risk"]["rewardRisk"],
            max_holding_sessions=params["risk"]["maxHoldingSessions"])
        order = build_order(sig, risk_spec, calendar)
        if order is None:
            continue
        fast_bars = fast_bars_by_ticker[sig.symbol]
        if order.order_date not in fast_bars.index:
            continue
        try:
            result = simulate_trade(order, fast_bars, calendar, cost_model)
        except Exception:
            continue
        if result is None:
            continue
        entry_fill, exit_fill = result
        exit_type_counts[exit_fill.fill_type] += 1
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec, atr_t))

    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit, deduped = {}, []
    for item in resolved:
        _, order, _, exit_fill, _, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date <= last_exit:
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped

    _schedule_portfolio(resolved, portfolio, portfolio_cfg)

    from datetime import date as _date

    def _to_ordinal(date_str):
        y, m, d = map(int, date_str[:10].split("-"))
        return _date(y, m, d).toordinal()

    trades = []
    for p in portfolio.closed_positions:
        entry, exit_ = p["entry"], p["exit"]
        trades.append({
            "symbol": p["symbol"], "pnl": p["pnl"], "entry_date": p["entry_date"],
            "exit_date": exit_.fill_date, "exit_type": exit_.fill_type,
            "holding_sessions": _to_ordinal(exit_.fill_date) - _to_ordinal(p["entry_date"]),
            "stop_distance": next((r[4].stop_distance for r in resolved
                                    if r[1].symbol == p["symbol"] and r[1].order_date == p["entry_date"]), None),
            "entry_price": entry.fill_price,
        })

    same_bar = [t for t in trades if t["entry_date"] == t["exit_date"]]
    curve, eq = [], portfolio.config.initial_capital
    for d, pnl in sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions):
        eq += pnl
        curve.append((d, eq))
    t_stats = trade_stats(trades)

    def _range_over_stop_ratio(subset):
        # 청산일 실현 변동폭 대신 stop_distance/entry_price 자체의 분포를 본다
        # (§6의 "변동폭/스톱폭 비율"과 근사 — realized range는 fast_bars 재조회가
        # 필요해 비싸다. entry_price 대비 stop_distance 비율이 후보 비교엔 충분).
        vals = [t["stop_distance"] / t["entry_price"] for t in subset
                if t["stop_distance"] and t["entry_price"]]
        if not vals:
            return None
        vals.sort()
        return vals[len(vals) // 2]

    return {
        "candidate": name,
        "signalCount": len(all_signals),
        "closedTradeCount": len(trades),
        "exitTypeCounts": dict(exit_type_counts),
        "sameBarTradeCount": len(same_bar),
        "sameBarShare": round(len(same_bar) / len(trades), 4) if trades else None,
        "medianStopOverEntry_allTrades": _range_over_stop_ratio(trades),
        "medianStopOverEntry_sameBarOnly": _range_over_stop_ratio(same_bar),
        "cagr": cagr(curve) if curve else None,
        "mdd": max_drawdown(curve) if curve else None,
        "sharpe": sharpe(curve) if curve else None,
        "finalEquity": eq if curve else None,
        "tradeCount": t_stats.get("tradeCount"),
        "winRate": t_stats.get("winRate"),
        "profitFactor": t_stats.get("profitFactor"),
        "avgHoldingPeriod": t_stats.get("avgHoldingPeriod"),
    }


def main():
    start, end = "2014-05-13", "2026-08-03"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    rule = load_strategy("5dc_v1a_p", repo_root)
    universe = UniverseProvider(repo_root=repo_root, include_delisted=False)
    calendar = TradingCalendar(repo_root=repo_root)

    t0 = time.time()
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    tickers = {e.ticker for e in universe.entries if e.source == "A1A"}
    bars_raw = a2a.load(tickers, start, end, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s, cache={'hit' if time.time()-t0 < 60 else 'miss/slow'})")

    # C3/C4는 baseline(C0) 결과에서 관측한 실제 분포를 써야 "이 데이터 기준"이라는
    # 뜻이 산다 - 임의 상수(TREND-BREAKOUT-v1의 7.62%)를 재사용하지 않는다.
    baseline = run_one_candidate(
        "C0_ORIGINAL_2xATR", lambda row, atr_t: 2.0 * atr_t,
        repo_root, start, end, rule, universe, bars_by_ticker, calendar)
    print(json.dumps(baseline, indent=2, default=str))

    # baseline 재시뮬레이션 안의 stop_distance/entry 분포에서 median·p75를 다시 구한다
    # (run_one_candidate가 median만 반환하므로 별도로 한 번 더 계산).
    all_signals_probe = []
    for symbol, bars in bars_by_ticker.items():
        try:
            features = rule.compute_features(bars)
        except Exception:
            continue
        for sig in rule.generate_signals(symbol, features):
            ts = pd.Timestamp(sig.signal_date)
            if ts in features.index and not pd.isna(features.loc[ts, "atr"]):
                all_signals_probe.append(2.0 * float(features.loc[ts, "atr"]) / features.loc[ts, "close"])
    all_signals_probe.sort()
    median_pct = all_signals_probe[len(all_signals_probe) // 2] if all_signals_probe else 0.05
    p75_pct = all_signals_probe[int(len(all_signals_probe) * 0.75)] if all_signals_probe else 0.08

    candidates = {
        "C1_2p5xATR": lambda row, atr_t: 2.5 * atr_t,
        "C2_3xATR": lambda row, atr_t: 3.0 * atr_t,
        "C3_FIXED_MEDIAN": lambda row, atr_t: median_pct * row["close"],
        "C4_CAP_P75": lambda row, atr_t: min(2.0 * atr_t, p75_pct * row["close"]),
    }

    results = [baseline]
    for name, fn in candidates.items():
        r = run_one_candidate(name, fn, repo_root, start, end, rule, universe, bars_by_ticker, calendar)
        print(json.dumps(r, indent=2, default=str))
        results.append(r)

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports",
                            "2026-08-21-risk-contract-fix-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "stop_distance_candidates_5dc.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "docs/control/세션인수인계-2026-08-16.md §6 리스크 계약 결함 — 후보 재시뮬레이션",
            "universeMode": "A1A_ONLY", "period": f"{start} ~ {end}",
            "derivedParams": {"median_pct_ownData": median_pct, "p75_pct_ownData": p75_pct},
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
