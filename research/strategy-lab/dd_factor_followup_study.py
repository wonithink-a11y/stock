#!/usr/bin/env python
"""Drawdown factor 후속 검증 3종 — ma_distance_drawdown_study.py의 A등급 판정
(dd_from_high_252/120, 6M 한정)에 대한 독립성·타이밍·조건부 강도 확인.

우선순위 ① 정보 중복: dd_from_high_252/120이 Momentum12M(raw12m =
close/close.shift(252)-1, momentum_decile_analysis.py VARIANTS와 동일 정의)의
재포장인지 확인한다. 월간 리밸런스 시점 cross-sectional 랭크상관 + 직교화 IC
(날짜별 랭크 회귀 잔차의 forward-return Spearman, 양방향).

우선순위 ② horizon 분해: 효과가 왜 6M에서만 나오는지 — fwd_d40/d80/d160을
추가해 IC·decile spread의 horizon 궤적을 확인하고, JT식 skip-1m 변형
(dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1, 신호는 t까지 데이터,
모멘텀 연구의 skip1m_12_1과 같은 관례)로 최근 1개월 성분의 역할을 본다.

우선순위 ③ 유동성 조건부: liq20 = 20D 평균 거래대금(PIT rolling) tercile별로
dd_252의 D10-D1 monthly spread(fwd_d120)를 재측정. 절대 컷(liq20>=1억원)도
함께 — PBR·LOWMOM60에서 반복된 "저유동성에서만 유효" 패턴 점검이 목적.

관례 재사용: macd_information_content_study.py / ma_distance_drawdown_study.py와
동일 (월초 리밸런스, 날짜별 qcut decile, daily Spearman IC, NW t).
PIT: 모든 feature는 t까지 데이터만 사용. d40/80/160은 행 기준 shift 재계산이라
패널 갭 종목(0.5%)에서 parquet 정의와 어긋날 수 있음(하단 caveats).
산출: reports/2026-08-26-dd-factor-followup/dd-followup-results.json
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-dd-factor-followup")

MIN_NAMES_PER_DATE = 30
NW_LAG_BY_HORIZON = {"fwd_d20": 2, "fwd_d40": 2, "fwd_d60": 3, "fwd_d80": 4,
                     "fwd_d120": 6, "fwd_d160": 8}
BASE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
EXTRA_HORIZONS = {"d40": 40, "d80": 80, "d160": 160}
DECOMP_HORIZONS = ["fwd_d20", "fwd_d40", "fwd_d60", "fwd_d80", "fwd_d120", "fwd_d160"]
DECOMP_FEATURES = {
    "dd_from_high_252": "close/max(close,252D) - 1",
    "dd_from_high_120": "close/max(close,120D) - 1",
    "dd_252_skip1m": "close[t-21]/max(close[t-252..t-21]) - 1",
    "mom252": "close/close[t-252] - 1 (raw12m)",
}
ABS_LIQ_CUT = 1e8  # 1억원, absolute_turnover_filter_validation.py의 컨벤션


def newey_west_t(x, lag):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return None
    e = x - x.mean()
    g0 = float(np.sum(e * e)) / n
    s = g0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        s += 2.0 * w * float(np.sum(e[l:] * e[:-l])) / n
    se = np.sqrt(max(s, 0.0) / n)
    return round(float(x.mean() / se), 3) if se > 0 else None


def naive_t(x):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 5:
        return None
    sd = x.std(ddof=1)
    return round(float(x.mean() / (sd / np.sqrt(len(x)))), 3) if sd > 0 else None


def compute_features(df):
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker", sort=False)["close"]
    for w in (60, 120, 252):
        hi = g.transform(lambda s: s.rolling(w, min_periods=w).max())
        df[f"dd_from_high_{w}"] = df["close"] / hi - 1.0
    df["mom252"] = df["close"] / g.transform(lambda s: s.shift(252)) - 1.0
    # skip-1m dd: 신호 창 [t-252 .. t-21], 모멘텀 연구 skip1m_12_1의 span과 동일
    lag_close = g.transform(lambda s: s.shift(21))
    df["dd_252_skip1m"] = lag_close / lag_close.rolling(232, min_periods=232).max() - 1.0
    df["liq20"] = df.groupby("ticker", sort=False)["total_amount"].transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    for h, n in EXTRA_HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s, n=n: s.shift(-n) / s - 1)
    return df


def integrity_check(df):
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    grp = df.groupby("ticker", sort=False)["close"]
    checks = {}
    for h in (20, 60, 120):
        own = grp.transform(lambda s, h=h: s.shift(-h) / s - 1)
        b = df[f"fwd_d{h}"]
        m = own.notna() & b.notna()
        diff = (own[m] - b[m]).abs()
        checks[f"d{h}"] = {
            "maxAbsDiff": round(float(diff.max()), 8),
            "shareRowsMismatched": round(float((diff > 1e-9).mean()), 6),
            "p99AbsDiff": round(float(diff.quantile(0.99)), 8),
            "note": "panel-gap rows only; parquet fwd (full session index) is authoritative and used throughout",
        }
    return checks


def monthly_rebalance_dates(dates):
    out, seen = [], set()
    for d in sorted(dates.unique()):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return set(out)


def summarize(recs):
    """[(date, value)] -> mean/std/t/share/yearly."""
    if not recs:
        return {"n": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean() / (sd / np.sqrt(len(vals)))) if sd > 0 else None
    by_year = {}
    for d, v in recs:
        by_year.setdefault(d[:4], []).append(v)
    yearly = {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())}
    return {"n": len(vals), "mean": round(float(vals.mean()), 5), "std": round(sd, 5),
            "tNaive": round(t, 3) if t is not None else None,
            "sharePositive": round(float((vals > 0).mean()), 4), "yearlyMean": yearly}


def rank_corr_dd_vs_mom(df, rebal):
    out = {}
    for a, b in (("dd_from_high_252", "mom252"), ("dd_from_high_120", "mom252"),
                 ("dd_from_high_60", "mom252")):
        sub = df[df["date"].isin(rebal)][["date", a, b]].dropna()
        recs = []
        for d, gd in sub.groupby("date"):
            if len(gd) < MIN_NAMES_PER_DATE:
                continue
            r = spearmanr(gd[a].to_numpy(), gd[b].to_numpy())
            if not np.isnan(r.statistic):
                recs.append((d, float(r.statistic)))
        out[f"{a}_vs_{b}"] = summarize(recs)
        s = out[f"{a}_vs_{b}"]
        print(f"  {a} vs mom252: rho={s['mean']:+.4f} (t={s['tNaive']}, n={s['n']}, posShare={s['sharePositive']})")
    return out


def orth_ic(df, feat, ctrl, horizons):
    """날짜별 랭크 직교화: resid_rank(feat | ctrl)의 forward-return Spearman."""
    out = {}
    need = [feat, ctrl] + horizons
    arr = df[["date"] + need].dropna(subset=[feat, ctrl])
    for h in horizons:
        recs = []
        for d, gd in arr.groupby("date"):
            gg = gd[[feat, ctrl, h]].dropna()
            n = len(gg)
            if n < 50:
                continue
            rf = gg[feat].rank().to_numpy()
            rc = gg[ctrl].rank().to_numpy()
            vr = rc.var()
            if vr <= 0:
                continue
            beta = float(np.cov(rc, rf, bias=True)[0, 1] / vr)
            resid = rf - beta * rc
            r = spearmanr(resid, gg[h].to_numpy())
            if not np.isnan(r.statistic):
                recs.append((d, float(r.statistic)))
        key = f"{feat}|{ctrl}|{h}"
        out[key] = summarize(recs)
        s = out[key]
        print(f"  {key}: IC={s['mean']:+.5f} (t={s['tNaive']}, n={s['n']})")
    return out


def uncond_ic(df, feat, horizons):
    out = {}
    for h in horizons:
        recs = []
        arr = df[["date", feat, h]].dropna()
        for d, gd in arr.groupby("date"):
            if len(gd) < MIN_NAMES_PER_DATE:
                continue
            r = spearmanr(gd[feat].to_numpy(), gd[h].to_numpy())
            if not np.isnan(r.statistic):
                recs.append((d, float(r.statistic)))
        key = f"{feat}|{h}"
        out[key] = summarize(recs)
        s = out[key]
        print(f"  {key}: IC={s['mean']:+.5f} (t={s['tNaive']}, n={s['n']})")
    return out


def decile_spread(df, feat, h, rebal):
    """월간 리밸런스 날짜별 qcut decile -> D10-D1 spread 시계열 요약 (+decile means)."""
    sub = df[df["date"].isin(rebal)].dropna(subset=[feat, h]).copy()

    def _q(grp):
        if len(grp) < MIN_NAMES_PER_DATE:
            grp["decile"] = np.nan
            return grp
        grp["decile"] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
        return grp

    s = sub.groupby("date", group_keys=False).apply(_q)
    s = s.dropna(subset=["decile"])
    s["decile"] = s["decile"].astype(int)
    pooled_mean = s.groupby("decile")[h].mean()
    sp_pairs = []
    for d, gd in s.groupby("date"):
        top = gd[gd["decile"] == 10][h]
        bot = gd[gd["decile"] == 1][h]
        if len(top) and len(bot):
            sp_pairs.append((d, float(top.mean() - bot.mean())))
    sp = np.array([v for _, v in sp_pairs], dtype=float)
    by_year = {}
    for d, v in sp_pairs:
        by_year.setdefault(d[:4], []).append(v)
    return {
        "panelRows": int(len(s)),
        "pooledDecileMeans": {int(i): round(float(pooled_mean.get(i, np.nan)), 5) for i in range(1, 11)},
        "pooledD10minusD1": round(float(pooled_mean.get(10, np.nan) - pooled_mean.get(1, np.nan)), 5),
        "monthlySpreadMean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
        "monthlySpreadNWT": newey_west_t(sp, NW_LAG_BY_HORIZON[h]),
        "nMonths": int(len(sp)),
        "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())},
    }


def liquidity_conditional(df, feat, h, rebal):
    """liq20 tercile(날짜별 상대) + 절대컷 하위집합에서 dd_252 D10-D1 spread 재측정."""
    sub_all = df[df["date"].isin(rebal)].dropna(subset=[feat, h]).copy()
    out = {}

    def spread_within(sub, label):
        def _q(grp):
            if len(grp) < MIN_NAMES_PER_DATE:
                grp["decile"] = np.nan
                return grp
            grp["decile"] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp
        s = sub.groupby("date", group_keys=False).apply(_q).dropna(subset=["decile"])
        s["decile"] = s["decile"].astype(int)
        sp_pairs = []
        for d, gd in s.groupby("date"):
            top = gd[gd["decile"] == 10][h]
            bot = gd[gd["decile"] == 1][h]
            if len(top) and len(bot):
                sp_pairs.append((d, float(top.mean() - bot.mean())))
        sp = np.array([v for _, v in sp_pairs], dtype=float)
        by_year = {}
        for d, v in sp_pairs:
            by_year.setdefault(d[:4], []).append(v)
        out[label] = {
            "panelRows": int(len(s)),
            "medianLiq20": round(float(sub["liq20"].median()), 0) if "liq20" in sub else None,
            "monthlySpreadMean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
            "monthlySpreadNWT": newey_west_t(sp, NW_LAG_BY_HORIZON[h]),
            "nMonths": int(len(sp)),
            "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())},
        }
        o = out[label]
        print(f"  [{label}] rows={o['panelRows']}, spread={o['monthlySpreadMean']:+.5f}, "
              f"NWT={o['monthlySpreadNWT']}, nMonths={o['nMonths']}")

    def _terc(grp):
        if len(grp) < MIN_NAMES_PER_DATE * 3:
            grp["liq_tercile"] = np.nan
            return grp
        grp["liq_tercile"] = pd.qcut(grp["liq20"].rank(method="first"), 3, labels=[1, 2, 3])
        return grp

    sub = sub_all.dropna(subset=["liq20"]).copy()
    sub = sub.groupby("date", group_keys=False).apply(_terc)
    sub = sub.dropna(subset=["liq_tercile"])
    sub["liq_tercile"] = sub["liq_tercile"].astype(int)
    for lab, name in ((1, "lowLiqTercile"), (2, "midLiqTercile"), (3, "highLiqTercile")):
        spread_within(sub[sub["liq_tercile"] == lab], name)
    spread_within(sub_all[sub_all["liq20"] >= ABS_LIQ_CUT], "absLiqGte1e8")
    spread_within(sub_all, "allUniverse")
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 research dataset...")
    cols = ["ticker", "date", "close", "total_amount", "fwd_d20", "fwd_d60", "fwd_d120"]
    df = pd.read_parquet(DATA, columns=cols)
    n_dupes = int(df.duplicated(subset=["ticker", "date"]).sum())
    if n_dupes:
        df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    print(f"rows={len(df)}, tickers={df['ticker'].nunique()}, period={df['date'].min()}~{df['date'].max()}")

    print("Computing features + extra forward returns...")
    df = compute_features(df)
    integ = integrity_check(df)
    for k, v in integ.items():
        print(f"  integrity {k}: mismatchShare={v['shareRowsMismatched']}, p99={v['p99AbsDiff']}")

    rebal = monthly_rebalance_dates(df["date"])

    report = {
        "question": ("Follow-ups on the A-grade drawdown finding (dd_from_high_252/120 at 6M): "
                     "(1) is it just Momentum12M re-packaged? (2) when does the effect kick in? "
                     "(3) does it survive liquidity conditioning?"),
        "data": {
            "source": DATA.replace(REPO_ROOT + os.sep, "").replace("\\", "/"),
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "integrityRecheckVsParquet": integ,
        },
        "featureDefinitions": DECOMP_FEATURES,
        "caveats": [
            "A4 panel scope ≈ currently-listed universe (survivorship caveat as before).",
            "fwd_d40/d80/d160 are recomputed with row-shift within the panel; on panel-gap rows (~0.5%, see integrityRecheck) they can deviate from a full-session-index definition.",
            "dd_252_skip1m mirrors the momentum study's skip1m_12_1 span: signal window ends t-21, high taken over [t-252..t-21]; forward returns still measured from t close.",
            "mom252 = raw12m of momentum_decile_analysis (no skip); its warm-up aligns with dd_from_high_252 so both share the same effective sample.",
            "Liquidity proxy is 20D mean KRX trading value (not market cap), same spirit as absolute_turnover_filter_validation.py.",
            "Overlapping forward windows; NW lag=h/21 on monthly spreads. No transaction costs.",
        ],
    }

    print("\n=== ① Rank correlation dd vs mom252 (monthly dates) ===")
    report["rankCorrelationDDvsMom"] = rank_corr_dd_vs_mom(df, rebal)

    print("\n=== ① Orthogonalized daily IC (residual of rank regression) ===")
    orth_block = {}
    for feat in ("dd_from_high_252", "dd_from_high_120"):
        orth_block.update(orth_ic(df, feat, "mom252", BASE_HORIZONS))
    orth_block.update(orth_ic(df, "mom252", "dd_from_high_252", BASE_HORIZONS))
    print("-- unconditional baselines (same sample) --")
    for feat in ("dd_from_high_252", "mom252"):
        orth_block.update(uncond_ic(df, feat, BASE_HORIZONS))
    report["orthogonalIC"] = orth_block

    print("\n=== ② Horizon decomposition (daily IC + monthly decile spread) ===")
    decomp_block = {}
    for feat in DECOMP_FEATURES:
        decomp_block[feat] = {}
        for h in DECOMP_HORIZONS:
            recs = []
            arr = df[["date", feat, h]].dropna()
            for d, gd in arr.groupby("date"):
                if len(gd) < MIN_NAMES_PER_DATE:
                    continue
                r = spearmanr(gd[feat].to_numpy(), gd[h].to_numpy())
                if not np.isnan(r.statistic):
                    recs.append((d, float(r.statistic)))
            ic = summarize(recs)
            sp = decile_spread(df, feat, h, rebal)
            decomp_block[feat][h] = {"dailyIC": ic, "monthlySpread": sp}
            print(f"  {feat:18s} {h:9s}: IC={ic['mean']:+.5f}(t={ic['tNaive']}), "
                  f"D10-D1={sp['monthlySpreadMean']:+.5f}(NWT={sp['monthlySpreadNWT']}), "
                  f"rho-pool={sp['pooledD10minusD1']:+.4f}")
    report["horizonDecomposition"] = decomp_block

    print("\n=== ③ Liquidity conditional (dd_from_high_252 vs fwd_d120) ===")
    report["liquidityConditional"] = liquidity_conditional(df, "dd_from_high_252", "fwd_d120", rebal)

    out_path = os.path.join(OUT_DIR, "dd-followup-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
