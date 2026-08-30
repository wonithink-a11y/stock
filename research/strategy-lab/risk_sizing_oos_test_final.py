#!/usr/bin/env python
"""Step 41 — Dual Momentum / EMA Trend Risk/Sizing OOS Test (Real Backtest)."""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "risk-sizing-oos-test-2026-08.json"
OUT_MD = HERE / "findings" / "risk-sizing-oos-test-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import HORIZONS  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
         "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
         "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
         "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
         "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "XMRUSDT", "ZECUSDT"]

VALID_START = pd.Timestamp("2024-05-01")
TEST_START = pd.Timestamp("2025-01-01")
TEST_END = pd.Timestamp("2026-08-28")


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
    
    return daily


def evaluate(rets):
    if len(rets) < 10:
        return {"error": "insufficient data"}
    rets_arr = np.array(rets)
    years = len(rets) / 365.25
    cum = np.prod(1 + rets)
    cagr = cum ** (1 / (len(rets) / 365.25)) - 1 if len(rets) > 0 else 0
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
    return {"cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
            "win_rate": float(win_rate), "profit_factor": float(pf),
            "n_trades": int(n_trades), "n_obs": len(rets)}


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
    daily["atr_14"] = (daily["high"] - daily["low"]).rolling(14).mean()
    daily["mom_60"] = c.pct_change(60)
    
    daily = daily[(daily.index >= pd.Timestamp("2025-01-01")) & (daily.index <= pd.Timestamp("2026-08-28"))]
    
    if strategy_name == "EMA_Trend":
        sig = pd.Series(0, index=daily.index)
        sig[daily["ema_50"] > daily["ema_200"]] = 1
        sig[daily["ema_50"] < daily["ema_200"]] = -1
    else:
        sig = pd.Series(0, index=daily.index)
        sig[(daily["mom30"] > 0) & (daily["mom_60"] > 0)] = 1
        sig[(daily["mom30"] < 0) | (daily["mom_60"] < 0)] = -1
    
    signal = sig
    pos = sig.replace({-1: 0}).ffill().fillna(0).astype(int)
    pos = pos * (daily["mom30"] > 0).astype(int)
    daily["position"] = pos
    
    regime_filter = params.get("regime_filter", "all")
    if regime_filter == "bull_only":
        pos = pos * (daily["mom30"] > 0).astype(int)
    elif regime_filter == "bear_only":
        pos = pos * (daily["mom30"] <= 0).astype(int)
    daily["position"] = pos
    
    c = daily["close"]
    h = daily["high"]
    l = daily["low"]
    atr = (h - l).rolling(14).mean()
    mom30 = c.pct_change(30)
    mom60 = c.pct_change(60)
    
    in_pos = False
    entry_px = np.nan
    trailing_high = np.nan
    rets = []
    
    c_arr = c.values
    h_arr = daily["high"].values
    l_arr = l.values
    atr_arr = (h - l).rolling(14).mean().values
    mom30_arr = c.pct_change(30).values
    mom30_arr = daily["mom30"].values
    
    in_pos = False
    entry_px = np.nan
    trailing_high = np.nan
    rets = []
    current_pos = 0
    
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
            entry_px = c.iloc[i]
            trailing_high = h.iloc[i]
            rets.append(-0.0005)
        elif in_pos and target_pos == 0:
            ret = c.iloc[i] / entry_px - 1 if entry_px > 0 else 0
            rets.append(ret - 0.0005)
            in_pos = False
            entry_px = np.nan
        elif in_pos:
            if entry_px > 0:
                ret = c.iloc[i] / entry_px - 1
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
                    if np.isnan(trailing_high) or h.iloc[i] > trailing_high:
                        trailing_high = h.iloc[i]
                    trail_px = trailing_high * (1 - params["trail_pct"])
                    if l.iloc[i] <= trail_px:
                        exited = True
                
                if exited:
                    ret = c.iloc[i] / entry_px - 1 if entry_px > 0 else 0
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
    years = len(rets) / 365.25
    cum = np.prod(1 + rets)
    cagr = cum ** (1 / (len(rets) / 365.25)) - 1 if len(rets) > 0 else 0
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
    return {"cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
            "win_rate": float(win_rate), "profit_factor": float(pf),
            "n_trades": int(n_trades), "n_obs": len(rets)}


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
    for w in [9, 21, 50, 200, 20, 60, 120]:
        daily[f"ema_{w}"] = c.ewm(span=w).mean()
    daily["mom30"] = c.pct_change(30)
    daily["mom_60"] = c.pct_change(60)
    daily["btc_regime"] = np.where(c.pct_change(30) > 0, "bull", "bear")
    daily["atr_14"] = (daily["high"] - daily["low"]).rolling(14).mean()
    daily["mom_60"] = c.pct_change(60)
    
    return daily


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    
    configs = [
        {"name": "DM_Base", "strategy": "Dual_Momentum", "params": {}},
        {"name": "DM_ATR2", "strategy": "Dual_Momentum", "params": {"atr_mult": 2.0}},
        {"name": "DM_ATR2_Trail5", "strategy": "Dual_Momentum", "params": {"atr_mult": 2.0, "trail_pct": 0.05}},
        {"name": "EMA_Base", "strategy": "EMA_Trend", "params": {}},
        {"name": "EMA_SL5_Trail5", "strategy": "EMA_Trend", "params": {"stop_pct": 0.05, "trail_pct": 0.05}},
        {"name": "DM_ATR2_Trail5_Bull", "strategy": "Dual_Momentum", "params": {"atr_mult": 2.0, "trail_pct": 0.05, "regime_filter": "bull_only"}},
    ]
    
    ALL = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "XMRUSDT", "ZECUSDT"]
    
    results = {}
    for cfg in configs:
        print(f"Testing {cfg['name']}...")
        sym_results = []
        for b in ALL:
            try:
                res = run_backtest(b, cfg["strategy"], cfg["params"])
                if "error" not in res:
                    sym_results.append(res)
            except Exception as e:
                print(f"  {b}: Error {e}")
                continue
        if sym_results:
            avg_cagr = np.mean([r["cagr"] for r in sym_results])
            avg_sharpe = np.mean([r["sharpe"] for r in sym_results])
            avg_dd = np.mean([r["max_dd"] for r in sym_results])
            avg_wr = np.mean([r["win_rate"] for r in sym_results])
            avg_pf = np.mean([r["profit_factor"] for r in sym_results])
            print(f"  {cfg['name']}: CAGR={avg_cagr:.2%}, Sharpe={avg_sharpe:.3f}, MDD={avg_dd:.2%}, WR={avg_wr:.2%}, PF={avg_pf:.2f}")
            results[cfg["name"]] = {"cagr": avg_cagr, "sharpe": avg_sharpe, "mdd": avg_dd, "wr": avg_wr, "pf": avg_pf}
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "Risk/Sizing OOS Test", "strategies": ["EMA_Trend", "Dual_Momentum"]},
        "results": results,
        "runtime_sec": round(time.time() - t_start, 1),
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    print(f"\nTotal runtime: {time.time() - t_start:.1f}s")
    print("JSON:", OUT_JSON)


if __name__ == "__main__":
    import time
    import pandas as pd
    import numpy as np
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    OUT_JSON = HERE / "findings" / "risk-sizing-oos-test-2026-08.json"
    OUT_MD = HERE / "findings" / "risk-sizing-oos-test-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import HORIZONS  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    SYM28 = ALL
    TARGETS = list(HORIZONS.keys())
    main()