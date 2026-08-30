#!/usr/bin/env python
"""Step 24 follow-up — taker_ratio_7 견고성 검증.

Step 24에서 발견된 taker_ratio_7(r7 t=5.43, fmresid t=2.79)가
ZEC 1종목 의존·기간·윈도우·통제 변화에 얼마나 견고한지 확인한다.

방법론: Step 24 동일(정렬 KST daily, forward r_H, lookahead 방지,
rolling OOS 60일 잔차). 기존 데이터만 사용, 수집·백테스트·수정 금지.
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
OUT_JSON = HERE / "findings" / "taker-ratio-robustness-2026-08.json"
OUT_MD = HERE / "findings" / "taker-ratio-robustness-2026-08.md"

import sys
sys.path.insert(0, str(HERE))
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank   # noqa: E402
from funding_premium_info_check import (                                   # noqa: E402
    load_joint, rolling_oos_resid, spread, corr2, ALL, NEW14, ARB, MINASSETS)

# 28종목 (ZEC 포함)
SYM28 = ALL
WINDOWS = [3, 5, 7, 14, 30]   # taker_ratio rolling mean windows
HORS = ["r_1", "r_3", "r_7"]
CONTROL_SETS = {
    "none": [],
    "funding": ["f_avg"],
    "mom30": ["mom30"],
    "fund+mom": ["f_avg", "mom30"],
    "fund+mom+qvol": ["f_avg", "mom30", "qvol_7d_chg"],
}


def build_taker_ratios(base, calendar):
    """activity 1h → KST daily taker_ratio (raw) 및 nbar + qvol 변화량."""
    a = pd.read_parquet(ACTIVITY / f"{base}USDT_1h.parquet")
    kst_day = (a["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    g = a.groupby(kst_day)
    day = pd.DataFrame({
        "qvol": g["quote_asset_volume"].sum(),
        "tbq":  g["taker_buy_quote_asset_volume"].sum(),
        "nbar": g.size(),
    })
    day.index.name = "date"
    day["taker_raw"] = day["tbq"] / day["qvol"]
    # qvol 변화량 (Step 24와 동일)
    day["qvol_1d_chg"] = day["qvol"] / day["qvol"].shift(1) - 1.0
    day["qvol_7d_chg"] = day["qvol"] / day["qvol"].shift(7) - 1.0
    for c in ["qvol_1d_chg", "qvol_7d_chg"]:
        day[c] = day[c].replace([np.inf, -np.inf], np.nan)
    # 각 윈도우 rolling mean (lookback 포함 — 당일 값도 정보로 허용, shift 안 함)
    for w in WINDOWS:
        day[f"taker_{w}d"] = day["taker_raw"].rolling(w, min_periods=max(2, w//3)).mean()
    return day.reindex(calendar)


def load_panel():
    """28종목 패널 구성: funding/basis + activity taker ratios."""
    frames = {}
    for b in SYM28:
        fr = load_joint(b)                     # f_avg, mom30, p_open, p_vol, close, r_*, calendar
        tr = build_taker_ratios(b, fr.index)
        fr = fr.join(tr, how="left")
        # 잔차: 각 통제 세트별
        for tag, ctrls in CONTROL_SETS.items():
            if not ctrls:
                fr[f"taker_7d_resid_{tag}"] = fr["taker_7d"]
            else:
                fr[f"taker_7d_resid_{tag}"] = rolling_oos_resid(
                    fr["taker_7d"].to_numpy(float),
                    [fr[c].to_numpy(float) for c in ctrls])
        fr["symbol"] = b
        frames[b] = fr
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    full["year"] = full["date"].dt.year
    return full, frames


def date_cs_ic(df, feat, h, min_assets=MINASSETS):
    ics = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[feat, h])
        if len(s) < min_assets:
            continue
        ic = stats.spearmanr(s[feat], s[h]).statistic
        if np.isfinite(ic):
            ics.append(ic)
    if len(ics) < 10:
        return {"n_dates": len(ics), "mean_ic": None, "t": None, "frac_pos": None, "median_ic": None}
    ics = np.array(ics, float)
    t = ics.mean() / (ics.std(ddof=1) / np.sqrt(len(ics)))
    return {"n_dates": len(ics), "mean_ic": round(float(ics.mean()), 6),
            "t": round(float(t), 3), "frac_pos": round(float((ics > 0).mean()), 4),
            "median_ic": round(float(np.median(ics)), 6)}


def q5q1_spread(df, feat, h):
    """date 내 Q5(상위 20%) - Q1(하위 20%) forward return, 일자별 평균 → t."""
    daily_spread = []
    for d, sub in df.groupby("date"):
        s = sub.dropna(subset=[feat, h])
        if len(s) < 5:
            continue
        q = s[feat].quantile([0.2, 0.8])
        q1 = s.loc[s[feat] <= q[0.2], h].mean()
        q5 = s.loc[s[feat] >= q[0.8], h].mean()
        if np.isfinite(q1) and np.isfinite(q5):
            daily_spread.append(q5 - q1)
    if len(daily_spread) < 10:
        return {"n_dates": len(daily_spread), "mean": None, "t": None}
    ds = np.array(daily_spread, float)
    t = ds.mean() / (ds.std(ddof=1) / np.sqrt(len(ds)))
    return {"n_dates": len(ds), "mean": round(float(ds.mean()), 6), "t": round(float(t), 3)}


def monotonicity_check(df, feat, h):
    """pooled asset 내 decile D1~D10 평균 수익률."""
    out = {}
    for b in SYM28:
        s = df[df["symbol"] == b].dropna(subset=[feat, h]).copy()
        if len(s) < 10:
            continue
        s["_dec"] = decile_rank(s[feat])
        means = s.groupby("_dec")[h].mean()
        out[b] = {int(k): round(float(v), 6) for k, v in means.items()}
    # pooled
    df2 = df.dropna(subset=[feat, h]).copy()
    for b in SYM28:
        m = df2["symbol"] == b
        v = df2.loc[m & df2[feat].notna(), feat].notna()
        df2.loc[m & v, "_dec"] = decile_rank(df2.loc[m & v, feat])
    pooled_means = df2.dropna(subset=["_dec", h]).groupby("_dec")[h].mean()
    out["pooled"] = {int(k): round(float(v), 6) for k, v in pooled_means.items()}
    out["pooled_spearman"] = round(float(stats.spearmanr(df2["_dec"].dropna(), df2.loc[df2["_dec"].notna(), h]).statistic), 4)
    return out


def main():
    full, frames = load_panel()

    # ZEC 제외 버전
    full_nozec = full[full["symbol"] != "ZEC"].copy()

    out = {"design": {
        "source": "Step 23 activity 1h + funding/basis (Step14/19)",
        "alignment": "KST daily, feature(d) 확정된 상태에서 r_H(d) 예측, no lookahead",
        "windows_tested": WINDOWS,
        "control_sets": list(CONTROL_SETS.keys()),
        "horizons": HORS,
        "universe": SYM28,
        "exclude_test": "ZEC",
    }}

    # 1) ZEC LOO 비교: 28종 vs 27종(ZEC 제외) — pooled r7 decile & date-CS
    out["zec_loo"] = {}
    for label, df in [("all28", full), ("nozec27", full_nozec)]:
        out["zec_loo"][label] = {
            "decile_r7": spread(df, "taker_7d", "r_7"),
            "date_cs_r7": date_cs_ic(df, "taker_7d", "r_7"),
            "q5q1_r7": q5q1_spread(df, "taker_7d", "r_7"),
            "monotonicity_r7": monotonicity_check(df, "taker_7d", "r_7"),
        }

    # 2) 기간별 (연도별 r7 decile)
    out["by_year_r7"] = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        out["by_year_r7"][int(y)] = {
            "decile": spread(ys, "taker_7d", "r_7"),
            "date_cs": date_cs_ic(ys, "taker_7d", "r_7"),
            "q5q1": q5q1_spread(ys, "taker_7d", "r_7"),
        }
        # nozec
        ys2 = full_nozec[full_nozec["year"] == y]
        out["by_year_r7"][int(y)]["nozec"] = spread(ys2, "taker_7d", "r_7")

    # 3) 윈도우별 (raw, all28 & nozec)
    out["by_window"] = {}
    for w in WINDOWS:
        feat = f"taker_{w}d"
        out["by_window"][feat] = {
            "all28": {
                "decile_r7": spread(full, feat, "r_7"),
                "date_cs_r7": date_cs_ic(full, feat, "r_7"),
                "q5q1_r7": q5q1_spread(full, feat, "r_7"),
                "monotonicity_r7": monotonicity_check(full, feat, "r_7"),
            },
            "nozec27": {
                "decile_r7": spread(full_nozec, feat, "r_7"),
                "date_cs_r7": date_cs_ic(full_nozec, feat, "r_7"),
            },
        }

    # 4) 단계적 통제 (taker_7d residual, r7)
    out["control_ladder"] = {}
    for tag, _ in CONTROL_SETS.items():
        rc = f"taker_7d_resid_{tag}"
        out["control_ladder"][tag] = {
            "all28": {
                "decile_r7": spread(full, rc, "r_7"),
                "date_cs_r7": date_cs_ic(full, rc, "r_7"),
                "q5q1_r7": q5q1_spread(full, rc, "r_7"),
            },
            "nozec27": {
                "decile_r7": spread(full_nozec, rc, "r_7"),
                "date_cs_r7": date_cs_ic(full_nozec, rc, "r_7"),
                "q5q1_r7": q5q1_spread(full_nozec, rc, "r_7"),
            }
        }

    # 5) 핵심 비교: ZEC 제외 + 통제 후 r7 t-stat 요약
    core = {}
    for tag in CONTROL_SETS:
        all_t = out["control_ladder"][tag]["all28"]["decile_r7"]["t"]
        noz_t = out["control_ladder"][tag]["nozec27"]["decile_r7"]["t"]
        core[tag] = {"all28_t": all_t, "nozec27_t": noz_t,
                     "delta_t": round((all_t or 0) - (noz_t or 0), 3)}
    out["core_comparison_r7_t"] = core

    # 6) 경제적 크기: r7 per-unit taker_ratio_7d (pooled OLS coeff)
    sub = full.dropna(subset=["taker_7d", "r_7"])
    x = sub["taker_7d"].to_numpy(float)
    y = sub["r_7"].to_numpy(float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() > 10:
        b1 = np.polyfit(x[ok], y[ok], 1)[0]
        out["economic_magnitude"] = {"ols_slope_per_unit": round(float(b1), 6),
                                     "implied_10pct_change_r7": round(float(b1 * 0.10), 6)}
    else:
        out["economic_magnitude"] = {}

    # 7) 다중검정 노트
    n_tests = len(WINDOWS) * len(CONTROL_SETS) * len(SYM28) * len(HORS)  # 대략
    out["multiple_testing_note"] = (
        f"windows={len(WINDOWS)} controls={len(CONTROL_SETS)} symbols={len(SYM28)} "
        f"horizons={len(HORS)} ≈ {len(WINDOWS)*len(CONTROL_SETS)} independent window/control "
        "combinations. No formal correction applied; report all t-stats explicitly."
    )

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # 콘솔 요약
    print("=== taker_ratio_7 robustness check ===")
    print("\n[1] ZEC LOO r7:")
    for label in ["all28", "nozec27"]:
        d = out["zec_loo"][label]["decile_r7"]
        print(f"  {label}: Δ={d['D1_minus_D10']:+.5f} t={d['t']} nD1={d['n_D1']}")

    print("\n[2] 연도별 r7 Δ(t)  (all28 / nozec):")
    for y, v in out["by_year_r7"].items():
        a = v["decile"]; nz = v.get("nozec", {})
        print(f"  {y}: all Δ={a['D1_minus_D10']:+.5f}(t{a['t']})  nozec Δ={nz.get('D1_minus_D10','NA')} (t{nz.get('t','NA')})")

    print("\n[3] 윈도우별 r7 Δ(t)  (all28 / nozec):")
    for feat, v in out["by_window"].items():
        a = v["all28"]["decile_r7"]; nz = v["nozec27"]["decile_r7"]
        print(f"  {feat:10s} all Δ={a['D1_minus_D10']:+.5f}(t{a['t']})  nozec Δ={nz['D1_minus_D10']:+.5f}(t{nz['t']})")

    print("\n[4] 통제 래더 r7 Δ(t)  (all28 / nozec):")
    for tag, v in out["control_ladder"].items():
        a = v["all28"]["decile_r7"]; nz = v["nozec27"]["decile_r7"]
        print(f"  {tag:16s} all Δ={a['D1_minus_D10']:+.5f}(t{a['t']})  nozec Δ={nz['D1_minus_D10']:+.5f}(t{nz['t']})")

    print("\n[5] 핵심 비교 (r7 t-stat):")
    for tag, v in core.items():
        print(f"  {tag:16s} all={v['all28_t']}  nozec={v['nozec27_t']}  Δt={v['delta_t']}")

    print("\n[6] 날짜-CS r7 (taker_7d):")
    dcs = out["zec_loo"]["all28"]["date_cs_r7"]
    print(f"  all28: mean_ic={dcs['mean_ic']:+.4f} t={dcs['t']} pos={dcs['frac_pos']:.2f}")
    dcs2 = out["zec_loo"]["nozec27"]["date_cs_r7"]
    print(f"  nozec: mean_ic={dcs2['mean_ic']:+.4f} t={dcs2['t']} pos={dcs2['frac_pos']:.2f}")

    print("\n[7] Q5-Q1 r7 (taker_7d):")
    for label in ["all28", "nozec27"]:
        q = out["zec_loo"][label]["q5q1_r7"]
        print(f"  {label}: mean={q['mean']:+.5f} t={q['t']}")

    if out["economic_magnitude"]:
        em = out["economic_magnitude"]
        print(f"\n[8] 경제적 크기: slope={em['ols_slope_per_unit']:.6f} per 1.0 taker_ratio "
              f"=> 0.10 change ≈ {em['implied_10pct_change_r7']:.5f} r7")

    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()