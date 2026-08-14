"""SMOKE-only orchestrator: universe -> price -> features -> signals -> orders ->
fills -> portfolio -> diagnostics.

This is deliberately not a general "run any config" driver yet - it loads exactly
one strategy by id and always classifies the run as SMOKE. There is no code path
that produces a PRIMARY-labeled result: A1A_ONLY is the only universe mode wired
in here, and PRIMARY requires A1A_A1B_MERGED with full A2a+A2b coverage (contract
section 11), which does not exist. Extending this once A2b lands is a config
change, not a rewrite (Phase 1 design item E).

No performance/return metrics (CAGR, Sharpe, win rate, profit factor, ...) are
computed here - that is a PRIMARY-run concern (decision 6, this phase's request).
Only pipeline diagnostics: counts, reasons, and a handful of full trade traces.
"""
import importlib.util
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.fastBars import FastBars  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.execution.executor import CostModel, build_order, simulate_trade  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402


def _drop_suspension_rows(bars):
    """Some A2a rows are the corrupted halt-artifact pattern: open=high=low=0
    while close still carries the last reference price. A row like that cannot
    be a real entry fill (open=0), and its 0 high/low injects a fake
    ~last_close-sized true-range spike into ATR (confirmed on real tickers:
    123690, 389470, 368770, 053060, 225570 - the last one spiked ATR to 9.5x
    its prior value on the halt day).

    NOTE ON SCOPE: this predicate is narrower than "volume==0". A prior version
    dropped every volume==0 row and was rejected after verification showed most
    of them (55,275 of 128,491 in the full universe) carry a flat but genuine
    OHLC quote (open==high==low==close, all nonzero) - not the corrupted
    all-zero pattern, and not shown to distort ATR. Those rows are kept; only
    the genuinely corrupted open=high=low=0 rows are dropped here.

    This is NOT a reuse of config/policies/price.v1.json's returnTransition
    rule - that rule (requireBothVolumePositive) is scoped to A2a/A2b/A5's pairwise
    return-transition calculations, keeps the row, and only excludes it from a
    specific pairwise comparison. Rolling-indicator computation (this engine) is
    not among that rule's consumers, so there is no existing predicate to reuse;
    this is a new, narrower rule for a new scenario, applied only to this
    in-memory view - it does not touch A2a's source files or its own cache.
    """
    return bars[~((bars["open"] == 0) & (bars["high"] == 0) & (bars["low"] == 0))]


def load_strategy(strategy_id, repo_root):
    path = os.path.join(repo_root, "research", "strategy-lab", "strategies", strategy_id, "rule.py")
    spec = importlib.util.spec_from_file_location(f"strategies.{strategy_id}.rule", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_smoke(strategy_id, start, end, repo_root, ticker_subset=None, trace_limit=5, rule_module=None):
    """rule_module: pass a pre-loaded module (e.g. a benchmarks/* variant that
    reuses strategies/5dc_v1a_p's compute_features/risk_spec_for/PARAMS but
    supplies its own generate_signals) to reuse this whole orchestration
    without duplicating it - execution/portfolio/cost/PIT below are untouched
    either way. When omitted, behaves exactly as before (loads strategies/<id>/rule.py)."""
    rule = rule_module if rule_module is not None else load_strategy(strategy_id, repo_root)
    params = rule.PARAMS
    assert params["universe"]["mode"] == "A1A_ONLY", "runner only wires A1A_ONLY - PRIMARY requires A2b (not built)"

    universe = UniverseProvider(repo_root=repo_root, include_delisted=False)
    tickers = universe.tickers if ticker_subset is None else (universe.tickers & set(ticker_subset))

    price_provider = A2aProvider(repo_root=repo_root, use_cache=True)
    bars_by_ticker_raw = price_provider.load(tickers, start, end, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_by_ticker_raw.items()}
    suspension_rows_dropped = sum(len(bars_by_ticker_raw[t]) - len(bars_by_ticker[t]) for t in bars_by_ticker_raw)
    calendar = TradingCalendar(repo_root=repo_root)

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

    diag = {
        "runClass": "SMOKE",
        "universeMode": universe.mode,
        "universeCoverage": universe.price_coverage_report(price_provider),
        "tickersScanned": len(bars_by_ticker),
        "suspensionRowsDropped": suspension_rows_dropped,
        "signalCount": 0,
        "invalidSignalCount": 0,
        "skippedSignalCount": 0,
        "skippedReasons": Counter(),
        "executableTradeCount": 0,
        "exitTypeCounts": Counter(),
        "executionErrorCount": 0,
        "firstSignalDate": None,
        "lastSignalDate": None,
    }

    all_signals = []
    features_by_ticker = {}
    fast_bars_by_ticker = {}  # perf only (profiled 2026-08-14, see FastBars docstring) -
    # a ticker's bars are looked up by simulate_trade repeatedly (once per signal on
    # that ticker, up to 60 lookups each) so the string-keyed dict is built once here
    # and reused, instead of every call re-parsing dates against a pandas DatetimeIndex.
    for symbol, bars in bars_by_ticker.items():
        try:
            features = rule.compute_features(bars)
        except Exception:
            diag["executionErrorCount"] += 1
            continue
        features_by_ticker[symbol] = features
        fast_bars_by_ticker[symbol] = FastBars(bars)
        for sig in rule.generate_signals(symbol, features):
            all_signals.append(sig)

    diag["signalCount"] = len(all_signals)
    if all_signals:
        all_dates = sorted(s.signal_date for s in all_signals)
        diag["firstSignalDate"], diag["lastSignalDate"] = all_dates[0], all_dates[-1]

    resolved = []  # (signal, order, entry_fill, exit_fill, risk_spec, atr_at_signal)
    for sig in all_signals:
        features = features_by_ticker[sig.symbol]
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index:
            diag["invalidSignalCount"] += 1
            continue
        row = features.loc[ts]
        if pd.isna(row["atr"]):
            diag["invalidSignalCount"] += 1
            continue

        risk_spec = rule.risk_spec_for(row)
        order = build_order(sig, risk_spec, calendar)
        if order is None:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["no_next_session"] += 1
            continue

        fast_bars = fast_bars_by_ticker[sig.symbol]
        if order.order_date not in fast_bars.index:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["no_bar_on_entry_date"] += 1
            continue

        try:
            result = simulate_trade(order, fast_bars, calendar, cost_model)
        except Exception:
            diag["executionErrorCount"] += 1
            continue

        if result is None:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["ran_out_of_bars_before_exit_resolved"] += 1
            continue

        entry_fill, exit_fill = result
        diag["executableTradeCount"] += 1
        diag["exitTypeCounts"][exit_fill.fill_type] += 1
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec, float(row["atr"])))

    # Two different signals on the same ticker can both resolve to complete
    # trades at the instrument level even while their holding windows overlap
    # (each is simulated independently against that ticker's own bars). Feeding
    # both into the portfolio schedule would leave an ambiguous exit event on
    # the overlap date - which of the two exit_fills belongs to whichever one
    # actually got admitted? So overlaps are resolved here, before scheduling:
    # per symbol, keep the earliest non-overlapping chain and drop the rest.
    # Portfolio.process_day() also refuses a second same-symbol entry as a
    # second, independent safety net - this loop is what keeps the schedule
    # itself unambiguous in the first place.
    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit = {}
    deduped = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date <= last_exit:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["overlaps_open_position_same_symbol"] += 1
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped
    diag["portfolioEligibleTradeCount"] = len(resolved)

    # drive the portfolio chronologically over only the dates where something happens
    by_entry_date = {}
    by_exit_date = {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    max_open_seen = 0
    for date in event_dates:
        exits_today = []
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:  # only if actually admitted earlier
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)
        # runtime invariant, not just a unit-test assumption: the contract caps
        # simultaneous positions at max_positions - verify it holds on every
        # single event day of the real run, not only in synthetic fixtures.
        assert len(portfolio.open_positions) <= portfolio_cfg.max_positions, (
            f"{date}: {len(portfolio.open_positions)} open positions exceeds max_positions="
            f"{portfolio_cfg.max_positions}"
        )
        max_open_seen = max(max_open_seen, len(portfolio.open_positions))

    diag["finalCash"] = portfolio.cash
    diag["closedPositionCount"] = len(portfolio.closed_positions)
    diag["openPositionCountAtEnd"] = len(portfolio.open_positions)
    diag["maxSimultaneousPositionsObserved"] = max_open_seen
    diag["skippedReasons"] = dict(diag["skippedReasons"])
    diag["exitTypeCounts"] = dict(diag["exitTypeCounts"])

    traces = _build_traces(resolved, portfolio, trace_limit)
    return {
        "diag": diag,
        "resolved": resolved,
        "portfolio": portfolio,
        "traces": traces,
        "bars_by_ticker": bars_by_ticker,
        "features_by_ticker": features_by_ticker,
        "calendar": calendar,
        "price_provider": price_provider,
        "universe": universe,
        "params": params,
    }


def _build_traces(resolved, portfolio, limit):
    closed_by_key = {
        (p["entry"].order.symbol, p["entry"].fill_date, p["exit"].fill_date): p
        for p in portfolio.closed_positions
    }
    traces = []
    for sig, order, entry_fill, exit_fill, risk_spec, atr_t in resolved:
        key = (order.symbol, entry_fill.fill_date, exit_fill.fill_date)
        pos = closed_by_key.get(key)
        if pos is None:
            continue  # resolvable at instrument level but never admitted (position-limit) - not a full trace
        traces.append({
            "symbol": order.symbol,
            "signalDate": sig.signal_date,
            "entryDate": entry_fill.fill_date,
            "entryPrice": entry_fill.fill_price,
            "atrAtSignal": atr_t,
            "stopDistance": risk_spec.stop_distance,
            "stopPrice": entry_fill.fill_price - risk_spec.stop_distance,
            "targetPrice": entry_fill.fill_price + risk_spec.reward_risk * risk_spec.stop_distance,
            "exitDate": exit_fill.fill_date,
            "exitType": exit_fill.fill_type,
            "exitPrice": exit_fill.fill_price,
            "shares": pos["shares"],
            "entryCostBps": entry_fill.cost_bps,
            "exitCostBps": exit_fill.cost_bps,
            "pnl": pos["pnl"],
        })
        if len(traces) >= limit:
            break
    return traces
