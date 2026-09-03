#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 43 — Donchian 20/55 Robustness OOS Validation (Real Backtest)

Step 42의 유일한 CONDITIONAL 후보였던 Donchian 20/55 (+ BTC Bull)를 검증한다.

검증 차원:
  - 채널 파라미터 그리드: (15,40) / (20,55) / (30,60) / (40,80)
  - BTC Bull 필터 ON/OFF
  - 동일 비용: 왕복 10bp + 편도 슬리피지 5bp (=왕복 20bp)
  - Train(2023-05~04)/Valid(2024-05~12)/Test(2025-01~2026-08) 완전 분리
  - 28종목 전체 평균 + 종목별
  - 연도별 성과 (Test)
  - Leave-One-Out (심볼 LOO): 종목 하나씩 제외한 Test 종목-평균 민감도
  - 거래 횟수 / turnover
  - CAGR, Sharpe, MDD, Calmar, PF

원칙:
  - Test 결과에 맞춰 파라미터를 재선택하지 않는다 (그리드는 사전 고정).
  - 채널 길이는 사전 지정 그리드이며, Test 성과로 튜닝하지 않는다.
  - placeholder 금지 — 실제 백테스트만 수행.
  - 기존 파일 수정 없이 신규 script + findings만 생성한다.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import price_structure_sweep_v2 as base  # 재사용 (읽기 전용 모듈)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "donchian-robustness-2026-08.json"
OUT_MD = HERE / "findings" / "donchian-robustness-2026-08.md"

SYMBOLS = base.SYMBOLS
WINDOWS = base.WINDOWS
TRAIN_START, TRAIN_END = WINDOWS["train"]
VALID_START, VALID_END = WINDOWS["valid"]
TEST_START, TEST_END = WINDOWS["test"]
ENTRY_COST = base.ENTRY_COST
EXIT_COST = base.EXIT_COST

# 채널 파라미터 그리드 (사전 고정, Test 기준 선택 안 함)
CHANNELS = [15, 20, 30, 40]
OUTER_LOOKBACK = {15: 40, 20: 55, 30: 60, 40: 80}


def donchian_signal(daily, n_high, n_low, bull_only):
    """Parameterized Donchian breakout long/flat signal -> position {0,1}.

    채널 고/저는 이전봉 기준(shift(1))으로 돌파를 판정해 look-ahead 방지.
    n_high: 진입용 상단 채널 기간, n_low: 청산용 하단 채널 기간.
    """
    d = daily
    hi = d["high"].rolling(n_high).max().shift(1)
    lo = d["low"].rolling(n_low).min().shift(1)
    sig = pd.Series(0, index=d.index)
    sig[d["close"] > hi] = 1
    sig[d["close"] < lo] = -1
    position = sig.replace({-1: 0}).ffill().fillna(0).astype(int)
    if bull_only:
        position = position * (d["btc_regime"] == "bull").astype(int)
    return position


def run_donchian(symbol, n_high, n_low, bull_only, window_key, btc_regime_series):
    daily = base.load_daily(symbol)
    if daily is None:
        return None
    start, end = WINDOWS[window_key]
    reg = pd.Series(btc_regime_series)
    daily["btc_regime"] = reg.reindex(daily.index).fillna("bull").values

    position = donchian_signal(daily, n_high, n_low, bull_only)
    daily_ret, trades = base.backtest_window(daily, position, {"regime_filter": "bull_only" if bull_only else "all"})

    win_trades = [t for t in trades if start <= t["entry_ts"] <= end]
    if len(win_trades) < 5:
        return None

    dm = base.metrics_from_daily(daily_ret, start, end, len(win_trades))
    if dm is None:
        return None
    tm = base.metrics_from_trade_rets([t["ret"] for t in win_trades], start, end)
    if tm:
        dm["n_trades"] = int(len(win_trades))
        dm["trade_cagr"] = tm.get("cagr")
        dm["trade_sharpe"] = tm.get("sharpe")
        dm["trade_pf"] = tm.get("profit_factor")
        dm["trade_wr"] = tm.get("win_rate")
    return dm


def aggregate(per_sym, metric="cagr"):
    vals = [r[metric] for r in per_sym.values() if r is not None]
    return float(np.mean(vals)) if vals else None


def compute_config(cfg, btc_regime_series):
    """Bind a config to fixed params and evaluate across a given symbol set."""
    n_high, n_low, bull = cfg["n_high"], cfg["n_low"], cfg["bull"]
    out = {"train": {}, "valid": {}, "test": {}}
    for window_key in out:
        per_sym = {}
        for sym in SYMBOLS:
            r = run_donchian(sym, n_high, n_low, bull, window_key, btc_regime_series)
            if r:
                per_sym[sym] = r
        out[window_key]["per_symbol"] = per_sym
        agg = {}
        metrics_map = {
            "cagr": "cagr", "sharpe": "sharpe", "max_dd": "max_dd",
            "calmar": "calmar", "profit_factor": "trade_pf",
            "win_rate": "trade_wr", "turnover": "turnover", "n_trades": "n_trades",
        }
        for metric, key in metrics_map.items():
            agg[metric] = aggregate(per_sym, key)
        # yearly (test only)
        if window_key == "test":
            years = sorted({y for r in per_sym.values() for y in r.get("yearly", {})})
            agg["yearly"] = {y: float(np.mean([r["yearly"][y] for r in per_sym.values()
                                               if y in r.get("yearly", {})])) for y in years}
        out[window_key]["agg"] = agg
        out[window_key]["n_symbols"] = len(per_sym)
    return out


def loo_over_symbols(cfg, btc_regime_series):
    """Leave-One-Out (심볼): 각 종목 하나를 제외한 Test 종목-평균 Sharpe/CAGR."""
    n_high, n_low, bull = cfg["n_high"], cfg["n_low"], cfg["bull"]
    # baseline on all symbols
    base_res = compute_config(cfg, btc_regime_series)["test"]["agg"]
    loo = {}
    for leave in SYMBOLS:
        per_sym = {}
        for sym in SYMBOLS:
            if sym == leave:
                continue
            r = run_donchian(sym, n_high, n_low, bull, "test", btc_regime_series)
            if r:
                per_sym[sym] = r
        sharpe = aggregate(per_sym, "sharpe")
        cagr = aggregate(per_sym, "cagr")
        loo[leave] = {"sharpe": sharpe, "cagr": cagr,
                      "n_symbols": len(per_sym)}
    all_sh = [v["sharpe"] for v in loo.values() if v["sharpe"] is not None]
    all_cg = [v["cagr"] for v in loo.values() if v["cagr"] is not None]
    return {
        "baseline_sharpe": base_res["sharpe"],
        "baseline_cagr": base_res["cagr"],
        "loo_min_sharpe": float(min(all_sh)) if all_sh else None,
        "loo_max_sharpe": float(max(all_sh)) if all_sh else None,
        "loo_span_sharpe": float(max(all_sh) - min(all_sh)) if all_sh else None,
        "loo_min_cagr": float(min(all_cg)) if all_cg else None,
        "loo_max_cagr": float(max(all_cg)) if all_cg else None,
        "loo_span_cagr": float(max(all_cg) - min(all_cg)) if all_cg else None,
        "worst_leave": [s for s, v in loo.items() if v["sharpe"] == (min(all_sh) if all_sh else None)][:3],
        "per_leave": loo,
    }


def main():
    t0 = time.time()
    print(f"[{0.0:.1f}s] Step 43 — Donchian 20/55 Robustness OOS Validation")
    print(f"OOS: Train {TRAIN_START.date()}~{TRAIN_END.date()} / "
          f"Valid {VALID_START.date()}~{VALID_END.date()} / "
          f"Test {TEST_START.date()}~{TEST_END.date()}")
    print(f"Cost: {base.COST_BP}bp round-trip + {base.SLIP_BP}bp slippage/side "
          f"(=20bp round trip)")

    configs = []
    for in_n in CHANNELS:
        out_n = OUTER_LOOKBACK[in_n]
        for bull in [False, True]:
            configs.append({
                "name": f"D{in_n}_{out_n}" + ("_Bull" if bull else ""),
                "n_high": in_n,
                "n_low": out_n,
                "bull": bull,
            })
    # 총 8 config (4 채널 × Bull ON/OFF)

    btc_regime_series = base.build_btc_regime()

    summary = {}
    for cfg in configs:
        print(f"Testing {cfg['name']}...")
        res = compute_config(cfg, btc_regime_series)
        loo = loo_over_symbols(cfg, btc_regime_series)
        summary[cfg["name"]] = {"config": cfg, "windows": res, "loo": loo}
        a = res["test"]["agg"]
        print(f"  TEST: CAGR={a['cagr']:.2%} Sharpe={a['sharpe']:.3f} "
              f"MDD={a['max_dd']:.2%} Calmar={a['calmar']:.2f} PF={a['profit_factor']:.2f} "
              f"TO={a['turnover']:.3f} trades={a['n_trades']} n_sym={res['test']['n_symbols']}")

    # Train에서 1위를 선택(재튜닝 아님 — 그리드 고정)해 Valid/Test 안정성 확인
    train_rank = sorted(summary.items(),
                        key=lambda kv: (kv[1]["windows"]["train"]["agg"]["sharpe"] or -9),
                        reverse=True)
    print("\n=== Train-최고 성과 config (Valid/Test 안정성 확인용) ===")
    for name, _ in train_rank[:3]:
        v = summary[name]["windows"]
        print(f"  {name}: Train sh={v['train']['agg']['sharpe']:.3f} | "
              f"Valid sh={v['valid']['agg']['sharpe']:.3f} CAGR={v['valid']['agg']['cagr']:.2%} | "
              f"Test sh={v['test']['agg']['sharpe']:.3f} CAGR={v['test']['agg']['cagr']:.2%}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "design": {
            "purpose": "Donchian 20/55 Robustness OOS Validation (Step 43)",
            "oos_split": {
                "train": [str(TRAIN_START.date()), str(TRAIN_END.date())],
                "valid": [str(VALID_START.date()), str(VALID_END.date())],
                "test": [str(TEST_START.date()), str(TEST_END.date())],
            },
            "costs": f"{base.COST_BP}bp round-trip + {base.SLIP_BP}bp slippage/side",
            "channel_grid": {str(i): OUTER_LOOKBACK[i] for i in CHANNELS},
            "bull_filters": ["OFF", "ON"],
            "loo": "leave-one-symbol-out on Test metrics",
            "param_selection_note": "channel lengths are pre-specified grid; "
                                    "no re-selection based on Test",
        },
        "results": {name: {
            "window_agg": {w: summary[name]["windows"][w]["agg"]
                           for w in ["train", "valid", "test"]},
            "n_symbols": {w: summary[name]["windows"][w]["n_symbols"]
                          for w in ["train", "valid", "test"]},
            "loo": summary[name]["loo"],
        } for name in summary},
        "runtime_sec": round(time.time() - t0, 1),
    }
    # per-symbol detail (test) in a separate key to keep JSON reviewable
    detail = {name: {"test_per_symbol": summary[name]["windows"]["test"]["per_symbol"]}
              for name in summary}
    payload["per_symbol_test"] = detail
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    print(f"\n=== Summary ===")
    print(f"Total runtime: {time.time() - t0:.1f}s")
    print(f"JSON: {OUT_JSON}")

    print("\n=== Leaderboard (Test, by Sharpe) ===")
    for i, (name, s) in enumerate(
        sorted(summary.items(), key=lambda kv: kv[1]["windows"]["test"]["agg"]["sharpe"],
               reverse=True), 1
    ):
        a = s["windows"]["test"]["agg"]
        print(f"  {i}. {name}: Sharpe={a['sharpe']:.3f} CAGR={a['cagr']:.2%} "
              f"MDD={a['max_dd']:.2%} Calmar={a['calmar']:.2f} "
              f"LOOspan={s['loo']['loo_span_sharpe']:.3f}")


if __name__ == "__main__":
    main()
