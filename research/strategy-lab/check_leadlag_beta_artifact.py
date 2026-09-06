#!/usr/bin/env python3
"""S2 kosdaq150 이상치 진단 1 - 잔차를 시장베타로 재계산.

세션인수인계-2026-09-05-b.md ($0) 이 지목한 의심:
    resid_i = s_ret_i - 1 * mkt_ret_ew(t)   (사전등록 $6, 계수 1 고정)
    exposure_i(kosdaq150) 도 이 resid 로 추정한 futures 베타
    -> exposure 와 fwd_resid 가 "베타" 를 공유해 IC 가 부풀려질 수 있다

진단: exposure(선물베타)는 그대로 두고, target 쪽만
    resid2_i = s_ret_i - beta_mkt_i * mkt_ret_ew(t)   (종목별 시장베타, TRAIN 추정)
로 바꿔 재계산한다. 인공물이면 kosdaq150·usd 의 NW t 가 무너진다.
kospi200 은 exposure 가 베타가 아니라 편입비중이라 대조군.

사전등록 코드(analyze_leadlag_s2.py)는 건드리지 않는다 - 이 스크립트는 진단
전용이며 §16-A 판정에 쓰지 않는다.

    python check_leadlag_beta_artifact.py --selftest
    python check_leadlag_beta_artifact.py [--limit N]
"""
import argparse
import os

import numpy as np
import pandas as pd
from scipy import stats

from analyze_leadlag_s2 import (
    LL, MIN_OBS_BETA, MIN_XS, N_TRAIN, N_VALID,
    estimate_betas, exposures, iter_days, load_static, newey_west_t,
)

PRODUCTS = ("kosdaq150", "usd", "kospi200")   # kospi200 = 대조군(편입비중, 베타 아님)
HORIZONS = (1,)                               # 이상치가 관측된 horizon만


def estimate_market_betas(dates_train, mkt):
    """종목별 시장베타: s_ret_1m 을 mkt_ret_ew(t) 에 동시점 회귀. TRAIN만."""
    acc = {}
    for dt, d in iter_days(dates_train):
        d = d[d["s_ret_1m"].notna()].copy()
        if dt not in mkt.index.get_level_values(0):
            continue
        m = mkt.loc[dt, "mkt_ret_ew"]
        d["mkt"] = d["min_idx"].map(m)
        d = d.dropna(subset=["mkt"])
        if d.empty:
            continue
        d["xy"] = d["mkt"] * d["s_ret_1m"]
        d["xx"] = d["mkt"] * d["mkt"]
        agg = d.groupby("ticker").agg(n=("mkt", "size"), Sx=("mkt", "sum"),
                                       Sy=("s_ret_1m", "sum"), Sxy=("xy", "sum"),
                                       Sxx=("xx", "sum"))
        for tk, r in agg.iterrows():
            a = acc.get(tk)
            if a is None:
                acc[tk] = [r.n, r.Sx, r.Sy, r.Sxy, r.Sxx]
            else:
                a[0] += r.n; a[1] += r.Sx; a[2] += r.Sy
                a[3] += r.Sxy; a[4] += r.Sxx
    betas = {}
    for tk, (n, Sx, Sy, Sxy, Sxx) in acc.items():
        if n < MIN_OBS_BETA:
            continue
        den = n * Sxx - Sx * Sx
        if den <= 0:
            continue
        betas[tk] = (n * Sxy - Sx * Sy) / den
    return betas


def day_resid2(d, mkt, dt, beta_mkt, horizons):
    """진단1 전용 잔차: s_ret - beta_mkt_i * mkt_ret_ew(t). ffill 없음(§16-D 유지)."""
    d = d[d["s_ret_1m"].notna()].copy()
    if dt not in mkt.index.get_level_values(0):
        return None
    m = mkt.loc[dt, "mkt_ret_ew"]
    d["mktret"] = d["min_idx"].map(m)
    d = d.dropna(subset=["mktret"])
    if d.empty:
        return None
    d["beta"] = d["ticker"].map(beta_mkt)
    d = d.dropna(subset=["beta"])
    if d.empty:
        return None
    d["resid2"] = d["s_ret_1m"] - d["beta"] * d["mktret"]
    d = d.sort_values(["ticker", "min_idx"])
    g = d.groupby("ticker", sort=False)["resid2"]
    for h in horizons:
        d["fwd2_%d" % h] = g.transform(
            lambda s: s.shift(-1).rolling(h, min_periods=h).sum().shift(-(h - 1)))
    return d


def run(products=PRODUCTS, horizons=HORIZONS, limit=0):
    fut, mkt, uni = load_static()
    dates = sorted(set(uni["trade_date"]) & set(d.split("=")[1] for d in
                       os.listdir(LL / "stock_1m") if d.startswith("date=")))
    dates = [d for d in dates if d >= "2025-08-26"]
    if limit:
        dates = dates[:limit]
    tr, va = dates[:N_TRAIN], dates[N_TRAIN:N_TRAIN + N_VALID]
    te = dates[N_TRAIN + N_VALID:]
    seg = {d: "TRAIN" for d in tr}; seg.update({d: "VALID" for d in va})
    seg.update({d: "TEST" for d in te})
    print("날짜 %d · TRAIN %d · VALID %d · TEST %d" % (len(dates), len(tr), len(va), len(te)), flush=True)

    betas = estimate_betas(tr, fut, mkt, uni)      # exposure(선물베타) - 원본 그대로
    ex = exposures(betas, uni)
    beta_mkt = estimate_market_betas(tr, mkt)      # 진단1 전용 시장베타
    print("시장베타 추정 %d종목" % len(beta_mkt), flush=True)

    ic2 = {(p, h, s): [] for p in products for h in horizons for s in ("TRAIN", "VALID", "TEST")}
    for n, (dt, d) in enumerate(iter_days(dates), 1):
        d2 = day_resid2(d, mkt, dt, beta_mkt, horizons)
        if d2 is None:
            continue
        try:
            fr = fut.loc[dt]
        except KeyError:
            continue
        s = seg[dt]
        for p in products:
            if p not in fr.columns:
                continue
            E = ex[p]
            e = (d2["ticker"].map(lambda t: E.get((dt, t))) if p == "kospi200"
                 else d2["ticker"].map(E))
            sub = d2.assign(expo=e, f=d2["min_idx"].map(fr[p]))
            sub = sub[sub["expo"].notna() & sub["f"].notna() & (sub["f"] != 0)]
            if sub.empty:
                continue
            for h in horizons:
                col = "fwd2_%d" % h
                for mi, g in sub[["expo", col, "f"]].dropna().groupby(sub["min_idx"]):
                    if len(g) < MIN_XS:
                        continue
                    r = stats.spearmanr(g["expo"], g[col]).statistic
                    if not np.isnan(r):
                        ic2[(p, h, s)].append(np.sign(g["f"].iloc[0]) * r)
        if n % 50 == 0:
            print("  %d/%d %s" % (n, len(dates), dt), flush=True)

    print("\n=== 진단1: resid2 = s_ret - beta_mkt_i*mkt_ret_ew (원본은 beta_mkt=1 고정) ===")
    for p in products:
        for h in horizons:
            row = []
            for s in ("TRAIN", "VALID", "TEST"):
                t_, n_ = newey_west_t(ic2[(p, h, s)])
                m_ = float(np.nanmean(ic2[(p, h, s)])) if ic2[(p, h, s)] else float("nan")
                row.append("%s meanIC=%.5f nwT=%.2f n=%d" % (s, m_, t_, n_))
            print("%-10s h=%d  " % (p, h) + " | ".join(row))


def selftest():
    rng = np.random.default_rng(0)
    # 시장베타 회귀: y = 2x + noise -> 추정 beta ~ 2
    n = 2000
    x = rng.normal(0, 1, n)
    y = 2.0 * x + rng.normal(0, 0.01, n)
    Sx, Sy, Sxy, Sxx = x.sum(), y.sum(), (x * y).sum(), (x * x).sum()
    beta = (n * Sxy - Sx * Sy) / (n * Sxx - Sx * Sx)
    assert abs(beta - 2.0) < 0.05
    # resid2 정의: beta_mkt=1이면 원본 resid와 일치해야 한다
    d = pd.DataFrame({"ticker": ["A"] * 3, "min_idx": [1, 2, 3], "s_ret_1m": [0.1, 0.2, -0.1]})
    beta_mkt = {"A": 1.0}
    mkt = pd.DataFrame({"trade_date": ["D"] * 3, "min_idx": [1, 2, 3],
                        "mkt_ret_ew": [0.05, 0.05, 0.05]}).set_index(["trade_date", "min_idx"])
    d2 = day_resid2(d, mkt, "D", beta_mkt, [1])
    expect = d["s_ret_1m"].values - 0.05
    assert np.allclose(d2["resid2"].values, expect)
    print("selftest 통과 (2건)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    run(limit=a.limit)


if __name__ == "__main__":
    main()
