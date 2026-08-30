#!/usr/bin/env python
"""Step 19 — Funding × Premium/Basis 독립 정보 검증.

Funding Rate와 Premium(mark/index 프리미엄)이 중복 정보인지, funding이 설명하지
못하는 premium 정보가 미래 수익률과 관련되는지 검증한다.

- 데이터: data/crypto/funding(28), data/crypto/basis(28: 8h + 1h).
- 시간 정렬: funding UTC ms → +9h → KST 날짜 d (Step 14 동일). premium 8h bucket도
  같은 규칙으로 KST 날짜 d에 매핑 (bucket 시작이 정확히 00/08/16Z).
- forward return: r_H(d) = close(d+H)/close(d)-1 (KST 달력).
  close(d) = basis 1h mark_close 중 KST 24:00(=UTC 15:00)에 마감되는 값
  (hour bucket start = 14:00 UTC). 모든 28종목 동일 소스(USDT perp mark).
  core13 종목에는 KRW 일봉 종가 대체 일치 로버스트 체크를 별도 출력.
  (Step 14/15의 KRW-기반 상관과 소스 차이가 통계를 크게 바꾸지 않음을 확인.)

Feature:
- f_avg, f_z     : Step 14 복제
- p_open         : day d 의 8h premium_open 평균 (KST-day 8h bucket 3건, 전부 close(d) 이전 결정)
- p_close        : 8h premium_close 평균. 단 08Z-시작 bucket(close 16Z=다음날 01:00 KST) 제외 — no lookahead
- p_mid          : (open+close)/2 평균 (동일 예외)
- p_vol          : 1h premium(mark_close/index_close-1)의 day d 내 표본 std
                   (16Z(d-1)..14Z(d) 시작 bucket — 전부 마감 ≤ 24:00 KST d)
- mom30          : close(d)/close(d-30)-1 (Step 14/15 동일)

절차: A 단독 / B funding 통제 / C momentum 통제 / D funding+momentum 통제 /
      E 결합 설명력. 백테스트·최적화·S2·데이터 수정 없음.
모든 residual: 자산별 rolling OLS, 과거 60일(t-60..t-1)만 추정 → 1-step OOS (Step15 동일).
데시일 스프레드: 자산 내 데시일 D1(낮은값)≠D10(높은값), Welch t (Step 14/15 동일).
출력: findings/funding-premium-independence-2026-08.json + MD.
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
from funding_predictive_check import BASES, HORIZONS, welch, decile_rank  # noqa: E402

FUNDING = HERE / "data" / "crypto" / "funding"
BASIS = HERE / "data" / "crypto" / "basis"
BASIS1H = BASIS / "1h"
DAILY = HERE / "data" / "crypto" / "daily"
OUT_JSON = HERE / "findings" / "funding-premium-independence-2026-08.json"
OUT_MD = HERE / "findings" / "funding-premium-independence-2026-08.md"

NEW14 = ["1000PEPE", "1000SHIB", "AAVE", "APT", "BCH", "BNB", "FIL", "INJ",
         "LTC", "SUI", "TRX", "WLD", "XMR", "ZEC"]
ARB = "ARB"
ALL = BASES + NEW14 + [ARB]  # 28

WINDOW = 60
MINOBS = 30
MINVOL = 12
MINASSETS = 5


# ---------------------------------------------------------------------------
def load_joint(base):
    """자산별 KST 데일리 패널 (funding + premium + mom + fwd returns)."""
    f = pd.read_parquet(FUNDING / f"{base}USDT.parquet")
    b8 = pd.read_parquet(BASIS / f"{base}USDT.parquet")
    b1 = pd.read_parquet(BASIS1H / f"{base}USDT_1h.parquet")

    # 1) funding → KST 날짜 (Step 14 동일)
    kst_dates = f.index.tz_convert("Asia/Seoul").normalize().tz_localize(None)
    fin = f.groupby(kst_dates).agg(f_avg=("fundingRate", "mean"),
                                   f_sum=("fundingRate", "sum"),
                                   nfund=("fundingRate", "size"))
    fin.index.name = "date"

    # 2) premium 8h → KST 날짜 (wall clock of UTC+9h)
    kst8 = (b8["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None)
    k8d = kst8.dt.normalize()
    h8 = b8["time"].dt.hour
    prem = b8.assign(_d=k8d)
    g = prem.groupby("_d")
    p_open = g["premium_open"].mean()
    tmp_close = prem["premium_close"].where(h8 != 8)          # 08Z bucket 제외
    p_mid = ((prem["premium_open"] + tmp_close.astype(float)) / 2).groupby(prem["_d"]).mean()
    p_close = tmp_close.groupby(prem["_d"]).mean()
    nprem = g.size()
    df_p = pd.DataFrame({"p_open": p_open, "p_close": p_close, "p_mid": p_mid, "nprem": nprem})
    df_p.index.name = "date"

    # 3) p_vol: 1h premium std (KST day d 내, 마감 ≤ 24:00 KST d)
    hp = b1["mark_close"] / b1["index_close"] - 1.0
    k1d = (b1["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    hv = pd.DataFrame({"_p": hp, "_d": k1d}).dropna(subset=["_p"])
    p_vol = hv.groupby("_d")["_p"].agg(lambda s: float(np.std(s)) if len(s) >= MINVOL else np.nan)
    p_vol.name = "p_vol"
    df_p = df_p.join(p_vol)

    # 4) 데일리 종가: KST 24:00 = UTC 15:00 = 1h bucket start 14:00 UTC
    m14 = b1["time"].dt.hour == 14
    d14 = b1.loc[m14, ["time", "mark_close"]].copy()
    d14["_date"] = d14["time"].dt.tz_localize(None).dt.normalize()
    close = d14.groupby("_date")["mark_close"].last()
    close.index.name = "date"

    # 5) 연속 KST 달력 위에 정렬
    calendar = pd.date_range(fin.index.min(), close.index.max(), freq="D", name="date")
    df = pd.DataFrame(index=calendar)
    df["f_avg"] = fin["f_avg"].reindex(calendar)
    df["f_sum"] = fin["f_sum"].reindex(calendar)
    df["nfund"] = fin["nfund"].reindex(calendar)
    for c in ["p_open", "p_close", "p_mid", "p_vol"]:
        df[c] = df_p[c].reindex(calendar)
    df["close"] = close.reindex(calendar)

    # 6) 파생 피처 (미래 정보 미사용)
    rmean = df["f_avg"].rolling(30, min_periods=20).mean().shift(1)
    rstd = df["f_avg"].rolling(30, min_periods=20).std().shift(1)
    df["f_z"] = (df["f_avg"] - rmean) / rstd
    df["mom30"] = df["close"] / df["close"].shift(30) - 1.0
    for hn, h in HORIZONS.items():
        df[hn] = df["close"].shift(-h) / df["close"] - 1.0
    df["symbol"] = base
    return df


def rolling_oos_resid(y, xs, window=WINDOW, minobs=MINOBS):
    """과거 창 t-60..t-1 OLS(y~1+x1+..) → t 적용 1-step OOS 잔차. 미래 미사용."""
    y = np.asarray(y, float)
    xs = [np.asarray(x, float) for x in xs]
    n = len(y)
    resid = np.full(n, np.nan)
    for t in range(window, n):
        ys = y[t - window:t]
        xsm = [x[t - window:t] for x in xs]
        ok = np.isfinite(ys)
        for x in xsm:
            ok &= np.isfinite(x)
        if ok.sum() < minobs:
            continue
        if not np.isfinite(y[t]) or any(not np.isfinite(x[t]) for x in xs):
            continue
        X = np.column_stack([np.ones(ok.sum())] + [x[ok] for x in xsm])
        b, *_ = np.linalg.lstsq(X, ys[ok], rcond=None)
        if not np.all(np.isfinite(b)):
            continue
        xr = np.concatenate([[1.0]] + [np.asarray(x[t], float).reshape(-1) for x in xs])
        resid[t] = y[t] - float(b @ xr)
    return resid


def corr2(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 30:
        return np.nan, np.nan, int(ok.sum()), np.nan
    pr, pp = stats.pearsonr(x[ok], y[ok])
    sr, sp = stats.spearmanr(x[ok], y[ok])
    return float(pr), float(sr), int(ok.sum()), float(pp)


def asset_decile(sub, feat):
    s = sub.dropna(subset=[feat]).copy()
    s["_dec"] = np.nan
    for b in s["symbol"].unique():
        m = s["symbol"] == b
        s.loc[m, "_dec"] = decile_rank(s.loc[m, feat])
    return s


def spread(sub, feat, h):
    s = asset_decile(sub, feat).dropna(subset=["_dec", h, "symbol"])
    if len(s) == 0:
        return {"D1_mean": None, "D10_mean": None, "D1_minus_D10": None,
                "t": None, "n_D1": 0, "n_D10": 0}
    d1 = s.loc[s["_dec"] == 1, h].to_numpy(float)
    d10 = s.loc[s["_dec"] == 10, h].to_numpy(float)
    t, p, delta = welch(d1, d10)
    return {
        "D1_mean": round(float(d1.mean()), 6) if len(d1) else None,
        "D10_mean": round(float(d10.mean()), 6) if len(d10) else None,
        "D1_minus_D10": (round(delta, 6) if not np.isnan(delta) else None),
        "t": (round(t, 3) if not np.isnan(t) else None),
        "n_D1": int(len(d1)), "n_D10": int(len(d10)),
    }


def pooled_cross(df, xcol, ycols):
    x = df[xcol].to_numpy(float)
    r = {}
    for yc in ycols:
        y = df[yc].to_numpy(float)
        pr, sr, n, pp = corr2(x, y)
        r[yc] = {"pearson": pr, "spearman": sr, "n": n, "p": pp}
    return r


def within_demean(df, cols):
    out = df.copy()
    for c in cols:
        out[c] = out[c] - out.groupby("date")[c].transform("mean")
    return out


def sub_by_date(df, min_assets=MINASSETS):
    cnt = df.groupby("date")["symbol"].transform("size")
    return df[cnt >= min_assets]


def resid_block(full, col, label):
    out = {"label": label,
           "pooled_decile": {h: spread(full, col, h) for h in HORIZONS},
           "corr": pooled_cross(full, col, list(HORIZONS))}
    import statsmodels.formula.api as smf
    out["partial_reg_symbol_fe"] = {}
    for h in HORIZONS:
        sub = full.dropna(subset=["f_avg", "p_open", "mom30", col, h]).copy()
        sub["_pres"] = sub[col]
        sub["_mom"] = sub["mom30"]
        m = smf.ols(f"{h} ~ _pres + _mom + f_avg + C(symbol)", data=sub).fit()
        m2 = smf.ols(f"{h} ~ _pres + C(symbol)", data=sub).fit()
        out["partial_reg_symbol_fe"][h] = {
            "n": int(len(sub)),
            "resid_t_with_ctrl": round(float(m.tvalues["_pres"]), 3),
            "resid_t_no_ctrl": round(float(m2.tvalues["_pres"]), 3),
        }
    out["by_group_r7"] = {}
    for g, syms in [("core13", BASES), ("orig14", BASES + [ARB]), ("new14", NEW14), ("all", ALL)]:
        out["by_group_r7"][g] = spread(full[full["symbol"].isin(syms)], col, "r_7")
    out["by_year_r7"] = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        out["by_year_r7"][int(y)] = spread(ys, col, "r_7")
    out["by_asset_r7"] = {b: spread(full[full["symbol"] == b], col, "r_7") for b in ALL}
    return out


def joint_block(full_e):
    """날짜-demean within OLS: r ~ (f | p | fp | fpm)."""
    out = {}
    for h in HORIZONS:
        sub = full_e.dropna(subset=["f_avg", "p_open", "mom30", h])
        dm = within_demean(sub, ["f_avg", "p_open", "mom30", h])
        Y = dm[h].to_numpy(float)

        def fit(cols):
            X = np.column_stack([dm[c].to_numpy(float) for c in cols])
            b, *_ = np.linalg.lstsq(X, Y, rcond=None)
            pred = X @ b
            res = Y - pred
            r2 = 1 - np.sum(res ** 2) / np.sum(Y ** 2)
            k = X.shape[1]
            n_ = len(Y)
            sigma2 = np.sum(res ** 2) / (n_ - k)
            cov = sigma2 * np.linalg.inv(X.T @ X)
            se = np.sqrt(np.abs(np.diag(cov)))
            t = b / se
            return r2, t, b

        r2f, tf, _ = fit(["f_avg"])
        r2p, tp, _ = fit(["p_open"])
        r2fp, tfp, _ = fit(["f_avg", "p_open"])
        r2fpm, tpm, bpm = fit(["f_avg", "p_open", "mom30"])
        out[h] = {
            "n": int(len(sub)),
            "n_dates": int(sub["date"].nunique()),
            "r2_f": round(float(r2f), 5), "r2_p": round(float(r2p), 5),
            "r2_fp": round(float(r2fp), 5), "r2_fpm": round(float(r2fpm), 5),
            "dR2_p_f": round(float(r2fp - r2f), 5),
            "dR2_f_p": round(float(r2fp - r2p), 5),
            "dR2_p_fpm": round(float(r2fpm - r2f), 5),
            "t_f": round(float(tf[0]), 3),
            "t_p": round(float(tp[0]), 3),
            "t_f_in_fp": round(float(tfp[0]), 3),
            "t_p_in_fp": round(float(tfp[1]), 3),
            "coef_p_fpm": round(float(bpm[1]), 8),
            "t_p_fpm": round(float(tpm[1]), 3),
            "t_mom_fpm": round(float(tpm[2]), 3),
        }
    return out


# ---------------------------------------------------------------------------
def main():
    frames = {b: load_joint(b) for b in ALL}
    for b in ALL:
        fr = frames[b]
        y = fr["p_open"].to_numpy(float)
        fa = fr["f_avg"].to_numpy(float)
        mo = fr["mom30"].to_numpy(float)
        fr["p_fresid"] = rolling_oos_resid(y, [fa])
        fr["p_mresid"] = rolling_oos_resid(y, [mo])
        fr["p_fmresid"] = rolling_oos_resid(y, [fa, mo])

    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    full["year"] = full["date"].dt.year

    out = {"design": {
        "alignment": ("funding/premium을 UTC→+9h→KST 날짜 d로 정렬; "
                      "r_H(d)=close(d+H)/close(d)-1, close=KST 24:00 마감 mark_close"
                      "(1h bucket start 14:00 UTC). "),
        "forward_return_close_source": "Binance USDT perp mark_close (28종목 공통). core13은 KRW 일봉과 로버스트 비교.",
        "groups": {"core13": BASES, "orig14": BASES + [ARB], "new14": NEW14, "all": ALL},
        "premium_features": {
            "p_open": "day d 내 8h premium_open 평균(3건, close(d) 이전 결정)",
            "p_close": "8h premium_close 평균 (08Z 시작 bucket 제외, 마감이 close(d) 이후이므로)",
            "p_mid": "(open+close)/2 평균 (동일 예외)",
            "p_vol": "1h premium std (16Z(d-1)..14Z(d) 시작 bucket, 마감 ≤ 24:00 KST d)",
            "basis_marker": "basis endpoint IP밴으로 NaN — 미사용, 복구/0대체 않음",
        },
        "resid": "rolling OLS p~1+.. on t-60..t-1 → 1-step OOS, minobs=30 (Step15 동일)",
        "forbidden": "백테스트/grid search/임계값 최적화/S2·데이터 수정 없음",
    }}

    # ---------- 0) feature 중복도 ----------
    overlap = {}
    for a, b in [("p_open", "f_avg"), ("p_open", "mom30"), ("p_close", "f_avg"),
                 ("p_vol", "f_avg"), ("p_open", "f_z"), ("f_avg", "mom30")]:
        pr, sr, n, pp = corr2(full[a].to_numpy(float), full[b].to_numpy(float))
        overlap[f"{a}~{b}"] = {"pear": pr, "spear": sr, "n": n, "p": pp}
    out["overlap_feature"] = overlap

    # ---------- A) 단독 효과 ----------
    FEAT_A = ["f_avg", "p_open", "p_close", "p_mid", "p_vol"]
    desc_a = {}
    for f in FEAT_A:
        desc_a[f] = {
            "pooled": {h: spread(full, f, h) for h in HORIZONS},
            "by_group": {},
            "btc": {h: spread(full[full["symbol"] == "BTC"], f, h) for h in HORIZONS},
            "eth": {h: spread(full[full["symbol"] == "ETH"], f, h) for h in HORIZONS},
        }
        for g, syms in [("core13", BASES), ("orig14", BASES + [ARB]), ("new14", NEW14)]:
            desc_a[f]["by_group"][g] = {h: spread(full[full["symbol"].isin(syms)], f, h)
                                        for h in HORIZONS}
    out["a_single"] = {
        "decile": desc_a,
        "corr": {f: pooled_cross(full, f, list(HORIZONS)) for f in FEAT_A},
        "r2_f_compare": None,
    }

    # ---------- B/C/D) residualize ----------
    out["b_funding_control"] = resid_block(full, "p_fresid", "p_open → (funding) resid")
    out["c_momentum_control"] = resid_block(full, "p_mresid", "p_open → (mom) resid")
    out["d_both_control"] = resid_block(full, "p_fmresid", "p_open → (funding+mom) resid")

    # ---------- E) 결합 정보 (date-demean) ----------
    full_e = sub_by_date(full).dropna(subset=["f_avg", "p_open", "mom30", "date"])
    out["e_joint"] = joint_block(full_e)
    import statsmodels.formula.api as smf
    out["e_symbol_fe_partial"] = {}
    for h in HORIZONS:
        sub = full.dropna(subset=["f_avg", "p_open", "mom30", h]).copy()
        sub["_mom"] = sub["mom30"]
        m = smf.ols(f"{h} ~ f_avg + p_open + _mom + C(symbol)", data=sub).fit()
        out["e_symbol_fe_partial"][h] = {
            "n": int(len(sub)),
            "f_avg_t": round(float(m.tvalues["f_avg"]), 3),
            "p_open_t": round(float(m.tvalues["p_open"]), 3),
            "mom_t": round(float(m.tvalues["_mom"]), 3),
            "r2": round(float(m.rsquared), 4),
        }

    # ---------- 그룹/연도/자산 (r7 중심) ----------
    out["by_group_r7"] = {}
    for g, syms in [("core13", BASES), ("orig14", BASES + [ARB]), ("new14", NEW14), ("all", ALL)]:
        sub = full[full["symbol"].isin(syms)]
        out["by_group_r7"][g] = {
            "p_open": spread(sub, "p_open", "r_7"),
            "f_avg": spread(sub, "f_avg", "r_7"),
            "p_fmresid": spread(sub, "p_fmresid", "r_7"),
            "p_mresid": spread(sub, "p_mresid", "r_7"),
        }
    out["by_asset_r7"] = {b: {
        "p_open": spread(frames[b], "p_open", "r_7"),
        "f_avg": spread(frames[b], "f_avg", "r_7"),
        "p_fmresid": spread(frames[b], "p_fmresid", "r_7"),
        "n_days": int(frames[b]["p_open"].notna().sum()),
        "first": str(frames[b].index.min().date()),
        "last": str(frames[b].index.max().date()),
    } for b in ALL}
    out["by_year_r7"] = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        out["by_year_r7"][int(y)] = {
            "n": int(len(ys)),
            "p_open": spread(ys, "p_open", "r_7"),
            "f_avg": spread(ys, "f_avg", "r_7"),
            "p_fmresid": spread(ys, "p_fmresid", "r_7"),
        }

    # ---------- 로버스트: core13 KRW 일봉 vs USDT mark ----------
    out["robust_core13_krw_vs_usdt"] = {}
    for b in BASES:
        dk = pd.read_parquet(DAILY / f"KRW-{b}.parquet")
        du = frames[b]["close"].dropna()
        rk = dk["close"].reindex(du.index)
        ok = rk.notna() & du.notna() & frames[b]["f_avg"].notna()
        if ok.sum() < 30:
            continue
        c1, _, _, _ = corr2(frames[b].loc[ok, "f_avg"].to_numpy(float),
                            (du[ok].shift(-1) / du[ok] - 1).to_numpy(float))
        c2, _, _, _ = corr2(frames[b].loc[ok, "f_avg"].to_numpy(float),
                            (rk[ok].shift(-1) / rk[ok] - 1).to_numpy(float))
        out["robust_core13_krw_vs_usdt"][b] = {
            "corr_f_usdt_r1": c1, "corr_f_krw_r1": c2, "n": int(ok.sum())}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- 콘솔 요약 ----------
    print("=== Step 19 funding × premium independence ===")
    print("[0] overlap")
    for k, v in overlap.items():
        print(f"  {k:16s} pear={v['pear']:+.4f} spear={v['spear']:+.4f} n={v['n']}")
    print("\n[A] 단독 데시일 D1-D10 스프레드 (t)")
    for f in FEAT_A:
        for h in HORIZONS:
            d = desc_a[f]["pooled"][h]
            print(f"  {f:8s} {h}: Δ={d['D1_minus_D10']:+.5f} t={d['t']} (nD1={d['n_D1']})")
    print("\n[B/C/D] p_open 잔차 데시일 스프레드 (t)")
    for tag, key in [("funding", "b_funding_control"),
                     ("mom", "c_momentum_control"),
                     ("fund+mom", "d_both_control")]:
        blk = out[key]
        for h in HORIZONS:
            d = blk["pooled_decile"][h]
            print(f"  {tag:8s} {h}: Δ={d['D1_minus_D10']:+.5f} t={d['t']} nD1={d['n_D1']}")
        cr = blk["corr"]
        print("        corr:", " | ".join(f"{h}:{cr[h]['pearson']:+.4f}" for h in cr))
    print("\n[E] 결합 (date-demean)")
    for h in HORIZONS:
        j = out["e_joint"][h]
        print(f"  {h}: r2_f={j['r2_f']:.4f} r2_p={j['r2_p']:.4f} r2_fp={j['r2_fp']:.4f} r2_fpm={j['r2_fpm']:.4f} "
              f"Δ(p|f)={j['dR2_p_f']:+.4f} Δ(f|p)={j['dR2_f_p']:+.4f} t_p_fpm={j['t_p_fpm']} n={j['n']}")
    print("\n[그룹 r7] p_open Δ(t) | fmresid Δ(t)")
    for g, v in out["by_group_r7"].items():
        print(f"  {g:8s} p_open Δ={v['p_open']['D1_minus_D10']:+.5f}(t{v['p_open']['t']}) | "
              f"fmresid Δ={v['p_fmresid']['D1_minus_D10']:+.5f}(t{v['p_fmresid']['t']})")
    print("\n[연도 r7] p_open Δ(t) | fmresid Δ(t)")
    for y, v in out["by_year_r7"].items():
        print(f"  {y}: p_open Δ={v['p_open']['D1_minus_D10']:+.5f}(t{v['p_open']['t']}) | "
              f"fmresid Δ={v['p_fmresid']['D1_minus_D10']:+.5f}(t{v['p_fmresid']['t']}) nD1={v['p_open']['n_D1']}")
    print("\n[자산 r7] p_open Δ(t) | f_avg Δ(t) | fmresid Δ(t)")
    for b in ALL:
        v = out["by_asset_r7"][b]
        print(f"  {b:10s} p_open Δ={v['p_open']['D1_minus_D10']:+.5f}(t{v['p_open']['t']}) | "
              f"f_avg Δ={v['f_avg']['D1_minus_D10']:+.5f}(t{v['f_avg']['t']}) | "
              f"fmresid Δ={v['p_fmresid']['D1_minus_D10']:+.5f}(t{v['p_fmresid']['t']}) nDay={v['n_days']}")
    print("\n[로버스트] core13 f_avg→USDTr1 corr (USDT mark vs KRW close)")
    rb = out["robust_core13_krw_vs_usdt"]
    for b, v in rb.items():
        print(f"  {b:6s} usdt={v['corr_f_usdt_r1']:+.4f}  krw={v['corr_f_krw_r1']:+.4f}  n={v['n']}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()