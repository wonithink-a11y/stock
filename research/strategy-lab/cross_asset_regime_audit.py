#!/usr/bin/env python
"""Step 36 — Cross-Asset Regime Factor Audit (BTC as market factor).

기존 데이터만 사용해 BTC가 시장 regime factor로 활용 가능한지 감사.
- BTC momentum/volatility/return/drawdown
- BTC dominance proxy
- BTC regime과 알트 idiosyncratic return 관계

데이터 가용성·기간·공통 universe·결측만 감사. 예측력 테스트·백테스트·수정·커밋 금지.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "cross-asset-regime-audit-2026-08.json"
OUT_MD = HERE / "findings" / "cross-asset-regime-audit-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, corr2  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL


def load_btc_daily():
    out = {}
    p = HERE / "data" / "crypto" / "daily" / "KRW-BTC.parquet"
    if p.exists():
        df = pd.read_parquet(p)
        out["krw_daily"] = {"rows": len(df), "start": str(df.index.min()), "end": str(df.index.max()),
                            "cols": list(df.columns)}
    p = HERE / "data" / "crypto" / "basis" / "1h" / "BTCUSDT_1h.parquet"
    if p.exists():
        h1 = pd.read_parquet(p)
        h14 = h1[h1["time"].dt.hour == 14].copy()
        h14["kst_date"] = (h14["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
        daily = h14.groupby("kst_date")["mark_close"].last()
        daily.index.name = "date"
        out["usdt_daily"] = {"rows": len(daily), "start": str(daily.index.min()), "end": str(daily.index.max())}
    return out


def load_btc_1h():
    p = HERE / "data" / "crypto" / "basis" / "1h" / "BTCUSDT_1h.parquet"
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
    daily["ret_1d"] = daily["close"].pct_change()
    h1_logret = np.log(h1["mark_close"]).diff().dropna()
    h1["log_ret"] = h1_logret
    rv = h1.groupby((h1["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize())["log_ret"].apply(lambda x: np.nansum(x**2))
    rv.name = "rv_1d"
    rv.index.name = "date"
    mom_data = {}
    for w in [7, 30]:
        mom_data[f"mom_{w}d"] = daily["close"].pct_change(w)
    return {"daily": daily, "rv": rv, "mom": mom_data}


def check_dominance_proxy():
    total_vol = {}
    for b in ALL:
        p = HERE / "data" / "crypto" / "activity" / f"{b}USDT_1h.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            kst_day = (df["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
            daily_qv = df.groupby(kst_day)["quote_asset_volume"].sum()
            total_vol[b] = daily_qv
    if total_vol:
        all_qv = pd.concat(total_vol.values(), axis=1)
        all_qv.columns = total_vol.keys()
        btc_qv = total_vol["BTC"]
        dominance = btc_qv / all_qv.sum(axis=1)
        return {"available": True, "rows": len(dominance), "start": str(dominance.index.min()), "end": str(dominance.index.max()),
                "mean_dominance": float(dominance.mean()), "std": float(dominance.std())}
    return {"available": False}


def check_alt_idiosyncratic():
    btc_data = load_btc_daily()
    return {"btc_daily": "usdt_daily" in btc_data, "krw_daily": "krw_daily" in btc_data}


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Starting Step 36 Cross-Asset Regime Audit...")
    
    # 1. BTC data availability
    print("\n[1] BTC Data Availability")
    btc_daily = load_btc_daily()
    print(f"  KRW daily: {btc_daily.get('krw_daily', {}).get('rows', 0)} rows")
    print(f"  USDT daily: {btc_daily.get('usdt_daily', {}).get('rows', 0)} rows")
    
    # 2. BTC 1h derived features
    print("\n[2] BTC 1h Derived Features")
    btc_1h = load_btc_1h()
    if btc_1h:
        daily = btc_1h["daily"]
        rv = btc_1h["rv"]
        mom = btc_1h["mom"]
        print(f"  Daily OHLCV: {len(daily)} rows, {daily.index.min()} ~ {daily.index.max()}")
        print(f"  RV_1d: {len(rv)} rows, mean={rv.mean():.6f}")
        for k, v in mom.items():
            print(f"  {k}: {len(v)} rows")
    
    # 3. BTC Dominance proxy
    print("\n[3] BTC Dominance Proxy (USDT market share)")
    dom = check_dominance_proxy()
    print(f"  Available: {dom.get('available', False)}")
    if dom.get("available"):
        print(f"  Rows: {dom['rows']}, {dom['start']} ~ {dom['end']}")
        print(f"  Mean: {dom['mean_dominance']:.4f}, Std: {dom['std']:.4f}")
    
    # 4. Alt idiosyncratic potential
    print("\n[4] Alt Idiosyncratic Return Potential")
    alt = check_alt_idiosyncratic()
    print(f"  BTC USDT daily: {alt['btc_daily']}")
    print(f"  BTC KRW daily: {alt['krw_daily']}")
    
    # 5. Load alt data for regime analysis
    print("\n[5] Alt Data for Regime Analysis")
    frames = {}
    for b in ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"]:
        fr = load_joint(b)
        frames[b] = fr
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    btc_ret = full[full["symbol"] == "BTC"][["date", "r_1", "r_3", "r_7", "mom30", "f_avg"]].rename(
        columns=lambda x: f"btc_{x}" if x != "date" else x)
    
    alts = full[full["symbol"] != "BTC"][["date", "symbol", "r_1", "r_3", "r_7", "mom30"]].copy()
    merged = alts.merge(btc_ret, on="date", how="left")
    merged["btc_regime"] = np.where(merged["btc_mom30"] > 0, "bull", "bear")
    merged["idio_r1"] = merged["r_1"] - merged["btc_r_1"]
    merged["idio_r7"] = merged["r_7"] - merged["btc_r_7"]
    
    regime_stats = merged.groupby("btc_regime")[["idio_r1", "idio_r7"]].describe()
    print(f"\n  Idiosyncratic return by BTC regime:")
    print(regime_stats)
    
    # 6. Correlation: BTC mom vs alt mom
    regime_corr = {}
    print("\n[6] BTC mom30 vs Alt mom30 correlation")
    for sym in ["ETH", "SOL", "XRP", "ADA", "DOGE"]:
        if sym in frames:
            common_idx = frames[sym].index.intersection(frames["BTC"].index)
            if len(common_idx) > 100:
                c = corr2(frames[sym].loc[common_idx, "mom30"].to_numpy(float), 
                         frames["BTC"].loc[common_idx, "mom30"].to_numpy(float))
                print(f"  {sym} mom30 vs BTC mom30: pear={c[0]:.4f}, spear={c[1]:.4f}")
                regime_corr[sym] = {"pearson": c[0], "spearman": c[1]}
            else:
                print(f"  {sym}: insufficient overlap ({len(common_idx)} points)")
                regime_corr[sym] = {"error": "insufficient_overlap"}
    
    # 7. BTC regime vs Alt forward returns
    print("\n[7] BTC regime vs Alt forward returns")
    regime_returns = {}
    for sym in ["ETH", "SOL", "XRP", "ADA", "DOGE"]:
        sub = merged[merged["symbol"] == sym].dropna(subset=["r_7", "btc_regime"])
        if len(sub) > 50:
            bull = sub[sub["btc_regime"] == "bull"]["r_7"].mean()
            bear = sub[sub["btc_regime"] == "bear"]["r_7"].mean()
            print(f"  {sym}: bull={bull:+.4f}, bear={bear:+.4f}, diff={bull-bear:+.4f}")
            regime_returns[sym] = {"bull_mean": float(bull), "bear_mean": float(bear), "diff": float(bull - bear)}
    
    # JSON output
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "BTC as market regime factor audit", "universe": "28 symbols"},
        "btc_daily": btc_daily,
        "btc_1h_features": {"daily_rows": len(btc_1h["daily"]) if btc_1h else 0,
                           "rv_mean": float(btc_1h["rv"].mean()) if btc_1h else None,
                           "mom_available": list(btc_1h["mom"].keys()) if btc_1h else []},
        "dominance_proxy": dom,
        "alt_idiosyncratic": alt,
        "regime_correlation": regime_corr,
        "regime_vs_alt_returns": regime_returns,
        "idiosyncratic_stats": {reg: {"idio_r1_mean": float(merged[merged["btc_regime"]==reg]["idio_r1"].mean()),
                                      "idio_r7_mean": float(merged[merged["btc_regime"]==reg]["idio_r7"].mean())}
                                 for reg in ["bull", "bear"]},
        "runtime_sec": round(time.time() - t_start, 1),
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    # Console summary
    print(f"\nTotal runtime: {time.time() - t_start:.1f}s")
    print("JSON:", OUT_JSON)
    
    # MD report
    print("\n=== Step 36 Cross-Asset Regime Audit Summary ===")
    print(f"BTC data: KRW {btc_daily.get('krw_daily',{}).get('rows',0)} rows, USDT {btc_daily.get('usdt_daily',{}).get('rows',0)} rows")
    print(f"BTC 1h: {btc_1h['daily'].shape if btc_1h else 0} rows, RV mean={btc_1h['rv'].mean():.6f}" if btc_1h else "BTC 1h: N/A")
    print(f"Dominance proxy: {dom.get('available', False)}, {dom.get('rows',0)} rows, mean={dom.get('mean_dominance',0):.4f}")
    print(f"BTC mom30 vs Alt mom30: ETH={regime_corr.get('ETH',{}).get('pearson',0):.4f}, SOL={regime_corr.get('SOL',{}).get('pearson',0):.4f}")
    print(f"BTC regime vs alt r7: ETH bull={regime_returns.get('ETH',{}).get('bull_mean',0):+.4f} bear={regime_returns.get('ETH',{}).get('bear_mean',0):+.4f}")
    print(f"Idiosyncratic r7 mean: bull={merged[merged['btc_regime']=='bull']['idio_r7'].mean():+.4f}, bear={merged[merged['btc_regime']=='bear']['idio_r7'].mean():+.4f}")


if __name__ == "__main__":
    import time
    import json
    import pandas as pd
    import numpy as np
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    OUT_JSON = HERE / "findings" / "cross-asset-regime-audit-2026-08.json"
    OUT_MD = HERE / "findings" / "cross-asset-regime-audit-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, corr2  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    main()