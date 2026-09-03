#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 45 — Donchian Position-Cap (K) Independent OOS Validation (Real Backtest)

Step 44에서 관측된 "종목 수 캡(K≈5)의 개선 효과"가 실제로 강건한지, 그리고
K=5가 Test에서 우연히 좋아진 것인지를 검증한다.

검증 설계:
  1. **K는 Test 결과로 선택하지 않는다** — 각 Bull config에서 Train 포트폴리오
     Sharpe를 기준으로 K*를 선택한 뒤, Valid·Test는 그 K*를 고정해 평가한다.
  2. Train(2023-05~2024-04) → Valid(2024-05~2024-12) → Test(2025-01~2026-08)
     OOS 순서를 엄격히 유지.
  3. 각 K ∈ {3,5,7,10,15,20,28}에 대해 CAGR/Sharpe/MDD/Calmar/PF/turnover/
     양수 CAGR 종목 비율/median CAGR·Sharpe 산출.
  4. 종목별 편중, ZEC 포함/제외, 심볼 LOO(28회) 수행.
  5. K=5 우연성 검증: Train 선택 K* vs Test 최적 K, K 스윕의 Test 안정성.
  6. Bull ON/OFF 비교. Bull 정의는 Step 43/44와 동일하게 BTC mom30>0 (2-state).
  7. Test 결과에 맞춘 파라미터 재선택 절대 금지.

포트폴리오 모델 (Step 44와 동일):
  - 동일가중 long book, 보유 종목 수 상한 = K.
  - 하루 롱 ≤ K개 → 모두 w=1/n. 롱 > K개 → standing mom30 최상위 K개에 w=1/K.
  - 총 노출 ≤ 100% (레버리지 없음).
  - 진입/보유/청산일 손익을 모두 반영(invested_during 마스크).

비용: 왕복 10bp + 편도 5bp 슬리피지 = 왕복 20bp (Step 42~44와 동일).
기존 파일 수정 없음. 신규 script + JSON + MD만 생성. 커밋·push 없음.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import price_structure_sweep_v2 as base  # 재사용 (읽기 전용)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "donchian-position-cap-oos-2026-08.json"
OUT_MD = HERE / "findings" / "donchian-position-cap-oos-2026-08.md"

SYMBOLS = base.SYMBOLS
WINDOWS = base.WINDOWS
ENTRY_COST = base.ENTRY_COST
EXIT_COST = base.EXIT_COST

N_HIGH = 20
N_LOW = 55
KS = [3, 5, 7, 10, 15, 20, 28]


def btc_2state(btc_mom30):
    """Step 43/44와 동일한 2-state Bull 정의: BTC mom30 > 0."""
    return pd.Series(np.where(btc_mom30.fillna(0) > 0, "bull", "bear"),
                     index=btc_mom30.index)


def donchian_long_signal(daily, n_high, n_low):
    """Donchian 20/55 롱/플랫 신호 {0,1} (이전봉 채널 돌파, look-ahead 없음)."""
    d = daily
    hi = d["high"].rolling(n_high).max().shift(1)
    lo = d["low"].rolling(n_low).min().shift(1)
    sig = pd.Series(0, index=d.index)
    sig[d["close"] > hi] = 1
    sig[d["close"] < lo] = -1
    return sig.replace({-1: 0}).ffill().fillna(0).astype(int)


def run_symbol(symbol, bull_on, btc_regime_series):
    """단일 심볼 백테스트. Returns dict or None.

    dict: daily_ret(전체 index 일별순수익, 비용 반영), position{0,1}, mom30,
          n_trades_per_window.
    """
    daily = base.load_daily(symbol)
    if daily is None:
        return None
    daily["btc_regime"] = pd.Series(btc_regime_series).reindex(daily.index).fillna("bull").values

    position = donchian_long_signal(daily, N_HIGH, N_LOW)
    if bull_on:
        position = position * (daily["btc_regime"] == "bull").astype(int)

    daily_ret, trades = base.backtest_window(daily, position, {})

    ntr = {}
    for wk, (s, e) in WINDOWS.items():
        ntr[wk] = int(sum(1 for t in trades if s <= t["entry_ts"] <= e))

    return {"daily_ret": daily_ret, "position": position,
            "mom30": daily["mom30"], "n_trades": ntr}


def invested_during(pos):
    """pos{0,1}에서 해당일 포지션 보유/진입/청산 여부 (exit-day 손익 누락 방지)."""
    return ((pos == 1) | (pos.shift(1) == 1)).fillna(False).astype(bool)


def portfolio_return(sym_res, K, ws, leaves=None):
    """동일가중 top-K 포트폴리오 일별 순수익 (윈도우만).

    반환: (port Series, n_days들 상세 딕셔너리 없음). leaves: 제외할 심볼 set.
    """
    syms = [s for s in sym_res if (leaves is None or s not in leaves)]
    dates = None
    for s in syms:
        sub = sym_res[s]["daily_ret"]
        slice_ = sub[(sub.index >= ws[0]) & (sub.index <= ws[1])]
        dates = slice_.index if dates is None else dates.union(slice_.index)
    if dates is None or len(dates) == 0:
        return None
    dates = dates.sort_values()
    n = len(dates)
    m = len(syms)
    R = np.zeros((n, m))
    I = np.zeros((n, m), dtype=bool)
    M = np.full((n, m), -np.inf)
    for j, s in enumerate(syms):
        r = sym_res[s]
        R[:, j] = r["daily_ret"].reindex(dates).fillna(0.0).values
        I[:, j] = invested_during(r["position"]).reindex(dates).fillna(False).astype(bool).values
        mom = r["mom30"].reindex(dates)
        M[: len(mom), j] = mom.fillna(-np.inf).values

    port = np.zeros(n)
    for i in range(n):
        rows = np.nonzero(I[i])[0]
        nc = len(rows)
        if nc == 0:
            continue
        if nc <= K:
            w = 1.0 / nc
            port[i] = R[i, rows].sum() * w
        else:
            keep = rows[np.argpartition(-M[i, rows], K - 1)[:K]]
            fitness = -M[i, keep]
            keep = keep[np.argsort(fitness)]
            port[i] = R[i, keep].sum() * (1.0 / K)
    return pd.Series(port, index=dates)


def portfolio_metrics(port, ws):
    if port is None or len(port) == 0 or port.abs().sum() == 0:
        return None
    year_frac = (ws[1] - ws[0]).days / 365.25
    cagr = ((1 + port).prod()) ** (1 / year_frac) - 1 if year_frac > 0 else 0.0
    ann_vol = np.std(port.values) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    curve = (1 + port).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    calmar = cagr / abs(dd) if dd != 0 else (np.inf if cagr > 0 else 0.0)
    pos = port[port > 0].sum()
    neg = -port[port < 0].sum()
    pf = (pos / neg) if neg > 0 else (np.inf if pos > 0 else 0.0)
    return {
        "cagr": round(float(cagr), 6),
        "sharpe": round(float(sharpe), 4),
        "max_dd": round(float(dd), 6),
        "calmar": round(float(calmar), 3),
        "pf": round(float(pf), 3),
        "n_obs": int(len(port)),
        "n_invested_days": int((port != 0).sum()),
    }


def symbol_standalone(sym_res, wk):
    """윈도우별 심볼 스탠드얼론 지표 (CAGR/Sharpe/MDD/Calmar/turnover/PF)."""
    out = {}
    s, e = WINDOWS[wk]
    for sym, r in sym_res.items():
        dr = r["daily_ret"].loc[(r["daily_ret"].index >= s) & (r["daily_ret"].index <= e)]
        if dr.abs().sum() == 0 or len(dr) == 0:
            continue
        m = base.metrics_from_daily(r["daily_ret"], s, e, r["n_trades"][wk])
        tr = [t["ret"] for t in []]
        out[sym] = {
            "cagr": m["cagr"], "sharpe": m["sharpe"], "max_dd": m["max_dd"],
            "calmar": m["calmar"], "turnover": m["turnover"],
            "n_trades": m["n_trades"],
        }
    return out


def agg(values):
    v = [x for x in values if x is not None and np.isfinite(float(x))]
    if not v:
        return {"mean": None, "median": None, "min": None, "max": None}
    return {"mean": round(float(np.mean(v)), 4), "median": round(float(np.median(v)), 4),
            "min": round(float(np.min(v)), 4), "max": round(float(np.max(v)), 4)}


def main():
    t0 = time.time()
    print(f"[{0.0:.1f}s] Step 45 — Donchian Position-Cap (K) Independent OOS Validation")
    print(f"Donchian {N_HIGH}/{N_LOW}. Costs 20bp rt. Bull = BTC mom30>0 (2-state, Step 43/44 동일).")
    print(f"OOS: Train {WINDOWS['train'][0].date()}~{WINDOWS['train'][1].date()} / "
          f"Valid {WINDOWS['valid'][0].date()}~{WINDOWS['valid'][1].date()} / "
          f"Test {WINDOWS['test'][0].date()}~{WINDOWS['test'][1].date()}")
    print(f"K grid: {KS}")

    btc = base.load_daily("BTCUSDT")
    btc_regime = btc_2state(btc["mom30"])

    configs = [{"name": "bull_OFF", "bull_on": False}, {"name": "bull_ON", "bull_on": True}]

    payload = {
        "design": {
            "purpose": "Donchian Position-Cap (K) Independent OOS Validation (Step 45)",
            "strategy": f"Donchian {N_HIGH}/{N_LOW}",
            "bull": "BTC mom30>0 (2-state, Step 43/44와 동일)",
            "K_grid": KS,
            "oos_split": {k: [str(v[0].date()), str(v[1].date())] for k, v in WINDOWS.items()},
            "costs": "10bp round-trip + 5bp slippage/side (=20bp)",
            "selection_rule": "K* 선택은 Train 포트폴리오 Sharpe로만; Valid/Test는 고정 K* 평가. Test 재선택 없음.",
            "portfolio": "equal-weight top-K by standing mom30, total exposure<=100%, no leverage",
        },
        "results": {},
        "runtime_sec": None,
    }

    for cfg in configs:
        print(f"\n=== {cfg['name']} ===")
        sym_res = {}
        for sym in SYMBOLS:
            r = run_symbol(sym, cfg["bull_on"], btc_regime)
            if r is not None:
                sym_res[sym] = r
        n_sym = len(sym_res)

        # 심볼 스탠드얼론 (K와 무관한 신호 수준 분포)
        standalone = {wk: symbol_standalone(sym_res, wk) for wk in ["train", "valid", "test"]}

        per_symbol_trade = {}
        for wk, smap in standalone.items():
            per_symbol_trade[wk] = {s: m["n_trades"] for s, m in smap.items()}

        # K 포트폴리오 — Train/Valid/Test 전체 K
        rows = {}
        for K in KS:
            per = {}
            for wk in ["train", "valid", "test"]:
                port = portfolio_return(sym_res, K, WINDOWS[wk])
                pm = portfolio_metrics(port, WINDOWS[wk])
                per[wk] = pm
            rows[K] = per

        # Train 기준 K* 선택 (포트폴리오 Sharpe)
        train_sh = {K: rows[K]["train"]["sharpe"] for K in KS}
        best_K = max(train_sh, key=lambda k: train_sh[k])
        print(f"  Train Sharpe per K: {train_sh}")
        print(f"  -> K* (Train 선택) = {best_K}")

        # 종목별 분포 지표 (윈도우별)
        dist = {}
        for wk in ["train", "valid", "test"]:
            smap = standalone[wk]
            cagrs = [m["cagr"] for m in smap.values()]
            sharps = [m["sharpe"] for m in smap.values()]
            if cagrs:
                dist[wk] = {
                    "n_symbols": len(smap),
                    "mean_cagr": agg(cagrs)["mean"], "median_cagr": agg(cagrs)["median"],
                    "mean_sharpe": agg(sharps)["mean"], "median_sharpe": agg(sharps)["median"],
                    "n_positive_cagr": int(sum(1 for c in cagrs if c > 0)),
                    "n_positive_sharpe": int(sum(1 for s in sharps if s > 0)),
                }

        # ZEC 포함/제외
        zec_in = rows
        zec_out = {}
        for K in KS:
            per = {}
            for wk in ["train", "valid", "test"]:
                port = portfolio_return(sym_res, K, WINDOWS[wk], leaves={"ZECUSDT"})
                per[wk] = portfolio_metrics(port, WINDOWS[wk])
            zec_out[K] = per

        # LOO — Test per K
        loo = {}
        max_symbols = n_sym
        carry_idx = None
        for K in KS:
            leaves_sh = {}
            for leave in SYMBOLS:
                port = portfolio_return(sym_res, K, WINDOWS["test"], leaves={leave})
                pm = portfolio_metrics(port, WINDOWS["test"])
                leaves_sh[leave] = pm["sharpe"] if pm else None
            sh_vals = [v for v in leaves_sh.values() if v is not None]
            base_test_sh = rows[K]["test"]["sharpe"]
            loo[K] = {
                "base_sharpe": base_test_sh,
                "min_sharpe": float(np.min(sh_vals)) if sh_vals else None,
                "max_sharpe": float(np.max(sh_vals)) if sh_vals else None,
                "span": round(float(np.max(sh_vals) - np.min(sh_vals)), 4) if sh_vals else None,
                "worst_leave": min(leaves_sh, key=lambda s: leaves_sh[s] if leaves_sh[s] is not None else np.inf),
            }

        print("  Test LOO span per K:", {K: (d["span"], d["worst_leave"]) for K, d in loo.items()})

        payload["results"][cfg["name"]] = {
            "n_symbols": n_sym,
            "k_by_window": {str(K): rows[K] for K in KS},
            "k_selected_on_train": best_K,
            "train_sharpe_by_k": {str(K): train_sh[K] for K in KS},
            "portfolio_without_zec": {str(K): zec_out[K] for K in KS},
            "loo_test": loo,
            "symbol_distribution": dist,
            "symbol_n_trades_test": per_symbol_trade["test"],
        }

    payload["runtime_sec"] = round(time.time() - t0, 1)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    print(f"\n=== Summary (runtime {payload['runtime_sec']}s) ===")
    for cfg in configs:
        r = payload["results"][cfg["name"]]
        print(f"\n[{cfg['name']}] n_sym={r['n_symbols']} K*={r['k_selected_on_train']}")
        for K in KS:
            t = r["k_by_window"][str(K)]["test"]
            if t:
                print(f"  K={K:2d} Test: CAGR={t['cagr']:>7.2%} Sh={t['sharpe']:+.3f} "
                      f"MDD={t['max_dd']:>7.2%} Calmar={t['calmar']:>6.2f} PF={t['pf']:>5.2f} "
                      f"| valid: {r['k_by_window'][str(K)]['valid']['sharpe']:+.3f}")
        print(f"  symbol dist (test): medC={r['symbol_distribution']['test']['median_cagr']:.2%} "
              f"posC={r['symbol_distribution']['test']['n_positive_cagr']}/{r['n_symbols']} "
              f"medSh={r['symbol_distribution']['test']['median_sharpe']:.3f}")

    print(f"\nJSON: {OUT_JSON}")


if __name__ == "__main__":
    main()