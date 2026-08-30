#!/usr/bin/env python
"""Single-symbol backtest for detailed per-coin analysis."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np

from engine.data.calendar import TradingCalendar
from engine.execution.executor import CostModel, build_order, simulate_trade
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.runner import _drop_suspension_rows, _schedule_portfolio
from engine.data.fastBars import FastBars
from engine.signals.schema import Signal


def run_single_symbol(strategy_id: str, symbol: str, timeframe: str = "daily", 
                       start: str = "2023-06-01", end: str = "2026-08-27"):
    """Run backtest for a single symbol."""
    
    # Load strategy
    import importlib.util
    strategy_dir = Path(__file__).resolve().parent / "strategies" / "crypto" / strategy_id
    rule_path = strategy_dir / "rule.py"
    spec = importlib.util.spec_from_file_location(f"strategies.crypto.{strategy_id}.rule", rule_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    
    with open(strategy_dir / "policy.json", encoding="utf-8") as f:
        policy = json.load(f)
    
    # Load data
    data_path = Path(__file__).resolve().parent / "data" / "crypto" / timeframe / f"{symbol}.parquet"
    bars = pd.read_parquet(data_path)
    bars = bars[(bars.index >= start) & (bars.index <= end)]
    bars = _drop_suspension_rows(bars)
    
    # Compute features and signals
    features = mod.compute_features_main(bars)
    signals = mod.generate_signals_main(symbol, features)
    
    print(f"\n{'='*50}")
    print(f"{strategy_id} | {symbol} | {timeframe}")
    print(f"{'='*50}")
    print(f"Bars: {len(bars)}, Signals: {len(signals)}")
    
    if not signals:
        return {"error": "No signals"}
    
    # Calendar
    calendar = TradingCalendar(repo_root=str(Path(__file__).resolve().parent.parent.parent))
    
    # Cost model (from policy)
    cost = policy.get("cost", {})
    cost_model = CostModel(
        entry_cost_bps=cost.get("entryCostBps", 5),
        exit_cost_bps=cost.get("exitCostBps", 5),
        slippage_bps=cost.get("slippageBps", 5),
    )
    
    portfolio_cfg = PortfolioConfig(
        initial_capital=100_000_000,
        max_positions=1,  # Single symbol
        equal_weight=True,
        fractional_shares=True,
        tie_break="ticker_ascending",
    )
    
    # Resolve trades
    resolved = []
    for sig in signals:
        ts = pd.Timestamp(sig.signal_date)
        if ts not in features.index:
            continue
        row = features.loc[ts]
        if pd.isna(row.get("atr", 0.0)):
            continue
        
        risk_spec = mod.risk_spec_for_main(row)
        order = build_order(sig, risk_spec, calendar)
        if order is None:
            continue
        
        fast_bars = FastBars(bars)
        if order.order_date not in fast_bars.index:
            continue
        
        try:
            result = simulate_trade(order, fast_bars, calendar, cost_model)
        except Exception:
            continue
        
        if result is None:
            continue
        
        entry_fill, exit_fill = result
        resolved.append((sig, order, entry_fill, exit_fill, risk_spec, float(row.get("atr", 0.0))))
    
    print(f"Resolved trades: {len(resolved)}")
    
    # Deduplicate
    resolved.sort(key=lambda item: item[1].order_date)
    by_symbol_last_exit = {}
    deduped = []
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        last_exit = by_symbol_last_exit.get(order.symbol)
        if last_exit is not None and order.order_date < last_exit:
            continue
        by_symbol_last_exit[order.symbol] = exit_fill.fill_date
        deduped.append(item)
    resolved = deduped
    
    # Portfolio
    portfolio = Portfolio(portfolio_cfg)
    _schedule_portfolio(resolved, portfolio, portfolio_cfg)
    
    # Collect trades
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
    
    # Metrics
    if not trades:
        return {"error": "No executed trades"}
    
    df = pd.DataFrame(trades)
    returns = df["return_pct"].values
    
    equity = 100_000_000
    equity_curve = [equity]
    for r in returns:
        equity *= (1 + r)
        equity_curve.append(equity)
    equity_curve = np.array(equity_curve)
    
    total_return = equity_curve[-1] / 100_000_000 - 1
    first_entry = pd.Timestamp(df["entry_date"].min())
    last_exit = pd.Timestamp(df["exit_date"].max())
    years = (last_exit - first_entry).days / 365.25
    cagr = (equity_curve[-1] / 100_000_000) ** (1 / years) - 1 if years > 0 else 0
    
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve / peak - 1
    max_dd = dd.min()
    
    mean_ret = np.mean(returns)
    std_ret = np.std(returns, ddof=1)
    sharpe = (mean_ret / std_ret * np.sqrt(365)) if std_ret > 0 else 0
    
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = len(wins) / len(returns) if len(returns) > 0 else 0
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
    
    # Yearly
    df["entry_year"] = pd.to_datetime(df["entry_date"]).dt.year
    yearly = {}
    for year, group in df.groupby("entry_year"):
        yr_returns = group["return_pct"].values
        yr_equity = 100_000_000
        for r in yr_returns:
            yr_equity *= (1 + r)
        yearly[int(year)] = {
            "trades": len(group),
            "return": round(yr_equity / 100_000_000 - 1, 4),
            "win_rate": round(len(yr_returns[yr_returns > 0]) / len(yr_returns), 4),
        }
    
    result = {
        "strategy": strategy_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "period": f"{start} ~ {end}",
        "num_signals": len(signals),
        "num_trades": len(trades),
        "total_return": round(float(total_return), 4),
        "cagr": round(float(cagr), 4),
        "max_drawdown": round(float(max_dd), 4),
        "sharpe": round(float(sharpe), 4),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 4) if profit_factor != np.inf else "inf",
        "avg_win": round(float(wins.mean()), 6) if len(wins) > 0 else 0,
        "avg_loss": round(float(losses.mean()), 6) if len(losses) > 0 else 0,
        "avg_holding_days": round(float(df["holding_days"].mean()), 1),
        "yearly": yearly,
        "trades": trades,
    }
    
    print(f"Total Return: {total_return:.2%}")
    print(f"CAGR: {cagr:.2%}")
    print(f"Max DD: {max_dd:.2%}")
    print(f"Sharpe: {sharpe:.4f}")
    print(f"Win Rate: {win_rate:.2%}")
    print(f"Profit Factor: {profit_factor:.4f}")
    print(f"Num Trades: {len(trades)}")
    print(f"Yearly: {yearly}")
    
    return result


if __name__ == "__main__":
    strategies = ["donchian_atr_v1", "trend_momentum_v1", "vol_regime_v1"]
    symbols = ["KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA"]
    
    all_results = []
    
    for strategy_id in strategies:
        print(f"\n\n{'#'*60}")
        print(f"# STRATEGY: {strategy_id}")
        print(f"{'#'*60}")
        
        for symbol in symbols:
            try:
                result = run_single_symbol(strategy_id, symbol)
                if "error" not in result:
                    all_results.append(result)
            except Exception as e:
                print(f"Error {strategy_id} {symbol}: {e}")
    
    # Save all results
    import datetime
    out_dir = Path(__file__).resolve().parent / "reports" / "crypto_backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"single_symbol_{timestamp}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n\nSaved: {out_path}")
    
    # Print comparative table
    print(f"\n{'='*100}")
    print(f"{'Strategy':<22} {'Symbol':<10} {'CAGR':>8} {'MDD':>8} {'Sharpe':>8} {'WR':>8} {'PF':>8} {'Trades':>6}")
    print("-" * 100)
    for r in all_results:
        print(f"{r['strategy']:<22} {r['symbol']:<10} {r['cagr']:>7.2%} {r['max_drawdown']:>7.2%} {r['sharpe']:>8.2f} {r['win_rate']:>7.2%} {str(r['profit_factor']):>8} {r['num_trades']:>6}")