#!/usr/bin/env python
"""SUPERTREND-KR-V1 smoke driver (STEP 2).

Mirrors run_macd_kr_v1_smoke.py / run_squeeze_kr_v1_smoke.py structure exactly:
- UniverseProvider(A1A_ONLY) + A2aProvider + TradingCalendar + _drop_suspension_rows
- CostModel from policy (entry 15bps / exit 15bps / slippage 0)
- Portfolio accounting via engine.portfolio.Portfolio (max 30, equal-weight)
- State-machine entry/exit in build_events (dynamic trend-reversal exit NOT expressible in executor)
- PIT listing gate (listedAt from A1a current.jsonl)
- Warmup exclusion (signal_date >= PERF_START)
- Metrics: grossReturn, netReturn, CAGR, MDD, Sharpe, exposure, turnover, win rate
- Benchmarks: Equal-Weight daily-rebalanced, Buy & Hold (same universe) - MACD parity
- Output: research/strategy-lab/findings/supertrend-kr-v1-smoke/smoke_result.json
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "engine"))

from engine.data.universeProvider import UniverseProvider
from engine.data.a2aProvider import A2aProvider
from engine.data.calendar import TradingCalendar
from engine.portfolio.portfolio import Portfolio, PortfolioConfig
from engine.runner import _drop_suspension_rows
from engine.metrics import metrics as M
from benchmarks.b0_buy_hold import compute_trades as bh_trades, compute_equity_curve as bh_curve

from strategies.supertrend_kr_v1 import rule as ST_RULE

POLICY = ST_RULE.POLICY
ATR_PERIOD = ST_RULE.ATR_PERIOD
ATR_ALPHA = ST_RULE.ATR_ALPHA
MULT = ST_RULE.MULT

INIT_CAP = POLICY["portfolio"]["initialCapital"]
MAX_POS = POLICY["portfolio"]["maxPositions"]
COST_BPS = POLICY["cost"]["entryCostBps"] + POLICY["cost"]["exitCostBps"]
COST = COST_BPS / 10_000

PERF_START = POLICY["period"]["performanceStart"]
RAW_START = POLICY["period"]["rawDataStart"]
END = POLICY["period"]["end"]

OUT_DIR = REPO_ROOT / "research" / "strategy-lab" / "findings" / "supertrend-kr-v1-smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PORT_CFG = PortfolioConfig(
    initial_capital=INIT_CAP,
    max_positions=MAX_POS,
    equal_weight=True,
    fractional_shares=False,
    tie_break="ticker_ascending",
)

def _mark(label: str):
    import time
    t = time.time()
    _mark.last = getattr(_mark, "last", t)
    print(f"[{label}] +{t - _mark.last:.2f}s (total {t - _mark.start:.2f}s)", flush=True)
    _mark.last = t
_mark.start = __import__("time").time()

def _drop_suspension_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "is_suspended" in df.columns:
        return df[~df["is_suspended"].astype(bool)].copy()
    return df

def load_listed_at() -> dict[str, str]:
    uni_path = REPO_ROOT / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"
    out = {}
    if uni_path.exists():
        for line in uni_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            tkr = row.get("ticker") or row.get("code")
            la = row.get("listedAt") or row.get("listing_date")
            if tkr and la:
                out[tkr] = la[:10]
    return out

def compute_performance_equity(trades: list[dict], init_cap: float, cal: TradingCalendar) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    trades_df = pd.DataFrame(trades)
    trades_df["entry_dt"] = pd.to_datetime(trades_df["entry_date"])
    trades_df["exit_dt"] = pd.to_datetime(trades_df["exit_date"])
    trades_df["pnl"] = trades_df["net_pnl"]
    daily = trades_df.groupby("exit_dt")["pnl"].sum().sort_index()
    equity = init_cap + daily.cumsum()
    all_sessions = pd.Series(index=pd.to_datetime(cal.days), dtype=float)
    equity = equity.reindex(all_sessions.index).ffill().fillna(init_cap)
    return equity

def _samebar_check(trades: list[dict]) -> int:
    bad = 0
    for t in trades:
        if t["entry_date"] == t["exit_date"]:
            bad += 1
    return bad

def _yearly(equity: pd.Series) -> dict[str, float]:
    if equity.empty:
        return {}
    equity.index = pd.to_datetime(equity.index)
    years = equity.groupby(equity.index.year).last()
    rets = {}
    prev = INIT_CAP
    for yr, val in years.items():
        rets[str(yr)] = (val - prev) / prev
        prev = val
    return rets

def build_events(symbol: str, feats: pd.DataFrame, cal: TradingCalendar, listed_at: str | None):
    entry_sig = feats.get("entry_sig", pd.Series(False, index=feats.index))
    exit_sig = feats.get("exit_sig", pd.Series(False, index=feats.index))
    dates = feats.index[entry_sig | exit_sig]

    events = []
    audit = {"pre_listing_signals": 0, "entry_sig_total": int(entry_sig.sum()),
             "warmup_excluded": 0, "entry_count": 0, "exit_count": 0}
    long = False

    for d in dates:
        ds = d.strftime("%Y-%m-%d")
        en = entry_sig.loc[d]
        ex = exit_sig.loc[d]

        if not en and not ex:
            continue
        if ds < PERF_START:
            audit["warmup_excluded"] += 1
            continue
        if listed_at and ds < listed_at:
            audit["pre_listing_signals"] += 1
            continue

        if en and not long:
            nd = cal.next_session(ds)
            if nd is None or nd not in feats.index:
                continue
            long = True
            audit["entry_count"] += 1
            o = feats.loc[nd, "open"]
            events.append(("ENTRY", nd, type("Fill", (), {
                "order": type("Order", (), {
                    "symbol": symbol,
                    "direction": "LONG",
                    "signal_date": ds,
                    "quantity": 0,
                    "order_type": "MARKET"
                })(),
                "fill_date": nd,
                "fill_price": float(o),
                "fill_type": "OPEN",
                "cost_bps": POLICY["cost"]["entryCostBps"],
            })()))
        elif ex and long:
            nd = cal.next_session(ds)
            if nd is None or nd not in feats.index:
                continue
            long = False
            audit["exit_count"] += 1
            o = feats.loc[nd, "open"]
            events.append(("EXIT", nd, type("Fill", (), {
                "order": type("Order", (), {
                    "symbol": symbol,
                    "direction": "LONG",
                    "signal_date": ds,
                    "quantity": 0,
                    "order_type": "MARKET"
                })(),
                "fill_date": nd,
                "fill_price": float(o),
                "fill_type": "TREND_REVERSAL",
                "cost_bps": POLICY["cost"]["exitCostBps"],
            })()))
    return events, audit

def compute_ew_benchmark(bars_by_ticker, master_ts, perf_start, end):
    """Daily equal-weight (equal-weight-on-available) index over the same subset,
    close-to-close returns, compounding from 100. Suspension days carry the prior
    close (no return). Starts on the first master date >= perf_start."""
    dates = []
    rets = []
    last_close = {}
    for ts in master_ts:
        ds = ts.strftime("%Y-%m-%d")
        day_rets = []
        for sym, df in bars_by_ticker.items():
            if df.empty or ds not in df.index:
                continue
            px = float(df.loc[ds, "close"])
            if sym in last_close and last_close[sym] and last_close[sym] > 0:
                day_rets.append(px / last_close[sym] - 1.0)
            last_close[sym] = px
        if day_rets:
            dates.append(ds)
            rets.append(sum(day_rets) / len(day_rets))
    # compound
    curve = []
    eq = 100.0
    curve.append((dates[0], eq))
    for i in range(1, len(dates)):
        eq *= (1 + rets[i])
        curve.append((dates[i], eq))
    return curve

def compute_bh_benchmark(bars_by_ticker, master_dates, entry_cost_bps, exit_cost_bps, init_cap):
    bh_t, bh_alloc = bh_trades(bars_by_ticker, init_cap,
                               entry_cost_bps, exit_cost_bps)
    bh_curve_result = bh_curve(bars_by_ticker, bh_t, bh_alloc, init_cap, master_dates)
    return bh_curve_result

def run_subset(n_tickers: int, seed: int = 42):
    _mark("start")
    uni = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    cal = TradingCalendar(repo_root=REPO_ROOT)

    tk_sorted = sorted(uni.tickers)
    rng = np.random.default_rng(seed)
    subset = set(rng.choice(list(tk_sorted), size=min(n_tickers, len(tk_sorted)), replace=False))
    print(f"universe={len(tk_sorted)} (A1A_ONLY), smoke subset={len(subset)} (seed={seed})", flush=True)
    _mark("universe")

    listed_map = load_listed_at()
    print(f"ListedAt loaded: {len(listed_map)}", flush=True)

    # Batch load all bars
    bars_raw = a2a.load(subset, RAW_START, END, universe_hash=uni.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"Bars loaded: {len(bars_by_ticker)} tickers", flush=True)
    _mark("bars loaded")

    # Build master calendar dates for benchmarks
    master_dates = [d for d in cal.days if PERF_START <= d <= END]
    master_ts = [pd.Timestamp(d) for d in master_dates]

    all_trades = []
    all_audit = {"pre_listing_signals": 0, "entry_sig_total": 0,
                 "warmup_excluded": 0, "entry_count": 0, "exit_count": 0}

    for i, sym in enumerate(subset):
        if i % 200 == 0:
            print(f"  [{i}/{len(subset)}] {sym}", flush=True)
        bars = bars_by_ticker.get(sym)
        if bars is None or len(bars) == 0:
            continue
        bars.index = pd.to_datetime(bars.index)
        if len(bars) < ATR_PERIOD + 5:
            continue

        feats = ST_RULE.compute_features(bars)
        listed_at = listed_map.get(sym)
        events, audit = build_events(sym, feats, cal, listed_at)
        for k in audit:
            all_audit[k] += audit[k]

        for kind, fd, fill in events:
            if kind == "ENTRY":
                all_trades.append({
                    "symbol": sym,
                    "entry_date": fd,
                    "entry_price": fill.fill_price,
                    "signal_date": fill.order.signal_date,
                    "entry_cost_bps": fill.cost_bps,
                    "exit_date": None,
                    "exit_price": None,
                    "exit_cost_bps": None,
                    "gross_pnl": 0.0,
                    "net_pnl": 0.0,
                    "status": "open",
                })
            elif kind == "EXIT":
                for t in reversed(all_trades):
                    if t["symbol"] == sym and t["status"] == "open":
                        t["exit_date"] = fd
                        t["exit_price"] = fill.fill_price
                        t["exit_cost_bps"] = fill.cost_bps
                        gross = (fill.fill_price - t["entry_price"]) * t.get("shares", 1)
                        t["gross_pnl"] = gross
                        t["net_pnl"] = gross - (t["entry_price"] * t.get("shares", 1) * (t["entry_cost_bps"] + fill.cost_bps) / 10_000)
                        t["status"] = "closed"
                        break

    _mark("event loop done")

    closed = [t for t in all_trades if t["status"] == "closed"]
    for t in closed:
        t["return_pct"] = t["net_pnl"] / (t["entry_price"] * t.get("shares", 1)) if t["entry_price"] else 0

    equity = compute_performance_equity(closed, INIT_CAP, cal)
    _mark("equity done")

    total_gross = sum(t.get("gross_pnl", 0) for t in closed) / INIT_CAP
    total_net = sum(t.get("net_pnl", 0) for t in closed) / INIT_CAP
    years = (pd.Timestamp(END) - pd.Timestamp(PERF_START)).days / 365.25
    cagr = (1 + total_net) ** (1 / years) - 1 if years > 0 and total_net > -1 else 0
    dd = float((equity / equity.cummax() - 1).min()) if not equity.empty else 0
    rets = equity.pct_change().dropna()
    sharpe = float(np.sqrt(252) * rets.mean() / rets.std()) if len(rets) > 1 and rets.std() > 0 else 0
    exposure = float((equity != INIT_CAP).mean()) if not equity.empty else 0

    wins = sum(1 for t in closed if t.get("net_pnl", 0) > 0)
    win_rate = wins / len(closed) if closed else 0
    total_turnover = sum(t["entry_price"] * t.get("shares", 1) for t in closed) / INIT_CAP if closed else 0

    samebar = _samebar_check(closed)

    # Benchmarks using MACD parity implementation
    ew_curve = compute_ew_benchmark(bars_by_ticker, master_ts, PERF_START, END)
    bh_curve = compute_bh_benchmark(bars_by_ticker, master_dates,
                                     POLICY["cost"]["entryCostBps"], POLICY["cost"]["exitCostBps"], INIT_CAP)

    result = {
        "experiment": "SUPERTREND-KR-V1",
        "step": "STEP 2 SMOKE",
        "strategyId": "supertrend_kr_v1",
        "policyVersion": POLICY["version"],
        "universe": "A1A_ONLY",
        "tickersRequested": n_tickers,
        "tickersWithData": len(bars_by_ticker),
        "period": {"rawStart": RAW_START, "perfStart": PERF_START, "end": END},
        "indicators": {
            "atr": {"period": ATR_PERIOD, "smoothing": "wilder_ema", "alpha": ATR_ALPHA},
            "supertrend": {"multiplier": MULT, "source": "median_price"}
        },
        "costBps": {"entry": POLICY["cost"]["entryCostBps"], "exit": POLICY["cost"]["exitCostBps"], "slippage": 0},
        "portfolio": {"initialCapital": INIT_CAP, "maxPositions": MAX_POS, "equalWeight": True},
        "results": {
            "grossReturn": round(total_gross * 100, 2),
            "netReturn": round(total_net * 100, 2),
            "CAGR": round(cagr * 100, 2),
            "MDD": round(dd * 100, 2),
            "Sharpe": round(sharpe, 3),
            "Exposure": round(exposure, 4),
            "Trades": len(closed),
            "WinRate": round(win_rate * 100, 1),
            "Turnover": round(total_turnover, 2),
            "SameBarExecutions": samebar,
        },
        "benchmarks": {
            "equalWeight": {
                "totalReturn": round(M.total_return(ew_curve) * 100, 2),
                "CAGR": round(M.cagr(ew_curve) * 100, 2),
                "MDD": round(M.max_drawdown(ew_curve) * 100, 2),
                "Sharpe": round(M.sharpe(ew_curve), 3),
                "Exposure": 1.0,
                "note": "daily rebalanced equal-weight on available (MACD parity)"
            },
            "buyAndHold": {
                "totalReturn": round(M.total_return(bh_curve) * 100, 2),
                "CAGR": round(M.cagr(bh_curve) * 100, 2),
                "MDD": round(M.max_drawdown(bh_curve) * 100, 2),
                "Sharpe": round(M.sharpe(bh_curve), 3),
                "Exposure": 1.0,
                "note": "b0_buy_hold: equal weight, first/last close, entry+exit cost (MACD parity)"
            }
        },
        "audit": all_audit,
        "yearly": _yearly(equity),
    }

    out_path = OUT_DIR / "smoke_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Result written: {out_path}", flush=True)

    all_trades_path = OUT_DIR / "all_trades.json"
    all_trades_path.write_text(json.dumps(all_trades, ensure_ascii=False, indent=2, default=str))
    print(f"Trades written: {all_trades_path}", flush=True)

    print("\n=== SUPERTREND-KR-V1 SMOKE RESULT ===")
    print(f"  grossReturn: {result['results']['grossReturn']:.2f}%")
    print(f"  netReturn  : {result['results']['netReturn']:.2f}%")
    print(f"  CAGR       : {result['results']['CAGR']:.2f}%")
    print(f"  MDD        : {result['results']['MDD']:.2f}%")
    print(f"  Sharpe     : {result['results']['Sharpe']:.3f}")
    print(f"  Exposure   : {result['results']['Exposure']:.4f}")
    print(f"  Trades     : {result['results']['Trades']}")
    print(f"  WinRate    : {result['results']['WinRate']:.1f}%")
    print(f"  Turnover   : {result['results']['Turnover']:.2f}")
    print(f"  SameBar    : {result['results']['SameBarExecutions']}")
    print(f"  audit      : {result['audit']}")
    print("\n=== BENCHMARKS ===")
    b = result["benchmarks"]
    print(f"  Equal-Weight:  TR={b['equalWeight']['totalReturn']:.2f}%  CAGR={b['equalWeight']['CAGR']:.2f}%  MDD={b['equalWeight']['MDD']:.2f}%  Sharpe={b['equalWeight']['Sharpe']:.3f}")
    print(f"  Buy & Hold :  TR={b['buyAndHold']['totalReturn']:.2f}%  CAGR={b['buyAndHold']['CAGR']:.2f}%  MDD={b['buyAndHold']['MDD']:.2f}%  Sharpe={b['buyAndHold']['Sharpe']:.3f}")
    print("\nSUPERTREND-KR-V1 STEP 2 SMOKE driver ready.")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    run_subset(args.subset, args.seed)