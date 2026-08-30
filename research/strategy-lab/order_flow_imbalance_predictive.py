#!/usr/bin/env python
"""Step 35 — Order-Flow Imbalance Predictive Test (Ultra Fast Core Only)."""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "order-flow-imbalance-predictive-2026-08.json"
OUT_MD = HERE / "findings" / "order-flow-imbalance-predictive-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, spread, corr2  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL
ACTIVITY = HERE / "data" / "crypto" / "activity"


def build_daily_order_flow(fr, base):
    """activity 1h → KST daily order-flow features."""
    p = ACTIVITY / f"{base}USDT_1h.parquet"
    if not p.exists():
        return fr
    a = pd.read_parquet(p)
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "quote_volume": g["quote_asset_volume"].sum(),
        "trade_count": g["number_of_trades"].sum(),
        "volume": g["volume"].sum(),
        "taker_buy_quote": g["taker_buy_quote_asset_volume"].sum(),
        "taker_buy_base": g["taker_buy_base_asset_volume"].sum(),
    })
    day.index.name = "date"
    day["taker_buy_ratio_q"] = day["taker_buy_quote"] / day["quote_volume"]
    day["taker_buy_ratio_b"] = day["taker_buy_base"] / day["volume"]
    day["imbalance_q"] = (day["taker_buy_quote"] - (day["quote_volume"] - day["taker_buy_quote"])) / day["quote_volume"]
    day["imbalance_b"] = (day["taker_buy_base"] - (day["volume"] - day["taker_buy_base"])) / day["volume"]
    day["buy_vol_q"] = day["taker_buy_quote"]
    day["sell_vol_q"] = day["quote_volume"] - day["taker_buy_quote"]
    day["buy_vol_b"] = day["taker_buy_base"]
    day["sell_vol_b"] = day["volume"] - day["taker_buy_base"]
    day = day.reindex(fr.index)
    for w in [3, 7, 30]:
        day[f"imb_q_chg_{w}d"] = day["imbalance_q"].pct_change(w)
        day[f"imb_b_chg_{w}d"] = day["imbalance_b"].pct_change(w)
    for col in ["imbalance_q", "imbalance_b"]:
        m = day[col].rolling(30, min_periods=10).mean().shift(1)
        s = day[col].rolling(30, min_periods=10).std().shift(1)
        day[f"{col}_z30"] = (day[col] - m) / s
    for c in day.select_dtypes(include="float").columns:
        day[c] = day[c].replace([np.inf, -np.inf], np.nan)
    return day.reindex(fr.index).add_suffix("_of")


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in ALL:
        fr = load_joint(b)
        p = ACTIVITY / f"{b}USDT_1h.parquet"
        if p.exists():
            a = pd.read_parquet(p)
            kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
            g = a.groupby(kst_day)
            day = pd.DataFrame({
                "quote_volume": g["quote_asset_volume"].sum(),
                "trade_count": g["number_of_trades"].sum(),
                "volume": g["volume"].sum(),
                "taker_buy_quote": g["taker_buy_quote_asset_volume"].sum(),
                "taker_buy_base": g["taker_buy_base_asset_volume"].sum(),
            })
            day.index.name = "date"
            day["taker_buy_ratio_q"] = day["taker_buy_quote"] / day["quote_volume"]
            day["taker_buy_ratio_b"] = day["taker_buy_base"] / day["volume"]
            day["imbalance_q"] = (day["taker_buy_quote"] - (day["quote_volume"] - day["taker_buy_quote"])) / day["quote_volume"]
            day["imbalance_b"] = (day["taker_buy_base"] - (day["volume"] - day["taker_buy_base"])) / day["volume"]
            day = day.reindex(fr.index)
            for w in [3, 7, 30]:
                day[f"imb_q_chg_{w}d"] = day["imbalance_q"].pct_change(w)
                day[f"imb_b_chg_{w}d"] = day["imbalance_b"].pct_change(w)
            for col in ["imbalance_q", "imbalance_b"]:
                m = day[col].rolling(30, min_periods=10).mean().shift(1)
                s = day[col].rolling(30, min_periods=10).std().shift(1)
                day[f"{col}_z30"] = (day[col] - m) / s
            for c in day.select_dtypes(include="float").columns:
                day[c] = day[c].replace([np.inf, -np.inf], np.nan)
            day = day.reindex(fr.index).add_suffix("_of")
            fr = fr.join(day, how="left")
        fr["symbol"] = b
        frames[b] = fr
    print(f"[{time.time()-t_start:.1f}s] Loaded {len(frames)} symbols")
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    CORE_FEATURES = [
        "taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"
    ]
    TARGETS = ["r_1", "r_3", "r_7"]
    
    # 1) Pooled decile (r_7 only for speed)
    pooled = {f: spread(full, f, "r_7") for f in CORE_FEATURES}
    
    # 2) Correlation with controls (vectorized)
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in CORE_FEATURES}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in CORE_FEATURES}
    
    # 3) LOO (BTC drop)
    loo = {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in CORE_FEATURES}
    
    out = {
        "design": {"purpose": "Order-flow imbalance predictive test (minimal core 4)", "features": ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"], "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile": {f: spread(full, f, "r_7") for f in CORE_FEATURES},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in CORE_FEATURES},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in CORE_FEATURES},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in CORE_FEATURES},
        "runtime_sec": round(time.time() - t_start, 1),
    }
    
    # Console
    print(f"\n=== Step 35 Order-Flow Imbalance Predictive Test ({time.time()-t_start:.1f}s) ===")
    print(f"Total obs: {len(full)}, Symbols: {full['symbol'].nunique()}")
    
    print("\n[1] Pooled Decile r_7:")
    for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]:
        d = spread(full, f, "r_7")
        print(f"  {f:30s} Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Corr with controls:")
    for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]:
        c1 = corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1]
        c2 = corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1]
        print(f"  {f:30s} vs_f={c1:+.4f} vs_mom={c2:+.4f}")
    
    print("\n[3] LOO BTC drop r_7:")
    for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]:
        d = spread(full[full["symbol"] != "BTC"], f, "r_7")
        print(f"  {f:30s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    # JSON
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "Order-flow imbalance predictive test (core 4)", "features": ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"], "targets": ["r_1", "r_3", "r_7"]},
        "pooled_decile": {f: spread(full, f, "r_7") for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]},
        "corr_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]},
        "corr_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]},
        "loo_btc": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["taker_buy_ratio_q_of", "imbalance_q_of", "imb_q_chg_7d_of", "imbalance_q_z30_of"]},
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
    OUT_JSON = HERE / "findings" / "order-flow-imbalance-predictive-2026-08.json"
    OUT_MD = HERE / "findings" / "order-flow-imbalance-predictive-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, spread, corr2  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    main()