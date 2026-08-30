#!/usr/bin/env python
"""A4 패널에서 Liquidity/Trading Value 자체의 cross-sectional 정보력 검증.

기존 연구와의 차별점 (중복 아님):
  - analyze_a4_research.py는 수급 netbuy feature의 IC였고, 거래대금·거래량·유동성
    변화를 standalone 팩터로 한 월간 decile/IC 분석은 없었다.
  - pbr_liquidity_tier_spread_check / absolute_turnover_filter_validation은
    PBR·LOWMOM60을 유동성 필터로 자른 것이고, 본 스크립트는 같은 A4 패널 위에서
    LOWMOM60(mom60)·REV20(rev20) 효과를 유동성 tercile별로 분해한다.

팩터 (전부 date t까지 정보만 사용 — PIT):
  log_amt      log1p(total_amount)                     당일 거래대금 수준
  log_amt20    log1p(20거래일 평균 거래대금)            유동성 수준 (turnover20 proxy)
  log_vol20    log1p(20거래일 평균 거래량)              유동성 수준 (주식수 기준)
  amt_surge    log(total_amount / 직전 20일 평균)       유동성 급증 (baseline은 shift(1))
  mom60        close/close.shift(60)-1                 LOWMOM60 원신호 (낮을수록 good)
  rev20        close/close.shift(20)-1                 REV20 원신호 (낮을수록 good)

표본: month-end 각 시점 cross-section, forward return은 패널의 fwd_d20/d60/d120
(close[t+n]/close[t]-1, adjusted) — 당일(t) 수익률 미포함, look-ahead 없음.
월간 샘플링 + 중첩 horizon 보정 Newey-West t (maxlag = horizon개월-1).

출력: findings/a4-liquidity-factor/{a4_liquidity_factor_results.json, study.md}

  python a4_liquidity_factor_check.py
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4",
                     "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "a4-liquidity-factor")
HORIZONS = {"d20": "1M(~20거래일)", "d60": "3M(~60거래일)", "d120": "6M(~120거래일)"}
NW_LAGS = {"d20": 0, "d60": 2, "d120": 5}  # 월간 샘플 중첩 개월수 - 1
LIQ_COL = "amt20"  # 유동성 tercile 기준 (20일 평균 거래대금)
MIN_NAMES = 100    # 월별 cross-section 최소 종목수


def newey_west_t(series, maxlag):
    x = np.asarray(pd.Series(series).dropna(), dtype=float)
    n = len(x)
    if n < 5 or np.std(x) == 0:
        return None
    mu = float(np.mean(x))
    x = x - mu
    s0 = float(np.sum(x * x)) / n
    var = s0
    for l in range(1, maxlag + 1):
        g = float(np.sum(x[l:] * x[:-l])) / n
        var += 2.0 * (1.0 - l / (maxlag + 1.0)) * g
    se = np.sqrt(var / n)
    return round(mu / se, 2) if se > 0 else None


def plain_t(series):
    x = pd.Series(series).dropna()
    if len(x) < 5 or x.std() == 0:
        return None
    return round(float(x.mean() / (x.std() / np.sqrt(len(x)))), 2)


def load_month_end_panel():
    """필요 컬럼만 로드 → wide로 파생계산 → month-end 행만 long으로 반환."""
    cols = ["ticker", "date", "total_amount", "total_volume", "close",
            "fwd_d20", "fwd_d60", "fwd_d120"]
    df = pd.read_parquet(PANEL, columns=cols)
    df = df[(df["close"] > 0) & df["total_amount"].notna()].copy()
    print(f"rows={len(df)} tickers={df['ticker'].nunique()} "
          f"dates={df['date'].nunique()} ({time.strftime('%H:%M:%S')})")

    close_w = df.pivot(index="date", columns="ticker", values="close").sort_index()
    amt_w = df.pivot(index="date", columns="ticker", values="total_amount").sort_index()
    vol_w = df.pivot(index="date", columns="ticker", values="total_volume").sort_index()

    amt20 = amt_w.rolling(20, min_periods=15).mean()
    vol20 = vol_w.rolling(20, min_periods=15).mean()
    surge = (amt_w / amt20.shift(1)).where(lambda x: x > 0)
    fac_w = {
        "log_amt": np.log1p(amt_w.where(lambda x: x >= 0)),
        "log_amt20": np.log1p(amt20.where(lambda x: x >= 0)),
        "log_vol20": np.log1p(vol20.where(lambda x: x >= 0)),
        "amt_surge": np.log(surge),
        "mom60": close_w / close_w.shift(60) - 1,
        "rev20": close_w / close_w.shift(20) - 1,
    }

    month_end = df["date"].groupby(df["date"].str[:7]).max()
    me_dates = sorted(month_end.tolist())
    print(f"month-end dates: {len(me_dates)}")

    keep = df[df["date"].isin(set(me_dates))][
        ["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"]].copy()
    fac_w["amt20"] = amt20
    merged = keep.set_index(["date", "ticker"])
    for name, w in fac_w.items():
        merged[name] = w.loc[w.index.isin(me_dates)].stack()
    merged = merged.reset_index()
    print(f"month-end rows={len(merged)} ({time.strftime('%H:%M:%S')})")
    return merged


def monthly_rank_ic(panel, factor, fwd):
    ics, dates = [], []
    for d, g in panel.groupby("date"):
        g = g[[factor, fwd]].dropna()
        if len(g) < MIN_NAMES:
            continue
        ics.append(g[factor].rank().corr(g[fwd].rank()))
        dates.append(d)
    return pd.Series(ics, index=dates)


def decile_table(panel, factor, fwd):
    rows = {}
    spreads = []
    for d, g in panel.groupby("date"):
        g = g[[factor, fwd]].dropna()
        if len(g) < MIN_NAMES:
            continue
        q = pd.qcut(g[factor].rank(method="first"), 10, labels=False) + 1
        m = g.groupby(q)[fwd].mean()
        rows[d] = m
        if 1 in m.index and 10 in m.index:
            spreads.append({"date": d, "spread": float(m[10] - m[1]),
                            "n": int(len(g))})
    if not rows:
        return None, None
    tab = pd.DataFrame(rows).T
    return tab, pd.DataFrame(spreads)


def ic_block(ic_series, horizon):
    lag = NW_LAGS[horizon]
    tstat = newey_west_t(ic_series, lag) if lag else plain_t(ic_series)
    return {
        "months": int(len(ic_series)),
        "icMean": round(float(ic_series.mean()), 4),
        "icStd": round(float(ic_series.std()), 4),
        "icIR_annualized": round(float(ic_series.mean() / ic_series.std() * np.sqrt(12)), 2)
        if ic_series.std() > 0 else None,
        "tstat_NW" if lag else "tstat": tstat,
        "pctPositiveMonths": round(float((ic_series > 0).mean()), 3),
    }


def spread_block(sp_df, horizon):
    s = sp_df["spread"]
    lag = NW_LAGS[horizon]
    return {
        "meanMonthlySpread": round(float(s.mean()), 4),
        "tstat_NW" if lag else "tstat": newey_west_t(s, lag) if lag else plain_t(s),
        "winRateMonths": round(float((s > 0).mean()), 3),
        "yearlyMeanSpread": {y: round(float(v), 4)
                             for y, v in s.groupby(sp_df["date"].str[:4]).mean().items()},
    }


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    panel = load_month_end_panel()

    liq_q = panel.dropna(subset=[LIQ_COL]).groupby("date")[LIQ_COL]
    panel["liq_tercile"] = (panel.dropna(subset=[LIQ_COL])
                            .groupby("date")[LIQ_COL]
                            .transform(lambda s: pd.qcut(s.rank(method="first"), 3,
                                                         labels=["T1_low", "T2_mid", "T3_high"])))

    results = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "panel": {"path": PANEL, "monthEndRows": int(len(panel)),
                          "tickers": int(panel["ticker"].nunique()),
                          "period": [panel["date"].min(), panel["date"].max()]},
               "pit": {"signalAt": "month-end t, t까지 정보만 사용(rolling backward)",
                        "fwdReturn": "close[t+n]/close[t]-1 — 당일 수익률 미포함",
                        "surgeBaseline": "직전 20일 평균(shift 1) — 당일값 미포함"},
               "factorIC": {}, "decileD10D1": {}, "decileMeans": {},
               "tercileStrategySpread": {}, "factorRankCorrelation": {}}

    # ── 1. 팩터별 Rank IC ──
    factors = ["log_amt", "log_amt20", "log_vol20", "amt_surge"]
    for f in factors:
        results["factorIC"][f] = {h: ic_block(monthly_rank_ic(panel, f, f"fwd_{h}"), h)
                                  for h in HORIZONS}

    # ── 2. Decile D1~D10 + D10-D1 spread ──
    for f in factors + ["mom60", "rev20"]:
        results["decileD10D1"][f] = {}
        results["decileMeans"][f] = {}
        for h in HORIZONS:
            tab, sp = decile_table(panel, f, f"fwd_{h}")
            if tab is None:
                continue
            avg = tab.mean()
            results["decileMeans"][f][h] = {
                f"D{i}": round(float(avg[i]), 4) for i in range(1, 11)}
            results["decileD10D1"][f][h] = spread_block(sp, h)

    # ── 3. 유동성 tercile × LOWMOM60/REV20 (quintile Q1-Q5 spread) ──
    def quintile_spread(g, sig, fwd):
        gg = g[[sig, fwd]].dropna()
        if len(gg) < 30:
            return None
        q = pd.qcut(gg[sig].rank(method="first"), 5, labels=False) + 1
        m = gg.groupby(q)[fwd].mean()
        return float(m[1] - m[5])  # low-signal minus high-signal

    for sig, label in [("mom60", "LOWMOM60_Q1lowMinusQ5high"),
                       ("rev20", "REV20_Q1lowMinusQ5high")]:
        out = {}
        for ter in ["T1_low", "T2_mid", "T3_high", "ALL"]:
            sub = panel if ter == "ALL" else panel[panel["liq_tercile"] == ter]
            out[ter] = {}
            for h in HORIZONS:
                sps = [(d, quintile_spread(g, sig, f"fwd_{h}"))
                       for d, g in sub.groupby("date")]
                sps = pd.DataFrame([{"date": d, "spread": s} for d, s in sps
                                    if s is not None])
                out[ter][h] = {
                    "months": int(len(sps)),
                    **spread_block(sps, h)} if len(sps) >= 24 else {"months": int(len(sps))}
        results["tercileStrategySpread"][label] = out

    # ── 4. 팩터 간 rank 상관 (월평균) ──
    cors = {f: [] for f in factors}
    for d, g in panel.groupby("date"):
        gg = g[factors].dropna()
        if len(gg) < MIN_NAMES:
            continue
        r = gg.rank().corr()
        for f in factors:
            cors[f].append(r.loc[f, "log_amt20"])
    for f in factors:
        results["factorRankCorrelation"][f + "_vs_logAmt20"] = \
            round(float(np.nanmean(cors[f])), 3)

    with open(os.path.join(OUT_DIR, "a4_liquidity_factor_results.json"), "w",
              encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)

    print(json.dumps(results["factorIC"], indent=2, ensure_ascii=False))
    print(json.dumps(results["decileD10D1"], indent=2, ensure_ascii=False)[:2000])
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
