#!/usr/bin/env python
"""Step 33 — Volatility Structure Predictive Test (Ultra Fast - Core Only)."""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "volatility-structure-predictive-2026-08.json"
OUT_MD = HERE / "findings" / "volatility-structure-predictive-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, spread, corr2  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL

def load_1h(base):
    p = HERE / "data" / "crypto" / "basis" / "1h" / f"{base}USDT_1h.parquet"
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
    daily = daily.drop(columns=["close"])
    daily["rv_1d"] = g["mark_close"].apply(lambda x: np.nansum(np.diff(np.log(x))**2))
    daily["rv_3d"] = daily["rv_1d"].rolling(3, min_periods=2).sum()
    daily["rv_7d"] = daily["rv_1d"].rolling(7, min_periods=4).sum()
    daily["atr_1d"] = (g["mark_high"].max() - g["mark_low"].min()) / g["mark_close"].last()
    daily["atr_3d"] = daily["atr_1d"].rolling(3, min_periods=2).mean()
    daily["atr_7d"] = daily["atr_1d"].rolling(7, min_periods=4).mean()
    daily["range_1d"] = (g["mark_high"].max() - g["mark_low"].min()) / g["mark_open"].first()
    daily["range_7d"] = daily["range_1d"].rolling(7, min_periods=4).mean()
    rng = daily["range_1d"]
    rng_mean = rng.rolling(30, min_periods=10).mean().shift(1)
    rng_std = rng.rolling(30, min_periods=10).std().shift(1)
    daily["range_z"] = (rng - rng_mean) / rng_std
    daily["rv_chg_3d"] = daily["rv_1d"].pct_change(3)
    daily["rv_chg_7d"] = daily["rv_1d"].pct_change(7)
    rv = daily["rv_1d"]
    daily["rv_pct_30d"] = rv.rolling(30, min_periods=10).rank(pct=True)
    daily["rv_pct_90d"] = rv.rolling(90, min_periods=30).rank(pct=True)
    for c in daily.select_dtypes(include="float").columns:
        daily[c] = daily[c].replace([np.inf, -np.inf], np.nan)
    return daily.add_suffix("_vol")


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in ALL:
        fr = load_joint(b)
        daily = load_1h(b)
        if daily is not None:
            fr = fr.join(daily, how="left")
        fr["symbol"] = b
        frames[b] = fr
    print(f"[{time.time()-t_start:.1f}s] Loaded {len(frames)} symbols")
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    FEATURES = [
        "rv_1d_vol", "rv_3d_vol", "rv_7d_vol",
        "atr_1d_vol", "atr_3d_vol", "atr_7d_vol",
        "range_1d_vol", "range_7d_vol", "range_z_vol",
        "rv_chg_3d_vol", "rv_chg_7d_vol",
        "rv_pct_30d_vol", "rv_pct_90d_vol",
    ]
    TARGETS = ["r_1", "r_3", "r_7"]
    
    # 1) Pooled decile - only r_7 for speed
    pooled = {f: {h: spread(full, f, h) for h in ["r_1", "r_3", "r_7"]} for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]}
    
    # 2) Correlation with controls
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]}
    
    # 3) LOO (BTC drop)
    loo = {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]}
    
    out = {
        "design": {"purpose": "Volatility structure predictive test (core 4 features)", "features": ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"], "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile": {f: {h: spread(full, f, h) for h in ["r_1", "r_3", "r_7"]} for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "runtime_sec": round(time.time() - t_start, 1),
    }
    
    # Console
    print(f"\n=== Step 33 Volatility Structure Predictive Test ({time.time()-t_start:.1f}s) ===")
    print(f"Total obs: {len(full)}, Symbols: {full['symbol'].nunique()}")
    
    print("\n[1] Pooled Decile r_7:")
    for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]:
        d = spread(full, f, "r_7")
        print(f"  {f:20s} Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Corr with controls:")
    for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]:
        c1 = corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1]
        c2 = corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1]
        print(f"  {f:20s} vs_f={c1:+.4f} vs_mom={c2:+.4f}")
    
    print("\n[3] LOO BTC drop r_7:")
    for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]:
        d = spread(full[full["symbol"] != "BTC"], f, "r_7")
        print(f"  {f:20s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    # JSON
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "Volatility structure predictive test (core 4)", "features": ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"], "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile": {f: {h: spread(full, f, h) for h in ["r_1", "r_3", "r_7"]} for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["rv_1d_vol", "rv_7d_vol", "range_z_vol", "atr_7d_vol"]},
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
    OUT_JSON = HERE / "findings" / "volatility-structure-predictive-2026-08.json"
    OUT_MD = HERE / "findings" / "volatility-structure-predictive-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, spread, corr2  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    main()