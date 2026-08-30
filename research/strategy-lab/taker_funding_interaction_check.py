#!/usr/bin/env python
"""Step 26 — taker_ratio_7 × funding residual 결합 정보 검증 (bull regime only).

Step 25에서 mom30>0 bull 구간에서만 신호가 강함을 확인.
이번 단계: bull regime 내에서 taker_ratio_7과 funding residual의
단독/결합 예측력을 2D quantile로 비교.

기존 데이터만 사용. 신규 수집·백테스트·전략화·S2/engine 수정·findings 수정·커밋 금지.
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
OUT_JSON = HERE / "findings" / "taker-funding-interaction-2026-08.json"
OUT_MD = HERE / "findings" / "taker-funding-interaction-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, MINASSETS)

SYM28 = ALL


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


def load_bull_panel():
    """mom30 > 0 (bull) 구간만 패널 구성."""
    frames = {}
    for b in SYM28:
        fr = load_joint(b)
        tr = build_taker_ratio(b, fr.index)
        fr = fr.join(tr, how="left")
        # funding residual: f_avg ~ mom30 rolling OOS
        f_resid = rolling_oos_resid(fr["f_avg"].to_numpy(float), [fr["mom30"].to_numpy(float)])
        fr["f_avg_fmresid"] = f_resid
        # mom30 regime
        fr["reg_mom30"] = np.where(fr["mom30"] > 0, "bull", "bear")
        # 필요한 컬럼만
        fr = fr[["close", "f_avg", "mom30", "f_avg_fmresid", "taker_7d",
                 "reg_mom30", "r_1", "r_3", "r_7"]].copy()
        fr["symbol"] = b
        frames[b] = fr
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    # bull만 필터
    bull = full[full["reg_mom30"] == "bull"].copy()
    # 유효 행
    bull = bull.dropna(subset=["taker_7d", "f_avg_fmresid", "r_1", "r_3", "r_7"]).copy()
    return bull


def q_spread_2d(df, x, y, h, q=5):
    """2D quantile grid에서 각 셀의 평균 forward return."""
    df = df.dropna(subset=[x, y, h]).copy()
    if len(df) < 50:
        return None
    df["_qx"] = pd.qcut(df[x].rank(method="first"), q, labels=False) + 1
    df["_qy"] = pd.qcut(df[y].rank(method="first"), q, labels=False) + 1
    # 셀별 평균
    cell_means = df.groupby(["_qx", "_qy"])[h].mean()
    cell_counts = df.groupby(["_qx", "_qy"])[h].size()
    # 전체 평균 대비 편차
    overall = df[h].mean()
    dev = cell_means - overall
    # 극단: Q1-Q1 (low taker, low fund_resid) vs Q5-Q5 (high, high) 등
    corners = {}
    for label, (qx, qy) in [("Q1_Q1", (1, 1)), ("Q1_Q5", (1, q)),
                            ("Q5_Q1", (q, 1)), ("Q5_Q5", (q, q))]:
        if (qx, qy) in cell_means.index:
            corners[label] = {
                "mean": round(float(cell_means.loc[(qx, qy)]), 6),
                "count": int(cell_counts.loc[(qx, qy)]),
                "dev_from_overall": round(float(dev.loc[(qx, qy)]), 6)
            }
    return {"grid_means": {f"{i},{j}": round(float(v), 6) for (i, j), v in cell_means.items()},
            "grid_counts": {f"{i},{j}": int(v) for (i, j), v in cell_counts.items()},
            "corners": corners,
            "overall_mean": round(float(overall), 6)}


def date_cs_ic_2d(df, x, y, h, min_assets=MINASSETS):
    """2D rank product IC: rank(x)*rank(y) 또는 두 rank 합산."""
    ics = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[x, y, h])
        if len(s) < min_assets:
            continue
        # 결합 rank: x rank + y rank (또는 곱셈)
        rx = s[x].rank(pct=True)
        ry = s[y].rank(pct=True)
        comb = rx + ry  # 합산 rank
        ic = stats.spearmanr(comb, s[h]).statistic
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 10:
        return {"n_dates": len(ics), "mean_ic": None, "t": None, "frac_pos": None}
    ics = np.array(ics, float)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {"n_dates": len(ics), "mean_ic": round(float(ics.mean()), 6),
            "t": round(float(t), 3), "frac_pos": round(float((ics > 0).mean()), 4)}


def single_feature_spread(df, feat, h):
    return spread(df, feat, h)


def check_cell_dominance(df, x, y, h, q=5):
    """특정 극단 셀이 전체 스프레드를 지배하는지 확인."""
    df = df.dropna(subset=[x, y, h]).copy()
    df["_qx"] = pd.qcut(df[x].rank(method="first"), q, labels=False) + 1
    df["_qy"] = pd.qcut(df[y].rank(method="first"), q, labels=False) + 1
    # Q5-Q1 (high taker, high fund_resid) vs Q1-Q5 등
    cells = {}
    for qx in [1, q]:
        for qy in [1, q]:
            sub = df[(df["_qx"] == qx) & (df["_qy"] == qy)]
            if len(sub) > 20:
                cells[f"Q{qx}_Q{qy}"] = {
                    "mean": float(sub[h].mean()),
                    "count": int(len(sub)),
                    "t_vs_overall": float(stats.ttest_1samp(sub[h], df[h].mean()).statistic)
                }
    return cells


def main():
    bull = load_bull_panel()
    bull_nozec = bull[bull["symbol"] != "ZEC"].copy()

    out = {"design": {
        "purpose": "bull regime(mom30>0)에서 taker_ratio_7 × funding residual(f_avg_fmresid) 결합 예측력 검증",
        "universe": "SYM28, mom30>0 only",
        "features": ["taker_7d", "f_avg_fmresid"],
        "horizons": list(HORIZONS.keys()),
        "method": "2D quantile (Q5×Q5) grid, 단독/결합 비교, ZEC 제외, 임계값 최적화 없음",
    }}

    feats_single = ["taker_7d", "f_avg_fmresid"]
    features_2d = ("taker_7d", "f_avg_fmresid")

    # 0) 단독 feature baseline (bull 전체)
    out["single_baseline_bull"] = {}
    for f in feats_single:
        out["single_baseline_bull"][f] = {h: spread(bull, f, h) for h in HORIZONS}

    # 1) 2D quantile 분석
    out["joint_2d"] = {}
    for h in HORIZONS:
        q2d = q_spread_2d(bull, *features_2d, h, q=5)
        out["joint_2d"][h] = q2d
        # 셀 지배 확인
        out["joint_2d"][h]["cell_dominance"] = check_cell_dominance(bull, *features_2d, h)

    # 2) 결합 rank date-CS IC
    out["joint_date_cs"] = {}
    for h in HORIZONS:
        out["joint_date_cs"][h] = date_cs_ic_2d(bull, *features_2d, h)

    # 3) ZEC 제외 동일 분석
    out["nozec"] = {}
    for h in HORIZONS:
        out["nozec"][h] = {
            "joint_2d": q_spread_2d(bull_nozec, *features_2d, h, q=5),
            "joint_date_cs": date_cs_ic_2d(bull_nozec, *features_2d, h),
            "single": {f: spread(bull_nozec, f, h) for f in feats_single},
        }

    # 4) 극단 셀 지배 여부: 전체 combined spread vs 단독 spread 비교
    out["combination_vs_single"] = {}
    for h in HORIZONS:
        # 결합 극단 (Q5+Q5) - (Q1+Q1) 스타일 spread 계산
        df = bull.dropna(subset=["taker_7d", "f_avg_fmresid", h]).copy()
        rx = df["taker_7d"].rank(pct=True)
        ry = df["f_avg_fmresid"].rank(pct=True)
        comb = rx + ry
        high = df[comb >= comb.quantile(0.8)][h]
        low = df[comb <= comb.quantile(0.2)][h]
        t, p, delta = welch(high, low)
        comb_spread = {"D_high": float(high.mean()), "D_low": float(low.mean()),
                       "delta": float(delta) if not np.isnan(delta) else None,
                       "t": float(t) if not np.isnan(t) else None,
                       "n_high": int(len(high)), "n_low": int(len(low))}
        # 단독
        s_taker = spread(bull, "taker_7d", h)
        s_fund = spread(bull, "f_avg_fmresid", h)
        out["combination_vs_single"][h] = {
            "combined_20pct": comb_spread,
            "taker_only": s_taker,
            "fund_resid_only": s_fund,
        }

    # 5) ZEC 제외에서 동일 결합 spread
    for h in HORIZONS:
        df = bull_nozec.dropna(subset=["taker_7d", "f_avg_fmresid", h]).copy()
        rx = df["taker_7d"].rank(pct=True)
        ry = df["f_avg_fmresid"].rank(pct=True)
        comb = rx + ry
        high = df[comb >= comb.quantile(0.8)][h]
        low = df[comb <= comb.quantile(0.2)][h]
        t, p, delta = welch(high, low)
        out["combination_vs_single"][h]["combined_20pct_nozec"] = {
            "delta": float(delta) if not np.isnan(delta) else None,
            "t": float(t) if not np.isnan(t) else None,
        }

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
    print("=== taker_ratio_7 × funding residual interaction (bull only) ===")
    print("\n[0] 단독 baseline (bull 전체):")
    for f in feats_single:
        print(f"  {f}:")
        for h in HORIZONS:
            s = out["single_baseline_bull"][f][h]
            print(f"  {h}: Δ={s['D1_minus_D10']:+.5f} t={s['t']} nD1={s['n_D1']}")

    print("\n[1] 2D Q5×Q5 grid corners (r7):")
    q2d = out["joint_2d"]["r_7"]
    if q2d:
        for label, v in q2d["corners"].items():
            print(f"  {label}: mean={v['mean']:+.5f} dev={v['dev_from_overall']:+.5f} n={v['count']}")

    print("\n[2] 결합 rank date-CS IC:")
    for h in HORIZONS:
        cs = out["joint_date_cs"][h]
        print(f"  {h}: mean_ic={cs['mean_ic']:+.4f} t={cs['t']} pos={cs['frac_pos']:.2f}")

    print("\n[3] 결합 vs 단독 spread (top/bottom 20%):")
    for h in HORIZONS:
        c = out["combination_vs_single"][h]
        cs = c["combined_20pct"]
        st = c["taker_only"]
        sf = c["fund_resid_only"]
        print(f"  {h}: combined Δ={cs['delta']:+.5f}(t={cs['t']})  "
              f"taker Δ={st['D1_minus_D10']:+.5f}(t={st['t']})  "
              f"fund Δ={sf['D1_minus_D10']:+.5f}(t={sf['t']})")

    print("\n[4] ZEC 제외 combined r7:")
    for h in HORIZONS:
        nz = out["combination_vs_single"][h].get("combined_20pct_nozec", {})
        print(f"  {h}: Δ={nz.get('delta')} t={nz.get('t')}")

    print("\n[5] 셀 지배 체크 (r7):")
    dom = out["joint_2d"]["r_7"]["cell_dominance"]
    for label, v in dom.items():
        print(f"  {label}: mean={v['mean']:+.5f} t_vs_all={v['t_vs_overall']:.2f} n={v['count']}")

    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()