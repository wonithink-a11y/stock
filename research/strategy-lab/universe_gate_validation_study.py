#!/usr/bin/env python
"""통합 실행가능성 유니버스 게이트 검증 — Liquidity/Volatility 스터디 후속.

목적: 새 factor 탐색이 아니라, 사전 필터 gate가 기존 역전 신호(LOWMOM60·REV20)의
alpha를 얼마나 보존하는지 확인한다. threshold 최적화는 하지 않는다 — vol exclusion은
volatility-atr-factor-a4-2026-08.md의 정의(날짜별 '전체' 횡단면 rv20 상위 decile
제외, 절벽 구조의 D10) 그대로, 유동성 1억원·가격 5,000원 고정값.

arms:
  A : 전체 유니버스(feature 유효 종목)
  B : A & 20세션 평균 거래대금 >= 1억원
  C : B & rv20 날짜별 상위 decile 제외
  D : C & close >= 5,000원

측정(각 arm × LOWMOM60(mom60)·REV20(mom20)):
  - 월평균 유니버스 크기·보존율
  - 시그널 바스켓(하위 decile) 평균 fwd 20/60/120 (gross + 순@30bps RT는 월간 홀딩인
    d20에만 부여 — 기존 관례(strategy_candidate_backtest.py·5DC policy) 재사용)
  - factor spread(D1-D10) 월별 시계열 NW t
  - arm 내 일별 IC(t)·연도별 IC(vs d60)
  - A 바스켓 대비 D 바스켓 겹침률(d60) — alpha 보존의 직접 지표

spread는 상대량이라 비용 미적용(LONG_ONLY 맥락에서 leg별 비용 부과는 왜곡 — 명시).
PIT: feature·gate 모두 t 종가까지 정보, 수익률은 t+h 대비. feature 계산식은
liquidity_factor_study.py를 import해 재사용하며, 동일 계산식의 PIT 절단 단언은
선행 스터디에서 통과됐다(0.000e+00).

산출: reports/2026-08-26-universe-gate/gate-results.json (+stdout). 커밋 없음.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from liquidity_factor_study import (  # noqa: E402
    DATA, REPO_ROOT,
    daily_ic_series, features_from_ohlc, load_full_ohlc,
    monthly_rebalance_dates, naive_t, newey_west_t, yearly_breakdown, ic_summary,
    LIQ_THRESHOLD,
)

OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-universe-gate")
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
MIN_NAMES_PER_DATE = 30
NW_LAG_BY_HORIZON = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}
COST_RT_BPS_PER_MONTH = 30.0
SIGNALS = {
    "LOWMOM60_mom60": {"feature": "mom60"},
    "REV20_mom20": {"feature": "mom20"},
}


def bottom_decile_sets(sub, feature, horizon="fwd_d60"):
    out = {}
    for d, gd in sub.groupby("date"):
        gg = gd[[feature, horizon, "ticker"]].dropna(subset=[feature])
        if len(gg) < MIN_NAMES_PER_DATE:
            continue
        dec = pd.qcut(gg[feature].rank(method="first"), 10, labels=False).to_numpy() + 1
        out[d] = set(gg.loc[dec == 1, "ticker"])
    return out


def monthly_spread_stats(sub, feature, horizon):
    sp = []
    for d, gd in sub.groupby("date"):
        gg = gd[[feature, horizon]].dropna()
        if len(gg) < MIN_NAMES_PER_DATE:
            continue
        dec = pd.qcut(gg[feature].rank(method="first"), 10, labels=False).to_numpy() + 1
        vals = gg[horizon].to_numpy()
        top, bot = vals[dec == 10], vals[dec == 1]
        if len(top) and len(bot):
            sp.append(float(bot.mean() - top.mean()))
    return {"nMonths": len(sp),
            "monthlySpreadMean": round(float(np.mean(sp)), 5) if sp else None,
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, NW_LAG_BY_HORIZON[horizon])}


def basket_stats(sub, feature, horizons):
    sizes = []
    acc = {h: [] for h in horizons}
    wr = {h: [] for h in horizons}
    for d, gd in sub.groupby("date"):
        gg = gd[[feature] + list(horizons)].dropna(subset=[feature])
        if len(gg) < MIN_NAMES_PER_DATE:
            continue
        dec = pd.qcut(gg[feature].rank(method="first"), 10, labels=False).to_numpy() + 1
        bot = dec == 1
        sizes.append(int(bot.sum()))
        for h in horizons:
            v = gg.loc[bot, h].dropna()
            if len(v):
                acc[h].append(float(v.mean()))
                wr[h].append(float((v > 0).mean()))
    out = {"avgBasketSize": round(float(np.mean(sizes)), 1) if sizes else None,
           "nMonths": len(sizes)}
    for h in horizons:
        gross = float(np.mean(acc[h])) if acc[h] else None
        out[h] = {"basketGrossMeanFwd": round(gross, 5) if gross is not None else None,
                  "basketWinrate": round(float(np.mean(wr[h])), 4) if wr[h] else None}
        if h == "fwd_d20" and gross is not None:
            out[h]["basketNetAt30bpsRTperMonth"] = round(gross - COST_RT_BPS_PER_MONTH / 10000.0, 5)
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 panel...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    wanted = set(panel["ticker"].unique())

    print("Streaming full A2a OHLCV + computing features (imports liquidity_factor_study)...")
    full, stream_stats = load_full_ohlc(wanted)
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)
    del frames, full

    df = panel.merge(feats, on=["ticker", "date"], how="inner")
    integrity = {}
    for h in (20, 60, 120):
        a, b = df[f"fwd_d{h}_x"], df[f"fwd_d{h}_y"]
        m = a.notna() & b.notna()
        diff = (a[m] - b[m]).abs()
        integrity[f"d{h}"] = {"exactMatchRate": round(float((diff < 1e-12).mean()), 6),
                              "maxAbsDiff": round(float(diff.max()), 6)}
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])
    print("  integrity: " + ", ".join(f"{k}: match={v['exactMatchRate']}" for k, v in integrity.items()))

    df["dv20"] = np.exp(df["dv20_log"])
    rebal = set(monthly_rebalance_dates(df["date"]))
    rb = df[df["date"].isin(rebal)].copy()

    def _q(grp):
        if len(grp) < MIN_NAMES_PER_DATE:
            grp["rv_decile"] = np.nan
            return grp
        grp["rv_decile"] = pd.qcut(grp["rv20_pct"].rank(method="first"), 10, labels=False) + 1
        return grp

    rb_all = rb.dropna(subset=["rv20_pct"]).groupby("date", group_keys=False).apply(_q)
    top_flags = set(map(tuple, rb_all.loc[rb_all["rv_decile"] == 10, ["ticker", "date"]].to_numpy()))
    rb["gate_liq"] = rb["dv20"] >= LIQ_THRESHOLD
    rb["gate_price"] = rb["close"] >= 5000.0
    rb["gate_vol_excl"] = [tuple(k) not in top_flags for k in zip(rb["ticker"], rb["date"])]

    arms = {
        "A_full": pd.Series(True, index=rb.index),
        "B_liq1e8": rb["gate_liq"],
        "C_B_plus_noExtremeVol": rb["gate_liq"] & rb["gate_vol_excl"].astype(bool),
        "D_C_plus_price5000": rb["gate_liq"] & rb["gate_vol_excl"].astype(bool) & rb["gate_price"],
    }
    base_n = float(len(rb))
    arm_sizes = {k: int(v.fillna(False).sum()) for k, v in arms.items()}
    retention = {k: round(arm_sizes[k] / base_n, 4) for k in arms}

    report = {
        "question": "Does the unified tradability gate preserve LOWMOM60/REV20 alpha while removing untradeable names?",
        "gateDefinition": {
            "liquidity": "20-session mean dollar volume >= 1e8 KRW (session-aligned volume*close)",
            "volExclusion": "rv20 top decile of each date's FULL cross-section (fixed definition, no threshold search)",
            "price": "close >= 5000 KRW",
            "costModel": f"{COST_RT_BPS_PER_MONTH}bps round-trip per monthly hold (existing repo convention); applied only to d20 basket means",
        },
        "armSizes": arm_sizes,
        "retentionVsA": retention,
        "forwardReturnIntegrityRecheckVsParquet": integrity,
        "haltArtifactRowsExcluded": stream_stats,
        "note": "Purpose is alpha preservation under tradability constraints, NOT return maximization.",
        "arms": {},
    }
    print(f"\narm sizes: {arm_sizes}")
    print(f"retention vs A: {retention}")

    results_by_arm = {}
    ic_series_cache = {}
    for arm_name, mask in arms.items():
        keep = mask.fillna(False).to_numpy()
        sub = rb[keep]
        arm_res = {"nRows": int(len(sub)),
                   "avgNamesPerMonth": round(float(sub.groupby("date").size().mean()), 1)}
        for sig_name, cfg in SIGNALS.items():
            feat = cfg["feature"]
            sig_res = {}
            for h in DECILE_HORIZONS:
                sig_res[f"spread_{h}"] = monthly_spread_stats(sub, feat, h)
            sig_res["baskets"] = basket_stats(sub, feat, DECILE_HORIZONS)
            key_ic = (arm_name, feat)
            if key_ic not in ic_series_cache:
                ic_series_cache[key_ic] = daily_ic_series(sub, feat, "fwd_d60")
            sig_res["dailyIC_vs_d60"] = ic_summary(ic_series_cache[key_ic])
            yic = yearly_breakdown(ic_series_cache[key_ic])
            neg_years = sum(1 for y in yic.values() if y["icMean"] < 0)
            sig_res["yearlyIC_vs_d60"] = yic
            sig_res["yearlySignSummary"] = {"negativeYears": neg_years, "totalYears": len(yic)}
            arm_res[sig_name] = sig_res
            print(f"\n[{arm_name}] {sig_name}: avgNames/mo={arm_res['avgNamesPerMonth']}")
            for h in DECILE_HORIZONS:
                s = sig_res[f"spread_{h}"]
                print(f"  spread {h}: {s['monthlySpreadMean']:+.5f} (NWT {s['monthlySpreadNWT']}, n={s['nMonths']})")
            b = sig_res["baskets"]
            for h in DECILE_HORIZONS:
                extra = f", net@30bps={b[h]['basketNetAt30bpsRTperMonth']:+.5f}" if "basketNetAt30bpsRTperMonth" in b[h] else ""
                print(f"  basket {h}: gross={b[h]['basketGrossMeanFwd']:+.5f}, wr={b[h]['basketWinrate']}{extra}")
            r = sig_res["dailyIC_vs_d60"]
            print(f"  IC(d60)={r.get('icMean')} (t={r.get('icT')}), negativeYears={neg_years}/{len(yic)}")
        results_by_arm[arm_name] = arm_res
    report["arms"] = results_by_arm

    print("\nbasket overlap (A -> D, d60):")
    overlap_block = {}
    for sig_name, cfg in SIGNALS.items():
        ba = bottom_decile_sets(rb[arms["A_full"].to_numpy()], cfg["feature"])
        bd = bottom_decile_sets(rb[arms["D_C_plus_price5000"].fillna(False).to_numpy()], cfg["feature"])
        ratios = [len(ba[d] & bd[d]) / len(ba[d]) for d in sorted(set(ba) & set(bd)) if ba[d]]
        ov = {"meanShareOfABasketSurvivingInD": round(float(np.mean(ratios)), 4) if ratios else None,
              "nMonthsCompared": len(ratios)}
        overlap_block[sig_name] = ov
        print(f"  {sig_name}: {ov}")
    report["basketOverlapAtoD"] = overlap_block

    out_path = os.path.join(OUT_DIR, "gate-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
