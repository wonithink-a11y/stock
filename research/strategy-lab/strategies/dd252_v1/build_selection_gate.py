#!/usr/bin/env python
"""DD252 selection.json 생성 - 게이트 적용 (Arm A vs Arm B_ATR)

Usage:
  python build_selection_gate.py --arm A
  python build_selection_gate.py --arm B_ATR
"""

import json
import os
import sys

import numpy as np
import pandas as pd

# --- Path setup ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# --- Imports ---
from engine.data.a2aProvider import A2aProvider
from engine.data.a2bProvider import A2bProvider
from engine.data.calendar import TradingCalendar
from engine.data.universeProvider import UniverseProvider
from engine.runner import _drop_suspension_rows

from liquidity_factor_study import (
    load_full_ohlc, features_from_ohlc,
    monthly_rebalance_dates, LIQ_THRESHOLD,
)

# --- Constants ---
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

START = "2016-01-01"
END = "2026-08-03"
TOP_N = 30
HOLD_SESSIONS = 120
MIN_HISTORY = 273
LIQ_THRESHOLD = 1e8


# ============================================================
# Utility functions
# ============================================================
def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


# ============================================================
# Data loading functions
# ============================================================
def load_universe_and_price(repo_root):
    """Universe와 가격 데이터 로드"""
    universe = UniverseProvider(repo_root=repo_root, include_delisted=True)
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    calendar = TradingCalendar(repo_root=repo_root)

    print(f"Universe: {len(universe.tickers)} tickers (A1A_A1B_MERGED)")
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}
    a1a_tickers = set(universe.tickers) - a1b_tickers
    print(f"  A1A: {len(a1a_tickers)}, A1B: {len(a1b_tickers)}")

    all_tickers = set(universe.tickers)
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    bars_raw = a2a.load(universe.tickers, "2016-01-01", END, universe_hash=None)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    a1b_tickers_set = {e.ticker for e in universe.entries if e.source == "A1B"}
    if a1b_tickers_set:
        a2b_provider = A2bProvider(repo_root=repo_root)
        a2b_raw = a2b_provider.load(list(a1b_tickers_set), "2016-01-01", END, universe_hash=None)
        for t, df in a2b_raw.items():
            if not df.empty:
                bars_by_ticker[t] = _drop_suspension_rows(df)

    print(f"bars loaded: {len(bars_by_ticker)} tickers")
    return bars_by_ticker, calendar


def compute_dd252(bars_by_ticker, rebalance_dates):
    """dd_252_skip1m 계산"""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 273:
            continue
        close = bars["close"]
        idx = close.index.astype(str)
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            val = dd.iloc[i]
            if pd.isna(val):
                continue
            rows.append({"ticker": ticker, "asOf": t, "dd_252_skip1m": float(val)})
    return pd.DataFrame(rows)


def load_gate_features(repo_root):
    """B_ATR 게이트용 유동성/변동성 피처 로드"""
    print("Loading liquidity/volatility features for B_ATR gate...")
    wanted = set(pd.read_parquet(
        os.path.join(repo_root, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet"),
        columns=['ticker'])['ticker'].unique())
    
    from liquidity_factor_study import load_full_ohlc, features_from_ohlc
    full, _ = load_full_ohlc(wanted)
    
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)
    feats["dv20"] = np.exp(feats["dv20_log"])
    feats["gate_liq"] = feats["dv20"] >= 1e8
    feats["gate_atr_excl"] = feats["atr14_decile"] != 10
    
    return feats[["ticker", "date", "gate_liq", "gate_atr_excl"]].rename(columns={"date": "asOf"})


def apply_gate_B_ATR(panel, gate_feats):
    """B_ATR 게이트 적용: dv20 >= 1e8 AND atr14_pct != 10"""
    print("Applying B_ATR gate...")
    feats_gate = gate_feats[["ticker", "asOf", "gate_liq", "gate_atr_excl"]]
    eligible = panel.dropna(subset=["dd_252_skip1m"]).merge(
        feats_gate, on=["ticker", "asOf"], how="left"
    )
    eligible = eligible[eligible["gate_liq"].fillna(False) & eligible["gate_atr_excl"].fillna(False)]
    print(f"[B_ATR] after gate: {len(eligible)} rows")
    return eligible


def build_selection_json(eligible, rebalance_dates, arm_name, this_dir, arm):
    """eligible DataFrame에서 selection.json 생성"""
    hold_sessions_by_date = {t: 120 for t in rebalance_dates}
    
    selection = {}
    monthly_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        top = g.sort_values("dd_252_skip1m", ascending=False).head(30)
        monthly_counts[asOf] = len(top)
        for ticker in top["ticker"]:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": 120})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(THIS_DIR, f"selection_{arm}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_gate.py",
            "arm": arm,
            "sourcePanel": "computed in-process from A2a/A2b bars (dd_252_skip1m) - MERGED universe",
            "period": f"2016-01-01 ~ {END}",
            "holdSessions": 120,
            "topN": 30,
            "minHistorySessions": 273,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"[{arm}] saved: selection_{arm}.json ({len(selection)} tickers, {len(monthly_counts)} months)")


def run_build(arm, repo_root, this_dir):
    """메인 빌드 로직"""
    END = "2026-08-03"
    START = "2016-01-01"
    
    # 1. Load universe and price data
    bars_by_ticker, calendar = load_universe_and_price(REPO_ROOT)

    # 2. Rebalance dates
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    # 3. Compute dd_252_skip1m
    print("Computing dd_252_skip1m...")
    panel = compute_dd252(load_universe_and_price(REPO_ROOT)[0], rebalance_dates)
    print(f"panel rows={len(panel)}")

    # 3. Apply gate
    if arm == "B_ATR":
        gate_feats = load_gate_features(REPO_ROOT)
        eligible = apply_gate_B_ATR(panel, rebalance_dates, gate_feats)
    else:
        eligible = panel.dropna(subset=["dd_252_skip1m"])

    print(f"[{arm}] eligible rows={len(eligible)}")

    # 3. Build selection.json
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    build_selection_json(eligible, rebalance_dates, arm, THIS_DIR, arm)


def load_universe_and_price(repo_root):
    """Universe와 가격 데이터 로드"""
    universe = UniverseProvider(repo_root=repo_root, include_delisted=True)
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    calendar = TradingCalendar(repo_root=repo_root)

    print(f"Universe: {len(universe.tickers)} tickers (A1A_A1B_MERGED)")
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}
    a1a_tickers = set(universe.tickers) - a1b_tickers
    print(f"  A1A: {len(a1a_tickers)}, A1B: {len(a1b_tickers)}")

    all_tickers = set(universe.tickers)
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    bars_raw = a2a.load(universe.tickers, "2016-01-01", END, universe_hash=None)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    a1b_tickers_set = {e.ticker for e in universe.entries if e.source == "A1B"}
    if a1b_tickers_set:
        a2b_provider = A2bProvider(repo_root=repo_root)
        a2b_raw = a2b_provider.load(list(a1b_tickers_set), "2016-01-01", END, universe_hash=None)
        for t, df in a2b_raw.items():
            if not df.empty:
                bars_by_ticker[t] = _drop_suspension_rows(df)

    print(f"bars loaded: {len(bars_by_ticker)} tickers")
    return bars_by_ticker, calendar


def compute_dd252(bars_by_ticker, rebalance_dates):
    """dd_252_skip1m 계산"""
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 273:
            continue
        close = bars["close"]
        idx = close.index.astype(str)
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            val = dd.iloc[i]
            if pd.isna(val):
                continue
            rows.append({"ticker": ticker, "asOf": t, "dd_252_skip1m": float(val)})
    return pd.DataFrame(rows)


def load_gate_features(repo_root):
    """B_ATR 게이트용 유동성/변동성 피처 로드"""
    print("Loading liquidity/volatility features for B_ATR gate...")
    wanted = set(pd.read_parquet(
        os.path.join(repo_root, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet"),
        columns=['ticker'])['ticker'].unique())
    
    from liquidity_factor_study import load_full_ohlc, features_from_ohlc
    full, _ = load_full_ohlc(wanted)
    
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)
    feats["dv20"] = np.exp(feats["dv20_log"])
    feats["gate_liq"] = feats["dv20"] >= 1e8
    feats["gate_atr_excl"] = feats["atr14_decile"] != 10
    
    return feats[["ticker", "date", "gate_liq", "gate_atr_excl"]].rename(columns={"date": "asOf"})


def apply_gate_B_ATR(panel, rebalance_dates, gate_feats):
    """B_ATR 게이트 적용: dv20 >= 1e8 AND atr14_pct != 10"""
    print("Applying B_ATR gate...")
    feats_gate = gate_feats[["ticker", "asOf", "gate_liq", "gate_atr_excl"]]
    eligible = panel.dropna(subset=["dd_252_skip1m"]).merge(
        feats_gate, on=["ticker", "asOf"], how="left"
    )
    eligible = eligible[eligible["gate_liq"].fillna(False) & eligible["gate_atr_excl"].fillna(False)]
    print(f"[B_ATR] after gate: {len(eligible)} rows")
    return eligible


def build_selection_json(eligible, rebalance_dates, arm_name, this_dir, arm):
    """eligible DataFrame에서 selection.json 생성"""
    hold_sessions_by_date = {t: 120 for t in rebalance_dates}
    
    selection = {}
    monthly_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        top = g.sort_values("dd_252_skip1m", ascending=False).head(30)
        monthly_counts[asOf] = len(top)
        for ticker in top["ticker"]:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": 120})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(THIS_DIR, f"selection_{arm}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_gate.py",
            "arm": arm,
            "sourcePanel": "computed in-process from A2a/A2b bars (dd_252_skip1m) - MERGED universe",
            "period": f"2016-01-01 ~ {END}",
            "holdSessions": 120,
            "topN": 30,
            "minHistorySessions": 273,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"[{arm}] saved: selection_{arm}.json ({len(selection)} tickers, {len(monthly_counts)} months)")


def run_build(arm, repo_root, this_dir):
    """메인 빌드 로직"""
    START = "2016-01-01"
    END = "2026-08-03"
    TOP_N = 30
    HOLD_SESSIONS = 120
    MIN_HISTORY = 273

    # 1. Load universe and price data
    bars_by_ticker, calendar = load_universe_and_price(REPO_ROOT)

    # 2. Rebalance dates
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    # 3. Compute dd_252_skip1m
    print("Computing dd_252_skip1m...")
    panel = compute_dd252(load_universe_and_price(REPO_ROOT)[0], rebalance_dates)
    print(f"panel rows={len(panel)}")

    # 3. Apply gate
    if arm == "B_ATR":
        gate_feats = load_gate_features(REPO_ROOT)
        eligible = apply_gate_B_ATR(panel, rebalance_dates, gate_feats)
    else:
        eligible = panel.dropna(subset=["dd_252_skip1m"])

    print(f"[{arm}] eligible rows={len(eligible)}")

    # 3. Build selection.json
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    build_selection_json(eligible, rebalance_dates, arm, THIS_DIR, arm)


def run_build(arm, repo_root, this_dir):
    START = "2016-01-01"
    END = "2026-08-03"
    TOP_N = 30
    HOLD_SESSIONS = 120
    MIN_HISTORY = 273

    # 1. Load universe and price data
    bars_by_ticker, calendar = load_universe_and_price(repo_root)

    # 2. Rebalance dates
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

    # 3. Compute dd_252_skip1m
    print("Computing dd_252_skip1m...")
    panel = compute_dd252(load_universe_and_price(repo_root)[0], rebalance_dates)
    print(f"panel rows={len(panel)}")

    # 3. Apply gate
    if arm == "B_ATR":
        gate_feats = load_gate_features(repo_root)
        eligible = apply_gate_B_ATR(panel, rebalance_dates, gate_feats)
    else:
        eligible = panel.dropna(subset=["dd_252_skip1m"])

    print(f"[{arm}] eligible rows={len(eligible)}")

    # 3. Build selection.json
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    build_selection_json(eligible, rebalance_dates, arm, this_dir, arm)


if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    
    arm = "A"
    if "--arm" in sys.argv:
        arm = sys.argv[sys.argv.index("--arm") + 1]
    
    if arm not in ("A", "B_ATR"):
        print("Usage: --arm A|B_ATR")
        sys.exit(1)
    
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    this_dir = os.path.dirname(os.path.abspath(__file__))
    
    run_build(arm, repo_root, this_dir)


if __name__ == "__main__":
    import pandas as pd
    import numpy as np
    
    arm = "A"
    if "--arm" in sys.argv:
        arm = sys.argv[sys.argv.index("--arm") + 1]
    
    if arm not in ("A", "B_ATR"):
        print("Usage: --arm A|B_ATR")
        sys.exit(1)
    
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    this_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Global constants
    END = "2026-08-03"
    START = "2016-01-01"
    TOP_N = 30
    HOLD_SESSIONS = 120
    MIN_HISTORY = 273
    
    run_build(arm, repo_root, this_dir)