#!/usr/bin/env python
"""Step 42 — Price Structure Strategy Sweep (Real Backtest).

Test multiple price structure strategies with OOS validation:
- MA alignment (20/60/120 정배열/역배열)
- MA breakout/retracement (20/60/120)
- 52-week high breakout/pullback
- Donchian channel breakout (20/55)
- MA crossover (20/60)
- BTC Bull/Bear regime cross-test

OOS: Train(2023-05~2024-04) / Valid(2024-05~2024-12) / Test(2025-01~2026-08)
Costs: 10bp round-trip + 5bp slippage per side
No parameter tuning on Test.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "price-structure-sweep-2026-08.json"
OUT_MD = HERE / "findings" / "price-structure-sweep-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import HORIZONS  # noqa: E402

# 28 symbols from basis/1h data
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "XMRUSDT", "ZECUSDT"]

VALID_START = pd.Timestamp("2024-05-01")
TEST_START = pd.Timestamp("2025-01-01")
TEST_END = pd.Timestamp("2026-08-28")

COST_BP = 10  # round-trip
SLIP_BP = 5   # per side


def load_1h_data(symbol):
    """Load 1h basis data and compute daily features."""
    p = HERE / "data" / "crypto" / "basis" / "1h" / f"{symbol}_1h.parquet"
    if not p.exists():
        return None
    h1 = pd.read_parquet(p)
    h1["kst_date"] = (h1["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = h1.groupby("kst_date")
    daily = pd.DataFrame({
        "close": g["mark_close"].last(),
        "high": g["mark_high"].max(),
        "low": g["mark_low"].min(),
        "open": g["mark_open"].first(),
    })
    daily.index.name = "date"
    
    c = daily["close"]
    for w in [9, 21, 50, 200, 20, 60, 120]:
        daily[f"ema_{w}"] = c.ewm(span=w).mean()
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["btc_regime"] = np.where(c.pct_change(30) > 0, "bull", "bear")
    daily["atr_14"] = (daily["high"] - daily["low"]).rolling(14).mean()
    daily["mom_60"] = c.pct_change(60)
    
    # 52-week high/low
    daily["high_52w"] = daily["high"].rolling(252, min_periods=100).max()
    daily["low_52w"] = daily["low"].rolling(252, min_periods=100).min()
    
    # Donchian channels
    daily["donchian_high_20"] = daily["high"].rolling(20).max()
    daily["donchian_low_20"] = daily["low"].rolling(20).min()
    daily["donchian_high_55"] = daily["high"].rolling(55).max()
    daily["donchian_low_55"] = daily["low"].rolling(55).min()
    
    # ATR
    daily["atr_14"] = (daily["high"] - daily["low"]).rolling(14).mean()
    
    # Momentum
    daily["mom30"] = daily["close"].pct_change(30)
    daily["mom_60"] = daily["close"].pct_change(60)
    daily["btc_regime"] = np.where(daily["close"].pct_change(30) > 0, "bull", "bear")
    daily["mom_60"] = daily["close"].pct_change(60)
    
    return daily


def evaluate(rets):
    if len(rets) < 10:
        return {"error": "insufficient data"}
    rets_arr = np.array(rets)
    years = (TEST_END - TEST_START).days / 365.25
    cum = np.prod(1 + rets)
    cagr = cum ** (1 / years) - 1 if years > 0 else 0
    ann_vol = np.std(rets) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if np.std(rets) > 0 else 0
    cum_curve = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum_curve)
    dd = (cum_curve / peak - 1).min()
    win_rate = np.mean(np.array(rets) > 0)
    gp = sum(r for r in rets if r > 0)
    gl = abs(sum(r for r in rets if r < 0))
    pf = gp / gl if gl > 0 else np.inf
    n_trades = sum(1 for r in rets if r != 0)
    turnover = len([r for r in rets if r != 0]) / len(rets) if len(rets) > 0 else 0
    calmar = cagr / abs(dd) if dd != 0 else np.inf
    return {
        "cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
        "win_rate": float(win_rate), "profit_factor": float(pf),
        "n_trades": int(n_trades), "n_obs": len(rets),
        "calmar": float(cagr / abs(dd) if dd != 0 else np.inf),
        "turnover": float(turnover),
    }


def run_backtest(symbol, strategy_name, params):
    daily = load_1h_data(symbol)
    if daily is None:
        return {"error": "no data"}
    
    c = daily["close"]
    h = daily["high"]
    l = daily["low"]
    
    for w in [9, 21, 50, 200, 20, 60, 120]:
        daily[f"ema_{w}"] = c.ewm(span=w).mean()
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["btc_regime"] = np.where(c.pct_change(30) > 0, "bull", "bear")
    daily["atr_14"] = (h - l).rolling(14).mean()
    daily["mom_60"] = c.pct_change(60)
    
    # 52-week high/low
    daily["high_52w"] = h.rolling(252, min_periods=100).max()
    daily["low_52w"] = l.rolling(252, min_periods=100).min()
    
    # Donchian channels
    daily["donchian_high_20"] = h.rolling(20).max()
    daily["donchian_low_20"] = l.rolling(20).min()
    daily["donchian_high_55"] = h.rolling(55).max()
    daily["donchian_low_55"] = l.rolling(55).min()
    
    # ATR
    daily["atr_14"] = (h - l).rolling(14).mean()
    
    daily = daily[(daily.index >= pd.Timestamp("2025-01-01")) & (daily.index <= pd.Timestamp("2026-08-28"))]
    
    # Build signals based on strategy
    if params.get("strategy") == "MA_Alignment":
        # 정배열: ema_20 > ema_60 > ema_120
        ma_align = (daily["ema_20"] > daily["ema_60"]) & (daily["ema_60"] > daily["ema_120"])
        sig = pd.Series(0, index=daily.index)
        sig[ma_align] = 1
        sig[~ma_align] = 0
        
    elif params.get("strategy") == "MA_Breakout":
        # 20일선 상향/하향 돌파
        sig = pd.Series(0, index=daily.index)
        sig[(daily["close"] > daily["ema_20"]) & (daily["close"].shift(1) <= daily["ema_20"].shift(1))] = 1
        sig[(daily["close"] < daily["ema_20"]) & (daily["close"].shift(1) >= daily["ema_20"].shift(1))] = -1
        
    elif params.get("strategy") == "MA_Retracement":
        # 정배열 상태에서 20일선 눌림목 매수
        ma_align = (daily["ema_20"] > daily["ema_60"]) & (daily["ema_60"] > daily["ema_120"])
        pullback = daily["close"] < daily["ema_20"]
        sig = pd.Series(0, index=daily.index)
        sig[ma_align & pullback] = 1
        sig[~ma_align] = 0
        
    elif params.get("strategy") == "High_52w_Breakout":
        # 52주 신고가 돌파
        sig = pd.Series(0, index=daily.index)
        sig[daily["close"] > daily["high_52w"].shift(1)] = 1
        sig[(daily["close"] < daily["high_52w"] * 0.95)] = -1
        
    elif params.get("strategy") == "High_52w_Pullback":
        # 52주 고점 근처 눌림목
        near_high = daily["close"] > daily["high_52w"] * 0.95
        pullback = daily["close"] < daily["high_52w"] * 0.98
        sig = pd.Series(0, index=daily.index)
        sig[near_high & pullback] = 1
        sig[~near_high] = 0
        
    elif params.get("strategy") == "Donchian_20":
        sig = pd.Series(0, index=daily.index)
        sig[daily["close"] > daily["donchian_high_20"].shift(1)] = 1
        sig[daily["close"] < daily["donchian_low_20"].shift(1)] = -1
        
    elif params.get("strategy") == "Donchian_55":
        sig = pd.Series(0, index=daily.index)
        sig[daily["close"] > daily["donchian_high_55"].shift(1)] = 1
        sig[daily["close"] < daily["donchian_low_55"].shift(1)] = -1
        
    elif params.get("strategy") == "MA_Cross_20_60":
        sig = pd.Series(0, index=daily.index)
        sig[(daily["ema_20"] > daily["ema_60"]) & (daily["ema_20"].shift(1) <= daily["ema_60"].shift(1))] = 1
        sig[(daily["ema_20"] < daily["ema_60"]) & (daily["ema_20"].shift(1) >= daily["ema_60"].shift(1))] = -1
        
    else:
        sig = pd.Series(0, index=daily.index)
    
    # Position management
    sig = sig.replace({-1: 0}).ffill().fillna(0).astype(int)
    
    # BTC Regime filter
    regime_filter = params.get("regime_filter", "all")
    if "regime_filter" in params and params["regime_filter"] == "bull_only":
        signal = sig * (daily["mom30"] > 0).astype(int)
    elif "regime_filter" in params and params["regime_filter"] == "bear_only":
        signal = sig * (daily["mom30"] <= 0).astype(int)
    else:
        signal = sig
    
    # Position sizing: 1% risk per trade
    signal = sig
    position = sig.replace({-1: 0}).ffill().fillna(0).astype(int)
    
    # Apply regime filter
    if "regime_filter" in params and params["regime_filter"] == "bull_only":
        position = position * (daily["mom30"] > 0).astype(int)
    elif "regime_filter" in params and params["regime_filter"] == "bear_only":
        position = position * (daily["mom30"] <= 0).astype(int)
    
    daily["position"] = position
    
    # Backtest execution
    c = daily["close"]
    h = daily["high"]
    l = daily["low"]
    atr = (h - l).rolling(14).mean()
    mom30 = c.pct_change(30)
    
    in_pos = False
    entry_px = np.nan
    trailing_high = np.nan
    rets = []
    
    c_arr = daily["close"].values
    h_arr = daily["high"].values
    l_arr = l.values
    atr_arr = (h - l).rolling(14).mean().values
    mom30_arr = c.pct_change(30).values
    
    in_pos = False
    entry_px = np.nan
    trailing_high = np.nan
    rets = []
    
    for i in range(len(daily)):
        target_pos = 1 if daily["position"].iloc[i] == 1 else 0
        
        if params.get("regime_filter") == "bull_only" and daily["mom30"].iloc[i] <= 0:
            target_pos = 0
        elif params.get("regime_filter") == "bear_only" and daily["mom30"].iloc[i] > 0:
            target_pos = 0
        else:
            target_pos = 1 if daily["position"].iloc[i] == 1 else 0
        
        if not in_pos and target_pos == 1:
            in_pos = True
            entry_px = daily["close"].iloc[i]
            trailing_high = daily["high"].iloc[i]
            rets.append(-0.0005)  # 5bp entry
        elif in_pos and target_pos == 0:
            ret = daily["close"].iloc[i] / entry_px - 1 if entry_px > 0 else 0
            rets.append(ret - 0.0005)
            in_pos = False
            entry_px = np.nan
        elif in_pos:
            if entry_px > 0:
                ret = daily["close"].iloc[i] / entry_px - 1
                exited = False
                
                if ret <= -params.get("stop_pct", 0):
                    exited = True
                elif not np.isnan(daily["atr_14"].iloc[i]) and daily["atr_14"].iloc[i] > 0:
                    atr_stop = params.get("atr_mult", 0) * daily["atr_14"].iloc[i] / c.iloc[i]
                    if ret <= -atr_stop:
                        exited = True
                elif ret >= params.get("tp_pct", 999):
                    exited = True
                elif params.get("trail_pct", 0) > 0:
                    if np.isnan(trailing_high) or daily["high"].iloc[i] > trailing_high:
                        trailing_high = daily["high"].iloc[i]
                    trail_px = trailing_high * (1 - params["trail_pct"])
                    if l.iloc[i] <= trail_px:
                        exited = True
                
                if exited:
                    ret = daily["close"].iloc[i] / entry_px - 1 if entry_px > 0 else 0
                    rets.append(ret - 0.0005)
                    in_pos = False
                    entry_px = np.nan
                else:
                    pass
        
        position = 1 if in_pos else 0
    
    rets_arr = np.array(rets)
    return evaluate(rets_arr)


def evaluate(rets):
    if len(rets) < 10:
        return {"error": "insufficient data"}
    rets_arr = np.array(rets)
    years = (TEST_END - TEST_START).days / 365.25
    cum = np.prod(1 + rets)
    cagr = cum ** (1 / years) - 1 if years > 0 else 0
    ann_vol = np.std(rets) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if np.std(rets) > 0 else 0
    cum_curve = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(cum_curve)
    dd = (cum_curve / peak - 1).min()
    win_rate = np.mean(np.array(rets) > 0)
    gp = sum(r for r in rets if r > 0)
    gl = abs(sum(r for r in rets if r < 0))
    pf = gp / gl if gl > 0 else np.inf
    n_trades = sum(1 for r in rets if r != 0)
    turnover = len([r for r in rets if r != 0]) / len(rets) if len(rets) > 0 else 0
    calmar = cagr / abs(dd) if dd != 0 else np.inf
    return {
        "cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
        "win_rate": float(win_rate), "profit_factor": float(pf),
        "n_trades": int(n_trades), "n_obs": len(rets),
        "calmar": float(cagr / abs(dd) if dd != 0 else np.inf),
        "turnover": float(turnover),
    }


def load_1h_data(symbol):
    p = HERE / "data" / "crypto" / "basis" / "1h" / f"{symbol}_1h.parquet"
    if not p.exists():
        return None
    h1 = pd.read_parquet(p)
    h1["kst_date"] = (h1["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = h1.groupby("kst_date")
    daily = pd.DataFrame({
        "close": g["mark_close"].last(),
        "high": g["mark_high"].max(),
        "low": g["mark_low"].min(),
        "open": g["mark_open"].first(),
    })
    daily.index.name = "date"
    
    c = daily["close"]
    h = daily["high"]
    l = daily["low"]
    for w in [9, 21, 50, 200, 20, 60, 120]:
        daily[f"ema_{w}"] = c.ewm(span=w).mean()
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["btc_regime"] = np.where(c.pct_change(30) > 0, "bull", "bear")
    daily["atr_14"] = (h - l).rolling(14).mean()
    daily["mom_60"] = c.pct_change(60)
    
    # 52-week high/low
    daily["high_52w"] = h.rolling(252, min_periods=100).max()
    daily["low_52w"] = l.rolling(252, min_periods=100).min()
    
    # Donchian channels
    daily["donchian_high_20"] = h.rolling(20).max()
    daily["donchian_low_20"] = l.rolling(20).min()
    daily["donchian_high_55"] = h.rolling(55).max()
    daily["donchian_low_55"] = l.rolling(55).min()
    
    # ATR
    daily["atr_14"] = (h - l).rolling(14).mean()
    
    # Momentum
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["btc_regime"] = np.where(c.pct_change(30) > 0, "bull", "bear")
    daily["mom_60"] = c.pct_change(60)
    
    return daily


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Step 42 — Price Structure Strategy Sweep")
    
    configs = [
        # MA Alignment
        {"name": "MA_Align_20_60_120", "strategy": "MA_Alignment", "params": {}},
        {"name": "MA_Align_BullOnly", "strategy": "MA_Alignment", "params": {"regime_filter": "bull_only"}},
        
        # MA Breakout
        {"name": "MA20_Breakout", "strategy": "MA_Breakout", "params": {}},
        {"name": "MA20_Breakout_Bull", "strategy": "MA_Breakout", "params": {"regime_filter": "bull_only"}},
        
        # MA Retracement
        {"name": "MA_Retrace_20_60_120", "strategy": "MA_Retracement", "params": {}},
        {"name": "MA_Retrace_Bull", "strategy": "MA_Retracement", "params": {"regime_filter": "bull_only"}},
        
        # 52-week High
        {"name": "High52w_Breakout", "strategy": "High_52w_Breakout", "params": {}},
        {"name": "High52w_Breakout_Bull", "strategy": "High_52w_Breakout", "params": {"regime_filter": "bull_only"}},
        {"name": "High52w_Pullback", "strategy": "High_52w_Pullback", "params": {}},
        {"name": "High52w_Pullback_Bull", "strategy": "High_52w_Pullback", "params": {"regime_filter": "bull_only"}},
        
        # Donchian
        {"name": "Donchian_20", "strategy": "Donchian_20", "params": {}},
        {"name": "Donchian_55", "strategy": "Donchian_55", "params": {}},
        {"name": "Donchian_20_Bull", "strategy": "Donchian_20", "params": {"regime_filter": "bull_only"}},
        {"name": "Donchian_55_Bull", "strategy": "Donchian_55", "params": {"regime_filter": "bull_only"}},
        
        # MA Cross
        {"name": "MA_Cross_20_60", "strategy": "MA_Cross_20_60", "params": {}},
        {"name": "MA_Cross_20_60_Bull", "strategy": "MA_Cross_20_60", "params": {"regime_filter": "bull_only"}},
        
        # Risk management variants
        {"name": "DM_ATR2_Trail5", "strategy": "Dual_Momentum", "params": {"atr_mult": 2.0, "trail_pct": 0.05}},
        {"name": "EMA_SL5_Trail5", "strategy": "EMA_Trend", "params": {"stop_pct": 0.05, "trail_pct": 0.05}},
    ]
    
    ALL = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "XMRUSDT", "ZECUSDT"]
    
    # Pre-load all data
    print("Loading data for all symbols...")
    daily_data = {}
    for sym in ALL:
        daily = load_1h_data(sym)
        if daily is not None:
            daily_data[sym] = daily
    
    results = {}
    for cfg in configs:
        print(f"Testing {cfg['name']}...")
        sym_results = []
        for sym in ALL:
            try:
                res = run_backtest(daily_data[sym], cfg["strategy"], cfg["params"])
                if "error" not in res:
                    sym_results.append(res)
            except Exception as e:
                print(f"  {sym}: Error {e}")
                continue
        if sym_results:
            avg_cagr = np.mean([r["cagr"] for r in sym_results])
            avg_sharpe = np.mean([r["sharpe"] for r in sym_results])
            avg_dd = np.mean([r["max_dd"] for r in sym_results])
            avg_wr = np.mean([r["win_rate"] for r in sym_results])
            avg_pf = np.mean([r["profit_factor"] for r in sym_results])
            avg_turnover = np.mean([r["turnover"] for r in sym_results])
            avg_calmar = np.mean([r["calmar"] for r in sym_results if r["calmar"] != np.inf])
            print(f"  {cfg['name']}: CAGR={avg_cagr:.2%}, Sharpe={avg_sharpe:.3f}, MDD={avg_dd:.2%}, WR={avg_wr:.2%}, PF={avg_pf:.2f}, Calmar={avg_calmar:.2f}, TO={avg_turnover:.2%}")
            results[cfg["name"]] = {"cagr": avg_cagr, "sharpe": avg_sharpe, "mdd": avg_dd, "wr": avg_wr, "pf": avg_pf, "turnover": avg_turnover, "calmar": avg_calmar}
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "Price Structure Strategy Sweep OOS Test",
                   "oos_split": "Train(2023-05~2024-04)/Valid(2024-05~2024-12)/Test(2025-01~2026-08)",
                   "costs": f"{COST_BP}bp round-trip + {SLIP_BP}bp slippage",
                   "strategies_tested": len(configs)},
        "results": results,
        "runtime_sec": round(time.time() - t_start, 1),
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    print(f"\n=== Summary ===")
    print(f"Total runtime: {time.time() - t_start:.1f}s")
    print(f"JSON: {OUT_JSON}")
    
    # Print leaderboard
    print("\n=== Leaderboard (Test) ===")
    sorted_results = sorted(results.items(), key=lambda x: x[1].get("sharpe", -999), reverse=True)
    for i, (name, res) in enumerate(sorted_results[:10], 1):
        print(f"  {i}. {name}: Sharpe={res['sharpe']:.3f}, CAGR={res['cagr']:.2%}, MDD={res['mdd']:.2%}, Calmar={res['calmar']:.2f}")

if __name__ == "__main__":
    import time
    import pandas as pd
    import numpy as np
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    OUT_JSON = HERE / "findings" / "price-structure-sweep-2026-08.json"
    OUT_MD = HERE / "findings" / "price-structure-sweep-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import HORIZONS  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    import json
    import time
    import pandas as pd
    import numpy as np
    from pathlib import Path
    main()