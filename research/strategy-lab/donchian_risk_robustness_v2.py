#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 44 — Donchian Risk & Bear-Regime Robustness (Real Backtest)

Step 43의 Donchian 20/55 계열에 리스크관리와 레짐 필터를 추가해 실제 백테스트.

검증 차원:
  - 종목별 포지션 cap (포트폴리오 w = min(1/n_long, cap), cap ∈ {1.0, 0.20, 0.10, 0.05})
  - ATR 기반 손절 (atr_mult ∈ {0, 1.0, 3.0}) — 일일 종가 기준으로 채널 청산과의
    우선순위 관계를 검증 (예상: Do. 채널 청산이 먼저 → ATR 손절 중복/무영향)
  - BTC Bull/Bear/Neutral 3상태 레짐 (임계 ±5%), 시대 점유율 보고
  - Bull-only vs 전체 구간(레짐 게이트 없음)
  - 중앙값 CAGR/Sharpe vs 평균값 비교 (이것이 핵심 지표 — 평균은 소수 대형
    승자(ZEC류)에 왜곡되므로 중앙값으로 강건성 판정)
  - 종목별 · 연도별 성과, LOO(심볼)
  - 비용: 왕복 10bp + 편도 5bp 슬리피지(=20bp)
  - Train(2023-05~04)/Valid(2024-05~12)/Test(2025-01~2026-08) 고정

원칙:
  - 파라미터는 최소 범위(사전 고정 그리드)만 사용, Test 재튜닝 금지.
  - placeholder 금지. 실제 백테스트만.
  - 기존 파일 수정 금지. 신규 script + findings만 생성.
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
OUT_JSON = HERE / "findings" / "donchian-risk-robustness-2026-08.json"
OUT_MD = HERE / "findings" / "donchian-risk-robustness-2026-08.md"

SYMBOLS = base.SYMBOLS
WINDOWS = base.WINDOWS
ENTRY_COST = base.ENTRY_COST
EXIT_COST = base.EXIT_COST

N_HIGH = 20
N_LOW = 55
REGIME_THR = 0.05


def btc_3state(btc_mom30, thr=REGIME_THR):
    """3상태 레짐 시리즈: bull / neutral / bear."""
    s = pd.Series(np.where(btc_mom30 > thr, "bull",
                   np.where(btc_mom30 < -thr, "bear", "neutral")),
                  index=btc_mom30.index)
    return s


def donchian_long_signal(daily, n_high, n_low):
    """Donchian 20/55 롱/플랫 신호 {0,1} (이전봉 채널 돌파, look-ahead 없음)."""
    d = daily
    hi = d["high"].rolling(n_high).max().shift(1)
    lo = d["low"].rolling(n_low).min().shift(1)
    sig = pd.Series(0, index=d.index)
    sig[d["close"] > hi] = 1
    sig[d["close"] < lo] = -1
    return sig.replace({-1: 0}).ffill().fillna(0).astype(int)


def run_symbol(symbol, atr_mult, regime_gate, btc_regime_series, ws):
    """단일 심볼 백테스트. Returns dict or None.
    dict: daily_ret(전체 index 순일별 수익), position{0,1}, mom30, n_trades(윈도우).
    """
    daily = base.load_daily(symbol)
    if daily is None:
        return None
    start, end = ws
    daily["btc_regime"] = pd.Series(btc_regime_series).reindex(daily.index).fillna("neutral").values

    position = donchian_long_signal(daily, N_HIGH, N_LOW)
    if regime_gate in ("bull_only", "bull_only_2state"):
        position = position * (daily["btc_regime"] == "bull").astype(int)
    elif regime_gate == "bear_only":
        position = position * (daily["btc_regime"] == "bear").astype(int)

    params = {"atr_mult": atr_mult} if atr_mult else {}
    daily_ret, trades = base.backtest_window(daily, position, params)
    win_trades = [t for t in trades if start <= t["entry_ts"] <= end]

    tm = base.metrics_from_trade_rets([t["ret"] for t in win_trades], start, end)
    return {
        "daily_ret": daily_ret,
        "position": position,
        "mom30": daily["mom30"],
        "n_trades": int(len(win_trades)),
        "trade_wr": tm.get("win_rate") if tm else None,
        "trade_pf": tm.get("profit_factor") if tm else None,
    }


def agg_stats(values):
    values = [v for v in values if v is not None and np.isfinite(v)]
    if not values:
        return None
    return {
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def symbol_standalone(sym_res, ws):
    """심볼별 스탠드얼론 지표 dict (윈도우 슬라이스 기준)."""
    out = {}
    for sym, r in sym_res.items():
        m = base.metrics_from_daily(r["daily_ret"], ws[0], ws[1], r["n_trades"])
        if m is None:
            continue
        m["trade_wr"] = r["trade_wr"]
        m["trade_pf"] = r["trade_pf"]
        out[sym] = m
    return out


def invested_during(pos):
    """pos{0,1} 시리즈에서 해당일에 포지션을 보유/진입/청산한 일을 표시.

    daily_ret는 진입일(진입비용만), 보유일(일별 수익), 청산일(청산일 수익+비용)을
    전부 담고 있으므로, 포트폴리오는 청산일도 포함해야 실제 손익이 사라지지 않는다.
    """
    return ((pos == 1) | (pos.shift(1) == 1)).fillna(False).astype(bool)


def portfolio_return(sym_res, cap, ws):
    """동일가중 cap 포트폴리오 일별 순수익 (윈도우만).

    포지션 cap: 종목당 최대 비중 = 1/K (K = max(1, round(1/cap)) 종목 상한).
    - 하루에 롱이 K개 이하면 모두 w=1/n (총 100%).
    - 롱이 K개를 넘으면 모멘텀(standing mom30) 최상위 K개만 w=1/K로 보유.
    - 어떤 경우든 총 노출 <= 100% (레버리지 없음).
    청산일(exit-day) 손익이 빠지지 않도록 invested_during 마스크 사용.
    """
    K = None if cap >= 1.0 else max(1, int(round(1 / cap)))

    # 사전 계산: 심볼별 invested 마스크와 daily_ret, mom30 (윈도우 정렬)
    rows = []
    for sym, r in sym_res.items():
        sub = r["daily_ret"].loc[(r["daily_ret"].index >= ws[0]) &
                                 (r["daily_ret"].index <= ws[1])]
        if len(sub) == 0:
            continue
        inv = invested_during(r["position"]).reindex(sub.index).fillna(False).astype(bool)
        rows.append((sym, sub, inv,
                     r["mom30"].reindex(sub.index).fillna(-np.inf).values))
    if not rows:
        return None

    idx = rows[0][1].index
    port = pd.Series(0.0, index=idx)
    for ts in idx:
        invested = [(sym, sub, mom_i) for sym, sub, inv, mom_i in rows
                    if inv.loc[ts]]
        n = len(invested)
        if n == 0:
            continue
        if K is None or n <= K:
            w = 1.0 / n
            members = invested
        else:
            w = 1.0 / K
            top = sorted(invested, key=lambda pr: pr[2][idx.get_loc(ts)], reverse=True)[:K]
            members = top
        port.loc[ts] = sum(w * sub.loc[ts] for _, sub, _ in members)
    return port


def portfolio_metrics(port, ws):
    idx = port[(port.index >= ws[0]) & (port.index <= ws[1])]
    if len(idx) == 0 or idx.abs().sum() == 0:
        return None
    year_frac = (ws[1] - ws[0]).days / 365.25
    cagr = ((1 + idx).prod()) ** (1 / year_frac) - 1 if year_frac > 0 else 0.0
    ann_vol = np.std(idx.values) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    curve = (1 + idx).cumprod()
    peak = curve.cummax()
    dd = (curve / peak - 1).min()
    calmar = cagr / abs(dd) if dd != 0 else (np.inf if cagr > 0 else 0.0)
    yearly = {int(y): float(((1 + grp).prod() - 1))
              for y, grp in idx.groupby(idx.index.year)}
    return {
        "cagr": float(cagr), "sharpe": float(sharpe), "max_dd": float(dd),
        "calmar": float(calmar), "yearly": yearly,
        "n_obs": int(len(idx)),
        "n_invested_days": int((idx != 0).sum()),
    }


def main():
    t0 = time.time()
    print(f"[{0.0:.1f}s] Step 44 — Donchian Risk & Bear-Regime Robustness")
    print(f"OOS: Train {WINDOWS['train'][0].date()}~{WINDOWS['train'][1].date()} / "
          f"Valid {WINDOWS['valid'][0].date()}~{WINDOWS['valid'][1].date()} / "
          f"Test {WINDOWS['test'][0].date()}~{WINDOWS['test'][1].date()}")
    print(f"Cost: 10bp rt + 5bp slip/side (=20bp). Donchian {N_HIGH}/{N_LOW}. Regime thr ±5%.")

    btc_setup = base.load_daily("BTCUSDT")
    btc_mom30 = btc_setup["mom30"]
    btc_regime_series = btc_3state(btc_mom30)
    # 2-state (mom30>0, Step 43 정의) 민감도 검증용
    btc_regime_2state = btc_3state(btc_mom30, thr=0.0)

    # 레짐 시대 점유율 (Train/Valid/Test)
    regime_shares = {}
    for wk in ["train", "valid", "test"]:
        wslice = btc_regime_series[(btc_regime_series.index >= WINDOWS[wk][0]) &
                                   (btc_regime_series.index <= WINDOWS[wk][1])]
        regime_shares[wk] = {k: int((wslice == k).sum()) for k in ["bull", "neutral", "bear"]}
        print(f"  {wk} regime days: {regime_shares[wk]}")

    atr_grid = [0, 1.0, 3.0]
    regime_grid = ["all", "bull_only", "bull_only_2state"]
    cap_grid = [1.0, 0.20, 0.10, 0.05]

    configs = []
    for atr in atr_grid:
        for regime in regime_grid:
            if regime == "bull_only_2state" and atr != 0:
                continue  # 2-state 민감도는 ATR0 조건에서만 (서로 직교 검증)
            configs.append({"name": f"ATR{atr:g}_regime={regime}", "atr": atr, "regime": regime})

    # 레짐 시리즈 매핑 (bull_only_2state -> 2-state 정의)
    regime_series_map = {
        "all": btc_regime_series,
        "bull_only": btc_regime_series,
        "bull_only_2state": btc_regime_2state,
    }

    results = {}
    for cfg in configs:
        sym_res = {}
        for sym in SYMBOLS:
            r = run_symbol(sym, cfg["atr"], cfg["regime"], regime_series_map[cfg["regime"]],
                           WINDOWS["test"])
            if r is not None:
                sym_res[sym] = r

        pm = symbol_standalone(sym_res, WINDOWS["test"])
        covers = list(pm.values())
        if not covers:
            print(f"  {cfg['name']}: no data")
            continue

        s_cagr = agg_stats([m["cagr"] for m in covers])
        s_sharpe = agg_stats([m["sharpe"] for m in covers])
        s_mdd = agg_stats([m["max_dd"] for m in covers])
        s_calmar = agg_stats([m["calmar"] for m in covers if np.isfinite(m["calmar"])])

        loo_vals = {}
        for leave in SYMBOLS:
            v = [m["sharpe"] for s, m in pm.items() if s != leave]
            loo_vals[leave] = float(np.mean(v)) if v else None
        loo_list = [x for x in loo_vals.values() if x is not None]

        yearly = {}
        for y in sorted({yy for m in covers for yy in m.get("yearly", {})}):
            yearly[y] = float(np.mean([m["yearly"][y] for m in covers
                                       if y in m.get("yearly", {})]))

        entry = {
            "n_symbols": len(pm),
            "mean_cagr": s_cagr["mean"], "median_cagr": s_cagr["median"],
            "mean_sharpe": s_sharpe["mean"], "median_sharpe": s_sharpe["median"],
            "mean_mdd": s_mdd["mean"], "mean_calmar": s_calmar["mean"],
            "mean_pf": agg_stats([m["trade_pf"] for m in covers])["mean"],
            "mean_wr": agg_stats([m["trade_wr"] for m in covers])["mean"],
            "mean_turnover": agg_stats([m["turnover"] for m in covers])["mean"],
            "n_positive_cagr": sum(1 for m in covers if m["cagr"] > 0),
            "n_positive_sharpe": sum(1 for m in covers if m["sharpe"] > 0),
            "yearly": yearly,
            "loo_mean_sharpe": float(np.mean(loo_list)),
            "loo_min_sharpe": float(np.min(loo_list)),
            "loo_max_sharpe": float(np.max(loo_list)),
            "loo_span_sharpe": float(np.max(loo_list) - np.min(loo_list)),
        }

        # 포트폴리오 cap
        entry["portfolio"] = {}
        for cap in cap_grid:
            port = portfolio_return(sym_res, cap, WINDOWS["test"])
            pmt = portfolio_metrics(port, WINDOWS["test"]) if port is not None else None
            entry["portfolio"][f"cap{cap:g}"] = pmt

        entry["per_symbol"] = pm
        results[cfg["name"]] = entry

        print(f"  {cfg['name']}: n={entry['n_symbols']} "
              f"meanC={entry['mean_cagr']:.2%} medC={entry['median_cagr']:.2%} "
              f"meanSh={entry['mean_sharpe']:.3f} medSh={entry['median_sharpe']:.3f} "
              f"meanDD={entry['mean_mdd']:.2%} posC={entry['n_positive_cagr']}/{entry['n_symbols']}")
        for cap, pmt in entry["portfolio"].items():
            if pmt:
                print(f"    [portfolio {cap}] CAGR={pmt['cagr']:.2%} sh={pmt['sharpe']:.3f} "
                      f"DD={pmt['max_dd']:.2%} Calmar={pmt['calmar']:.2f} "
                      f"inv_days={pmt['n_invested_days']}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "design": {
            "purpose": "Donchian Risk & Bear-Regime Robustness (Step 44)",
            "strategy": f"Donchian {N_HIGH}/{N_LOW}",
            "oos_split": {k: [str(v[0].date()), str(v[1].date())] for k, v in WINDOWS.items()},
            "costs": "10bp round-trip + 5bp slippage/side (=20bp)",
            "regime": f"BTC 3-state (bull/neutral/bear) thr ±{REGIME_THR}; bull_only_2state=mom30>0 (Step 43 정의 민감도)",
            "regime_shares": regime_shares,
            "atr_stops": atr_grid,
            "regime_gates": regime_grid,
            "position_caps": cap_grid,
            "param_note": "minimal pre-specified grid; no Test re-tuning",
            "portfolio_note": "equal-weight book, top-K by standing mom30 = K=max(1,round(1/cap)), total exposure<=100%, no leverage; exit-day PnL included (invested_during mask)",
        },
        "results": results,
        "runtime_sec": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    print(f"\n=== Summary ===")
    print(f"Total runtime: {time.time() - t0:.1f}s")
    print(f"JSON: {OUT_JSON}")

    print("\n=== Test: config -> median Sharpe | mean Sharpe | portfolio cap effect ===")
    for name, res in sorted(results.items(), key=lambda kv: kv[1]["median_sharpe"], reverse=True):
        caps = " | ".join(
            f"{k}:CAGR={v['cagr']:.1%},sh={v['sharpe']:.2f}" for k, v in res["portfolio"].items()
            if v)
        print(f"  {name:24s} medSh={res['median_sharpe']:.3f} meanSh={res['mean_sharpe']:.3f} "
              f"medC={res['median_cagr']:.2%} | {caps}")


if __name__ == "__main__":
    main()