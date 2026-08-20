#!/usr/bin/env python
"""5DC-v1A-P survivorship-bias comparison driver (RESEARCH, not production).

Replicates engine/runner.py::run_smoke pipeline exactly, but wires in a
research-provided merged price source so we can compare:

    A1A_ONLY        (2,558 survivor symbols, A2a prices)
    A1A_A1B_MERGED  (+ 504 delisted symbols, A2b prices from the 2026-08-16
                     CI artifact a2b-shard-0, quality-excluded set applied)

Read-only w.r.t. production: reads data/backfill/price/a2a via A2aProvider,
reads the A2b artifact (temp dir) directly, writes NOTHING to the repo except
the report json under research/strategy-lab/reports/. Engine code untouched.

ExitAt semantics (DESIGN.md §4.5 default (b)): a delisted ticker's bars simply
end at its last traded date; positions that cannot resolve a STOP/TARGET before
data end are skipped by simulate_trade ("ran_out_of_bars") - same natural-end
handling as the design's option (b). No forced TIME_EXIT is injected.
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.fastBars import FastBars  # noqa: E402
from engine.data.priceProvider import PriceProvider  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.execution.executor import CostModel, build_order, simulate_trade  # noqa: E402
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.runner import load_strategy  # noqa: E402


def _drop_suspension_rows(bars):
    """Same predicate as runner.run_smoke._drop_suspension_rows."""
    return bars[~((bars["open"] == 0) & (bars["high"] == 0) & (bars["low"] == 0))]


class A2bProvider(PriceProvider):
    """Research-side A2b provider over the CI artifact shard (accepted set only)."""

    _SCHEMA_FIELDS = ("ticker", "date", "open", "high", "low", "close", "volume")

    def __init__(self, shard_path, accepted_tickers, manifest_tag="ci-a2b-shard-0"):
        self.shard_path = shard_path
        self.accepted = set(accepted_tickers)
        self._manifest_tag = manifest_tag
        self._bars = {}

    @property
    def manifest_hash(self):
        return self._manifest_tag

    def coverage(self, ticker):
        df = self._bars.get(ticker)
        if df is None or df.empty:
            return None
        return (df.index[0].strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d"))

    def load(self, tickers, start, end, universe_hash="none"):
        tickers = set(tickers) & self.accepted
        buffers = {t: [] for t in tickers}
        with open(self.shard_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                ticker = row["ticker"]
                if ticker not in buffers:
                    continue
                date = row["date"]
                if date < start or date > end:
                    continue
                missing = [k for k in self._SCHEMA_FIELDS if k not in row]
                if missing:
                    raise ValueError(f"A2b schema violation: missing {missing} ({ticker} {date})")
                buffers[ticker].append(row)

        result = {}
        for t, rows in buffers.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype("float32")
            df["volume"] = df["volume"].astype("int64")
            result[t] = df[["open", "high", "low", "close", "volume"]]
        self._bars = result
        return result


def load_merged_bars(repo_root, universe, start, end, a2b_shard, a2b_accepted, use_cache=False):
    """Load A1a bars from A2a + A1b bars from the artifact. Returns
    (bars_by_ticker, price_provider)."""
    a1a_tickers = {e.ticker for e in universe.entries if e.source == "A1A"}
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}

    a2a = A2aProvider(repo_root=repo_root, use_cache=use_cache)
    bars_a1a = a2a.load(a1a_tickers, start, end, universe_hash=universe.universe_hash)

    a2b = A2bProvider(shard_path=a2b_shard, accepted_tickers=a2b_accepted)
    bars_a1b = a2b.load(a1b_tickers, start, end, universe_hash=universe.universe_hash)
    merged = dict(bars_a1a)
    merged.update(bars_a1b)

    class _MergedProvider(PriceProvider):
        @property
        def manifest_hash(self):
            return f"{a2a.manifest_hash}+{a2b.manifest_hash}"

        def coverage(self, ticker):
            if ticker in bars_a1a:
                return a2a.coverage(ticker)
            if ticker in bars_a1b:
                return a2b.coverage(ticker)
            return None

        def load(self, tickers, start, end, universe_hash="none"):
            return {t: merged[t] for t in set(tickers) if t in merged}

    return merged, _MergedProvider()


def run_5dc_pipeline(repo_root, start, end, rule, universe, bars_by_ticker, price_provider, max_positions_override=None):
    """Faithful copy of engine/runner.py::run_smoke from the bars-onward stage."""
    params = rule.PARAMS
    calendar = TradingCalendar(repo_root=repo_root)

    cost_model = CostModel(
        entry_cost_bps=params["cost"]["entryCostBps"],
        exit_cost_bps=params["cost"]["exitCostBps"],
        slippage_bps=params["cost"]["slippageBps"],
    )
    mp = max_positions_override if max_positions_override is not None else params["portfolio"]["maxPositions"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=mp,
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
        "suspensionRowsDropped": 0,
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
    fast_bars_by_ticker = {}
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

    resolved = []
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

    max_open_seen = _schedule_portfolio(resolved, portfolio, portfolio_cfg)

    diag["finalCash"] = portfolio.cash
    diag["closedPositionCount"] = len(portfolio.closed_positions)
    diag["openPositionCountAtEnd"] = len(portfolio.open_positions)
    diag["maxSimultaneousPositionsObserved"] = max_open_seen
    diag["skippedReasons"] = dict(diag["skippedReasons"])
    diag["exitTypeCounts"] = dict(diag["exitTypeCounts"])

    return {"diag": diag, "resolved": resolved, "portfolio": portfolio,
            "bars_by_ticker": bars_by_ticker, "features_by_ticker": features_by_ticker,
            "calendar": calendar, "price_provider": price_provider, "universe": universe,
            "params": params}


def _schedule_portfolio(resolved, portfolio, portfolio_cfg):
    """Same as runner._schedule_portfolio (same-bar contract included)."""
    by_entry_date = {}
    by_exit_date = {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    max_open_seen = 0

    def _check_invariant(date):
        assert len(portfolio.open_positions) <= portfolio_cfg.max_positions, (
            f"{date}: {len(portfolio.open_positions)} open positions exceeds max_positions="
            f"{portfolio_cfg.max_positions}"
        )
        return len(portfolio.open_positions)

    for date in event_dates:
        exits_today = []
        same_bar_exit_candidates = []
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)
        max_open_seen = max(max_open_seen, _check_invariant(date))

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])
                max_open_seen = max(max_open_seen, _check_invariant(date))

    return max_open_seen


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def realized_pnl_metrics(portfolio, start, end):
    events = sorted((p["exit_date"], p["pnl"]) for p in portfolio.closed_positions)
    curve = []
    eq = portfolio.config.initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return None
    return {
        "initialCapital": portfolio.config.initial_capital,
        "finalEquity": eq,
        "totalReturn": total_return(curve),
        "cagr": cagr(curve),
        "mdd": max_drawdown(curve),
        "sharpe": sharpe(curve),
        "sortino": sortino(curve),
        "calmar": calmar(curve),
    }


def trades_from_portfolio(portfolio):
    trades = []
    for p in portfolio.closed_positions:
        entry = p["entry"]
        exit_ = p["exit"]
        trades.append({
            "pnl": p["pnl"],
            "holding_sessions": _to_ordinal(exit_.fill_date) - _to_ordinal(p["entry_date"]),
            "symbol": p["symbol"],
            "entry_date": p["entry_date"],
            "exit_date": exit_.fill_date,
            "exit_type": exit_.fill_type,
            "entry_price": entry.fill_price,
            "exit_price": exit_.fill_price,
            "shares": p["shares"],
        })
    return trades


def yearly_breakdown(trades):
    years = defaultdict(lambda: {"count": 0, "win": 0, "loss": 0,
                                  "grossWin": 0.0, "grossLoss": 0.0, "net": 0.0})
    for t in trades:
        y = t["exit_date"][:4]
        b = years[y]
        b["count"] += 1
        if t["pnl"] >= 0:
            b["win"] += 1
            b["grossWin"] += t["pnl"]
        else:
            b["loss"] += 1
            b["grossLoss"] += t["pnl"]
        b["net"] += t["pnl"]
    return {y: {**v, "winRate": round(v["win"] / v["count"], 4) if v["count"] else None,
                "pf": round(v["grossWin"] / abs(v["grossLoss"]), 4) if v["grossLoss"] else None}
            for y, v in sorted(years.items())}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--a2b-shard", required=True, help="path to a2b-shard-0.jsonl")
    ap.add_argument("--a2b-diag", required=True, help="path to _diagnostics.json (for qualityExcluded)")
    ap.add_argument("--include-delisted", action="store_true")
    ap.add_argument("--use-a2a-cache", action="store_true", help="read existing A2a cache only (A1A_ONLY validation)")
    ap.add_argument("--max-positions", type=int, default=None, help="override portfolio max_positions (sensitivity)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    start, end = "2014-05-13", "2026-08-03"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    diag_full = json.load(open(args.a2b_diag, encoding="utf-8"))
    qx = diag_full.get("qualityExcluded") or []
    qx_tickers = {q["ticker"] for q in qx}
    all_shard_tickers = set()
    with open(args.a2b_shard, encoding="utf-8") as f:
        for line in f:
            all_shard_tickers.add(json.loads(line)["ticker"])
    accepted = all_shard_tickers - qx_tickers
    print(f"A2b shard tickers: {len(all_shard_tickers)} | qualityExcluded: {len(qx_tickers)} | accepted: {len(accepted)}")

    rule = load_strategy("5dc_v1a_p", repo_root)

    universe = UniverseProvider(repo_root=repo_root, include_delisted=args.include_delisted)
    print(f"universe: {universe.mode} ({len(universe.tickers)} entries)")

    t0 = time.time()
    bars_raw, provider = load_merged_bars(repo_root, universe, start, end, args.a2b_shard, accepted, use_cache=args.use_a2a_cache)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    dropped = sum(len(bars_raw[t]) - len(bars_by_ticker[t]) for t in bars_raw)
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s) | suspension rows dropped: {dropped}")

    result = run_5dc_pipeline(repo_root, start, end, rule, universe, bars_by_ticker, provider, max_positions_override=args.max_positions)
    elapsed = time.time() - t0

    diag = result["diag"]
    portfolio = result["portfolio"]
    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio, start, end)

    same_bar = [t for t in trades if t["entry_date"] == t["exit_date"]]
    same_bar_by_type = Counter(t["exit_type"] for t in same_bar)

    a1b_symbols = {e.ticker for e in universe.entries if e.source == "A1B"}
    a1b_trades = [t for t in trades if t["symbol"] in a1b_symbols]
    a1b_pnl = sum(t["pnl"] for t in a1b_trades)

    report = {
        "analysis_date": "2026-08-17",
        "model_name": "deepseek",
        "purpose": "survivorship-bias comparison (research)",
        "runIdentification": {
            "strategyId": "5dc_v1a_p",
            "runClass": "SMOKE",
            "universeMode": diag["universeMode"],
            "engineGitCommit": "CURRENT_HEAD(c140c26+)",
            "a2aManifestHash": result["price_provider"].manifest_hash,
            "a2bSource": args.a2b_shard,
            "period": f"{start} ~ {end}",
            "elapsedSeconds": round(elapsed, 1),
        },
        "assumptions": {
            "exitAtHandling": "natural-end (option b): delisted ticker bars end at last traded date; "
                              "unresolved positions skipped by simulate_trade",
            "a2bQualityExclusion": "120 tickers excluded per CI finalize diagnostics (qualityExcluded)",
            "delistedPIT": "signals only on [firstTraded, lastTraded] (bars naturally bounded)",
            "043090": f"in qualityExcluded -> not tradable in merged run (1 ticker, negligible)",
        },
        "diag": {
            "tickersScanned": diag["tickersScanned"],
            "signalCount": diag["signalCount"],
            "invalidSignalCount": diag["invalidSignalCount"],
            "skippedSignalCount": diag["skippedSignalCount"],
            "skippedReasons": diag["skippedReasons"],
            "executableTradeCount": diag["executableTradeCount"],
            "portfolioEligibleTradeCount": diag["portfolioEligibleTradeCount"],
            "closedPositionCount": diag["closedPositionCount"],
            "openPositionCountAtEnd": diag["openPositionCountAtEnd"],
            "maxSimultaneousPositionsObserved": diag["maxSimultaneousPositionsObserved"],
            "finalCash": diag["finalCash"],
            "exitTypeCounts": diag["exitTypeCounts"],
            "universeCoverage": diag["universeCoverage"],
        },
        "sameBarCensus": {
            "sameBarTrades": len(same_bar),
            "totalClosedTrades": len(trades),
            "sameBarShare": round(len(same_bar) / len(trades), 4) if trades else None,
            "byExitType": dict(same_bar_by_type),
        },
        "a1bTradeCensus": {
            "a1bSymbolsWithTrades": len({t["symbol"] for t in a1b_trades}),
            "a1bTradeCount": len(a1b_trades),
            "a1bNetPnl": round(a1b_pnl, 2),
        },
        "resultTable": {
            "initialCapital": params_init_cap(portfolio),
            "finalEquity": realized["finalEquity"],
            "totalReturn": realized["totalReturn"],
            "cagr": realized["cagr"],
            "mdd": realized["mdd"],
            "sharpe": realized["sharpe"],
            "sortino": realized["sortino"],
            "calmar": realized["calmar"],
            **{k: v for k, v in t_stats.items()},
        },
        "yearlyBreakdown": yearly_breakdown(trades),
        "allTrades": trades,
    }

    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "reports", "2026-08-17-survivorship-bias-measurement",
        f"run_{'merged' if args.include_delisted else 'a1a_only'}.json",
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(json.dumps({
        "elapsedSeconds": round(elapsed, 1),
        "universeMode": diag["universeMode"],
        "tickersScanned": diag["tickersScanned"],
        "signalCount": diag["signalCount"],
        "closedPositionCount": diag["closedPositionCount"],
        "a1bTrades": len(a1b_trades),
        "a1bNetPnl": round(a1b_pnl, 2),
        "resultTable": {
            "cagr": realized["cagr"], "mdd": realized["mdd"],
            "finalEquity": realized["finalEquity"],
            **{k: v for k, v in t_stats.items() if k in ("winCount", "lossCount", "winRate", "profitFactor", "avgHoldingPeriod")},
        },
    }, indent=2, default=str))
    print("saved:", out_path)


def params_init_cap(portfolio):
    return portfolio.config.initial_capital


if __name__ == "__main__":
    main()