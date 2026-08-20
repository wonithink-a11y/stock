#!/usr/bin/env python
"""SL-2 step 0: read full_smoke_result.pkl ONCE (667MB) and write a slim,
reusable dataset so every later analysis is seconds instead of minutes.

Read-only w.r.t. the source pickle. Writes only into reports/2026-08-16-sl2-sequential/.

Emits:
  slim_trades.json      2,154 portfolio-admitted closed positions (flat dicts)
  slim_resolved.json    all instrument-level resolved trades (pre-portfolio)
  slim_diag.json        runner diag + portfolio cash + params
  trade_paths.pkl       per resolved trade: the OHLC window from order_date over
                        the full max_holding horizon (needed for MFE/MAE and for
                        re-simulating alternative stop rules) - small, ~2k x 60 rows
  daily_closes.pkl      {date: {symbol: close}} restricted to symbols that ever
                        held a position (needed for any mark-to-market equity curve)
  sessions.json         trading calendar sessions over the backtest window
"""
import os
import pickle
import json
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "reports", "2026-08-16-sl2-sequential")
START, END = "2014-05-13", "2026-08-03"

print("loading pickle ...", flush=True)
with open(os.path.join(HERE, "full_smoke_result.pkl"), "rb") as f:
    result = pickle.load(f)
print("loaded", flush=True)

portfolio = result["portfolio"]
bars_by_ticker = result["bars_by_ticker"]
calendar = result["calendar"]
resolved = result["resolved"]
diag = result["diag"]
params = result["params"]


def fill_d(fill):
    return {"date": fill.fill_date, "price": float(fill.fill_price),
            "type": fill.fill_type, "cost_bps": float(fill.cost_bps)}


trades = []
for p in portfolio.closed_positions:
    trades.append({
        "symbol": p["symbol"],
        "shares": int(p["shares"]),
        "pnl": float(p["pnl"]),
        "entry_date": p["entry_date"],
        "exit_date": p["exit_date"],
        "entry": fill_d(p["entry"]),
        "exit": fill_d(p["exit"]),
        "entry_fill_date": p["entry"].fill_date,
        "order_date": p["entry"].order.order_date,
        "signal_date": p["entry"].order.signal_date,
        "stop_distance": float(p["entry"].order.risk_spec.stop_distance),
        "reward_risk": float(p["entry"].order.risk_spec.reward_risk),
        "max_holding": int(p["entry"].order.risk_spec.max_holding_sessions),
    })

res_slim = []
for sig, order, entry_fill, exit_fill, risk_spec, atr_t in resolved:
    res_slim.append({
        "symbol": order.symbol,
        "signal_date": sig.signal_date,
        "order_date": order.order_date,
        "entry": fill_d(entry_fill),
        "exit": fill_d(exit_fill),
        "atr_at_signal": float(atr_t),
        "stop_distance": float(risk_spec.stop_distance),
        "reward_risk": float(risk_spec.reward_risk),
        "max_holding": int(risk_spec.max_holding_sessions),
    })

json.dump(trades, open(os.path.join(OUT, "slim_trades.json"), "w"), indent=0)
json.dump(res_slim, open(os.path.join(OUT, "slim_resolved.json"), "w"), indent=0)
json.dump({"diag": {k: (dict(v) if hasattr(v, "items") else v) for k, v in diag.items()},
           "portfolio_cash": float(portfolio.cash),
           "open_at_end": len(portfolio.open_positions),
           "params": params},
          open(os.path.join(OUT, "slim_diag.json"), "w"), indent=1, default=str)

sessions = calendar.sessions_between(START, END)
sessions = [s if isinstance(s, str) else s.strftime("%Y-%m-%d") for s in sessions]
json.dump(sessions, open(os.path.join(OUT, "sessions.json"), "w"))

# --- per-trade forward OHLC window (order_date .. +max_holding sessions) ---
paths = {}
for i, r in enumerate(res_slim):
    sym = r["symbol"]
    bars = bars_by_ticker.get(sym)
    if bars is None:
        continue
    window = calendar.next_n_sessions(r["order_date"], r["max_holding"])
    window = [w if isinstance(w, str) else w.strftime("%Y-%m-%d") for w in window]
    rows = []
    for d in window:
        if d in bars.index:
            row = bars.loc[d]
            rows.append((d, float(row["open"]), float(row["high"]),
                         float(row["low"]), float(row["close"])))
    paths[(sym, r["order_date"])] = rows
pickle.dump(paths, open(os.path.join(OUT, "trade_paths.pkl"), "wb"))

# --- daily closes for every symbol that ever held a portfolio position ---
symbols = {t["symbol"] for t in trades}
daily_closes = {}
for sym in symbols:
    bars = bars_by_ticker.get(sym)
    if bars is None:
        continue
    for idx, row in bars.iterrows():
        d = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        daily_closes.setdefault(d, {})[sym] = float(row["close"])
pickle.dump(daily_closes, open(os.path.join(OUT, "daily_closes.pkl"), "wb"))

print(f"trades={len(trades)} resolved={len(res_slim)} paths={len(paths)} "
      f"sessions={len(sessions)} closeDates={len(daily_closes)} symbols={len(symbols)}")
print("portfolio.cash =", portfolio.cash, "open_at_end =", len(portfolio.open_positions))
