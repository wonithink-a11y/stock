#!/usr/bin/env python
"""Step 38 — Fibonacci Retracement Strategy Audit (Ultra Minimal)."""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "fibonacci-retracement-2026-08.json"
OUT_MD = HERE / "findings" / "fibonacci-retracement-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, spread, corr2, rolling_oos_resid, HORIZONS  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL
TARGETS = list(HORIZONS.keys())
FIB_LEVELS = [0.382, 0.500, 0.618, 0.786]
SWING_WINDOW = 20  # lookback for swing high/low
PROXIMITY = 0.005  # 0.5% proximity to level


def calc_fib_levels(high, low):
    """Calculate Fibonacci retracement levels from swing high/low."""
    diff = high - low
    return {
        "fib_382": high - 0.382 * diff,
        "fib_500": high - 0.500 * diff,
        "fib_618": high - 0.618 * diff,
        "fib_786": high - 0.786 * diff,
    }


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in ALL:
        fr = load_joint(b)
        # Calculate swing high/low (rolling 20-day)
        fr["swing_high"] = fr["close"].rolling(20, min_periods=10).max()
        fr["swing_low"] = fr["close"].rolling(20, min_periods=10).min()
        # Fibonacci levels
        for k, v in {"fib_382": 0.382, "fib_500": 0.500, "fib_618": 0.618, "fib_786": 0.786}.items():
            fr[k] = fr["swing_high"] - v * (fr["swing_high"] - fr["swing_low"])
        # Proximity to each level
        for k in ["fib_382", "fib_500", "fib_618", "fib_786"]:
            fr[f"dist_{k}"] = (fr["close"] - fr[k]) / fr[k]
        # Trend direction (close vs swing high/low)
        fr["trend_up"] = (fr["close"] > fr["swing_high"].shift(1)).astype(float)
        fr["trend_down"] = (fr["close"] < fr["swing_low"].shift(1)).astype(float)
        # BTC regime
        fr["btc_regime"] = np.where(fr["mom30"] > 0, "bull", "bear")
        fr["symbol"] = b
        frames[b] = fr
    print(f"[{time.time()-t_start:.1f}s] Loaded {len(frames)} symbols")
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    # Features: proximity to each fib level (abs distance < 0.5%)
    FEATURES = [f"dist_fib_{int(l*1000)}" for l in [0.382, 0.500, 0.618, 0.786]]
    # Rename for cleaner output
    FIB_FEATURES = ["dist_fib_382", "dist_fib_500", "dist_fib_618", "dist_fib_786"]
    
    # 1) Pooled decile (r_7)
    pooled = {f: spread(full, f, "r_7") for f in FIB_FEATURES if f in full.columns}
    
    # 2) Correlation with controls
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns}
    
    # 3) Regime split
    regime_results = {}
    for regime in ["bull", "bear"]:
        sub = full[full["btc_regime"] == regime]
        regime_results[regime] = {f: spread(sub, f, "r_7") for f in FIB_FEATURES if f in sub.columns}
    
    # 4) LOO
    loo = {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in FIB_FEATURES if f in full.columns}
    
    # 4) Controlled residuals
    from funding_premium_info_check import rolling_oos_resid
    for f in FIB_FEATURES:
        if f in full.columns:
            full[f"{f}_fmresid"] = rolling_oos_resid(
                full[f].to_numpy(float),
                [full["f_avg"].to_numpy(float), full["mom30"].to_numpy(float)])
    controlled = {f: spread(full, f"{f}_fmresid", "r_7") for f in FIB_FEATURES if f in full.columns}
    
    # 5) Correlation with controls
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns}
    
    # LOO
    loo = {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in FIB_FEATURES if f in full.columns}
    
    out = {
        "design": {
            "purpose": "Fibonacci retracement predictive test",
            "swing_window": 20,
            "fib_levels": FIB_LEVELS,
            "proximity": PROXIMITY,
            "features": FIB_FEATURES,
            "targets": TARGETS,
        },
        "pooled_decile_r7": {f: spread(full, f, "r_7") for f in FIB_FEATURES if f in full.columns},
        "controlled_fm": {f: spread(full, f"{f}_fmresid", "r_7") for f in FIB_FEATURES if f in full.columns},
        "regime_split_r7": {r: {f: v for f, v in regime_results[r].items()} for r in regime_results},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in FIB_FEATURES if f in full.columns},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns},
        "runtime_sec": round(time.time() - t_start, 1),
    }
    
    # Console
    print(f"\n=== Step 38 Fibonacci Retracement Audit ({time.time()-t_start:.1f}s) ===")
    print(f"Total obs: {len(full)}, Symbols: {full['symbol'].nunique()}")
    
    print("\n[1] Pooled Decile r_7:")
    for f in FIB_FEATURES:
        if f in full.columns:
            d = spread(full, f, "r_7")
            print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Regime split r_7:")
    for regime in ["bull", "bear"]:
        print(f"  {regime}:")
        for f in FIB_FEATURES:
            if f in full.columns:
                d = spread(full[full["btc_regime"] == regime], f, "r_7")
                print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    print("\n[3] Controlled (fund+mom resid) r_7:")
    for f in FIB_FEATURES:
        if f in full.columns:
            d = spread(full, f"{f}_fmresid", "r_7")
            print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    print("\n[4] LOO BTC drop r_7:")
    for f in FIB_FEATURES:
        if f in full.columns:
            d = spread(full[full["symbol"] != "BTC"], f, "r_7")
            print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    # JSON
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "Fibonacci retracement predictive test", "levels": FIB_LEVELS, "targets": TARGETS},
        "pooled_decile_r7": {f: spread(full, f, "r_7") for f in FIB_FEATURES if f in full.columns},
        "controlled_fm": {f: spread(full, f"{f}_fmresid", "r_7") for f in FIB_FEATURES if f in full.columns},
        "regime_split_r7": {r: {f: v for f, v in regime_results[r].items()} for r in regime_results},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in FIB_FEATURES if f in full.columns},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FIB_FEATURES if f in full.columns},
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
    OUT_JSON = HERE / "findings" / "fibonacci-retracement-2026-08.json"
    OUT_MD = HERE / "findings" / "fibonacci-retracement-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, spread, corr2, rolling_oos_resid, HORIZONS  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    SYM28 = ALL
    TARGETS = list(HORIZONS.keys())
    FIB_LEVELS = [0.382, 0.500, 0.618, 0.786]
    PROXIMITY = 0.005
    main()