#!/usr/bin/env python
"""Step 14 — Funding Rate 예측력 기초 검증.

Funding feature(일평균/당일누적/rolling z-score/7D 변화량)와
1D/3D/7D forward return 관계를 통계적으로 검증한다.

시간 정렬 규칙 (중요):
- Funding timestamp는 UTC ms. KST 날짜 d = (funding_time + 9h)의 KST 날짜.
- KST 일봉 d(00:00 KST 경계, Upbit)에는 펀딩 3건(01:00/09:00/17:00 KST)이 속한다.
  이 중 마지막(17:00 KST)은 일봉 d의 종가(24:00 KST) 이전에 확정 → feature(d)는
  close(d) 시점에 모두 알려져 있어 forward return 예측에 lookahead 없음.
- forward return r_H(d) = close(d+H)/close(d) - 1  (KST 달력 기준 H일 후 종가).
- rolling z-score는 '직전 30 KST일'만 사용(shift(1), min_periods=20) — 오늘 값 제외.

금지 준수: 전략 코드/파라미터 수정 없음, grid search 없음, 백테스트 없음.
출력: findings JSON + 콘솔 요약 (MD는 별도 작성).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scipy import stats

HERE = Path(__file__).resolve().parent
FUNDING = HERE / "data" / "crypto" / "funding"
DAILY = HERE / "data" / "crypto" / "daily"
OUT_JSON = HERE / "findings" / "funding-predictive-baseline-2026-08.json"

BASES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE",
         "DOT", "ATOM", "AVAX", "LINK", "NEAR", "OP", "UNI"]

HORIZONS = {"r_1": 1, "r_3": 3, "r_7": 7}
FEATURES = ["f_avg", "f_sum", "f_z", "f_chg7"]


def load_frames(base):
    fund = pd.read_parquet(FUNDING / f"{base}USDT.parquet")
    ohlcv = pd.read_parquet(DAILY / f"KRW-{base}.parquet")
    assert ohlcv.index.name == "date" and ohlcv.index.tz is None, "OHLCV는 KST naive 기대"

    # --- 펀딩 → KST 일봉 정렬 ---
    kst_dates = fund.index.tz_convert("Asia/Seoul").normalize().tz_localize(None)
    g = fund.groupby(kst_dates)
    fin = pd.DataFrame({
        "f_avg": g["fundingRate"].mean(),
        "f_sum": g["fundingRate"].sum(),
        "nfund": g.size(),
    })
    fin.index.name = "date"

    # --- 연속 KST 달력 위에서 피처/종가 재정렬 ---
    close = ohlcv["close"].rename("close")
    cal_start = fin.index.min()
    cal_end = ohlcv.index.max()
    calendar = pd.date_range(cal_start, cal_end, freq="D", name="date")

    df = fin.reindex(calendar)
    df["close"] = close.reindex(calendar)

    # 피처 (오늘 이후 정보 미사용)
    rmean = df["f_avg"].rolling(30, min_periods=20).mean().shift(1)
    rstd = df["f_avg"].rolling(30, min_periods=20).std().shift(1)
    df["f_z"] = (df["f_avg"] - rmean) / rstd
    df["f_chg7"] = df["f_avg"] - df["f_avg"].shift(7)
    df["past30_ret"] = df["close"] / df["close"].shift(30) - 1.0

    # forward returns
    for hn, h in HORIZONS.items():
        df[hn] = df["close"].shift(-h) / df["close"] - 1.0

    df["symbol"] = base
    return df


def welch(a, b):
    if len(a) < 5 or len(b) < 5:
        return np.nan, np.nan, 0.0
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return float(t), float(p), float(a.mean() - b.mean())


def corr2(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 30:
        return np.nan, np.nan, np.nan, np.nan
    pr, pp = stats.pearsonr(x[ok], y[ok])
    sr, sp = stats.spearmanr(x[ok], y[ok])
    return float(pr), float(pp), float(sr), float(sp)


def decile_rank(s):
    return (s.rank(pct=True) * 10).clip(0, 9).astype(int) + 1


def main():
    frames = {b: load_frames(b) for b in BASES}
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    full = full[~full["symbol"].isna()]

    out = {"grouping_rule": (
        "funding UTC ms → KST 날짜 d(=UTC+9h의 KST calendar date); KST 일봉 d 종가 "
        "(24:00 KST) 시점에 펀딩 3건 모두 확정 → feature(d)에 lookahead 없음; "
        "r_H(d)=close(d+H)/close(d)-1 (KST 달력, H=1/3/7)"),
        "by_symbol": {}, "pooled": {}}

    # ---- 0) 정렬 유효성: KST 일당 펀딩 이벤트 수 ----
    nfund_stats = {}
    for b, fr in frames.items():
        vc = fr["nfund"].dropna().value_counts()
        nfund_stats[b] = vc.to_dict()
    out["aligned_events_per_kst_day"] = nfund_stats

    # ---- 1) 상관 (pooled + asset별) ----
    corr_pool = {}
    corr_by_asset = {}
    for f in FEATURES:
        for h in HORIZONS:
            x = full[f].to_numpy(dtype=float)
            y = full[h].to_numpy(dtype=float)
            ok = ~(np.isnan(x) | np.isnan(y))
            pr, pp, sr, sp = corr2(x[ok], y[ok])
            corr_pool[f"{f}~{h}"] = {
                "n": int(ok.sum()),
                "pearson": pr, "pear_p": pp,
                "spearman": sr, "spear_p": sp,
            }
    # asset별 pearson/spearman (n 표기 최소화, BTC 별도)
    for b, fr in frames.items():
        fr = fr.dropna(subset=list(HORIZONS) + FEATURES)
        for f in FEATURES:
            for h in HORIZONS:
                x, y = fr[f].to_numpy(float), fr[h].to_numpy(float)
                ok = ~(np.isnan(x) | np.isnan(y))
                pr, pp, sr, sp = corr2(x[ok], y[ok])
                corr_by_asset.setdefault(f, {}).setdefault(h, {})[b] = {
                    "n": int(ok.sum()), "pear": pr, "spear": sr}
    out["corr_pooled"] = corr_pool
    out["corr_by_asset"] = corr_by_asset

    # ---- 2) asset별 decile(D1~D10) + sign split 의 mean forward return ----
    # 피처별 asset 내 decile 부여 후 pooled로 집계 (asset 균형)
    full = full.copy()
    for f in FEATURES:
        full[f + "_dec"] = np.nan
        for b in BASES:
            m = full["symbol"] == b
            valid = full.loc[m, f].notna()
            full.loc[m & valid, f + "_dec"] = decile_rank(full.loc[m & valid, f])

    dec_tables = {}
    extreme = {}
    for f in FEATURES:
        col = f + "_dec"
        for h in HORIZONS:
            sub = full.dropna(subset=[col, h])
            g = sub.groupby(col)[h]
            means = g.mean()
            ns = g.size()
            # D1(기금) vs D10(고금)
            d1 = sub.loc[sub[col] == 1, h].to_numpy(float)
            d10 = sub.loc[sub[col] == 10, h].to_numpy(float)
            t, p, delta = welch(d1, d10)
            dec_tables.setdefault(f, {})[h] = {
                "mean_by_dec": {int(k): (round(float(v), 6), int(ns.loc[k])) for k, v in means.items()},
                "D1_n": int(len(d1)), "D10_n": int(len(d10)),
                "D1_mean": (round(float(d1.mean()), 6) if len(d1) else None),
                "D10_mean": (round(float(d10.mean()), 6) if len(d10) else None),
                "D1_minus_D10": round(delta, 6) if not np.isnan(delta) else None,
                "t": (round(t, 3) if not np.isnan(t) else None),
                "p": (round(p, 4) if not np.isnan(p) else None),
                "reversal_supported": bool(delta > 0),  # 기금(D1) 수익이 고금(D10)보다 높은지
            }
            extreme.setdefault(f, {})[h] = {
                "D1_mean": round(float(d1.mean()), 6) if len(d1) else None,
                "D10_mean": round(float(d10.mean()), 6) if len(d10) else None,
                "delta": round(delta, 6) if not np.isnan(delta) else None,
                "t": (round(t, 3) if not np.isnan(t) else None),
            }
    out["decile_tables"] = dec_tables

    # ---- 3) sign split: f_avg 부호별 forward return (pooled + asset별) ----
    sign_pool = {}
    sign_by_asset = {}
    for h in HORIZONS:
        sub = full.dropna(subset=["f_avg", h])
        pos = sub.loc[sub["f_avg"] > 0, h].to_numpy(float)
        neg = sub.loc[sub["f_avg"] < 0, h].to_numpy(float)
        t, p, delta = welch(pos, neg)
        sign_pool[h] = {
            "pos_n": int(len(pos)), "neg_n": int(len(neg)),
            "pos_mean": round(float(pos.mean()), 6), "neg_mean": round(float(neg.mean()), 6),
            "pos_minus_neg": round(delta, 6) if not np.isnan(delta) else None,
            "t": round(t, 3) if not np.isnan(t) else None, "p": round(p, 4) if not np.isnan(p) else None,
        }
        per_asset = {}
        for b in BASES:
            m = full["symbol"] == b
            s = sub.loc[m]
            if len(s) == 0:
                continue
            pp = s.loc[s["f_avg"] > 0, h].to_numpy(float)
            nn = s.loc[s["f_avg"] < 0, h].to_numpy(float)
            per_asset[b] = {
                "pos_mean": round(float(pp.mean()), 6) if len(pp) else None,
                "neg_mean": round(float(nn.mean()), 6) if len(nn) else None,
                "pos_n": int(len(pp)), "neg_n": int(len(nn)),
            }
        sign_by_asset[h] = per_asset
    out["sign_pooled"] = sign_pool
    out["sign_by_asset"] = sign_by_asset

    # ---- 4) 추세 부산물 여부 + 부분회귀 ----
    trend = {}
    for f in FEATURES:
        x = full[f].to_numpy(float)
        y = full["past30_ret"].to_numpy(float)
        ok = ~(np.isnan(x) | np.isnan(y))
        pr, pp, sr, sp = corr2(x[ok], y[ok])
        trend[f] = {"pear": pr, "spear": sr, "p": pp, "n": int(ok.sum())}
    out["corr_feature_vs_past30_ret"] = trend

    # 부분회귀: r_h ~ f_avg + past30_ret + symbol FE (pooled)
    import statsmodels.formula.api as smf
    reg = {}
    for h in ["r_1", "r_3", "r_7"]:
        sub = full.dropna(subset=["f_avg", h, "past30_ret"])
        m0 = smf.ols(f"{h} ~ f_avg + C(symbol)", data=sub).fit()
        m1 = smf.ols(f"{h} ~ f_avg + past30_ret + C(symbol)", data=sub).fit()
        reg[h] = {
            "n": int(len(sub)),
            "favg_coef_fe_only": round(float(m0.params["f_avg"]), 8),
            "favg_t_fe_only": round(float(m0.tvalues["f_avg"]), 3),
            "favg_p_fe_only": round(float(m0.pvalues["f_avg"]), 4),
            "favg_coef_fe_and_mom": round(float(m1.params["f_avg"]), 8),
            "favg_t_fe_and_mom": round(float(m1.tvalues["f_avg"]), 3),
            "favg_p_fe_and_mom": round(float(m1.pvalues["f_avg"]), 4),
            "mom_coef": round(float(m1.params["past30_ret"]), 6),
            "mom_t": round(float(m1.tvalues["past30_ret"]), 3),
            "r2_fe_only": round(float(m0.rsquared), 4),
            "r2_fe_and_mom": round(float(m1.rsquared), 4),
        }
    out["partial_regression"] = reg

    # ---- 5) 집중도: LOO 코인 + 연도별 delta ----
    loo = {}
    for b in BASES:
        rest = full[full["symbol"] != b].dropna(subset=["f_avg", "r_7"])
        col = rest["f_avg"].rank(pct=True)
        d1 = rest.loc[col <= 0.1, "r_7"].to_numpy(float)
        d10 = rest.loc[col >= 0.9, "r_7"].to_numpy(float)
        t, p, delta = welch(d1, d10)
        loo[b] = {"D1_minus_D10": (round(delta, 6) if not np.isnan(delta) else None),
                  "t": (round(t, 3) if not np.isnan(t) else None), "n_D1": int(len(d1)), "n_D10": int(len(d10))}
    full_all = full.dropna(subset=["f_avg", "r_7"]).copy()
    colall = full_all["f_avg"].rank(pct=True)
    t0, p0, delta0 = welch(full_all.loc[colall <= 0.1, "r_7"].to_numpy(float),
                           full_all.loc[colall >= 0.9, "r_7"].to_numpy(float))
    out["loo_extreme_delta_r7"] = {"all": {"D1_minus_D10": (round(delta0, 6) if not np.isnan(delta0) else None),
                                            "t": (round(t0, 3) if not np.isnan(t0) else None)}, "drop_each_coin": loo}

    # 연도별 (f_avg, r_7) 극단 델타
    years = {}
    full_all["year"] = full_all["date"].dt.year
    for y in sorted(full_all["year"].dropna().unique()):
        sub = full_all[full_all["year"] == y]
        if len(sub) < 200:
            continue
        col = sub["f_avg"].rank(pct=True)
        d1 = sub.loc[col <= 0.1, "r_7"].to_numpy(float)
        d10 = sub.loc[col >= 0.9, "r_7"].to_numpy(float)
        t, p, delta = welch(d1, d10)
        years[int(y)] = {"D1_mean": round(float(d1.mean()), 6), "D10_mean": round(float(d10.mean()), 6),
                         "D1_minus_D10": round(delta, 6) if not np.isnan(delta) else None,
                         "t": (round(t, 3) if not np.isnan(t) else None),
                         "n_D1": int(len(d1)), "n_D10": int(len(d10))}
    out["extreme_delta_by_year_r7"] = years

    # ---- 6) asset별 기금/고금 극단 delta (f_avg, r_7) ----
    asset_delta_r7 = {}
    for b in BASES:
        sub = full[full["symbol"] == b].dropna(subset=["f_avg", "r_7"])
        col = sub["f_avg"].rank(pct=True)
        d1 = sub.loc[col <= 0.1, "r_7"].to_numpy(float)
        d10 = sub.loc[col >= 0.9, "r_7"].to_numpy(float)
        t, p, delta = welch(d1, d10)
        asset_delta_r7[b] = {"D1_mean": round(float(d1.mean()), 6), "D10_mean": round(float(d10.mean()), 6),
                             "D1_minus_D10": round(delta, 6) if not np.isnan(delta) else None,
                             "t": (round(t, 3) if not np.isnan(t) else None), "n_D1": int(len(d1)), "n_D10": int(len(d10))}
    out["asset_extreme_delta_r7_favg"] = asset_delta_r7

    # ---- 7) 극단 bucket 구성 비중 (코인별, D1/D10) ----
    comp = {}
    sub = full.dropna(subset=["f_avg"])
    col = sub["f_avg"].rank(pct=True)
    comp["D1"] = sub.loc[col <= 0.1, "symbol"].value_counts().to_dict()
    comp["D10"] = sub.loc[col >= 0.9, "symbol"].value_counts().to_dict()
    out["extreme_bucket_composition"] = comp

    out["funding_carry_context"] = {
        b: {"cumsum_daily_funding_total": round(float(frames[b]["f_sum"].sum()), 6),
            "n_days": int(frames[b]["f_sum"].notna().sum())}
        for b in BASES
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- 콘솔 요약 ----------
    print("=== Step 14 funding predictive baseline ===")
    print("\n[정렬] KST 일당 평균 펀딩 이벤트 수 (총 날짜 수 기준 mode):",
          {b: max(s.items(), key=lambda kv: kv[1])[0] for b, s in nfund_stats.items()})
    print("\n[1] pooled correlation (n, pearson, spearman)")
    for k, v in corr_pool.items():
        print(f"  {k:12s} n={v['n']:6d} pear={v['pearson']:+.4f}  spear={v['spearman']:+.4f}")
    print("\n[2] 극단 decile D1-D10 delta (기금-고금 forward return)")
    for f in FEATURES:
        for h in HORIZONS:
            e = extreme[f][h]
            print(f"  {f:7s} {h}: D1={e['D1_mean']:+.5f} D10={e['D10_mean']:+.5f} Δ={e['delta']:+.5f} t={e['t']}")
    print("\n[3] sign split (f_avg>0 vs <0) forward return")
    for h, v in sign_pool.items():
        print(f"  {h}: pos={v['pos_mean']:+.5f}(n={v['pos_n']}) neg={v['neg_mean']:+.5f}(n={v['neg_n']}) Δ={v['pos_minus_neg']:+.5f} t={v['t']}")
    print("\n[4] feature vs past30_ret corr (추세 부산물 여부)")
    for f, v in trend.items():
        print(f"  {f:7s} pear={v['pear']:+.4f} spear={v['spear']:+.4f}")
    print("\n[5] 부분회귀 r_h ~ f_avg (+ past30_ret) + symbol FE")
    for h, v in reg.items():
        print(f"  {h}: coef_fe={v['favg_coef_fe_only']:+.6f}(t={v['favg_t_fe_only']}) coef_fe+mom={v['favg_coef_fe_and_mom']:+.6f}(t={v['favg_t_fe_and_mom']}) mom_t={v['mom_t']} r2={v['r2_fe_only']}->{v['r2_fe_and_mom']}")
    print("\n[6] asset별 극단 delta (f_avg, r7)")
    for b, v in asset_delta_r7.items():
        print(f"  {b:5s} D1={v['D1_mean']:+.5f} D10={v['D10_mean']:+.5f} Δ={v['D1_minus_D10']:+.5f} t={v['t']}")
    print("\n[7] 연도별 극단 delta (f_avg, r7)")
    for y, v in years.items():
        print(f"  {y}: Δ={v['D1_minus_D10']:+.5f} t={v['t']} (nD1={v['n_D1']})")
    print("\n[8] LOO")
    print("  all:", out["loo_extreme_delta_r7"]["all"])
    print("  drop:", {b: v["D1_minus_D10"] for b, v in loo.items()})
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()