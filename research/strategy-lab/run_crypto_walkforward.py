"""Walk-forward / OOS validation framework for crypto strategies.

Uses the existing engine infrastructure:
- engine.runner for trade simulation and portfolio management
- engine.metrics for CAGR, MDD, Sharpe, etc.
- 60/15/25 TRAIN/VALID/TEST split (time-ordered)
- Multiple parameter configs tested on TRAIN, best frozen for VALID/TEST
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SLAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SLAB)

from engine.runner import load_strategy  # noqa: E402
from engine.runner import (CostModel, build_order, simulate_trade,  # noqa: E402
                           _drop_suspension_rows, _merge_continuous_same_symbol_holds,
                           _schedule_portfolio, FastBars)
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.metrics import metrics as em  # noqa: E402
from engine.data.cryptoProvider import load_crypto_bars  # noqa: E402

OUT_DIR = os.path.join(SLAB, "findings", "crypto-strategies")


def load_crypto_data(markets, timeframe="D", count=1000):
    """Load crypto data for all markets."""
    print(f"Loading {timeframe} data for {len(markets)} markets...")
    bars = load_crypto_bars(markets, timeframe=timeframe, count=count)
    print(f"  Loaded: {list(bars.keys())}")
    for m, df in bars.items():
        print(f"    {m}: {len(df)} bars, {df.index[0].date()} ~ {df.index[-1].date()}")
    return bars


def run_crypto_backtest(strategy_id, bars_by_ticker, start, end, param_overrides=None, trace_limit=0):
    """Run a crypto backtest using pre-loaded bars and the engine's simulation/portfolio logic."""
    # Load strategy module
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    rule = load_strategy(strategy_id, str(REPO_ROOT))
    
    # Apply parameter overrides
    if param_overrides:
        for k, v in param_overrides.items():
            if k in rule.PARAMS:
                rule.PARAMS[k] = v
            elif k in rule.PARAMS.get("risk", {}):
                rule.PARAMS["risk"][k] = v
            elif k in rule.PARAMS.get("cost", {}):
                rule.PARAMS["cost"][k] = v
            elif k in rule.PARAMS.get("portfolio", {}):
                rule.PARAMS["portfolio"][k] = v
    
    params = rule.PARAMS
    universe = params["testUniverse"]
    
    # Filter bars to universe and date range
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    filtered_bars = {}
    for symbol in universe:
        if symbol in bars_by_ticker:
            df = bars_by_ticker[symbol]
            df = df[(df.index >= start_ts) & (df.index <= end_ts)]
            if len(df) > 0:
                filtered_bars[symbol] = df
    
    if not filtered_bars:
        return {"diag": {"error": "No data for universe"}, "portfolio": None, "params": params}
    
    # Clean suspension rows (adapted for crypto - just drop zero OHLC)
    bars_by_ticker_clean = {t: _drop_suspension_rows(df) for t, df in filtered_bars.items()}
    
    calendar = TradingCalendar(repo_root=str(REPO_ROOT))
    
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
        "runClass": "CRYPTO",
        "universeMode": "CRYPTO_FIXED",
        "tickersScanned": len(bars_by_ticker_clean),
        "suspensionRowsDropped": sum(len(filtered_bars[t]) - len(bars_by_ticker_clean[t]) for t in filtered_bars),
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
    
    # Compute features and generate signals for each symbol
    for symbol, bars in bars_by_ticker_clean.items():
        try:
            # Strategy compute_features may need all_bars for regime filter
            if hasattr(rule, 'compute_features') and 'all_bars' in rule.compute_features.__code__.co_varnames:
                features = rule.compute_features(bars, symbol=symbol, all_bars=bars_by_ticker_clean)
            else:
                features = rule.compute_features(bars)
        except Exception as e:
            diag["executionErrorCount"] += 1
            continue
        features_by_ticker[symbol] = features
        fast_bars_by_ticker[symbol] = FastBars(bars)
        
        # Generate signals
        for sig in rule.generate_signals(symbol, features):
            all_signals.append(sig)
    
    diag["signalCount"] = len(all_signals)
    if all_signals:
        all_dates = sorted(s.signal_date for s in all_signals)
        diag["firstSignalDate"], diag["lastSignalDate"] = all_dates[0], all_dates[-1]
    
    # Resolve signals to trades (same logic as runner.py)
    resolved = []
    for sig in all_signals:
        features = features_by_ticker[sig.symbol]
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index:
            diag["invalidSignalCount"] += 1
            continue
        row = features.loc[ts]
        if pd.isna(row.get("atr", 0.0)):
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
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec, float(row.get("atr", 0.0))))
    
    # Deduplicate overlapping signals on same symbol
    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit = {}
    deduped = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date < last_exit:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["overlaps_open_position_same_symbol"] += 1
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped
    diag["portfolioEligibleTradeCount"] = len(resolved)
    
    # Merge continuous holds if enabled
    continuous_holds_merged_count = 0
    if params.get("scheduling", {}).get("continuousHoldOnRenewal", False):
        resolved, continuous_holds_merged_count = _merge_continuous_same_symbol_holds(resolved)
    diag["continuousHoldsMergedCount"] = continuous_holds_merged_count
    
    # Schedule portfolio
    max_open_seen = _schedule_portfolio(resolved, portfolio, portfolio_cfg)
    
    diag["finalCash"] = portfolio.cash
    diag["closedPositionCount"] = len(portfolio.closed_positions)
    diag["openPositionCountAtEnd"] = len(portfolio.open_positions)
    diag["maxSimultaneousPositionsObserved"] = max_open_seen
    diag["skippedReasons"] = dict(diag["skippedReasons"])
    diag["exitTypeCounts"] = dict(diag["exitTypeCounts"])
    
    # Build traces
    traces = []
    closed_by_key = {
        (p["entry"].order.symbol, p["entry"].fill_date, p["exit"].fill_date): p
        for p in portfolio.closed_positions
    }
    for sig, order, entry_fill, exit_fill, risk_spec, atr_t in resolved:
        key = (order.symbol, entry_fill.fill_date, exit_fill.fill_date)
        pos = closed_by_key.get(key)
        if pos is None:
            continue
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
        if len(traces) >= trace_limit:
            break
    
    return {
        "diag": diag,
        "resolved": resolved,
        "portfolio": portfolio,
        "traces": traces,
        "bars_by_ticker": bars_by_ticker_clean,
        "features_by_ticker": features_by_ticker,
        "calendar": calendar,
        "params": params,
    }


def compute_equity_curve(portfolio, dates_all):
    """Build equity curve from portfolio closed positions."""
    # Portfolio tracks cash + positions; we need daily equity
    # The portfolio object has closed_positions with entry/exit dates and PnL
    # We'll reconstruct daily equity
    
    daily_pnl = {}
    for pos in portfolio.closed_positions:
        entry_date = pos["entry"].fill_date
        exit_date = pos["exit"].fill_date
        pnl = pos["pnl"]
        # Distribute PnL to exit date (simplified)
        if exit_date not in daily_pnl:
            daily_pnl[exit_date] = 0
        daily_pnl[exit_date] += pnl
    
    # Build equity curve
    initial_capital = portfolio.config.initial_capital
    equity = initial_capital
    curve = []
    for d in sorted(dates_all):
        if d in daily_pnl:
            equity += daily_pnl[d]
        curve.append((d, equity))
    return curve


def compute_metrics_from_result(result):
    """Compute comprehensive metrics from run_crypto_backtest result."""
    portfolio = result["portfolio"]
    diag = result["diag"]
    params = result["params"]
    
    if portfolio is None or not portfolio.closed_positions:
        return {"error": "No trades"}
    
    # Get all trading dates
    dates_all = set()
    for pos in portfolio.closed_positions:
        dates_all.add(pos["entry"].fill_date)
        dates_all.add(pos["exit"].fill_date)
    dates_all = sorted(dates_all)
    
    # Equity curve
    equity_curve = compute_equity_curve(portfolio, dates_all)
    
    # Metrics
    total_ret = em.total_return(equity_curve)
    cagr = em.cagr(equity_curve)
    mdd = em.max_drawdown(equity_curve)
    sharpe = em.sharpe(equity_curve)
    sortino = em.sortino(equity_curve)
    calmar = em.calmar(equity_curve)
    
    # Trade stats
    trades = []
    for pos in portfolio.closed_positions:
        trades.append({
            "pnl": pos["pnl"],
            "holding_sessions": (pd.Timestamp(pos["exit"].fill_date) - pd.Timestamp(pos["entry"].fill_date)).days,
        })
    tstats = em.trade_stats(trades)
    
    # Turnover (total traded notional / capital)
    total_traded = sum(abs(pos["pnl"]) + pos["entry"].fill_price * pos["shares"] for pos in portfolio.closed_positions)
    turnover = total_traded / params["portfolio"]["initialCapital"] if params["portfolio"]["initialCapital"] > 0 else 0
    
    # Annual returns
    annual = {}
    if equity_curve:
        eq_df = pd.DataFrame(equity_curve, columns=["date", "equity"])
        eq_df["date"] = pd.to_datetime(eq_df["date"])
        eq_df = eq_df.set_index("date")
        yearly = eq_df.resample("YE").last()
        yearly_ret = yearly["equity"].pct_change().dropna()
        for idx, ret in yearly_ret.items():
            annual[str(idx.year)] = round(float(ret) * 100, 2)
    
    return {
        "totalReturnPct": round(total_ret * 100, 2) if total_ret else None,
        "cagrPct": round(cagr * 100, 2) if cagr else None,
        "mddPct": round(mdd * 100, 2) if mdd else None,
        "sharpe": round(sharpe, 3) if sharpe else None,
        "sortino": round(sortino, 3) if sortino else None,
        "calmar": round(calmar, 3) if calmar else None,
        "winRatePct": round(tstats["winRate"] * 100, 2) if tstats["winRate"] else None,
        "profitFactor": round(tstats["profitFactor"], 3) if tstats["profitFactor"] else None,
        "tradeCount": tstats["tradeCount"],
        "avgHoldingDays": round(tstats["avgHoldingPeriod"], 1) if tstats["avgHoldingPeriod"] else None,
        "turnover": round(turnover, 2),
        "annualReturns": annual,
        "nSignals": diag["signalCount"],
        "nTrades": diag["executableTradeCount"],
        "maxPositions": diag.get("maxSimultaneousPositionsObserved", 0),
    }


def split_dates(dates, train=0.6, valid=0.15, test=0.25):
    """Split dates into TRAIN/VALID/TEST (time-ordered)."""
    n = len(dates)
    i_tr = int(n * train)
    i_va = int(n * (train + valid))
    return {
        "train": dates[:i_tr],
        "valid": dates[i_tr:i_va],
        "test": dates[i_va:],
    }


def run_walkforward(strategy_id, bars_by_ticker, param_grid, timeframe="D"):
    """Run walk-forward validation: TRAIN selects best params, VALID/TEST evaluate."""
    
    # Get all available dates from the first market
    first_market = list(bars_by_ticker.keys())[0]
    all_dates = sorted(bars_by_ticker[first_market].index.strftime("%Y-%m-%d").unique())
    
    splits = split_dates(all_dates)
    print(f"\nDate splits:")
    print(f"  TRAIN: {splits['train'][0]} ~ {splits['train'][-1]} ({len(splits['train'])} days)")
    print(f"  VALID: {splits['valid'][0]} ~ {splits['valid'][-1]} ({len(splits['valid'])} days)")
    print(f"  TEST:  {splits['test'][0]} ~ {splits['test'][-1]} ({len(splits['test'])} days)")
    
    # Grid search on TRAIN
    print(f"\nGrid search on TRAIN ({len(param_grid)} configs)...")
    train_results = []
    for i, params in enumerate(param_grid):
        print(f"  [{i+1}/{len(param_grid)}] {params}")
        try:
            result = run_crypto_backtest(
                strategy_id, bars_by_ticker,
                splits["train"][0], splits["train"][-1],
                param_overrides=params,
                trace_limit=0,
            )
            metrics = compute_metrics_from_result(result)
            metrics["params"] = params
            train_results.append(metrics)
            print(f"    -> Sharpe={metrics.get('sharpe')}, CAGR={metrics.get('cagrPct')}%, Trades={metrics.get('tradeCount')}")
        except Exception as e:
            print(f"    -> ERROR: {e}")
            train_results.append({"params": params, "error": str(e)})
    
    # Select best by Sharpe (or CAGR if Sharpe unavailable)
    valid_results = [r for r in train_results if "error" not in r and r.get("sharpe") is not None]
    if not valid_results:
        print("No valid TRAIN results!")
        return None
    
    best = max(valid_results, key=lambda x: x["sharpe"] if x["sharpe"] is not None else -999)
    print(f"\nBest TRAIN config (Sharpe={best['sharpe']:.3f}): {best['params']}")
    
    # Evaluate on VALID
    print("\nEvaluating best config on VALID...")
    valid_result = run_crypto_backtest(
        strategy_id, bars_by_ticker,
        splits["valid"][0], splits["valid"][-1],
        param_overrides=best["params"],
        trace_limit=5,
    )
    valid_metrics = compute_metrics_from_result(valid_result)
    print(f"  VALID: Sharpe={valid_metrics.get('sharpe')}, CAGR={valid_metrics.get('cagrPct')}%, Trades={valid_metrics.get('tradeCount')}")
    
    # Evaluate on TEST
    print("\nEvaluating best config on TEST...")
    test_result = run_crypto_backtest(
        strategy_id, bars_by_ticker,
        splits["test"][0], splits["test"][-1],
        param_overrides=best["params"],
        trace_limit=5,
    )
    test_metrics = compute_metrics_from_result(test_result)
    print(f"  TEST: Sharpe={test_metrics.get('sharpe')}, CAGR={test_metrics.get('cagrPct')}%, Trades={test_metrics.get('tradeCount')}")
    
    # Also run on FULL for reference
    print("\nEvaluating best config on FULL period...")
    full_result = run_crypto_backtest(
        strategy_id, bars_by_ticker,
        all_dates[0], all_dates[-1],
        param_overrides=best["params"],
        trace_limit=5,
    )
    full_metrics = compute_metrics_from_result(full_result)
    print(f"  FULL: Sharpe={full_metrics.get('sharpe')}, CAGR={full_metrics.get('cagrPct')}%, Trades={full_metrics.get('tradeCount')}")
    
    return {
        "strategy": strategy_id,
        "timeframe": timeframe,
        "splits": {k: f"{v[0]}~{v[-1]}" for k, v in splits.items()},
        "paramGrid": param_grid,
        "trainResults": train_results,
        "bestParams": best["params"],
        "validMetrics": valid_metrics,
        "testMetrics": test_metrics,
        "fullMetrics": full_metrics,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="crypto_donchian_atr",
                    choices=["crypto_donchian_atr", "crypto_trend_momentum", "crypto_regime_filtered"])
    ap.add_argument("--timeframe", default="D", choices=["D", "4H"])
    ap.add_argument("--markets", nargs="+", default=["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA", "KRW-DOGE", "KRW-DOT"])
    ap.add_argument("--count", type=int, default=800)
    ap.add_argument("--smoke", action="store_true", help="Quick test with limited data")
    args = ap.parse_args()
    
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # Load data
    bars = load_crypto_data(args.markets, timeframe=args.timeframe, count=args.count)
    if not bars:
        print("No data loaded!")
        return 1
    
    if args.smoke:
        # Quick test
        result = run_crypto_backtest(args.strategy, bars,
                              list(bars.values())[0].index[0].strftime("%Y-%m-%d"),
                              list(bars.values())[0].index[-1].strftime("%Y-%m-%d"),
                              trace_limit=5)
        metrics = compute_metrics_from_result(result)
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
        return 0
    
    # Parameter grids for each strategy (small, fixed grids - no over-optimization)
    if args.strategy == "crypto_donchian_atr":
        param_grid = [
            {"donchianPeriod": 20, "atrMult": 2.0, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 2.5, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 3.0, "maxHoldingSessions": 60},
            {"donchianPeriod": 30, "atrMult": 2.0, "maxHoldingSessions": 60},
            {"donchianPeriod": 30, "atrMult": 2.5, "maxHoldingSessions": 60},
            {"donchianPeriod": 40, "atrMult": 2.0, "maxHoldingSessions": 60},
        ]
    elif args.strategy == "crypto_trend_momentum":
        param_grid = [
            {"trendPeriod": 200, "momShortPeriod": 20, "momMediumPeriod": 60, "maxHoldingSessions": 60},
            {"trendPeriod": 150, "momShortPeriod": 20, "momMediumPeriod": 60, "maxHoldingSessions": 60},
            {"trendPeriod": 200, "momShortPeriod": 10, "momMediumPeriod": 30, "maxHoldingSessions": 60},
            {"trendPeriod": 200, "momShortPeriod": 20, "momMediumPeriod": 60, "maxHoldingSessions": 30},
        ]
    else:  # crypto_regime_filtered
        param_grid = [
            {"donchianPeriod": 20, "atrMult": 2.0, "volThreshold": 0.03, "useVolRegimeFilter": True, "useBtcTrendFilter": True, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 2.5, "volThreshold": 0.03, "useVolRegimeFilter": True, "useBtcTrendFilter": True, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 2.0, "volThreshold": 0.04, "useVolRegimeFilter": True, "useBtcTrendFilter": True, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 2.0, "volThreshold": 0.03, "useVolRegimeFilter": True, "useBtcTrendFilter": False, "maxHoldingSessions": 60},
            {"donchianPeriod": 20, "atrMult": 2.0, "volThreshold": 0.03, "useVolRegimeFilter": False, "useBtcTrendFilter": True, "maxHoldingSessions": 60},
        ]
    
    # Run walk-forward
    result = run_walkforward(args.strategy, bars, param_grid, timeframe=args.timeframe)
    
    # Save results
    out_file = os.path.join(OUT_DIR, f"{args.strategy}_{args.timeframe}_walkforward.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\nSaved: {out_file}")
    
    # Also save markdown summary
    md_file = os.path.join(OUT_DIR, f"{args.strategy}_{args.timeframe}_walkforward.md")
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(f"# {args.strategy} ({args.timeframe}) Walk-Forward Results\n\n")
        f.write(f"**Markets**: {', '.join(args.markets)}\n\n")
        f.write(f"**Splits**: TRAIN={result['splits']['train']}, VALID={result['splits']['valid']}, TEST={result['splits']['test']}\n\n")
        
        f.write("## Best Parameters (selected on TRAIN)\n\n")
        f.write("```json\n")
        f.write(json.dumps(result["bestParams"], indent=2))
        f.write("\n```\n\n")
        
        f.write("## Performance Comparison\n\n")
        f.write("| Period | CAGR | MDD | Sharpe | WinRate | PF | Trades | Turnover |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for period, metrics in [("TRAIN (best)", result["bestParams"]), ("VALID", result["validMetrics"]), ("TEST", result["testMetrics"]), ("FULL", result["fullMetrics"])]:
            if isinstance(metrics, dict) and "cagrPct" in metrics:
                f.write(f"| {period} | {metrics.get('cagrPct','-')}% | {metrics.get('mddPct','-')}% | {metrics.get('sharpe','-')} | {metrics.get('winRatePct','-')}% | {metrics.get('profitFactor','-')} | {metrics.get('tradeCount','-')} | {metrics.get('turnover','-')} |\n")
            else:
                f.write(f"| {period} | - | - | - | - | - | - | - |\n")
        
        f.write("\n## Annual Returns (FULL period)\n\n")
        full = result["fullMetrics"]
        if "annualReturns" in full:
            f.write("| Year | Return |\n")
            f.write("|---|---:|\n")
            for yr, ret in full["annualReturns"].items():
                f.write(f"| {yr} | {ret}% |\n")
        
        f.write("\n## TRAIN Grid Results\n\n")
        f.write("| Config | Sharpe | CAGR | Trades |\n")
        f.write("|---|---:|---:|---:|\n")
        for r in result["trainResults"]:
            if "error" not in r:
                f.write(f"| {r['params']} | {r.get('sharpe','-')} | {r.get('cagrPct','-')}% | {r.get('tradeCount','-')} |\n")
            else:
                f.write(f"| {r['params']} | ERROR: {r['error']} |\n")
    
    print(f"Saved: {md_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())