"""B0 - Market/Universe Buy & Hold benchmark (spec confirmed 2026-08-14).

Unlike B1/B2/B3, this is not a signal-driven strategy and does not go through
engine/execution or engine/portfolio at all - there is no stop/target/time-exit
and no max_positions concentration limit (a passive full-universe benchmark
is not the same kind of thing as a concentrated 10-slot strategy, and forcing
it through that machinery was the exact contract mismatch flagged before
implementing).

    universe    A1A_ONLY, every ticker with any data in [start, end]
    weight      equal across all such tickers
    entry       each ticker's own first available session, at that day's close
    exit        each ticker's own last available session, at that day's close
    rebalance   none
    cost        entry cost once, exit cost once (same bps as the strategy family)
"""
import pandas as pd


def compute_trades(bars_by_ticker, initial_capital, entry_cost_bps, exit_cost_bps):
    tickers = [t for t, df in bars_by_ticker.items() if not df.empty]
    if not tickers:
        return [], 0.0
    alloc = initial_capital / len(tickers)

    trades = []
    for t in tickers:
        df = bars_by_ticker[t]
        entry_date, exit_date = df.index[0], df.index[-1]
        entry_price = float(df.loc[entry_date, "close"])
        exit_price = float(df.loc[exit_date, "close"])
        all_in_entry_price = entry_price * (1 + entry_cost_bps / 10000)
        shares = int(alloc // all_in_entry_price)
        if shares <= 0:
            continue
        cost_basis = entry_price * shares * (1 + entry_cost_bps / 10000)
        proceeds = exit_price * shares * (1 - exit_cost_bps / 10000)
        trades.append({
            "symbol": t,
            "entry_date": entry_date.strftime("%Y-%m-%d"), "entry_price": entry_price,
            "exit_date": exit_date.strftime("%Y-%m-%d"), "exit_price": exit_price,
            "shares": shares, "cost_basis": cost_basis, "proceeds": proceeds,
            "pnl": proceeds - cost_basis, "holding_sessions": len(df),
        })
    return trades, alloc


def compute_equity_curve(bars_by_ticker, trades, alloc, initial_capital, master_dates):
    """Daily mark-to-market: before a ticker's own entry date its allocated
    capital sits as cash; between entry and exit it's marked at that ticker's
    close (forward-filled across any gap days); after exit it's the realized,
    constant proceeds. Uninvested cash from any skipped (unaffordable) ticker
    stays flat cash for the whole period."""
    if not trades:
        return [(master_dates[0], initial_capital), (master_dates[-1], initial_capital)]

    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in master_dates])
    panel = pd.DataFrame(index=idx)
    for tr in trades:
        t = tr["symbol"]
        s = bars_by_ticker[t]["close"].reindex(idx)
        entry_d, exit_d = pd.Timestamp(tr["entry_date"]), pd.Timestamp(tr["exit_date"])
        s = s.ffill()
        col = s * tr["shares"]
        col.loc[idx < entry_d] = alloc
        col.loc[idx > exit_d] = tr["proceeds"]
        panel[t] = col

    # capital earmarked for tickers that turned out unaffordable (shares<=0,
    # skipped from `trades`) stays as flat, uncommitted cash for the whole period
    uninvested_cash = initial_capital - alloc * len(trades)
    daily_total = panel.sum(axis=1, skipna=True) + uninvested_cash
    return [(d.strftime("%Y-%m-%d"), float(v)) for d, v in daily_total.items()]
