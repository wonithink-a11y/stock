#!/usr/bin/env python
"""Step 39 — GitHub 공개 Crypto 전략 재현 테스트 (Close-only).

load_joint 데이터는 high/low 없으므로 close-only 지표만 사용.
RSI, MACD, EMA, Bollinger Bands (close 기반)만 가능.
Supertrend/ATR/VWAP은 high/low 필요하므로 제외.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "github-strategy-reproduction-2026-08.json"
OUT_MD = HERE / "findings" / "github-strategy-reproduction-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, HORIZONS  # noqa: E402
from funding_premium_info_check import ALL  # noqa: E402

SYM28 = ALL
TARGETS = list(HORIZONS.keys())


def add_close_indicators(fr):
    """close-only 지표들만 추가."""
    c = fr["close"]
    
    # RSI
    delta = fr["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    fr["rsi_14"] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    fr["macd"] = ema12 - ema26
    fr["macd_signal"] = fr["macd"].ewm(span=9).mean()
    fr["macd_hist"] = fr["macd"] - fr["macd_signal"]
    
    # EMA
    for span in [9, 21, 50, 200]:
        fr[f"ema_{span}"] = c.ewm(span=span).mean()
    
    # Bollinger Bands
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    fr["bb_upper"] = ma20 + 2 * std20
    fr["bb_lower"] = ma20 - 2 * std20
    fr["bb_mid"] = ma20
    
    return fr


def run_strategy_1_rsi_mr(fr):
    """Strategy 1: RSI Mean Reversion (Freqtrade style)
    Entry: RSI < 30
    Exit: RSI > 70
    """
    fr = fr.copy()
    fr["signal"] = 0
    fr.loc[fr["rsi_14"] < 30, "signal"] = 1
    fr.loc[fr["rsi_14"] > 70, "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def run_strategy_2_macd(fr):
    """Strategy 2: MACD Crossover"""
    fr = fr.copy()
    fr["signal"] = 0
    fr.loc[(fr["macd"] > fr["macd_signal"]) & (fr["macd"].shift(1) <= fr["macd_signal"].shift(1)), "signal"] = 1
    fr.loc[(fr["macd"] < fr["macd_signal"]) & (fr["macd"].shift(1) >= fr["macd_signal"].shift(1)), "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def run_strategy_3_ema_cross(fr):
    """Strategy 3: EMA 9/21 Crossover"""
    fr = fr.copy()
    fr["signal"] = 0
    fr.loc[(fr["ema_9"] > fr["ema_21"]) & (fr["ema_9"].shift(1) <= fr["ema_21"].shift(1)), "signal"] = 1
    fr.loc[(fr["ema_9"] < fr["ema_21"]) & (fr["ema_9"].shift(1) >= fr["ema_21"].shift(1)), "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def run_strategy_4_bb_mr(fr):
    """Strategy 4: Bollinger Bands Mean Reversion"""
    fr = fr.copy()
    fr["signal"] = 0
    fr.loc[fr["close"] < fr["bb_lower"], "signal"] = 1
    fr.loc[fr["close"] > fr["bb_upper"], "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def run_strategy_5_ema_trend(fr):
    """Strategy 5: EMA Trend Following (EMA50 > EMA200 = Long)"""
    fr = fr.copy()
    fr["signal"] = 0
    fr.loc[fr["ema_50"] > fr["ema_200"], "signal"] = 1
    fr.loc[fr["ema_50"] < fr["ema_200"], "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def run_strategy_6_dual_momentum(fr):
    """Strategy 6: Dual Momentum (mom30 + mom60)"""
    fr = fr.copy()
    fr["mom_60"] = fr["close"].pct_change(60)
    fr["signal"] = 0
    fr.loc[(fr["mom30"] > 0) & (fr["mom_60"] > 0), "signal"] = 1
    fr.loc[(fr["mom30"] < 0) | (fr["mom_60"] < 0), "signal"] = -1
    fr["position"] = fr["signal"].replace({-1: 0}).ffill().fillna(0)
    fr["ret_strat"] = fr["position"].shift(1) * fr["r_1"]
    return fr


def add_close_indicators(fr):
    c = fr["close"]
    delta = fr["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    fr["rsi_14"] = 100 - (100 / (1 + rs))
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    fr["macd"] = ema12 - ema26
    fr["macd_signal"] = fr["macd"].ewm(span=9).mean()
    for span in [9, 21, 50, 200]:
        fr[f"ema_{span}"] = c.ewm(span=span).mean()
    ma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    fr["bb_upper"] = ma20 + 2 * std20
    fr["bb_lower"] = ma20 - 2 * std20
    fr["bb_mid"] = ma20
    return fr


def evaluate_strategy(fr):
    rets = fr["ret_strat"].dropna()
    if len(rets) < 10:
        return {"error": "insufficient data"}
    years = len(rets) / 365.25
    cum = (1 + rets).prod()
    cagr = cum ** (1 / (len(rets) / 365.25)) - 1 if years > 0 else 0
    ann_vol = rets.std() * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0
    cum_curve = (1 + rets).cumprod()
    peak = cum_curve.expanding().max()
    dd = (cum_curve / peak - 1).min()
    win_rate = (rets > 0).mean()
    gross_profit = rets[rets > 0].sum()
    gross_loss = abs(rets[rets < 0].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else np.inf
    n_trades = len(fr[fr["signal"] != 0])
    return {
        "cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
        "win_rate": float(win_rate), "profit_factor": float(pf),
        "n_trades": int(n_trades), "n_obs": len(rets),
    }


def main():
    t_start = time.time()
    print(f"[{time.time()-t_start:.1f}s] Loading 28 symbols...")
    frames = {}
    for b in ALL:
        fr = load_joint(b)
        fr = add_close_indicators(fr)
        fr["btc_regime"] = np.where(fr["mom30"] > 0, "bull", "bear")
        fr["symbol"] = b
        frames[b] = fr
    print(f"[{time.time()-t_start:.1f}s] Loaded {len(frames)} symbols")
    
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    
    strategies = {
        "1_RSI_MR": run_strategy_1_rsi_mr,
        "2_MACD_Cross": run_strategy_2_macd,
        "3_EMA9_21_Cross": run_strategy_3_ema_cross,
        "4_BB_MR": run_strategy_4_bb_mr,
        "5_EMA_Trend": run_strategy_5_ema_trend,
        "6_Dual_Momentum": run_strategy_6_dual_momentum,
    }
    
    results = {}
    for name, func in strategies.items():
        print(f"\nRunning {name}...")
        results[name] = {}
        for b in SYM28:
            fr = frames[b].copy()
            fr = func(fr)
            res = evaluate_strategy(fr)
            results[name][b] = res
        all_fr = pd.concat([func(frames[b].copy()) for b in SYM28]).reset_index(drop=True)
        results[name]["aggregated"] = evaluate_strategy(all_fr)
    
    # B&H baseline
    all_fr = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    bh_ret = all_fr.groupby("date")["r_1"].mean()
    bh_cum = (1 + bh_ret).cumprod()
    years = len(bh_ret) / 365.25
    bh_cagr = bh_cum.iloc[-1] ** (1 / (len(bh_ret) / 365.25)) - 1
    bh_sharpe = (bh_cagr) / (bh_ret.std() * np.sqrt(365.25))
    bh_dd = ((1 + bh_ret).cumprod() / (1 + bh_ret).cumprod().expanding().max() - 1).min()
    print(f"B&H: CAGR={bh_cagr:.2%}, Sharpe={bh_sharpe:.2f}, MDD={bh_dd:.2%}")
    
    print("\n=== Strategy Results ===")
    for name, res in results.items():
        agg = res["aggregated"]
        print(f"\n{name}:")
        print(f"  CAGR={agg['cagr']:.2%}, Sharpe={agg['sharpe']:.2f}, MDD={agg['max_dd']:.2%}")
        print(f"  WR={agg['win_rate']:.2%}, PF={agg['profit_factor']:.2f}, Trades={agg['n_trades']}")
    
    # JSON
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (np.generic, pd.Timestamp)): return str(obj)
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "design": {"purpose": "GitHub strategy reproduction test", "strategies": list(strategies.keys())},
        "results": {name: {k: _to_jsonable(v) for k, v in res.items()} for name, res in results.items()},
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
    OUT_JSON = HERE / "findings" / "github-strategy-reproduction-2026-08.json"
    OUT_MD = HERE / "findings" / "github-strategy-reproduction-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    from funding_premium_info_check import load_joint, HORIZONS  # noqa: E402
    from funding_premium_info_check import ALL  # noqa: E402
    SYM28 = ALL
    TARGETS = list(HORIZONS.keys())
    main()