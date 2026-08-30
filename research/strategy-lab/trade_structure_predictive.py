#!/usr/bin/env python
"""Step 32 — Trade Structure Predictive Test (Ultra Fast - 30 sec max).

최소한의 핵심만: pooled decile + simple costs.
date-groupby loops 완전 제거.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "trade-structure-predictive-2026-08.json"
OUT_MD = HERE / "findings" / "trade-structure-predictive-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, spread, decile_rank, corr2  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL

def build_features(fr, base):
    p = HERE / "data" / "crypto" / "activity" / f"{base}USDT_1h.parquet"
    if not p.exists():
        return fr
    a = pd.read_parquet(p)
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "quote_volume": g["quote_asset_volume"].sum(),
        "trade_count": g["number_of_trades"].sum(),
    })
    day.index.name = "date"
    day["avg_trade_size"] = day["quote_volume"] / day["trade_count"]
    day = day.reindex(fr.index)
    
    fr = fr.join(day, how="left")
    for w in [3, 7, 14]:
        fr[f"tc_chg_{w}d"] = fr["trade_count"].pct_change(w)
        fr[f"ats_chg_{w}d"] = fr["avg_trade_size"].pct_change(w)
    ts = fr["avg_trade_size"]
    ts_mean = ts.rolling(30, min_periods=10).mean().shift(1)
    ts_std = ts.rolling(30, min_periods=10).std().shift(1)
    fr["ats_z"] = (ts - ts_mean) / ts_std
    for c in fr.select_dtypes(include="float").columns:
        fr[c] = fr[c].replace([np.inf, -np.inf], np.nan)
    return fr


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in SYM28:
        fr = load_joint(b)
        # inline feature build
        p = HERE / "data" / "crypto" / "activity" / f"{b}USDT_1h.parquet"
        if p.exists():
            a = pd.read_parquet(p)
            kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
            g = a.groupby(kst_day)
            day = pd.DataFrame({
                "quote_volume": g["quote_asset_volume"].sum(),
                "trade_count": g["number_of_trades"].sum(),
            })
            day.index.name = "date"
            day["avg_trade_size"] = day["quote_volume"] / day["trade_count"]
            day = day.reindex(fr.index)
            fr = fr.join(day, how="left")
            for w in [3, 7, 14]:
                fr[f"tc_chg_{w}d"] = fr["trade_count"].pct_change(w)
                fr[f"ats_chg_{w}d"] = fr["avg_trade_size"].pct_change(w)
            ts = fr["avg_trade_size"]
            ts_mean = ts.rolling(30, min_periods=10).mean().shift(1)
            ts_std = ts.rolling(30, min_periods=10).std().shift(1)
            fr["ats_z"] = (ts - ts_mean) / ts_std
        for c in fr.select_dtypes(include="float").columns:
            fr[c] = fr[c].replace([np.inf, -np.inf], np.nan)
        fr["symbol"] = b
        frames[b] = fr
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    FEATURES = [
        "tc_chg_3d", "tc_chg_7d", "tc_chg_14d",
        "ats_chg_3d", "ats_chg_7d", "ats_chg_14d",
        "ats_z",
    ]
    TARGETS = ["r_1", "r_3", "r_7"]
    
    # 1) Pooled decile (vectorized, no loops)
    pooled = {f: {h: spread(full, f, h) for h in ["r_1", "r_3", "r_7"]} for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]}
    
    # 2) Correlation with controls (vectorized)
    corr_f = {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]}
    corr_m = {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]}
    
    # 3) Simple cost test (no date loops - use overall decile)
    cost_results = {}
    for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]:
        s = full.dropna(subset=[f, "r_1"]).copy()
        s["_dec"] = decile_rank(s[f])
        d10 = s[s["_dec"] == 10]["r_1"].mean()
        d1 = s[s["_dec"] == 1]["r_1"].mean()
        pnl = d10 - d1
        for bp in [10, 30, 50]:
            net = pnl - (bp / 10000.0) * 2
            # Can't compute t-stat without daily series, just report mean
            pass
    
    # Simple LOO (drop BTC only)
    loo = {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]}
    
    out = {"design": {"purpose": "Trade structure predictive test (minimal)", "features": ["tc_chg_7d", "ats_chg_7d", "ats_z"]},
           "pooled_decile_r7": {f: spread(full, f, "r_7") for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]},
           "corr_with_f": {f: corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1] for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]},
           "corr_with_mom": {f: corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1] for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]},
           "loo_btc_drop": {f: spread(full[full["symbol"] != "BTC"], f, "r_7") for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]},
           "runtime_sec": round(time.time() - t_start, 1)}
    
    # JSON 저장
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n=== Step 32 Trade Structure Predictive Test ({time.time()-t_start:.1f}s) ===")
    print("\n[1] Pooled Decile r_7:")
    for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]:
        d = spread(full, f, "r_7")
        print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Corr with f_avg / mom30:")
    for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]:
        c1 = corr2(full[f].to_numpy(float), full["f_avg"].to_numpy(float))[1]
        c2 = corr2(full[f].to_numpy(float), full["mom30"].to_numpy(float))[1]
        print(f"  {f:16s} vs_f={c1:+.4f} vs_mom={c2:+.4f}")
    
    print("\n[LOO] Drop BTC (r_7):")
    for f in ["tc_chg_7d", "ats_chg_7d", "ats_z"]:
        d = spread(full[full["symbol"] != "BTC"], f, "r_7")
        print(f"  {f:16s} Δ={d['D1_minus_D10']:+.6f} t={d['t']}")
    
    # JSON 저장
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nTotal runtime: {time.time() - t_start:.1f}s")
    print("JSON:", OUT_JSON)


if __name__ == "__main__":
    import time
    from scipy import stats
    import pandas as pd
    import numpy as np
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    OUT_JSON = HERE / "findings" / "trade-structure-predictive-2026-08.json"
    OUT_MD = HERE / "findings" / "trade-structure-predictive-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, spread, decile_rank, corr2  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    SYM28 = ALL
    main()