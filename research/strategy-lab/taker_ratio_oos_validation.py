#!/usr/bin/env python
"""Step 27 — taker_ratio_7 실전형 OOS 검증 (Bull regime only).

Step 25/26 결과: taker_7d는 mom30>0 bull 구간에서 단독 강건.
이번 단계: 고정 규칙으로 walk-forward OOS 검증, 실전 거래비용 반영.

금지: 파라미터 최적화, 백테스트 엔진 수정, 기존 데이터 변경, 커밋.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
ACTIVITY = HERE / "data" / "crypto" / "activity"
OUT_JSON = HERE / "findings" / "taker-ratio-oos-2026-08.json"
OUT_MD = HERE / "findings" / "taker-ratio-oos-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, MINASSETS)

SYM28 = ALL
COSTS_BP = [10, 30, 50]  # 거래비용 basis points
QUANTILES = [0.1, 0.2, 0.3]  # 상위/하위 포트폴리오
HORNS = ["r_1", "r_3", "r_7", "r_14", "r_30"]


def build_taker_ratio(base, calendar):
    a = pd.read_parquet(ACTIVITY / f"{base}USDT_1h.parquet")
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "qvol": g["quote_asset_volume"].sum(),
        "tbq":  g["taker_buy_quote_asset_volume"].sum(),
    })
    day.index.name = "date"
    day["taker_raw"] = day["tbq"] / day["qvol"]
    day["taker_7d"] = day["taker_raw"].rolling(7, min_periods=3).mean()
    return day.reindex(calendar)[["taker_raw", "taker_7d"]]


def build_forward_returns(fr, max_h=30):
    """close 기반 forward return 계산 (Step 25/26 동일)."""
    for h in [1, 3, 7, 14, 30]:
        if f"r_{h}" not in fr.columns:
            fr[f"r_{h}"] = fr["close"].shift(-h) / fr["close"] - 1.0
    return fr


def load_bull_panel():
    frames = {}
    for b in SYM28:
        fr = load_joint(b)
        fr = build_forward_returns(fr)
        tr = build_taker_ratio(b, fr.index)
        fr = fr.join(tr, how="left")
        # mom30 regime (고정 룰: mom30 > 0)
        fr["reg_mom30"] = np.where(fr["mom30"] > 0, "bull", "bear")
        fr = fr[["close", "taker_7d", "mom30", "reg_mom30"] + [f"r_{h}" for h in [1,3,7,14,30]]].copy()
        fr["symbol"] = b
        frames[b] = fr
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    bull = full[full["reg_mom30"] == "bull"].copy()
    bull = bull.dropna(subset=["taker_7d", "r_1", "r_3", "r_7", "r_14", "r_30"]).copy()
    return bull


def apply_costs(returns, cost_bp, turnover):
    """거래비용 적용: net = gross - cost_bp * turnover / 10000"""
    return returns - cost_bp * turnover / 10000.0


def portfolio_metrics(daily_rets, cost_bp=0, turnover_pct=0.0):
    """일간 수익률 시계열에서 CAGR, Sharpe, MaxDD, 승률 계산."""
    rets = daily_rets.dropna()
    if len(rets) < 20:
        return {}
    net = rets - cost_bp * turnover_pct / 10000.0
    cum = (1 + net).cumprod()
    years = len(rets) / 365.25
    cagr = cum.iloc[-1] ** (1 / years) - 1 if years > 0 else 0
    ann_vol = net.std() * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0
    peak = cum.expanding().max()
    dd = (cum / peak - 1).min()
    win_rate = (net > 0).mean()
    return {
        "cagr": round(float(cagr), 6),
        "sharpe": round(float(sharpe), 4),
        "max_dd": round(float(dd), 6),
        "win_rate": round(float(win_rate), 4),
        "ann_vol": round(float(ann_vol), 6),
        "total_return": round(float(cum.iloc[-1] - 1), 6),
        "n_days": int(len(rets)),
    }


def main():
    bull = load_bull_panel()

    # 날짜별 cross-sectional rank 기반 포트폴리오 구성
    # 각 날짜 taker_7d rank → quantile portfolio
    out = {"design": {
        "universe": "28 symbols, mom30>0 bull only",
        "feature": "taker_7d (7d rolling mean of taker buy quote ratio)",
        "regime_rule": "mom30 > 0 (Step 25 고정, 재최적화 없음)",
        "costs_bp": COSTS_BP,
        "quantiles": QUANTILES,
        "horizons": HORNS,
        "rebal": "daily (next-day r_1 used for daily P&L)",
        "note": "walk-forward: 파라미터 고정, 매일 rank 갱신, r_1로 일간 P&L 누적",
    }}

    # 날짜별 rank 계산 (동일 기간 cross-section)
    bull = bull.copy()
    for d, sub in bull.groupby("date"):
        idx = sub.index
        if len(sub) >= MINASSETS:
            bull.loc[idx, "taker_rank"] = sub["taker_7d"].rank(pct=True)
    bull = bull.dropna(subset=["taker_rank"]).copy()

    # 핵심: 일간 P&L = r_1 (next-day return)
    # H>1 지평은 정보용으로만 보고, 포트폴리오 성과는 r_1 누적으로 평가
    results = {}
    for q in QUANTILES:
        q_low = q
        q_high = 1 - q
        key = f"Q{int(q*100)}"
        results[key] = {}

        # 일간 Long/Short r_1 수익률 시계열 구성
        daily_ls = []
        dates_sorted = sorted(bull["date"].unique())
        prev_long_symbols = set()
        prev_short_symbols = set()
        turnover = 0
        for d in dates_sorted:
            sub = bull[bull["date"] == d]
            if len(sub) < MINASSETS:
                continue
            # rank 기준 상위/하위 q 심볼
            long_syms = set(sub[sub["taker_rank"] >= q_high]["symbol"].values)
            short_syms = set(sub[sub["taker_rank"] <= q_low]["symbol"].values)
            # 오늘의 r_1 수익률 (long/short 각각의 r_1 평균)
            long_ret = sub[sub["symbol"].isin(long_syms)]["r_1"].mean()
            short_ret = sub[sub["symbol"].isin(short_syms)]["r_1"].mean()
            if np.isfinite(long_ret) and np.isfinite(short_ret):
                daily_ls.append(long_ret - short_ret)
            # turnover 근사: 심볼 교체율 (첫 날 제외)
            if prev_long_symbols and prev_short_symbols and len(long_syms) > 0 and len(short_syms) > 0:
                turnover += len(long_syms.symmetric_difference(prev_long_symbols)) / len(long_syms)
                turnover += len(short_syms.symmetric_difference(prev_short_symbols)) / len(short_syms)
            prev_long_symbols = long_syms
            prev_short_symbols = short_syms

        if len(daily_ls) < 20:
            continue
        daily_ls = np.array(daily_ls)
        avg_turnover = turnover / max(len(daily_ls), 1) if len(daily_ls) > 0 else 0

        # 비용별 net 성과
        for cost in COSTS_BP:
            net = daily_ls - cost * avg_turnover / 10000.0
            res = portfolio_metrics(pd.Series(net), cost, avg_turnover)
            if res:
                results[key][cost] = res

    # EW benchmark: bull 기간 전체 종목 r_1 평균
    ew_daily = bull.groupby("date")["r_1"].mean().dropna()
    out["ew_benchmark"] = {"r_1": portfolio_metrics(ew_daily, 0, 0)}

    # 결과 저장
    out["portfolio_results"] = results
    out["n_bull_days"] = int(bull["date"].nunique())
    out["n_bull_obs"] = int(len(bull))
    out["avg_turnover"] = {k: v.get(30, {}).get("ann_vol", 0) for k, v in results.items()}  # placeholder

    # 연도별/반기별 분해 (r_1 daily P&L 동일 방식)
    out["by_year"] = {}
    for y in sorted(bull["date"].dt.year.unique()):
        ys = bull[bull["date"].dt.year == y]
        if len(ys) < 50:
            continue
        out["by_year"][int(y)] = {"n_days": int(ys["date"].nunique()), "obs": int(len(ys))}
        for q in QUANTILES:
            key = f"Q{int(q*100)}"
            out["by_year"][int(y)][key] = {}
            # r_1 daily P&L
            daily_ls = []
            dates_sorted = sorted(ys["date"].unique())
            for d in dates_sorted:
                sub = ys[ys["date"] == d]
                if len(sub) < MINASSETS:
                    continue
                long_ret = sub[sub["taker_rank"] >= 1-q]["r_1"].mean()
                short_ret = sub[sub["taker_rank"] <= q]["r_1"].mean()
                if np.isfinite(long_ret) and np.isfinite(short_ret):
                    daily_ls.append(long_ret - short_ret)
            if daily_ls:
                out["by_year"][int(y)][key]["r_1"] = portfolio_metrics(pd.Series(daily_ls))

    # 최근 구간 2025H2, 2026H1, 2026H2
    out["recent_halves"] = {}
    for label, start, end in [("2025H2", "2025-07-01", "2025-12-31"),
                              ("2026H1", "2026-01-01", "2026-06-30"),
                              ("2026H2", "2026-07-01", "2026-08-28")]:
        ys = bull[(bull["date"] >= start) & (bull["date"] <= end)]
        out["recent_halves"][label] = {"n_days": int(ys["date"].nunique())}
        for q in QUANTILES:
            key = f"Q{int(q*100)}"
            daily_ls = []
            for d, sub in ys.groupby("date"):
                if len(sub) < MINASSETS:
                    continue
                long_ret = sub[sub["taker_rank"] >= 1-q]["r_1"].mean()
                short_ret = sub[sub["taker_rank"] <= q]["r_1"].mean()
                if np.isfinite(long_ret) and np.isfinite(short_ret):
                    daily_ls.append(long_ret - short_ret)
            if daily_ls:
                out["recent_halves"][label][key] = {"r_1": portfolio_metrics(pd.Series(daily_ls))}

    # ZEC 제외
    bull_nozec = bull[bull["symbol"] != "ZEC"]
    out["nozec"] = {}
    for q in QUANTILES:
        key = f"Q{int(q*100)}"
        out["nozec"][key] = {}
        daily_ls = []
        dates_sorted = sorted(bull_nozec["date"].unique())
        for d in dates_sorted:
            sub = bull_nozec[bull_nozec["date"] == d]
            if len(sub) < MINASSETS:
                continue
            long_ret = sub[sub["taker_rank"] >= 1-q]["r_1"].mean()
            short_ret = sub[sub["taker_rank"] <= q]["r_1"].mean()
            if np.isfinite(long_ret) and np.isfinite(short_ret):
                daily_ls.append(long_ret - short_ret)
        if daily_ls:
            out["nozec"][key]["r_1"] = portfolio_metrics(pd.Series(daily_ls))

    # JSON 직렬화
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [_to_jsonable(v) for v in obj]
        return str(obj)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")

    # 콘솔 요약
    print("=== taker_ratio_7 OOS validation (bull only, r_1 daily P&L) ===")
    print(f"Bull days: {out['n_bull_days']}  Obs: {out['n_bull_obs']}")
    print("\n[EW Benchmark r_1]:", out["ew_benchmark"].get("r_1", {}))
    for q in QUANTILES:
        key = f"Q{int(q*100)}"
        if key in results and 30 in results[key]:
            r = results[key][30]
            print(f"\n[{key} Long-Short r_1, cost 30bp]: CAGR={r.get('cagr'):.4f}, Sharpe={r.get('sharpe'):.3f}, "
                  f"MaxDD={r.get('max_dd'):.4f}, WR={r.get('win_rate'):.3f}, Vol={r.get('ann_vol'):.4f}")

    print("\n[Yearly Q10 r_1]:")
    for y, v in out["by_year"].items():
        if "Q10" in v and "r_1" in v["Q10"]:
            r = v["Q10"]["r_1"]
            print(f"  {y}: CAGR={r.get('cagr'):.4f}, Sharpe={r.get('sharpe'):.3f}, DD={r.get('max_dd'):.4f}, WR={r.get('win_rate'):.3f}")

    print("\n[Recent Halves Q10 r_1]:")
    for label, v in out["recent_halves"].items():
        if "Q10" in v and "r_1" in v["Q10"]:
            r = v["Q10"]["r_1"]
            print(f"  {label}: CAGR={r.get('cagr'):.4f}, Sharpe={r.get('sharpe'):.3f}, DD={r.get('max_dd'):.4f}, WR={r.get('win_rate'):.3f}")

    print("\n[ZEC Excluded Q10 r_1]:", out["nozec"].get("Q10", {}).get("r_1", {}))

    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()