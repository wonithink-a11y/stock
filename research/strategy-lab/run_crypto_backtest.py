#!/usr/bin/env python
"""Crypto Strategy Backtest Engine with Walk-Forward/OOS Validation.

Features:
- Loads crypto data from Parquet (daily/4h)
- Runs strategies using engine/runner.py orchestration (adapted for crypto)
- Computes: CAGR, MDD, Sharpe, Profit Factor, Win Rate, Turnover, Yearly performance
- Walk-forward / OOS: train/valid/test splits by time
- Multiple symbols, multiple timeframes
- Realistic costs: fees + slippage
"""
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.data.calendar import TradingCalendar
from engine.execution.executor import CostModel, build_order, simulate_trade
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.runner import _drop_suspension_rows, _merge_continuous_same_symbol_holds, _schedule_portfolio
from engine.signals.schema import Signal

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data" / "crypto"
REPORTS_DIR = Path(__file__).resolve().parent / "reports" / "crypto_backtest"

# Fix REPO_ROOT - go up from research/strategy-lab to stock project root
# C:\Users\User\projects\stock\research\strategy-lab -> C:\Users\User\projects\stock
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class BacktestConfig:
    strategy_id: str
    timeframe: str  # "daily" or "4h"
    symbols: List[str]
    start_date: str
    end_date: str
    initial_capital: float = 100_000_000
    max_positions: int = 5
    entry_cost_bps: float = 5.0
    exit_cost_bps: float = 5.0
    slippage_bps: float = 5.0
    fractional_shares: bool = True
    equal_weight: bool = True
    tie_break: str = "ticker_ascending"
    continuous_hold: bool = False
    # Walk-forward
    train_pct: float = 0.6
    valid_pct: float = 0.2
    test_pct: float = 0.2


def load_crypto_data(symbols: List[str], timeframe: str, start: str, end: str) -> Dict[str, pd.DataFrame]:
    """Load crypto data from Parquet files."""
    bars_by_ticker = {}
    tf_dir = DATA_DIR / timeframe
    
    for symbol in symbols:
        path = tf_dir / f"{symbol}.parquet"
        if not path.exists():
            print(f"  Warning: {path} not found")
            continue
        df = pd.read_parquet(path)
        # Filter date range
        df = df[(df.index >= start) & (df.index <= end)]
        if len(df) > 0:
            bars_by_ticker[symbol] = _drop_suspension_rows(df)
    
    return bars_by_ticker


def load_strategy_module(strategy_id: str):
    """Load strategy rule module from strategies/crypto/{strategy_id}/rule.py"""
    import importlib.util
    strategy_dir = Path(__file__).resolve().parent / "strategies" / "crypto" / strategy_id
    rule_path = strategy_dir / "rule.py"
    spec = importlib.util.spec_from_file_location(f"strategies.crypto.{strategy_id}.rule", rule_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, strategy_dir


def run_backtest(config: BacktestConfig) -> Dict:
    """Run full backtest for a strategy on given symbols/timeframe."""
    print(f"\n{'='*60}")
    print(f"Backtest: {config.strategy_id} | {config.timeframe} | {config.start_date} ~ {config.end_date}")
    print(f"Symbols: {config.symbols}")
    print(f"{'='*60}")
    
    # Load strategy
    strategy_mod, strategy_dir = load_strategy_module(config.strategy_id)
    with open(strategy_dir / "policy.json", encoding="utf-8") as f:
        policy = json.load(f)
    
    params = policy.get("params", {})
    
    # Load data
    bars_by_ticker = load_crypto_data(config.symbols, config.timeframe, config.start_date, config.end_date)
    print(f"Loaded {len(bars_by_ticker)} symbols")
    
    if not bars_by_ticker:
        return {"error": "No data loaded"}
    
    # Calendar (crypto trades 24/7, but we use bar timestamps)
    calendar = TradingCalendar(repo_root=str(REPO_ROOT))
    
    # Cost model
    cost_model = CostModel(
        entry_cost_bps=config.entry_cost_bps,
        exit_cost_bps=config.exit_cost_bps,
        slippage_bps=config.slippage_bps,
    )
    
    portfolio_cfg = PortfolioConfig(
        initial_capital=config.initial_capital,
        max_positions=config.max_positions,
        equal_weight=config.equal_weight,
        fractional_shares=config.fractional_shares,
        tie_break=config.tie_break,
    )
    
    # Compute features and generate signals for all symbols
    all_signals = []
    features_by_ticker = {}
    fast_bars_by_ticker = {}
    
    from engine.data.fastBars import FastBars
    
    for symbol, bars in bars_by_ticker.items():
        try:
            features = strategy_mod.compute_features_main(bars)
        except Exception as e:
            print(f"  Error computing features for {symbol}: {e}")
            continue
        
        features_by_ticker[symbol] = features
        fast_bars_by_ticker[symbol] = FastBars(bars)
        
        for sig in strategy_mod.generate_signals_main(symbol, features):
            all_signals.append(sig)
    
    print(f"Total signals generated: {len(all_signals)}")
    
    if not all_signals:
        return {"error": "No signals generated"}
    
    # Sort signals by date
    all_signals.sort(key=lambda s: s.signal_date)
    
    # Resolve trades (simulate each signal)
    resolved = []
    diag = {
        "signalCount": len(all_signals),
        "invalidSignalCount": 0,
        "skippedSignalCount": 0,
        "skippedReasons": {},
        "executableTradeCount": 0,
        "exitTypeCounts": {},
        "executionErrorCount": 0,
    }
    
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
        
        risk_spec = strategy_mod.risk_spec_for_main(row)
        order = build_order(sig, risk_spec, calendar)
        if order is None:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["no_next_session"] = diag["skippedReasons"].get("no_next_session", 0) + 1
            continue
        
        fast_bars = fast_bars_by_ticker[sig.symbol]
        if order.order_date not in fast_bars.index:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["no_bar_on_entry_date"] = diag["skippedReasons"].get("no_bar_on_entry_date", 0) + 1
            continue
        
        try:
            result = simulate_trade(order, fast_bars, calendar, cost_model)
        except Exception as e:
            diag["executionErrorCount"] += 1
            continue
        
        if result is None:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["ran_out_of_bars"] = diag["skippedReasons"].get("ran_out_of_bars", 0) + 1
            continue
        
        entry_fill, exit_fill = result
        diag["executableTradeCount"] += 1
        diag["exitTypeCounts"][exit_fill.fill_type] = diag["exitTypeCounts"].get(exit_fill.fill_type, 0) + 1
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec, float(row.get("atr", 0.0))))
    
    print(f"Resolved trades: {diag['executableTradeCount']}")
    
    # Deduplicate overlapping trades per symbol
    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit = {}
    deduped = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date < last_exit:
            diag["skippedSignalCount"] += 1
            diag["skippedReasons"]["overlap"] = diag["skippedReasons"].get("overlap", 0) + 1
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped
    
    # Continuous hold merge
    continuous_merged = 0
    if config.continuous_hold:
        resolved, continuous_merged = _merge_continuous_same_symbol_holds(resolved)
    
    # Portfolio scheduling
    portfolio = Portfolio(portfolio_cfg)
    max_open = _schedule_portfolio(resolved, portfolio, portfolio_cfg)
    
    # Build trade list for metrics
    trades = []
    for sig, order, entry_fill, exit_fill, risk_spec, atr_t in resolved:
        key = (order.symbol, entry_fill.fill_date, exit_fill.fill_date)
        pos = None
        for p in portfolio.closed_positions:
            if (p["entry"].order.symbol, p["entry"].fill_date, p["exit"].fill_date) == key:
                pos = p
                break
        if pos is None:
            continue
        trades.append({
            "symbol": order.symbol,
            "entry_date": entry_fill.fill_date,
            "exit_date": exit_fill.fill_date,
            "entry_price": entry_fill.fill_price,
            "exit_price": exit_fill.fill_price,
            "shares": pos["shares"],
            "pnl": pos["pnl"],
            "return_pct": pos["pnl"] / (entry_fill.fill_price * pos["shares"]) if entry_fill.fill_price * pos["shares"] != 0 else 0,
            "exit_type": exit_fill.fill_type,
            "holding_days": (pd.Timestamp(exit_fill.fill_date) - pd.Timestamp(entry_fill.fill_date)).days,
        })
    
    # Calculate metrics
    metrics = calculate_metrics(trades, config.initial_capital, config.timeframe)
    
    # Walk-forward splits
    wf_metrics = {}
    if len(trades) > 10:
        wf_metrics = walk_forward_analysis(trades, config)
    
    result = {
        "config": {
            "strategy_id": config.strategy_id,
            "timeframe": config.timeframe,
            "symbols": config.symbols,
            "start_date": config.start_date,
            "end_date": config.end_date,
        },
        "diagnostics": diag,
        "portfolio": {
            "final_cash": portfolio.cash,
            "closed_positions": len(portfolio.closed_positions),
            "open_positions": len(portfolio.open_positions),
            "max_simultaneous": max_open,
            "continuous_merged": continuous_merged,
        },
        "metrics": metrics,
        "walk_forward": wf_metrics,
        "trades": trades[:100],  # Limit stored trades
    }
    
    return result


def calculate_metrics(trades: List[Dict], initial_capital: float, timeframe: str) -> Dict:
    """Calculate comprehensive performance metrics."""
    if not trades:
        return {"error": "No trades"}
    
    df = pd.DataFrame(trades)
    
    # Daily returns (approximate by distributing PnL over holding period)
    # For simplicity, use trade-level returns
    returns = df["return_pct"].values
    
    # Equity curve (assuming equal weight, sequential compounding)
    equity = initial_capital
    equity_curve = [initial_capital]
    for r in returns:
        equity *= (1 + r)
        equity_curve.append(equity)
    equity_curve = np.array(equity_curve)
    
    # Total return
    total_return = equity_curve[-1] / initial_capital - 1
    
    # CAGR
    # Estimate years from trade dates
    first_entry = pd.Timestamp(df["entry_date"].min())
    last_exit = pd.Timestamp(df["exit_date"].max())
    years = (last_exit - first_entry).days / 365.25
    cagr = (equity_curve[-1] / initial_capital) ** (1 / years) - 1 if years > 0 else 0
    
    # Max Drawdown
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve / peak - 1
    max_dd = dd.min()
    
    # Sharpe (annualized)
    # Use trade returns as daily equivalent for daily, or 4h equivalent
    periods_per_year = 365 if timeframe == "daily" else 365 * 6  # 4h bars per year
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    sharpe = (mean_ret / std_ret * np.sqrt(periods_per_year)) if std_ret > 0 else 0
    
    # Win Rate
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = len(wins) / len(returns) if len(returns) > 0 else 0
    
    # Profit Factor
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
    
    # Average Win / Loss
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    
    # Turnover (approximate: sum of position sizes / capital)
    turnover = len(trades) / max(1, years)
    
    # Yearly performance
    df["entry_year"] = pd.to_datetime(df["entry_date"]).dt.year
    yearly = {}
    for year, group in df.groupby("entry_year"):
        yr_returns = group["return_pct"].values
        yr_equity = initial_capital
        for r in yr_returns:
            yr_equity *= (1 + r)
        yearly[int(year)] = {
            "trades": len(group),
            "return": round(yr_equity / initial_capital - 1, 4),
            "win_rate": round(len(yr_returns[yr_returns > 0]) / len(yr_returns), 4),
        }
    
    # Per-symbol performance
    by_symbol = {}
    for symbol, group in df.groupby("symbol"):
        sym_returns = group["return_pct"].values
        by_symbol[symbol] = {
            "trades": len(group),
            "return": round(np.prod(1 + sym_returns) - 1, 4),
            "win_rate": round(len(sym_returns[sym_returns > 0]) / len(sym_returns), 4),
            "avg_return": round(np.mean(sym_returns), 6),
        }
    
    return {
        "total_return": round(float(total_return), 4),
        "cagr": round(float(cagr), 4),
        "max_drawdown": round(float(max_dd), 4),
        "sharpe": round(float(sharpe), 4),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 4) if profit_factor != np.inf else "inf",
        "avg_win": round(float(avg_win), 6),
        "avg_loss": round(float(avg_loss), 6),
        "turnover_per_year": round(float(turnover), 2),
        "num_trades": len(trades),
        "avg_holding_days": round(float(df["holding_days"].mean()), 1),
        "yearly": yearly,
        "by_symbol": by_symbol,
        "final_equity": round(float(equity_curve[-1]), 0),
    }


def walk_forward_analysis(trades: List[Dict], config: BacktestConfig) -> Dict:
    """Walk-forward / OOS analysis by time splits."""
    df = pd.DataFrame(trades)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    
    first_date = df["entry_date"].min()
    last_date = df["entry_date"].max()
    total_days = (last_date - first_date).days
    
    train_end = first_date + pd.Timedelta(days=int(total_days * config.train_pct))
    valid_end = train_end + pd.Timedelta(days=int(total_days * config.valid_pct))
    
    splits = {
        "train": df[df["entry_date"] <= train_end],
        "valid": df[(df["entry_date"] > train_end) & (df["entry_date"] <= valid_end)],
        "test": df[df["entry_date"] > valid_end],
    }
    
    result = {}
    for name, split_df in splits.items():
        if len(split_df) == 0:
            result[name] = {"trades": 0}
            continue
        returns = split_df["return_pct"].values
        equity = config.initial_capital
        for r in returns:
            equity *= (1 + r)
        total_ret = equity / config.initial_capital - 1
        years = len(split_df) / (365 if config.timeframe == "daily" else 365/6)  # rough
        
        wins = returns[returns > 0]
        losses = returns[returns < 0]
        win_rate = len(wins) / len(returns) if len(returns) > 0 else 0
        pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else np.inf
        
        result[name] = {
            "trades": len(split_df),
            "return": round(float(total_ret), 4),
            "cagr": round(float((1 + total_ret) ** (1 / max(0.1, years)) - 1), 4) if years > 0 else 0,
            "win_rate": round(float(win_rate), 4),
            "profit_factor": round(float(pf), 4) if pf != np.inf else "inf",
            "period": f"{split_df['entry_date'].min().date()} ~ {split_df['entry_date'].max().date()}",
        }
    
    return result


def save_results(result: Dict, strategy_id: str, timeframe: str):
    """Save backtest results to JSON."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{strategy_id}_{timeframe}_{timestamp}.json"
    path = REPORTS_DIR / filename
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"Saved: {path}")
    return path


def print_summary(result: Dict):
    """Print formatted summary."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    m = result.get("metrics", {})
    print(f"\n{'='*50}")
    print(f"RESULTS: {result['config']['strategy_id']} ({result['config']['timeframe']})")
    print(f"{'='*50}")
    print(f"Period: {result['config']['start_date']} ~ {result['config']['end_date']}")
    print(f"Symbols: {', '.join(result['config']['symbols'])}")
    print(f"\n--- Performance ---")
    
    def fmt_pct(key, default="N/A"):
        val = m.get(key, default)
        if isinstance(val, (int, float)):
            return f"{val:.2%}"
        return str(val)
    
    def fmt_float(key, default="N/A", decimals=4):
        val = m.get(key, default)
        if isinstance(val, (int, float)):
            return f"{val:.{decimals}f}"
        return str(val)
    
    print(f"Total Return:    {fmt_pct('total_return')}")
    print(f"CAGR:            {fmt_pct('cagr')}")
    print(f"Max Drawdown:    {fmt_pct('max_drawdown')}")
    print(f"Sharpe Ratio:    {fmt_float('sharpe')}")
    print(f"Win Rate:        {fmt_pct('win_rate')}")
    print(f"Profit Factor:   {fmt_float('profit_factor')}")
    print(f"Avg Win:         {fmt_pct('avg_win')}")
    print(f"Avg Loss:        {fmt_pct('avg_loss')}")
    print(f"Turnover/Year:   {fmt_float('turnover_per_year', decimals=1)}")
    print(f"Num Trades:      {m.get('num_trades', 'N/A')}")
    print(f"Avg Holding:     {fmt_float('avg_holding_days', decimals=1)} days")
    print(f"Final Equity:    {m.get('final_equity', 'N/A'):,.0f} KRW")
    
    print(f"\n--- By Symbol ---")
    for sym, sym_m in m.get("by_symbol", {}).items():
        print(f"  {sym}: {sym_m['trades']} trades, {sym_m['return']:.2%} ret, {sym_m['win_rate']:.2%} WR")
    
    print(f"\n--- Yearly ---")
    for year, yr in sorted(m.get("yearly", {}).items()):
        print(f"  {year}: {yr['trades']} trades, {yr['return']:.2%} ret, {yr['win_rate']:.2%} WR")
    
    wf = result.get("walk_forward", {})
    if wf:
        print(f"\n--- Walk-Forward ---")
        for name, wf_m in wf.items():
            if wf_m.get("trades", 0) > 0:
                print(f"  {name.upper()}: {wf_m['trades']} trades, {wf_m['return']:.2%} ret, {wf_m['cagr']:.2%} CAGR, {wf_m['win_rate']:.2%} WR ({wf_m['period']})")


def main():
    # Strategies to test
    strategies = [
        "donchian_atr_v1",
        "trend_momentum_v1", 
        "vol_regime_v1",
    ]
    
    # Timeframes - only daily has sufficient history (4h only ~5 months)
    timeframes = ["daily"]
    
    # Symbols (major liquid coins)
    symbols = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA"]
    
    # Date range (use available data)
    start_date = "2023-06-01"
    end_date = "2026-08-27"
    
    all_results = []
    
    for strategy_id in strategies:
        for timeframe in timeframes:
            # Adjust max_holding for 4h
            max_holding = 60 if timeframe == "daily" else 120
            
            config = BacktestConfig(
                strategy_id=strategy_id,
                timeframe=timeframe,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                max_positions=5,
            )
            
            try:
                result = run_backtest(config)
                if "error" not in result:
                    print_summary(result)
                    save_results(result, strategy_id, timeframe)
                    all_results.append(result)
                else:
                    print(f"Failed: {result['error']}")
            except Exception as e:
                print(f"Error running {strategy_id} {timeframe}: {e}")
                import traceback
                traceback.print_exc()
    
    # Comparative summary
    print(f"\n{'='*60}")
    print("COMPARATIVE SUMMARY")
    print(f"{'='*60}")
    print(f"{'Strategy':<25} {'TF':<4} {'CAGR':>8} {'MDD':>8} {'Sharpe':>8} {'WR':>8} {'PF':>8} {'Trades':>6}")
    print("-" * 75)
    for r in all_results:
        m = r["metrics"]
        print(f"{r['config']['strategy_id']:<25} {r['config']['timeframe']:<4} "
              f"{m.get('cagr', 0):>7.2%} {m.get('max_drawdown', 0):>7.2%} "
              f"{m.get('sharpe', 0):>8.2f} {m.get('win_rate', 0):>7.2%} "
              f"{str(m.get('profit_factor', 'N/A')):>8} {m.get('num_trades', 0):>6}")


if __name__ == "__main__":
    main()