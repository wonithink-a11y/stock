#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 42 — Price Structure Strategy Sweep (Real Backtest, v2)

Replaces price_structure_sweep.py (which was non-functional due to an
argument-passing bug: run_backtest received strategy name as 2nd arg but
consulted params.get("strategy"), which was always empty -> zero positions).

Design differences vs. the original v1:
  1. run_backtest takes (symbol, strategy_name, params): signal built from
     the strategy_name argument (fixes the all-zero-position bug).
  2. Proper OOS flow: Train(2023-05~2024-04) parameter selection ->
     Valid(2024-05~2024-12) fixed verification -> Test(2025-01~2026-08)
     final evaluation.  No Test peeking.
  3. Cost model made explicit: 10bp round-trip + 5bp slippage/side
     (i.e. 10bp charged on entry, 10bp charged on exit for a 20bp round trip).
  4. turnover = round-trips / trading-days (meaningful, was always 1.0 in v1).
  5. Adds per-year performance breakdown on the Test window.

Data: 28 symbols under data/crypto/basis/1h/*_1h.parquet (existing only,
no new data collection).
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "crypto" / "basis" / "1h"
OUT_JSON = HERE / "findings" / "price-structure-sweep-v2-2026-08.json"
OUT_MD = HERE / "findings" / "price-structure-sweep-v2-2026-08.md"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
    "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
    "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
    "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT",
]

TRAIN_START = pd.Timestamp("2023-05-01")
TRAIN_END = pd.Timestamp("2024-04-30")
VALID_START = pd.Timestamp("2024-05-01")
VALID_END = pd.Timestamp("2024-12-31")
TEST_START = pd.Timestamp("2025-01-01")
TEST_END = pd.Timestamp("2026-08-28")

# Cost model: 10bp round-trip commission + 5bp slippage per side.
COST_BP = 10      # round-trip commission
SLIP_BP = 5       # slippage per side
# Charged as 10bp (=5 comm + 5 slip) on entry, 10bp on exit for 20bp round trip.
ENTRY_COST = (COST_BP / 2 + SLIP_BP) / 10000.0   # 0.0010
EXIT_COST = (COST_BP / 2 + SLIP_BP) / 10000.0    # 0.0010

WINDOWS = {
    "train": (TRAIN_START, TRAIN_END),
    "valid": (VALID_START, VALID_END),
    "test": (TEST_START, TEST_END),
}


def load_daily(symbol):
    """Load 1h basis data -> daily OHLC + feature frame (full history)."""
    p = DATA / f"{symbol}_1h.parquet"
    if not p.exists():
        return None
    h1 = pd.read_parquet(p)
    tz = getattr(h1["time"].dtype, "tz", None)
    if tz is not None:
        dt = h1["time"].dt.tz_convert("Asia/Seoul")
    else:
        dt = h1["time"] + pd.Timedelta(hours=9)
    h1["kst_date"] = dt.dt.tz_localize(None).dt.normalize()
    g = h1.groupby("kst_date")
    daily = pd.DataFrame({
        "close": g["mark_close"].last(),
        "high": g["mark_high"].max(),
        "low": g["mark_low"].min(),
        "open": g["mark_open"].first(),
    })
    daily.index.name = "date"
    daily = daily.sort_index()
    c = daily["close"]
    h = daily["high"]
    l = daily["low"]
    for w in [9, 21, 50, 200, 20, 60, 120]:
        daily[f"ema_{w}"] = c.ewm(span=w).mean()
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["atr_14"] = (h - l).rolling(14).mean()
    daily["high_52w"] = h.rolling(252, min_periods=100).max()
    daily["low_52w"] = l.rolling(252, min_periods=100).min()
    daily["donchian_high_20"] = h.rolling(20).max()
    daily["donchian_low_20"] = l.rolling(20).min()
    daily["donchian_high_55"] = h.rolling(55).max()
    daily["donchian_low_55"] = l.rolling(55).min()
    return daily


def build_signal(daily, strategy_name, params):
    """Return a target position series in {0, 1} using strategy_name.

    position=1 means inline-to-long.  Exits are represented by returning to
    0.  ATR/stop/trail exits are applied later in the trade loop, so here we
    only produce the "entry / trend-off" signal.
    """
    d = daily
    sig = pd.Series(0, index=d.index)

    if strategy_name == "MA_Alignment":
        ma_align = (d["ema_20"] > d["ema_60"]) & (d["ema_60"] > d["ema_120"])
        sig[ma_align] = 1

    elif strategy_name == "MA_Breakout":
        up = (d["close"] > d["ema_20"]) & (d["close"].shift(1) <= d["ema_20"].shift(1))
        down = (d["close"] < d["ema_20"]) & (d["close"].shift(1) >= d["ema_20"].shift(1))
        sig[up] = 1
        sig[down] = -1
        sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    elif strategy_name == "MA_Retracement":
        ma_align = (d["ema_20"] > d["ema_60"]) & (d["ema_60"] > d["ema_120"])
        pullback = d["close"] < d["ema_20"]
        sig[ma_align & pullback] = 1

    elif strategy_name == "High_52w_Breakout":
        sig[d["close"] > d["high_52w"].shift(1)] = 1
        sig[d["close"] < d["high_52w"] * 0.95] = -1
        sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    elif strategy_name == "High_52w_Pullback":
        near_high = d["close"] > d["high_52w"] * 0.95
        pullback = d["close"] < d["high_52w"] * 0.98
        sig[near_high & pullback] = 1

    elif strategy_name == "Donchian_20":
        sig[d["close"] > d["donchian_high_20"].shift(1)] = 1
        sig[d["close"] < d["donchian_low_20"].shift(1)] = -1
        sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    elif strategy_name == "Donchian_55":
        sig[d["close"] > d["donchian_high_55"].shift(1)] = 1
        sig[d["close"] < d["donchian_low_55"].shift(1)] = -1
        sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    elif strategy_name == "MA_Cross_20_60":
        up = (d["ema_20"] > d["ema_60"]) & (d["ema_20"].shift(1) <= d["ema_60"].shift(1))
        down = (d["ema_20"] < d["ema_60"]) & (d["ema_20"].shift(1) >= d["ema_60"].shift(1))
        sig[up] = 1
        sig[down] = -1
        sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    elif strategy_name == "Dual_Momentum":
        sig[(d["mom30"] > 0) & (d["mom_60"] > 0)] = 1

    elif strategy_name == "EMA_Trend":
        sig[d["ema_21"] > d["ema_50"]] = 1

    else:
        raise ValueError(f"unknown strategy: {strategy_name}")

    position = sig.replace({-1: 0}).ffill().fillna(0).astype(int)

    # Regime filter (BTC market regime applied market-wide).
    regime_filter = params.get("regime_filter", "all")
    if regime_filter == "bull_only":
        position = position * (d["btc_regime"] == "bull").astype(int)
    elif regime_filter == "bear_only":
        position = position * (d["btc_regime"] == "bear").astype(int)

    return position


def backtest_window(daily, position, params):
    """Simulate one long-flat strategy and return daily equity / trade stats.

    position is the target position series aligned to daily's full index.
    Trades: enter at close when target goes 1, exit at close when:
      - target returns to 0, or
      - stop / ATR stop / take-profit / trailing stop triggers.
    Costs: ENTRY_COST on entry, EXIT_COST on exit.
    Return (daily_ret Series, trade_rets list, n_days, n_roundtrips).
    """
    d = daily
    close = d["close"]
    high = d["high"]
    low = d["low"]

    daily_ret = pd.Series(0.0, index=d.index)
    trades = []  # list of {"entry_ts","exit_ts","ret"}
    in_pos = False
    entry_ts = None
    entry_px = np.nan
    trailing_high = np.nan

    stop_pct = params.get("stop_pct", 0)
    atr_mult = params.get("atr_mult", 0)
    tp_pct = params.get("tp_pct", 999)
    trail_pct = params.get("trail_pct", 0)

    for i in range(len(d)):
        target = int(position.iloc[i]) == 1

        # Accumulate daily PnL while holding (close vs prior close).
        if in_pos and i > 0:
            daily_ret.iloc[i] += close.iloc[i] / close.iloc[i - 1] - 1

        if not in_pos and target:
            # enter at today's close (signal observed on prior bars)
            entry_px = close.iloc[i]
            entry_ts = d.index[i]
            trailing_high = high.iloc[i] if not np.isnan(high.iloc[i]) else entry_px
            in_pos = True
            daily_ret.iloc[i] += -ENTRY_COST

        elif in_pos and not target:
            gross = close.iloc[i] / entry_px - 1 if entry_px > 0 else 0.0
            trades.append({"entry_ts": entry_ts, "exit_ts": d.index[i],
                           "ret": gross - EXIT_COST})
            daily_ret.iloc[i] += -EXIT_COST
            in_pos = False
            entry_ts = None
            entry_px = np.nan
            trailing_high = np.nan

        elif in_pos:
            exited = False
            if stop_pct:
                gross_tmp = close.iloc[i] / entry_px - 1
                if gross_tmp <= -stop_pct:
                    exited = True
            if not exited and atr_mult and not np.isnan(d["atr_14"].iloc[i]) and d["atr_14"].iloc[i] > 0:
                gross_tmp = close.iloc[i] / entry_px - 1
                atr_stop = atr_mult * d["atr_14"].iloc[i] / close.iloc[i]
                if gross_tmp <= -atr_stop:
                    exited = True
            if not exited and tp_pct < 999:
                gross_tmp = close.iloc[i] / entry_px - 1
                if gross_tmp >= tp_pct:
                    exited = True
            if not exited and trail_pct:
                if not np.isnan(high.iloc[i]) and high.iloc[i] > trailing_high:
                    trailing_high = high.iloc[i]
                trail_px = trailing_high * (1 - trail_pct)
                if low.iloc[i] <= trail_px:
                    exited = True

            if exited:
                gross = close.iloc[i] / entry_px - 1
                trades.append({"entry_ts": entry_ts, "exit_ts": d.index[i],
                               "ret": gross - EXIT_COST})
                daily_ret.iloc[i] += -EXIT_COST
                in_pos = False
                entry_ts = None
                entry_px = np.nan
                trailing_high = np.nan

    return daily_ret, trades


def metrics_from_trade_rets(trade_rets, start, end):
    """Aggregate metrics from round-trip trade returns."""
    if len(trade_rets) < 5:
        return None
    year_frac = (end - start).days / 365.25
    cum = np.prod(1 + np.array(trade_rets))
    cagr = cum ** (1 / year_frac) - 1 if year_frac > 0 else 0.0
    rets = np.array(trade_rets)
    ann_vol = np.std(rets) * np.sqrt(len(rets) / year_frac) if year_frac > 0 else 0.0
    sharpe = (np.mean(rets) / np.std(rets)) * np.sqrt(len(rets)) if np.std(rets) > 0 else 0.0
    curve = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(curve)
    dd = (curve / peak - 1).min()
    win_rate = np.mean(rets > 0)
    gp = sum(r for r in rets if r > 0)
    gl = abs(sum(r for r in rets if r < 0))
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else 0.0)
    calmar = cagr / abs(dd) if dd != 0 else (np.inf if cagr > 0 else 0.0)
    return {
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": float(dd),
        "win_rate": float(win_rate),
        "profit_factor": float(pf),
        "calmar": float(calmar),
        "n_trades": int(len(trade_rets)),
    }


def metrics_from_daily(daily_ret, start, end, n_trades):
    """Aggregate CAGR/Sharpe/MDD + yearly perf from a daily return series."""
    if daily_ret.abs().sum() == 0:
        return None
    # Only count days inside the window
    window = daily_ret[(daily_ret.index >= start) & (daily_ret.index <= end)]
    if len(window) == 0:
        return None
    year_frac = (end - start).days / 365.25
    cagr = ((1 + window).prod()) ** (1 / year_frac) - 1 if year_frac > 0 else 0.0
    ann_vol = np.std(window.values) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    curve = (1 + window).cumprod()
    peak = curve.cummax()
    dd = (curve / peak - 1).min()
    calmar = cagr / abs(dd) if dd != 0 else (np.inf if cagr > 0 else 0.0)
    turnover = n_trades / len(window) if len(window) > 0 else 0.0

    # yearly performance (only meaningful for test window)
    yearly = {}
    for year, grp in window.groupby(window.index.year):
        yr = float(((1 + grp).prod() - 1))
        yearly[int(year)] = yr

    return {
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_dd": float(dd),
        "calmar": float(calmar),
        "turnover": float(turnover),
        "n_obs": int(len(window)),
        "n_trades": int(n_trades),
        "yearly": yearly,
    }


def run_strategy(symbol, strategy_name, params, window_key, btc_regime_series):
    daily = load_daily(symbol)
    if daily is None:
        return None
    start, end = WINDOWS[window_key]

    # BTC market regime (market-wide filter) aligned by date index.
    reg = pd.Series(btc_regime_series)
    daily["btc_regime"] = reg.reindex(daily.index).fillna("bull").values

    position = build_signal(daily, strategy_name, params)
    daily_ret, trades = backtest_window(daily, position, params)

    # Window-specific trades: round-trips whose entry falls inside the window.
    win_trades = [t for t in trades if start <= t["entry_ts"] <= end]
    if len(win_trades) < 5:
        return None

    dm = metrics_from_daily(daily_ret, start, end, len(win_trades))
    if dm is None:
        return None
    tm = metrics_from_trade_rets([t["ret"] for t in win_trades], start, end)
    if tm:
        dm["trade_cagr"] = tm.get("cagr")
        dm["trade_sharpe"] = tm.get("sharpe")
        dm["trade_pf"] = tm.get("profit_factor")
        dm["trade_wr"] = tm.get("win_rate")
    return dm


# Tunable parameter grid for risk-management variants (selected on Train)
PARAM_GRID = {
    "DM_ATR2_Trail5": [
        {"atr_mult": 2.0, "trail_pct": 0.05},
        {"atr_mult": 1.5, "trail_pct": 0.03},
        {"atr_mult": 2.5, "trail_pct": 0.07},
    ],
    "EMA_SL5_Trail5": [
        {"stop_pct": 0.05, "trail_pct": 0.05},
        {"stop_pct": 0.03, "trail_pct": 0.03},
        {"stop_pct": 0.07, "trail_pct": 0.07},
    ],
}


def select_params_on_train(cfg, btc_regime_series):
    """Pick the param set maximizing Train Sharpe (market-average)."""
    strategy = cfg["strategy"]
    grid = PARAM_GRID.get(cfg["name"])
    if not grid:
        return dict(cfg["params"])
    best = None
    best_sharpe = -np.inf
    for p in grid:
        params = dict(cfg["params"])
        params.update(p)
        sh = []
        for sym in SYMBOLS:
            r = run_strategy(sym, strategy, params, "train", btc_regime_series)
            if r:
                sh.append(r["sharpe"])
        avg = float(np.mean(sh)) if sh else -np.inf
        if avg > best_sharpe:
            best_sharpe = avg
            best = params
    return best if best else dict(cfg["params"])


def build_btc_regime():
    """Return {date: 'bull'|'bear'} Series from BTCUSDT mom30 on full index."""
    btc = load_daily("BTCUSDT")
    reg = np.where(btc["mom30"].fillna(0) > 0, "bull", "bear")
    return pd.Series(reg, index=btc.index)


def main():
    t0 = time.time()
    print(f"[{0.0:.1f}s] Step 42 (v2) — Price Structure Strategy Sweep")
    print(f"OOS: Train {TRAIN_START.date()}~{TRAIN_END.date()} / "
          f"Valid {VALID_START.date()}~{VALID_END.date()} / "
          f"Test {TEST_START.date()}~{TEST_END.date()}")

    configs = [
        {"name": "MA_Align_20_60_120", "strategy": "MA_Alignment", "params": {}},
        {"name": "MA_Align_BullOnly", "strategy": "MA_Alignment", "params": {"regime_filter": "bull_only"}},
        {"name": "MA20_Breakout", "strategy": "MA_Breakout", "params": {}},
        {"name": "MA20_Breakout_Bull", "strategy": "MA_Breakout", "params": {"regime_filter": "bull_only"}},
        {"name": "MA_Retrace_20_60_120", "strategy": "MA_Retracement", "params": {}},
        {"name": "MA_Retrace_Bull", "strategy": "MA_Retracement", "params": {"regime_filter": "bull_only"}},
        {"name": "High52w_Breakout", "strategy": "High_52w_Breakout", "params": {}},
        {"name": "High52w_Breakout_Bull", "strategy": "High_52w_Breakout", "params": {"regime_filter": "bull_only"}},
        {"name": "High52w_Pullback", "strategy": "High_52w_Pullback", "params": {}},
        {"name": "High52w_Pullback_Bull", "strategy": "High_52w_Pullback", "params": {"regime_filter": "bull_only"}},
        {"name": "Donchian_20", "strategy": "Donchian_20", "params": {}},
        {"name": "Donchian_55", "strategy": "Donchian_55", "params": {}},
        {"name": "Donchian_20_Bull", "strategy": "Donchian_20", "params": {"regime_filter": "bull_only"}},
        {"name": "Donchian_55_Bull", "strategy": "Donchian_55", "params": {"regime_filter": "bull_only"}},
        {"name": "MA_Cross_20_60", "strategy": "MA_Cross_20_60", "params": {}},
        {"name": "MA_Cross_20_60_Bull", "strategy": "MA_Cross_20_60", "params": {"regime_filter": "bull_only"}},
        {"name": "DM_ATR2_Trail5", "strategy": "Dual_Momentum", "params": {}},
        {"name": "EMA_SL5_Trail5", "strategy": "EMA_Trend", "params": {}},
    ]

    # Select params on Train for tunable variants
    btc_regime_series = build_btc_regime()
    for cfg in configs:
        sel = select_params_on_train(cfg, btc_regime_series)
        cfg["selected_params"] = sel
        if cfg["name"] in PARAM_GRID:
            print(f"  {cfg['name']}: Train-selected params = {sel}")

    results = {"test": {}, "valid": {}, "train": {}}
    for window_key in ["train", "valid", "test"]:
        print(f"\n=== {window_key.upper()} window ===")
        for cfg in configs:
            agg = []
            for sym in SYMBOLS:
                r = run_strategy(sym, cfg["strategy"], cfg["selected_params"], window_key, btc_regime_series)
                if r:
                    agg.append(r)
            if not agg:
                print(f"  {cfg['name']}: no data")
                continue
            mean = {
                "cagr": float(np.mean([r["cagr"] for r in agg])),
                "sharpe": float(np.mean([r["sharpe"] for r in agg])),
                "max_dd": float(np.mean([r["max_dd"] for r in agg])),
                "calmar": float(np.mean([r["calmar"] for r in agg if r["calmar"] != np.inf])),
                "turnover": float(np.mean([r["turnover"] for r in agg])),
                "n_trades": int(np.mean([r["n_trades"] for r in agg])),
                "win_rate": float(np.mean([r["trade_wr"] for r in agg])),
                "profit_factor": float(np.mean([r["trade_pf"] for r in agg])),
            }
            if window_key == "test":
                mean["yearly"] = {}
                years = sorted({y for r in agg for y in r.get("yearly", {})})
                for y in years:
                    ys = [r["yearly"][y] for r in agg if y in r.get("yearly", {})]
                    mean["yearly"][y] = float(np.mean(ys)) if ys else None
            results[window_key][cfg["name"]] = mean
            print(f"  {cfg['name']}: CAGR={mean['cagr']:.2%}, Sharpe={mean['sharpe']:.3f}, "
                  f"MDD={mean['max_dd']:.2%}, Calmar={mean['calmar']:.2f}, TO={mean['turnover']:.2%}, "
                  f"WR={mean['win_rate']:.2%}, PF={mean['profit_factor']:.2f}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "design": {
            "purpose": "Price Structure Strategy Sweep - OOS Train/Valid/Test",
            "oos_split": {
                "train": [str(TRAIN_START.date()), str(TRAIN_END.date())],
                "valid": [str(VALID_START.date()), str(VALID_END.date())],
                "test": [str(TEST_START.date()), str(TEST_END.date())],
            },
            "costs": f"{COST_BP}bp round-trip + {SLIP_BP}bp slippage/side "
                     f"(20bp round trip total)",
            "strategies_tested": len(configs),
            "params_selected_on_train": {c["name"]: c["selected_params"] for c in configs},
        },
        "results": results,
        "runtime_sec": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    print(f"\n=== Summary ===")
    print(f"Total runtime: {time.time() - t0:.1f}s")
    print(f"JSON: {OUT_JSON}")

    print("\n=== Leaderboard (Test, by Sharpe) ===")
    test = results["test"]
    for i, (name, res) in enumerate(
        sorted(test.items(), key=lambda x: x[1]["sharpe"], reverse=True)[:10], 1
    ):
        yb = res.get("yearly", {})
        print(f"  {i}. {name}: Sharpe={res['sharpe']:.3f}, CAGR={res['cagr']:.2%}, "
              f"MDD={res['max_dd']:.2%}, Calmar={res['calmar']:.2f}, yearly={yb}")


if __name__ == "__main__":
    main()
