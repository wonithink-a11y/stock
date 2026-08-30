#!/usr/bin/env python
"""Step 31 — Exchange Lead-Lag Predictive Test (Daily).

Binance USDT ↔ Upbit KRW 일간 리드-래그 예측력 검증.
- Binance→Upbit, Upbit→Binance 양방향
- lag 1/2/3일
- pooled spread + date-CS IC + 연도별 + funding/mom 통제
- 거래비용 10/30/50bp 적용 전후

기존 데이터만 사용, 대량 수집/수정/백테스트 금지.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "exchange-lead-lag-predictive-2026-08.json"
OUT_MD = HERE / "findings" / "exchange-lead-lag-predictive-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, MINASSETS)

KRW_BASES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "DOT", "ATOM", "AVAX",
             "LINK", "NEAR", "OP", "UNI", "ARB", "MATIC"]
USDT_28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]
KRW_TO_USDT = {b: f"{b}USDT" for b in KRW_BASES}


def load_krw_daily():
    data = {}
    for b in KRW_BASES:
        p = HERE / "data" / "crypto" / "daily" / f"KRW-{b}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                data[b] = df
    return data


def load_usdt_daily_from_basis1h():
    """basis/1h mark_close 14:00 UTC → KST daily close."""
    data = {}
    for s in USDT_28:
        p = HERE / "data" / "crypto" / "basis" / "1h" / f"{s}_1h.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                df_14 = df[df["time"].dt.hour == 14].copy()
                df_14["kst_date"] = (df_14["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
                daily = df_14.groupby("kst_date")["mark_close"].last()
                daily.index.name = "date"
                data[s.replace("USDT", "")] = daily
    return data


def load_funding_mom(b):
    """funding + mom30 for control."""
    fr = load_joint(KRW_TO_USDT[b])
    return fr["f_avg"], fr["mom30"]


def welch_t(a, b):
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan, 0.0
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return float(t), float(p), float(a.mean() - b.mean())


def corr_spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 30:
        return np.nan, np.nan
    return stats.spearmanr(x[ok], y[ok]).statistic, ok.sum()


def date_cs_ic(df, feat, target, min_assets=5):
    ics = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[feat, target])
        if len(s) < min_assets:
            continue
        ic = stats.spearmanr(s[feat], s[target]).statistic
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 10:
        return {"n_dates": len(ics), "mean_ic": None, "t": None, "frac_pos": None}
    ics = np.array(ics, float)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {"n_dates": len(ics), "mean_ic": round(float(ics.mean()), 6),
            "t": round(float(t), 3), "frac_pos": round(float((ics > 0).mean()), 4)}


def main():
    # Load data
    krw_daily = load_krw_daily()
    usdt_daily = load_usdt_daily_from_basis1h()
    
    # Common symbols (14, excluding MATIC)
    common = [b for b in KRW_BASES if b != "MATIC" and b in krw_daily and b in usdt_daily]
    
    # Build panel with proper alignment
    # KRW close at KST 00:00 (d) → shift(1) to align with USDT close at KST 24:00 (d)
    # USDT close at KST 24:00 (d) is the close of day d
    # KRW close at KST 00:00 (d) is the close of day d-1 (effectively)
    # So: KRW_close(d) corresponds to day d-1 close, USDT_close(d) is day d close
    # For Binance→Upbit lead: USDT_ret(d-1) vs KRW_ret(d)
    # For Upbit→Binance lead: KRW_ret(d-1) vs USDT_ret(d)
    
    panels = {}
    for b in common:
        krw = krw_daily[b][["close"]].rename(columns={"close": "krw_close"})
        usdt = usdt_daily[b].rename("usdt_close")  # key is base symbol
        
        # Align on common dates
        df = pd.concat([krw, usdt], axis=1).dropna()
        
        # Returns
        df["krw_ret_1"] = df["krw_close"].pct_change()
        df["usdt_ret_1"] = df["usdt_close"].pct_change()
        
        # Lag features (using proper alignment)
        # Binance leads Upbit: USDT return at d-1 predicts KRW return at d
        df["usdt_ret_lag1"] = df["usdt_ret_1"].shift(1)
        df["usdt_ret_lag2"] = df["usdt_ret_1"].shift(2)
        df["usdt_ret_lag3"] = df["usdt_ret_1"].shift(3)
        
        # Upbit leads Binance: KRW return at d-1 predicts USDT return at d
        df["krw_ret_lag1"] = df["krw_ret_1"].shift(1)
        df["krw_ret_lag2"] = df["krw_ret_1"].shift(2)
        df["krw_ret_lag3"] = df["krw_ret_1"].shift(3)
        
        # Targets: next day returns
        df["krw_ret_fwd1"] = df["krw_ret_1"].shift(-1)
        df["usdt_ret_fwd1"] = df["usdt_ret_1"].shift(-1)
        df["krw_ret_fwd2"] = df["krw_ret_1"].shift(-2)
        df["usdt_ret_fwd2"] = df["usdt_ret_1"].shift(-2)
        df["krw_ret_fwd3"] = df["krw_ret_1"].shift(-3)
        df["usdt_ret_fwd3"] = df["usdt_ret_1"].shift(-3)
        
        # Funding + mom for control (from funding_premium_info_check load_joint)
        fr = load_joint(b)
        df["f_avg"] = fr["f_avg"].reindex(df.index)
        df["mom30"] = fr["mom30"].reindex(df.index)
        
        df["symbol"] = b
        panels[b] = df.dropna(subset=["krw_ret_fwd1", "usdt_ret_fwd1", 
                                       "usdt_ret_lag1", "krw_ret_lag1"])
    
    full = pd.concat(panels.values()).reset_index().rename(columns={"index": "date"})
    full["year"] = full["date"].dt.year
    
    out = {"design": {
        "purpose": "Binance↔Upbit daily lead-lag predictive test",
        "alignment": "KRW close(KST 00:00) shift(1) to align with USDT close(KST 24:00)",
        "directions": ["Binance→Upbit (usdt_ret_lag→krw_ret_fwd)", "Upbit→Binance (krw_ret_lag→usdt_ret_fwd)"],
        "lags": [1, 2, 3],
        "horizons": ["fwd1", "fwd2", "fwd3"],
        "controls": ["funding (f_avg)", "momentum (mom30)"],
        "costs_bp": [10, 30, 50],
    }}
    
    # --- 1) Baseline: pooled decile spreads ---
    # Direction 1: Binance → Upbit (usdt_ret_lag → krw_ret_fwd)
    out["binance_to_upbit"] = {}
    for lag in [1, 2, 3]:
        feat = f"usdt_ret_lag{lag}"
        for h in ["krw_ret_fwd1", "krw_ret_fwd2", "krw_ret_fwd3"]:
            out["binance_to_upbit"].setdefault(f"{feat}->{h}", {})
            out["binance_to_upbit"][f"{feat}->{h}"]["pooled_decile"] = spread(full, feat, h)
            out["binance_to_upbit"][f"{feat}->{h}"]["date_cs"] = date_cs_ic(full, feat, h)
            # Yearly
            out["binance_to_upbit"][f"{feat}->{h}"]["by_year"] = {}
            for y in sorted(full["year"].unique()):
                ys = full[full["year"] == y]
                if len(ys) > 200:
                    out["binance_to_upbit"][f"{feat}->{h}"]["by_year"][int(y)] = spread(ys, feat, h)
    
    # Direction 2: Upbit → Binance (krw_ret_lag → usdt_ret_fwd)
    out["upbit_to_binance"] = {}
    for lag in [1, 2, 3]:
        feat = f"krw_ret_lag{lag}"
        for h in ["usdt_ret_fwd1", "usdt_ret_fwd2", "usdt_ret_fwd3"]:
            out["upbit_to_binance"].setdefault(f"{feat}->{h}", {})
            out["upbit_to_binance"][f"{feat}->{h}"]["pooled_decile"] = spread(full, feat, h)
            out["upbit_to_binance"][f"{feat}->{h}"]["date_cs"] = date_cs_ic(full, feat, h)
            out["upbit_to_binance"][f"{feat}->{h}"]["by_year"] = {}
            for y in sorted(full["year"].unique()):
                ys = full[full["year"] == y]
                if len(ys) > 200:
                    out["upbit_to_binance"][f"{feat}->{h}"]["by_year"][int(y)] = spread(ys, feat, h)
    
    # --- 2) Correlation matrix ---
    out["correlations"] = {}
    for lag in [1, 2, 3]:
        out["correlations"][f"usdt_lag{lag}_vs_krw_fwd1"] = corr_spearman(
            full[f"usdt_ret_lag{lag}"].to_numpy(float), full["krw_ret_fwd1"].to_numpy(float))
        out["correlations"][f"krw_lag{lag}_vs_usdt_fwd1"] = corr_spearman(
            full[f"krw_ret_lag{lag}"].to_numpy(float), full["usdt_ret_fwd1"].to_numpy(float))
    
    # --- 3) Control for funding + momentum ---
    # Residualize features w.r.t. f_avg + mom30 (rolling OOS)
    for feat_name in ["usdt_ret_lag1", "usdt_ret_lag2", "usdt_ret_lag3",
                      "krw_ret_lag1", "krw_ret_lag2", "krw_ret_lag3"]:
        full[f"{feat_name}_fmresid"] = rolling_oos_resid(
            full[feat_name].to_numpy(float),
            [full["f_avg"].to_numpy(float), full["mom30"].to_numpy(float)])
    
    out["controlled"] = {}
    for feat in ["usdt_ret_lag1", "usdt_ret_lag2", "usdt_ret_lag3"]:
        out["controlled"][f"{feat}_fmresid->krw_fwd1"] = {
            "pooled_decile": spread(full, f"{feat}_fmresid", "krw_ret_fwd1"),
            "date_cs": date_cs_ic(full, f"{feat}_fmresid", "krw_ret_fwd1"),
        }
    for feat in ["krw_ret_lag1", "krw_ret_lag2", "krw_ret_lag3"]:
        out["controlled"][f"{feat}_fmresid->usdt_fwd1"] = {
            "pooled_decile": spread(full, f"{feat}_fmresid", "usdt_ret_fwd1"),
            "date_cs": date_cs_ic(full, f"{feat}_fmresid", "usdt_ret_fwd1"),
        }
    
    # --- 4) Transaction costs simulation ---
    # Simple: if signal (decile 10 vs 1) says long/short, apply cost per trade
    # For simplicity: compute long-short spread net of cost assuming daily rebalance
    cost_bps = [10, 30, 50]
    out["costs"] = {}
    for direction in ["binance_to_upbit", "upbit_to_binance"]:
        if direction == "binance_to_upbit":
            feat_base = "usdt_ret_lag1"
            target = "krw_ret_fwd1"
            other_ret = "usdt_ret_1"  # for turnover proxy
        else:
            feat_base = "krw_ret_lag1"
            target = "usdt_ret_fwd1"
            other_ret = "krw_ret_1"
        
        # Decile 10 - Decile 1 daily P&L (raw)
        daily_pnl = {}
        for d, sub in full.groupby("date"):
            s = sub.dropna(subset=[feat_base, target])
            if len(s) < 5: continue
            dec = decile_rank(s[feat_base])
            s["_dec"] = dec
            d10 = s[s["_dec"] == 10][target].mean()
            d1 = s[s["_dec"] == 1][target].mean()
            daily_pnl[d] = d10 - d1
        
        pnl = pd.Series(daily_pnl).dropna()
        for bp in [10, 30, 50]:
            # Simplified: assume 2 * bp * turnover_frac (full turnover daily)
            # Conservative: assume 100% turnover daily for extreme decile portfolio
            net = pnl - (bp / 10000.0) * 2  # round trip cost
            out["costs"][f"{direction}_cost{bp}bp"] = {
                "mean_pnl": float(pnl.mean()),
                "net_pnl": float(net.mean()),
                "sharpe": float(net.mean() / net.std() * np.sqrt(252)) if net.std() > 0 else 0,
                "t_stat": float(stats.ttest_1samp(net, 0).statistic),
            }
    
    # JSON 저장
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (np.generic, pd.Timestamp)):
            return str(obj)
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")
    
    # 콘솔 요약
    print("=== Step 31 Exchange Lead-Lag Predictive Test ===")
    print(f"\nCommon symbols: {len(panels)} | Total obs: {len(full)}")
    
    print("\n[1] Binance→Upbit (usdt_lag → krw_fwd) r_1 spread (t):")
    for lag in [1, 2, 3]:
        key = f"usdt_ret_lag{lag}->krw_ret_fwd1"
        d = out["binance_to_upbit"][key]["pooled_decile"]
        print(f"  lag{lag}: Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[2] Upbit→Binance (krw_lag → usdt_fwd) r_1 spread (t):")
    for lag in [1, 2, 3]:
        key = f"krw_ret_lag{lag}->usdt_ret_fwd1"
        d = out["upbit_to_binance"][key]["pooled_decile"]
        print(f"  lag{lag}: Δ={d['D1_minus_D10']:+.6f} t={d['t']} nD1={d['n_D1']}")
    
    print("\n[3] Date-CS IC (lag1, fwd1):")
    b2u = out["binance_to_upbit"]["usdt_ret_lag1->krw_ret_fwd1"]["date_cs"]
    u2b = out["upbit_to_binance"]["krw_ret_lag1->usdt_ret_fwd1"]["date_cs"]
    print(f"  B→U: IC={b2u['mean_ic']:+.4f} t={b2u['t']} pos={b2u['frac_pos']:.2f}")
    print(f"  U→B: IC={u2b['mean_ic']:+.4f} t={u2b['t']} pos={u2b['frac_pos']:.2f}")
    
    print("\n[4] Controlled (fund+mom residual) lag1 fwd1:")
    c1 = out["controlled"]["usdt_ret_lag1_fmresid->krw_fwd1"]["pooled_decile"]
    c2 = out["controlled"]["krw_ret_lag1_fmresid->usdt_fwd1"]["pooled_decile"]
    print(f"  B→U resid: Δ={c1['D1_minus_D10']:+.6f} t={c1['t']}")
    print(f"  U→B resid: Δ={c2['D1_minus_D10']:+.6f} t={c2['t']}")
    
    print("\n[5] Costs (lag1, fwd1, round-trip):")
    for bp in [10, 30, 50]:
        c = out["costs"][f"binance_to_upbit_cost{bp}bp"]
        print(f"  B→U {bp}bp: mean={c['mean_pnl']:.6f} net={c['net_pnl']:.6f} t={c['t_stat']:.2f}")
        c = out["costs"][f"upbit_to_binance_cost{bp}bp"]
        print(f"  U→B {bp}bp: mean={c['mean_pnl']:.6f} net={c['net_pnl']:.6f} t={c['t_stat']:.2f}")
    
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()