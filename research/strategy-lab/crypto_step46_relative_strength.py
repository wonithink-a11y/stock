#!/usr/bin/env python
"""Step 46 — Cross-Sectional Relative Strength (코인 간 상대강도).

이전까지의 질문("이 지표가 미래 수익률을 예측하는가")을 바꿔서 "같은 시점에
어떤 코인이 다른 코인보다 강한가"를 본다. 지금까지 이 라인이 반복해서 걸린
함정(ZEC/WLD 같은 소수 종목 편중, mean과 median의 괴리, Train에서 고른 최선이
Valid에서 무너짐)을 처음부터 배제하는 순서로 설계한다:

  상대강도 Rank → 동일가중 포트폴리오 → 종목별 분포(median 우선) → LOO →
  BTC regime → OOS(Train/Valid/Test) → 비용

데이터·유니버스·period 경계는 이 라인의 기존 스크립트와 완전히 동일하게
재사용한다(funding_premium_info_check.load_joint, ALL=28종목,
donchian_position_cap_oos_v2.py의 Train 2023-05~2024-04/Valid 2024-05~
2024-12/Test 2025-01~2026-08 구간) - 새 방법론을 안 만들고 기존 것과
비교 가능하게 유지한다.

신호: mom7(7일 모멘텀)의 그 날 횡단면 percentile rank. 포트폴리오: 매일
상위 K개 동일가중, 1일 보유(r_1) - overlapping window 문제(오늘 KR
treasury 검증에서 걸린 것과 같은 함정)를 피하려 일부러 겹치지 않는 1일
보유를 기본으로 쓴다. r_3/r_7은 참고용으로만 보고(겹침 명시).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_premium_info_check import load_joint, ALL  # noqa: E402

OUT_JSON = HERE / "findings" / "crypto-step46-relative-strength-2026-09.json"
OUT_MD = HERE / "findings" / "crypto-step46-relative-strength-2026-09.md"

TRAIN_END = "2024-04-30"
VALID_END = "2024-12-31"
K_LIST = [5, 7]
COST_BPS_LIST = [10, 30, 50]  # 매일 리밸런스=사실상 100% 회전 가정, 왕복비용


def period_of(d):
    s = str(d)[:10]
    if s <= TRAIN_END:
        return "TRAIN"
    if s <= VALID_END:
        return "VALID"
    return "TEST"


def cagr_of(daily_rets):
    if len(daily_rets) < 2:
        return None
    r = np.asarray(daily_rets, dtype=float)
    span_years = len(r) / 365.0
    eq = float(np.prod(1 + r))
    return eq ** (1 / max(span_years, 1e-9)) - 1 if eq > 0 else None


def sharpe_of(daily_rets):
    r = np.asarray(daily_rets, dtype=float)
    if len(r) < 5 or r.std(ddof=1) == 0:
        return None
    return float(r.mean() / r.std(ddof=1) * np.sqrt(365))


def mdd_of(daily_rets):
    r = np.asarray(daily_rets, dtype=float)
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    return float(dd.min()) if len(dd) else None


def main():
    print("Loading 28-symbol panel...", flush=True)
    frames = []
    for b in ALL:
        fr = load_joint(b).reset_index().rename(columns={"index": "date"})
        fr["mom7"] = fr["close"] / fr["close"].shift(7) - 1.0
        fr = fr[["date", "symbol", "close", "mom7", "mom30", "r_1", "r_3", "r_7"]]
        frames.append(fr)
    full = pd.concat(frames, ignore_index=True)
    full["date"] = pd.to_datetime(full["date"]).dt.strftime("%Y-%m-%d")
    full["period"] = full["date"].map(period_of)

    # BTC regime (시장 전체 레짐 - BTC 자신의 mom30, 매 날짜에 전 종목 공통 적용)
    btc_regime = full[full["symbol"] == "BTC"].set_index("date")["mom30"]
    full["btc_regime"] = full["date"].map(lambda d: "bull" if (btc_regime.get(d, np.nan) or 0) > 0 else "bear")

    # 상대강도 rank: 그 날 mom7의 횡단면 percentile (자기 자신 포함 28종목 중)
    full["rs_pct"] = full.groupby("date")["mom7"].rank(pct=True)
    valid_mask = full["mom7"].notna() & full["r_1"].notna()

    print(f"  {full['date'].nunique()} dates, {full['symbol'].nunique()} symbols, "
          f"{valid_mask.sum()} valid rows", flush=True)

    results = {"design": {
        "signal": "mom7 cross-sectional percentile rank (rs_pct)",
        "portfolio": "top-K equal-weight, 1-day hold (r_1), daily rebalance",
        "universe": ALL, "trainEnd": TRAIN_END, "validEnd": VALID_END,
    }, "byK": {}}

    for K in K_LIST:
        thresh = 1 - K / len(ALL)
        picks = full[valid_mask & (full["rs_pct"] > thresh)].copy()

        # ---- 1. 포트폴리오(동일가중) 일별 수익률 ----
        port_daily = picks.groupby("date")["r_1"].mean()
        port_df = pd.DataFrame({"ret": port_daily})
        port_df["period"] = port_df.index.map(period_of)

        period_stats = {}
        for p in ["TRAIN", "VALID", "TEST"]:
            sub = port_df[port_df["period"] == p]["ret"].tolist()
            period_stats[p] = {
                "n": len(sub), "cagr": round(cagr_of(sub), 4) if cagr_of(sub) is not None else None,
                "sharpe": round(sharpe_of(sub), 3) if sharpe_of(sub) is not None else None,
                "mdd": round(mdd_of(sub), 4) if sub else None,
            }

        # ---- 2. 종목별 분포(median 우선) ----
        per_symbol = picks.groupby("symbol")["r_1"].agg(["mean", "median", "count"])
        per_symbol_pickfreq = picks.groupby("symbol").size() / len(full["date"].unique())
        symbol_dist = {
            "meanOfSymbolMeans": round(float(per_symbol["mean"].mean()), 5),
            "medianOfSymbolMeans": round(float(per_symbol["mean"].median()), 5),
            "topContributor": per_symbol["mean"].idxmax(),
            "topContributorMean": round(float(per_symbol["mean"].max()), 5),
            "bottomContributor": per_symbol["mean"].idxmin(),
            "bottomContributorMean": round(float(per_symbol["mean"].min()), 5),
            "pickFrequencyRange": [round(float(per_symbol_pickfreq.min()), 3),
                                    round(float(per_symbol_pickfreq.max()), 3)],
        }

        # ---- 3. LOO(symbol leave-one-out) - TEST 구간 Sharpe로 확인 ----
        test_picks = picks[picks["period"] == "TEST"]
        loo_sharpes = {}
        for sym in ALL:
            sub_picks = test_picks[test_picks["symbol"] != sym]
            sub_daily = sub_picks.groupby("date")["r_1"].mean()
            sh = sharpe_of(sub_daily.tolist())
            if sh is not None:
                loo_sharpes[sym] = round(sh, 3)
        loo_vals = list(loo_sharpes.values())
        loo_summary = {
            "fullTestSharpe": period_stats["TEST"]["sharpe"],
            "looRange": [round(min(loo_vals), 3), round(max(loo_vals), 3)] if loo_vals else None,
            "looSpan": round(max(loo_vals) - min(loo_vals), 3) if loo_vals else None,
            "mostInfluentialExclusion": min(loo_sharpes, key=loo_sharpes.get) if loo_sharpes else None,
        }

        # ---- 4. BTC regime 분해 ----
        regime_by_date = full.drop_duplicates("date").set_index("date")["btc_regime"]
        port_df["regime"] = port_df.index.map(regime_by_date)
        regime_stats = {}
        for reg in ["bull", "bear"]:
            for p in ["TRAIN", "VALID", "TEST"]:
                sub = port_df[(port_df["period"] == p) & (port_df["regime"] == reg)]["ret"].tolist()
                regime_stats[f"{reg}_{p}"] = {
                    "n": len(sub), "sharpe": round(sharpe_of(sub), 3) if sharpe_of(sub) is not None else None,
                    "meanRet": round(float(np.mean(sub)), 5) if sub else None,
                }

        # ---- 5. 비용 민감도(일일 리밸런스=100% 회전 가정) ----
        cost_stats = {}
        for cost_bp in COST_BPS_LIST:
            net = port_df["ret"] - cost_bp / 10000.0
            net_by_period = {}
            for p in ["TRAIN", "VALID", "TEST"]:
                sub = net[port_df["period"] == p].tolist()
                net_by_period[p] = {"cagr": round(cagr_of(sub), 4) if cagr_of(sub) is not None else None,
                                     "sharpe": round(sharpe_of(sub), 3) if sharpe_of(sub) is not None else None}
            cost_stats[f"{cost_bp}bp"] = net_by_period

        results["byK"][f"K{K}"] = {
            "periodStats": period_stats, "symbolDistribution": symbol_dist,
            "loo": loo_summary, "regimeStats": regime_stats, "costSensitivity": cost_stats,
        }

        print(f"\n=== K={K} ===", flush=True)
        for p in ["TRAIN", "VALID", "TEST"]:
            s = period_stats[p]
            print(f"  {p}: n={s['n']} CAGR={s['cagr']} Sharpe={s['sharpe']} MDD={s['mdd']}", flush=True)
        print(f"  종목분포: mean-of-means={symbol_dist['meanOfSymbolMeans']} "
              f"median-of-means={symbol_dist['medianOfSymbolMeans']} "
              f"top={symbol_dist['topContributor']}({symbol_dist['topContributorMean']})", flush=True)
        print(f"  LOO: full={loo_summary['fullTestSharpe']} range={loo_summary['looRange']} "
              f"most_influential_exclusion={loo_summary['mostInfluentialExclusion']}", flush=True)
        print(f"  regime(TEST): bull={regime_stats.get('bull_TEST')} bear={regime_stats.get('bear_TEST')}", flush=True)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {OUT_JSON}", flush=True)


if __name__ == "__main__":
    main()
