#!/usr/bin/env python
"""Step 37 — BTC Regime × MA Strategy Audit (Ultra Minimal)."""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "btc-regime-ma-2026-08.json"
OUT_MD = HERE / "findings" / "btc-regime-ma-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, spread, corr2  # noqa: E402
from funding_premium_info_check import ALL, HORIZONS  # noqa: E402

SYM28 = ALL
TARGETS = list(HORIZONS.keys())
MA_WINS = [20, 60, 120]


def add_ma_features(fr):
    """Add MA features to a single symbol frame."""
    close = fr["close"]
    for w in MA_WINS:
        ma = close.rolling(w, min_periods=w).mean()
        fr[f"ma_{w}"] = ma
        fr[f"dist_{w}"] = (fr["close"] - ma) / ma
    fr["ma_align_full"] = ((fr["ma_20"] > fr["ma_60"]) & (fr["ma_60"] > fr["ma_120"])).astype(float)
    for w in MA_WINS:
        fr[f"ma_slope_{w}"] = fr[f"ma_{w}"].pct_change(5)
    fr["btc_regime"] = np.where(fr["mom30"] > 0, "bull", "bear")
    return fr


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in ALL:
        fr = load_joint(b)
        # Build MA features inline
        close = fr["close"]
        for w in MA_WINS:
            ma = close.rolling(w, min_periods=w).mean()
            fr[f"ma_{w}"] = ma
            fr[f"dist_{w}"] = (fr["close"] - ma) / ma
        fr["ma_align_full"] = ((fr["ma_20"] > fr["ma_60"]) & (fr["ma_60"] > fr["ma_120"])).astype(float)
        for w in MA_WINS:
            fr[f"ma_slope_{w}"] = fr[f"ma_{w}"].pct_change(5)
        fr["btc_regime"] = np.where(fr["mom30"] > 0, "bull", "bear")
        fr["symbol"] = b
        frames[b] = fr
    print(f"[{time.time()-t_start:.1f}s] Loaded {len(frames)} symbols")
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    FEATURES = ["dist_20", "dist_60", "dist_120", "ma_slope_20", "ma_slope_60", "ma_slope_120"]
    
    # 1) Pooled decile r_7
    pooled = {f: spread(full, f, "r_7") for f in FEATURES}
    
    # 2) Correlation with controls
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FEATURES}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FEATURES}
    
    # 3) Regime split
    regime_results = {}
    for regime in ["bull", "bear"]:
        sub = full[full["btc_regime"] == regime]
        regime_results[regime] = {f: spread(sub, f, "r_7") for f in FEATURES}
    
    out = {
        "design": {"purpose": "BTC regime × MA audit (minimal)", "features": FEATURES, "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile_r7": {f: spread(full, f, "r_7") for f in FEATURES},
        "regime_split_r7": {r: {f: v for f, v in regime_results[r].items()} for r in regime_results},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FEATURES},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FEATURES},
        "runtime_sec": round(time.time() - t_start, 1),
    }
    
    # Console
    print(f"\n=== Step 37 BTC Regime × MA Audit ({time.time()-t_start:.1f}s) ===")
    print(f"Total obs: {len(full)}, Symbols: {full['symbol'].nunique()}")
    
    print("\n[1] Pooled Decile r_7:")
    for f in FEATURES:
        d = spread(full, f, "r_7")
        print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Regime split r_7:")
    for regime in ["bull", "bear"]:
        print(f"  {regime}:")
        for f in ["dist_20", "dist_60", "dist_120", "ma_slope_20", "ma_slope_60"]:
            d = spread(full[full["btc_regime"] == regime], f, "r_7")
            print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    print("\n[2] Corr with controls:")
    for f in FEATURES:
        c1 = corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1]
        c2 = corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1]
        print(f"  {f:16s} vs_f={c1:+.4f} vs_mom={c2:+.4f}")
    
    # JSON
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "BTC regime × MA audit (minimal)", "features": FEATURES, "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile_r7": {f: spread(full, f, "r_7") for f in FEATURES},
        "regime_split_r7": {r: {f: v for f, v in regime_results[r].items()} for r in regime_results},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in FEATURES},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in FEATURES},
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
    OUT_JSON = HERE / "findings" / "btc-regime-ma-2026-08.json"
    OUT_MD = HERE / "findings" / "btc-regime-ma-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, spread, corr2, HORIZONS  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    main()