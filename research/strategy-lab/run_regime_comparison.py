#!/usr/bin/env python
"""
Experiment: Compare Materials-based Strategy vs GPT Regime Strategy
- Same period, same capital, same backtest engine
- Experiment 1: Materials-based (risk parity / vol targeting / MDD-based allocation)
- Experiment 2: GPT Regime strategy (Bull/Neutral/Risk-Off regime switching)
"""

import os
import sys
import json
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Try to import yfinance, fallback if not available
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    print("WARNING: yfinance not available. Install with: pip install yfinance")

# Local imports
from engine.metrics.metrics import (
    total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats
)


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass
class BacktestConfig:
    start_date: str = "2015-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 100_000_000  # 100M KRW equivalent
    rebalance_freq: str = "M"  # Monthly rebalance
    cost_bps: float = 10.0  # 10 bps per trade (round-trip)
    slippage_bps: float = 5.0
    
    # Asset universe
    assets: Dict[str, str] = field(default_factory=lambda: {
        "SPY": "SPY",           # S&P 500
        "QQQ": "QQQ",           # Nasdaq 100
        "TLT": "TLT",           # 20+ Year Treasury Bond
        "IEF": "IEF",           # 7-10 Year Treasury Bond
        "GLD": "GLD",           # Gold
        "DBC": "DBC",           # Commodities
        "VNQ": "VNQ",           # REITs
        "EFA": "EFA",           # Developed Intl
        "EEM": "EEM",           # Emerging Markets
    })
    
    # Regime strategy parameters
    regime_lookback: int = 200  # For SMA trends
    vix_threshold: float = 25.0
    spy_sma_period: int = 200
    momentum_period: int = 12*21  # 12 months
    
    # Materials strategy parameters
    target_vol: float = 0.10  # 10% annual target vol
    max_leverage: float = 1.5
    min_weight: float = 0.0
    max_weight: float = 1.0
    rebalance_threshold: float = 0.05  # 5% drift triggers rebalance


# ============================================================
# DATA LOADING
# ============================================================

class DataManager:
    """Manages data loading and caching"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cache_dir = os.path.join(os.path.dirname(__file__), ".cache", "market_data")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._cache = {}
    
    def _get_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{symbol.replace('-', '_')}.parquet")
    
    def _normalize_ts(self, ts):
        """Ensure timestamp is tz-naive for comparison"""
        if hasattr(ts, 'tz') and ts.tz is not None:
            return ts.tz_localize(None)
        return ts
    
    def load_data(self, symbols: List[str], start: str, end: str) -> pd.DataFrame:
        """Load price data for multiple symbols"""
        all_data = {}
        start_ts = self._normalize_ts(pd.Timestamp(start))
        end_ts = self._normalize_ts(pd.Timestamp(end))
        
        for sym in symbols:
            cache_path = self._get_cache_path(sym)
            
            # Try load from cache
            if os.path.exists(cache_path):
                try:
                    df = pd.read_parquet(cache_path)
                    df.index = pd.to_datetime(df.index)
                    df.index = self._normalize_ts(df.index)
                    # Check if cache covers our date range
                    if df.index[0] <= start_ts and df.index[-1] >= end_ts:
                        all_data[sym] = df.loc[start:end, 'Close'].rename(sym)
                        continue
                except Exception as e:
                    print(f"Cache read failed for {sym}: {e}")
            
            # Fetch from yfinance
            if YFINANCE_AVAILABLE:
                try:
                    ticker = yf.Ticker(sym)
                    df = ticker.history(start=start, end=end, auto_adjust=True)
                    if not df.empty:
                        df.index = pd.to_datetime(df.index)
                        df.index = self._normalize_ts(df.index)
                        df = df[['Close']].rename(columns={'Close': sym})
                        # Save to cache
                        cache_df = pd.DataFrame({sym: df[sym]}, index=df.index)
                        cache_df.to_parquet(os.path.join(self.cache_dir, f"{sym.replace('-', '_')}.parquet"))
                        all_data[sym] = df[sym]
                        print(f"  Loaded {sym}: {len(df)} bars")
                    else:
                        print(f"WARNING: No data for {sym}")
                except Exception as e:
                    print(f"Error loading {sym}: {e}")
            else:
                print(f"WARNING: yfinance not available, cannot fetch {sym}")
        
        if not all_data:
            raise ValueError("No data loaded!")
        
        # Combine and align
        prices = pd.DataFrame(all_data).sort_index()
        prices = prices.ffill().dropna()
        return prices


# ============================================================
# STRATEGY 1: MATERIALS-BASED (Risk Parity / Vol Targeting / MDD-based)
# ============================================================

class MaterialsStrategy:
    """
    Experiment 1: Materials-based strategy
    
    Core ideas from materials:
    - Volatility targeting (risk parity style)
    - MDD-based risk management
    - Volatility-based position sizing
    - US equity focus with defensive assets
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.name = "Materials_Based"
    
    def compute_signals(self, prices: pd.DataFrame, date: pd.Timestamp) -> Dict[str, float]:
        """Compute target weights for each asset at given date"""
        # Get data up to date (exclusive - no lookahead)
        hist = prices.loc[:date].copy()
        if len(hist) < 60:
            return {col: 1.0/len(self.config.assets) for col in self.config.assets}
        
        # Compute returns
        returns = hist.pct_change().dropna()
        
        # 1. Volatility targeting (Risk Parity style)
        # Use 63-day rolling vol (3 months)
        vol_window = 63
        if len(returns) < vol_window:
            return {col: 1.0/len(self.config.assets) for col in self.config.assets}
        
        vol = returns.tail(vol_window).std() * np.sqrt(252)
        vol = vol.replace(0, np.nan).fillna(method='bfill')
        
        # Risk parity weights (inverse volatility)
        inv_vol = 1.0 / vol
        rp_weights = inv_vol / inv_vol.sum()
        
        # 2. MDD-based risk management
        # Compute trailing MDD for each asset
        mdd_lookback = 252  # 1 year
        if len(hist) >= mdd_lookback:
            recent = hist.tail(mdd_lookback)
            cummax = recent.cummax()
            mdd = (recent / cummax - 1).min()
            # Reduce weight for assets with deep MDD
            mdd_penalty = 1 + mdd  # mdd is negative, so this reduces weight
            mdd_penalty = mdd_penalty.clip(0.2, 1.0)
        else:
            mdd_penalty = pd.Series(1.0, index=hist.columns)
        
        # 3. Momentum filter (12-month)
        mom_period = 252
        if len(hist) >= mom_period:
            mom = hist.iloc[-1] / hist.iloc[-mom_period] - 1
            mom_signal = (mom > 0).astype(float) * 0.5 + 0.5  # 0.5 to 1.0
        else:
            mom_signal = pd.Series(0.75, index=hist.columns)
        
        # 4. Combine weights
        # Base: Risk Parity
        weights = rp_weights * mdd_penalty * mom_signal
        
        # Normalize
        weights = weights / weights.sum()
        
        # Apply constraints
        weights = weights.clip(self.config.min_weight, self.config.max_weight)
        weights = weights / weights.sum()
        
        # Ensure all assets present
        for col in self.config.assets:
            if col not in weights:
                weights[col] = 0.0
        
        return weights.to_dict()


# ============================================================
# STRATEGY 2: GPT REGIME STRATEGY
# ============================================================

class RegimeStrategy:
    """
    Experiment 2: GPT Regime Strategy
    
    Market Regime Detection:
    - Bull: SPY > SMA(200) AND VIX < 20
    - Neutral: SPY > SMA(200) XOR VIX < 20 (mixed)
    - Risk-Off: SPY < SMA(200) OR VIX > 30
    
    Allocation by regime:
    - Bull: 100% Equity (SPY/QQQ), 0% Bonds/Gold
    - Neutral: 60% Equity, 40% Bonds/Gold
    - Risk-Off: 20% Equity, 80% Bonds/Gold
    
    Within equity: SPY/QQQ split by momentum
    Within defensive: TLT/IEF/GLD split by vol/sharpe
    """
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.name = "GPT_Regime"
    
    def detect_regime(self, prices: pd.DataFrame, date: pd.Timestamp) -> str:
        """Detect market regime at given date"""
        hist = prices.loc[:date].copy()
        if len(hist) < 200:
            return "neutral"
        
        # Get SPY data
        if 'SPY' not in hist.columns:
            return "neutral"
        
        spy = hist['SPY']
        spy_sma200 = spy.rolling(200).mean().iloc[-1]
        spy_price = spy.iloc[-1]
        
        # VIX proxy: 20-day realized vol of SPY * sqrt(252) * 100
        spy_returns = spy.pct_change().dropna()
        if len(spy_returns) >= 20:
            vix_proxy = spy_returns.tail(20).std() * np.sqrt(252) * 100
        else:
            vix_proxy = 20.0
        
        # Regime logic
        spy_above_sma = spy_price > spy_sma200
        vix_low = vix_proxy < 20
        vix_high = vix_proxy > 30
        
        if spy_above_sma and vix_low:
            return "bull"
        elif (not spy_above_sma) or vix_high:
            return "risk_off"
        else:
            return "neutral"
    
    def compute_signals(self, prices: pd.DataFrame, date: pd.Timestamp) -> Dict[str, float]:
        """Compute target weights based on regime"""
        hist = prices.loc[:date].copy()
        if len(hist) < 200:
            return {col: 1.0/len(self.config.assets) for col in self.config.assets}
        
        regime = self.detect_regime(prices, date)
        
        # Base allocation by regime
        if regime == "bull":
            equity_weight = 1.0
            defensive_weight = 0.0
        elif regime == "neutral":
            equity_weight = 0.6
            defensive_weight = 0.4
        else:  # risk_off
            equity_weight = 0.2
            defensive_weight = 0.8
        
        # Split equity between SPY/QQQ based on momentum
        equity_assets = ['SPY', 'QQQ']
        defensive_assets = ['TLT', 'IEF', 'GLD', 'DBC', 'VNQ', 'EFA', 'EEM']
        
        # Momentum for equity split
        equity_hist = prices[equity_assets].loc[:date].tail(63)
        if len(equity_hist) >= 20:
            mom = equity_hist.iloc[-1] / equity_hist.iloc[-20] - 1
            spy_w = 0.5 + 0.5 * np.tanh(mom['SPY'] - mom['QQQ'])  # -0.5 to 0.5 adjustment
            spy_w = np.clip(spy_w, 0.2, 0.8)
        else:
            spy_w = 0.5
        
        # Defensive split: inverse volatility
        def_hist = prices[defensive_assets].loc[:date].tail(63).pct_change().dropna()
        if len(def_hist) >= 20:
            def_vol = def_hist.std() * np.sqrt(252)
            inv_vol = 1.0 / def_vol.replace(0, np.nan).fillna(method='bfill')
            def_weights = inv_vol / inv_vol.sum()
        else:
            def_weights = pd.Series(1.0/len(defensive_assets), index=defensive_assets)
        
        # Build final weights
        weights = {}
        for a in equity_assets:
            weights[a] = equity_weight * (spy_w if a == 'SPY' else 1-spy_w)
        for a in defensive_assets:
            weights[a] = defensive_weight * def_weights.get(a, 0)
        
        # Normalize
        total = sum(weights.values())
        if total > 0:
            weights = {k: v/total for k, v in weights.items()}
        
        # Ensure all assets present
        for col in self.config.assets:
            if col not in weights:
                weights[col] = 0.0
        
        return weights


# ============================================================
# BACKTEST ENGINE
# ============================================================

class BacktestEngine:
    """Monthly rebalance backtest engine with transaction costs"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.cost_per_trade = config.cost_bps / 10000  # bps to decimal
        self.slippage = config.slippage_bps / 10000
    
    def run(self, prices: pd.DataFrame, strategy, config: BacktestConfig) -> Dict:
        """Run backtest for a strategy"""
        rebalance_dates = self._get_rebalance_dates(prices.index, config)
        
        portfolio_value = config.initial_capital
        weights = {col: 1.0/len(config.assets) for col in config.assets}
        # positions stores SHARES, not dollar values
        positions = {col: 0.0 for col in config.assets}
        cash = config.initial_capital
        
        equity_curve = []
        trade_log = []
        weight_history = []
        
        for i, date in enumerate(rebalance_dates):
            # Get target weights
            target_weights = strategy.compute_signals(prices, date)
            
            # Get current prices
            prices_today = prices.loc[date] if date in prices.index else prices.loc[:date].iloc[-1]
            
            # Calculate current portfolio value from SHARES * PRICES
            portfolio_value = cash
            for asset, shares in positions.items():
                if asset in prices_today.index and shares != 0:
                    portfolio_value += shares * prices_today[asset]
            
            # Calculate target positions (in SHARES)
            target_positions = {}
            for asset, weight in target_weights.items():
                if asset in prices_today.index and prices_today[asset] > 0:
                    target_value = portfolio_value * weight
                    target_positions[asset] = target_value / prices_today[asset]
            
            # Calculate trades (in SHARES)
            trades = {}
            for asset in config.assets:
                current_shares = positions.get(asset, 0)
                target_shares = target_positions.get(asset, 0)
                trade_shares = target_shares - current_shares
                if abs(trade_shares) > 1e-6:
                    trades[asset] = trade_shares
            
            # Execute trades (at same day close - simplified)
            trade_cost = 0
            for asset, shares in trades.items():
                if asset in prices_today.index and prices_today[asset] > 0:
                    trade_value = abs(shares) * prices_today[asset]
                    cost = trade_value * (self.cost_per_trade + self.slippage)
                    trade_cost += cost
                    if shares > 0:  # Buy
                        cash -= trade_value + cost
                    else:  # Sell
                        cash += trade_value - cost
                    positions[asset] = positions.get(asset, 0) + shares
            
            # Record equity (portfolio_value already includes trade costs via cash adjustment)
            equity_curve.append({
                'date': date,
                'portfolio_value': portfolio_value - trade_cost,
                'cash': cash,
                **{f'pos_{k}': v for k, v in positions.items()},
                **{f'w_{k}': target_weights.get(k, 0) for k in target_weights}
            })
            
            weight_history.append({**{'date': date}, **target_weights})
        
        # Calculate metrics
        equity_df = pd.DataFrame(equity_curve).set_index('date')
        equity_df['return'] = equity_df['portfolio_value'].pct_change()
        
        # Calculate metrics
        returns = equity_df['return'].dropna()
        metrics = self._calculate_metrics(returns, equity_df['portfolio_value'])
        
        # Trade stats
        trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
        
        return {
            'equity_curve': equity_df,
            'weight_history': pd.DataFrame(weight_history).set_index('date'),
            'metrics': metrics,
            'trades': trades_df,
            'final_value': equity_df['portfolio_value'].iloc[-1],
        }
    
    def _get_rebalance_dates(self, index: pd.DatetimeIndex, config: BacktestConfig) -> List[pd.Timestamp]:
        """Get monthly rebalance dates (first trading day of each month)"""
        # Convert to period, group, get first date of each month
        periods = index.to_period('M')
        first_dates = index[~periods.duplicated(keep='first')]
        start_ts = pd.Timestamp(config.start_date) + pd.DateOffset(months=3)
        return [d for d in first_dates if d >= start_ts]
    
    def _calculate_metrics(self, returns: pd.Series, equity: pd.Series) -> Dict:
        """Calculate performance metrics"""
        total_ret = (equity.iloc[-1] / equity.iloc[0]) - 1
        years = (equity.index[-1] - equity.index[0]).days / 365.25
        cagr_val = (1 + total_ret) ** (1/years) - 1 if years > 0 else 0
        
        # MDD
        cum = (1 + returns).cumprod()
        running_max = np.maximum.accumulate(cum)
        dd = (cum / running_max - 1).min()
        
        # Sharpe
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        # Sortino
        downside = returns[returns < 0]
        sortino = returns.mean() / downside.std() * np.sqrt(252) if len(downside) > 0 and downside.std() > 0 else 0
        
        # Calmar
        calmar = cagr_val / abs(dd) if dd != 0 else 0
        
        # Win rate
        winrate = (returns > 0).mean()
        
        return {
            'total_return': total_ret,
            'cagr': cagr_val,
            'mdd': dd,
            'sharpe': sharpe,
            'sortino': sortino,
            'calmar': calmar,
            'winrate': winrate,
            'volatility': returns.std() * np.sqrt(252),
            'num_trades': 0,  # placeholder
        }


# ============================================================
# MAIN EXECUTION
# ============================================================

def run_experiment():
    """Run both experiments and compare"""
    print("="*80)
    print("REGIME STRATEGY COMPARISON EXPERIMENT")
    print("="*80)
    
    # Configuration
    config = BacktestConfig(
        start_date="2015-01-01",
        end_date="2024-12-31",
        initial_capital=100_000_000,
    )
    
    # Load data
    print("\n[1/4] Loading market data...")
    dm = DataManager(config)
    prices = dm.load_data(list(config.assets.keys()), config.start_date, config.end_date)
    print(f"Loaded {len(prices)} rows, {len(prices.columns)} assets")
    print(f"Date range: {prices.index[0].date()} to {prices.index[-1].date()}")
    
    # Initialize strategies
    print("\n[2/4] Initializing strategies...")
    materials_strat = MaterialsStrategy(BacktestConfig())
    regime_strat = RegimeStrategy(BacktestConfig())
    
    # Run backtests
    print("\n[3/4] Running backtests...")
    engine = BacktestEngine(BacktestConfig())
    
    print("\n--- Running Materials-Based Strategy ---")
    materials_result = engine.run(prices, MaterialsStrategy(BacktestConfig()), BacktestConfig())
    
    print("\n--- Running Regime Strategy ---")
    regime_result = engine.run(prices, RegimeStrategy(BacktestConfig()), BacktestConfig())
    
    # Compare results
    print("\n[4/4] Comparing results...")
    compare_results(materials_result, regime_result)
    
    # Save results
    save_results(materials_result, regime_result)
    
    return materials_result, regime_result


def compare_results(r1: Dict, r2: Dict):
    """Print comparison of two backtest results"""
    print("\n" + "="*80)
    print("BACKTEST COMPARISON")
    print("="*80)
    
    m1, m2 = r1['metrics'], r2['metrics']
    
    print(f"\n{'Metric':<20} {'Materials':>15} {'Regime':>15} {'Diff':>15}")
    print("-"*65)
    for key in ['total_return', 'cagr', 'mdd', 'sharpe', 'sortino', 'calmar', 'winrate', 'volatility']:
        v1 = m1.get(key, 0)
        v2 = m2.get(key, 0)
        diff = v2 - v1
        if key in ['mdd']:
            diff = v2 - v1  # For MDD, less negative is better
        print(f"{key:<20} {v1:>15.4f} {v2:>15.4f} {diff:>+15.4f}")
    
    # Final values
    print(f"\n{'Final Value':<20} {r1['final_value']:>15,.0f} {r2['final_value']:>15,.0f}")
    
    # Equity curves comparison
    eq1 = r1['equity_curve']['portfolio_value']
    eq2 = r2['equity_curve']['portfolio_value']
    
    # Align dates
    common_dates = eq1.index.intersection(eq2.index)
    if len(common_dates) > 0:
        eq1_aligned = eq1.loc[common_dates]
        eq2_aligned = eq2.loc[common_dates]
        corr = np.corrcoef(eq1_aligned.pct_change().dropna(), eq2_aligned.pct_change().dropna())[0,1]
        print(f"Equity Correlation: {corr:.4f}")


def save_results(r1: Dict, r2: Dict):
    """Save results to files"""
    out_dir = os.path.join(os.path.dirname(__file__), "..", "reports", f"regime_comparison_{datetime.now().strftime('%Y%m%d')}")
    os.makedirs(out_dir, exist_ok=True)
    
    # Save equity curves
    r1['equity_curve'].to_parquet(os.path.join(out_dir, "materials_equity.parquet"))
    r2['equity_curve'].to_parquet(os.path.join(out_dir, "regime_equity.parquet"))
    
    r1['weight_history'].to_parquet(os.path.join(out_dir, "materials_weights.parquet"))
    r2['weight_history'].to_parquet(os.path.join(out_dir, "regime_weights.parquet"))
    
    # Save metrics
    with open(os.path.join(out_dir, "comparison.json"), 'w') as f:
        json.dump({
            'materials': r1['metrics'],
            'regime': r2['metrics'],
        }, f, indent=2, default=str)
    
    print(f"\nResults saved to {out_dir}")


if __name__ == "__main__":
    # Check yfinance
    if not YFINANCE_AVAILABLE:
        print("ERROR: yfinance not installed. Run: pip install yfinance")
        sys.exit(1)
    
    run_experiment()