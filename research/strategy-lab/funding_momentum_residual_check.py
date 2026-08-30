#!/usr/bin/env python
"""Step 15 — Funding Momentum-Residual 검증.

Funding feature(f_avg, f_z, f_chg7)에서 30D price momentum으로부터
설명되는 성분을 제거한 잔차(residual)가 미래 수익률 정보를 갖는지 검증한다.

- 데이터/시간정렬: Step 14와 동일(funding_predictive_check.load_frames 재사용).
- Momentum: mom(d) = close(d)/close(d-30) - 1  (동일 라벨 기준, d 종가 시점 관측 가능).
- 잔차 추정: 자산별 롤링 OLS(f ~ 1 + mom), **과거 60일 창(t-60..t-1)만으로 추정**하고
  현재 시점 t에 적용하는 1스텝 OOS 잔차 — 미래 데이터 일절 미사용.
  (fit 포함 OLS 대비 보수적이며 '각 시점 이용 가능한 과거만 사용' 준수.)
- 검증: pooled/자산별/연도별 상관·데시일 스프레드·부분회귀·LOO.
- 금지 준수: grid search/임계값 최적화/백테스트/S2 수정 없음.
출력: findings JSON + 콘솔 요약.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_predictive_check import (  # noqa: E402
    BASES, HORIZONS, load_frames, welch, decile_rank,
)

OUT_JSON = HERE / "findings" / "funding-momentum-residual-2026-08.json"

WINDOW = 60
MINOBS = 30

# 잔차 만들 대상 피처 (원본 피처명)
RESID_FEATURES = ["f_avg", "f_z", "f_chg7"]


def rolling_oos_residual(y, x, window=WINDOW, minobs=MINOBS):
    """과거 창(t-w..t-1) OLS 추정 → t에 적용한 1스텝 OOS 잔차."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    n = len(y)
    resid = np.full(n, np.nan)
    beta_series = np.full(n, np.nan)
    alpha_series = np.full(n, np.nan)
    for t in range(window, n):
        lo = t - window
        ys = y[lo:t]
        xs = x[lo:t]
        ok = np.isfinite(ys) & np.isfinite(xs)
        if ok.sum() < minobs:
            continue
        X = np.column_stack([np.ones(ok.sum()), xs[ok]])
        b, *_ = np.linalg.lstsq(X, ys[ok], rcond=None)
        if not (np.all(np.isfinite(b))):
            continue
        if not (np.isfinite(y[t]) and np.isfinite(x[t])):
            continue
        pred = b[0] + b[1] * x[t]
        resid[t] = y[t] - pred
        beta_series[t] = b[1]
        alpha_series[t] = b[0]
    return resid, beta_series, alpha_series


def corr2(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 30:
        return np.nan, np.nan, 0, 0
    pr, pp = stats.pearsonr(x[ok], y[ok])
    sr, sp = stats.spearmanr(x[ok], y[ok])
    return float(pr), float(sr), int(ok.sum()), float(pp)


def extreme_delta(sub, feat, h, pt=True):
    """per-asset decile rank 후 D1-D10 델타. feat 열 존재 필요."""
    sub = sub.dropna(subset=[feat, h, "symbol"])
    sub = sub.copy()
    sub["_dec"] = np.nan
    for b in BASES:
        m = sub["symbol"] == b
        v = sub.loc[m, feat]
        sub.loc[m, "_dec"] = decile_rank(v)
    d1 = sub.loc[sub["_dec"] == 1, h].to_numpy(float)
    d10 = sub.loc[sub["_dec"] == 10, h].to_numpy(float)
    t, p, delta = welch(d1, d10)
    return {
        "D1_mean": round(float(d1.mean()), 6) if len(d1) else None,
        "D10_mean": round(float(d10.mean()), 6) if len(d10) else None,
        "D1_minus_D10": round(delta, 6) if not np.isnan(delta) else None,
        "t": (round(t, 3) if not np.isnan(t) else None),
        "n_D1": int(len(d1)), "n_D10": int(len(d10)),
    }


def main():
    # ---- 데이터 구성 (Step 14와 동일 규칙) ----
    frames = {b: load_frames(b) for b in BASES}
    # 잔차 열 추가
    for b, fr in frames.items():
        x = fr["past30_ret"].to_numpy(float)
        for f in RESID_FEATURES:
            y = fr[f].to_numpy(float)
            r, beta, alpha = rolling_oos_residual(y, x)
            fr[f + "_resid"] = r
            fr[f + "_beta"] = beta
        fr["symbol"] = b

    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})

    out = {
        "design": {
            "momentum": "mom(d)=close(d)/close(d-30)-1 (동일 라벨, close(d) 시점 관측)",
            "residual_fit": "rolling OLS f~1+mom on t-60..t-1, 적용 t (1-step OOS), minobs=30",
            "alignment": "Step 14와 동일 (funding UTC→KST, r_H=close(d+H)/close(d)-1)",
        },
        "carry_over_step14": {
            "pooled_corr_raw_r7": None,
        },
    }

    # mom이 funding을 얼마나 설명하는가 (roll fit R² 근사: beta·alpha 요약)
    fit = {}
    for b in BASES:
        fr = frames[b]
        beta = fr["f_avg_beta"].dropna()
        fit[b] = {
            "beta_mean": round(float(beta.mean()), 5),
            "beta_abs_mean": round(float(beta.abs().mean()), 5),
            "n_resid_valid": int(fr["f_avg_resid"].notna().sum()),
        }
    out["momentum_fit_beta"] = fit

    # ---- 1) pooled 상관: raw vs residual ----
    corr_pool = {}
    for f in RESID_FEATURES:
        for tag in ["", "_resid"]:
            feat = f + tag
            for h in HORIZONS:
                x = full[feat].to_numpy(float)
                y = full[h].to_numpy(float)
                pr, sr, n, pp = corr2(x, y)
                corr_pool[f"{feat}~{h}"] = {
                    "pearson": pr, "spearman": sr, "n": n, "pear_p": pp}
    out["corr_pooled"] = corr_pool

    # ---- 2) pooled 데시일 스프레드: raw vs residual ----
    dec = {}
    for f in RESID_FEATURES:
        for tag in ["", "_resid"]:
            feat = f + tag
            for h in HORIZONS:
                dec[f"{feat}|{h}"] = extreme_delta(full, feat, h)
    out["decile_spread_pooled"] = dec

    # ---- 3) 부분회귀 (1단계 잔차의 독립성 확인) ----
    import statsmodels.formula.api as smf
    reg = {}
    for h in HORIZONS:
        sub = full.dropna(subset=["f_avg", "f_avg_resid", h, "past30_ret"])
        sub = sub.copy()
        m_raw = smf.ols(f"{h} ~ mom + f_avg + C(symbol)", data=sub.assign(mom=sub["past30_ret"])).fit()
        m_res = smf.ols(f"{h} ~ mom + f_avg_resid + C(symbol)", data=sub.assign(mom=sub["past30_ret"])).fit()
        m_res_only = smf.ols(f"{h} ~ f_avg_resid + C(symbol)", data=sub).fit()
        reg[h] = {
            "n": int(len(sub)),
            "raw_favg_t_with_mom": round(float(m_raw.tvalues["f_avg"]), 3),
            "raw_favg_p_with_mom": round(float(m_raw.pvalues["f_avg"]), 4),
            "resid_t_with_mom": round(float(m_res.tvalues["f_avg_resid"]), 3),
            "resid_p_with_mom": round(float(m_res.pvalues["f_avg_resid"]), 4),
            "resid_t_no_mom": round(float(m_res_only.tvalues["f_avg_resid"]), 3),
            "resid_coef_no_mom": round(float(m_res_only.params["f_avg_resid"]), 8),
            "mom_t": round(float(m_raw.tvalues["mom"]), 3),
        }
    out["partial_regression"] = reg

    # ---- 4) 연도별: residual r7 스프레드 (f_avg_resid) ----
    sub = full.dropna(subset=["f_avg_resid", "r_7", "symbol"]).copy()
    sub["year"] = sub["date"].dt.year
    years = {}
    for y in sorted(sub["year"].unique()):
        ys = sub[sub["year"] == y]
        if len(ys) < 200:
            continue
        years[int(y)] = extreme_delta(ys, "f_avg_resid", "r_7")
    out["year_spread_r7_favg_resid"] = years

    # ---- 5) 자산별: raw vs residual r7 스프레드 ----
    by_asset = {}
    for b in BASES:
        fr = frames[b]
        by_asset[b] = {
            "raw": extreme_delta(fr, "f_avg", "r_7"),
            "resid": extreme_delta(fr, "f_avg_resid", "r_7"),
        }
    out["asset_spread_r7"] = by_asset

    # ---- 6) LOO (pooled, f_avg_resid, r7) ----
    loo = {}
    suball = full.dropna(subset=["f_avg_resid", "r_7"])
    loo["all"] = extreme_delta(suball, "f_avg_resid", "r_7")
    for b in BASES:
        rest = suball[suball["symbol"] != b]
        loo[f"drop_{b}"] = extreme_delta(rest, "f_avg_resid", "r_7")
    out["loo_r7_favg_resid"] = loo

    # ---- 7) raw vs residual 상관 (정보 중복도) ----
    overlap = {}
    for f in RESID_FEATURES:
        x = full[f].to_numpy(float)
        y = full[f + "_resid"].to_numpy(float)
        pr, sr, n, pp = corr2(x, y)
        overlap[f] = {"corr_pear": pr}
    out["raw_resid_overlap"] = overlap

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- 콘솔 ----
    print("=== Step 15 funding momentum-residual ===")
    print("\n[0] momentum→funding fit (rolling beta of f_avg on mom):")
    for b in BASES:
        print(f"  {b:5s} beta_mean={fit[b]['beta_mean']:+.4f} |beta|avg={fit[b]['beta_abs_mean']:.4f} resid_n={fit[b]['n_resid_valid']}")
    print("\n[1] pooled corr  (pear: raw | resid; n)")
    for f in RESID_FEATURES:
        for h in HORIZONS:
            raw = corr_pool[f"{f}~{h}"]
            res = corr_pool[f"{f}_resid~{h}"]
            print(f"  {f:7s} {h}: raw={raw['pearson']:+.4f} resid={res['pearson']:+.4f} (n={res['n']})")
    print("\n[2] decile D1-D10 spread (raw | resid)")
    for f in RESID_FEATURES:
        for h in HORIZONS:
            d_raw = dec[f"{f}|{h}"]
            d_res = dec[f"{f}_resid|{h}"]
            print(f"  {f:7s} {h}: raw=Δ{d_raw['D1_minus_D10']:+.5f}(t{d_raw['t']})  resid=Δ{d_res['D1_minus_D10']:+.5f}(t{d_res['t']})")
    print("\n[3] partial regression (with mom, symbol FE)")
    for h, v in reg.items():
        print(f"  {h}: raw_favg t={v['raw_favg_t_with_mom']}  resid t(with mom)={v['resid_t_with_mom']}  resid t(no mom)={v['resid_t_no_mom']}  mom_t={v['mom_t']}")
    print("\n[4] 연도별 resid r7 spread")
    for y, v in years.items():
        print(f"  {y}: Δ={v['D1_minus_D10']:+.5f} t={v['t']} (nD1={v['n_D1']})")
    print("\n[5] 자산별 r7 spread (raw | resid)")
    for b, v in by_asset.items():
        print(f"  {b:5s} raw=Δ{v['raw']['D1_minus_D10']:+.5f}(t{v['raw']['t']})  resid=Δ{v['resid']['D1_minus_D10']:+.5f}(t{v['resid']['t']})")
    print("\n[6] LOO r7 resid:", loo["all"])
    print("\n[7] raw~resid corr:", {k: round(v["corr_pear"], 3) for k, v in overlap.items()})
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()