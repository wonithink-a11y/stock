#!/usr/bin/env python
"""MA Distance / Drawdown-from-High 정보력 검증 — A4 research dataset 기반,
Momentum12M decile 연구와 동일 관례의 독립 재현 (macd_information_content_study.py
템플릿 재사용).

목적: MA Distance·Drawdown factor의 향후 주가수익률 독립 정보력 확인.
production/scoring engine 무변경, 새 데이터 수집 없음. 원천은
research/strategy-lab/data/a4/a4-research-dataset.parquet 하나.

검증 feature (7개):
  MA Distance   : close/MA20-1, close/MA60-1, close/MA120-1, close/MA200-1
  Drawdown      : close/rolling-max(close,60D)-1, close/rolling-max(close,120D)-1,
                  close/rolling-max(close,252D)-1

가설:
  Drawdown  — "최근 고점에서 많이 하락한 종목일수록 이후 반등하는가?"
              (반등이면 D1=최대낙폭이 D10=고점부근을 이겨야 → D10-D1 spread < 0)
  MA Distance — "이동평균에서 크게 이탈한 종목에 평균회귀 또는 추세추종 효과가 있는가?"
              (추세추종이면 spread > 0, 평균회귀면 spread < 0)

관례 재사용 출처:
  - 월간 리밸런스·날짜별 qcut decile·D10-D1 monthly spread + Newey-West:
    macd_information_content_study.py ← momentum_decile_analysis.py (Momentum12M)
  - 일별 cross-sectional Spearman IC + t=mean/(std/sqrt(nDays)):
    analyze_a4_research.py
  - forward return 정의 close[t+h]/close[t]-1: build_a4_research_dataset.py PIT 규약

PIT 설계:
  - MA는 trailing rolling mean, rolling high는 trailing rolling max — t값은 t까지의
    데이터만으로 결정. 스크립트 안에서 "앞 60% 잘라낸 계열로 재계산 == 전체 계열 값"
    단언으로 경험적 검증한다(look-ahead 시 불일치 발생).
  - 당일 종가 신호를 당일 수익률에 쓰지 않는다 — 모든 수익률은 t 종가 대비 t+h 종가.
  - rolling high 창은 당일(t) 종가를 포함한다(표준 drawdown 정의, t 종가 신호 시점에
    이미 관측 가능하므로 PIT-safe).

산출: reports/2026-08-26-ma-drawdown-information-content/ma-drawdown-results.json
data/backfill 읽기 전용(CLAUDE.md 규칙 4), production 무변경.
"""
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-ma-drawdown-information-content")

DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]  # 1M / 3M / 6M (거래일)
FEATURES = {
    "ma_dist_20": "close/MA20 - 1",
    "ma_dist_60": "close/MA60 - 1",
    "ma_dist_120": "close/MA120 - 1",
    "ma_dist_200": "close/MA200 - 1",
    "dd_from_high_60": "close/rolling-max(close,60) - 1",
    "dd_from_high_120": "close/rolling-max(close,120) - 1",
    "dd_from_high_252": "close/rolling-max(close,252) - 1",
}
MIN_NAMES_PER_DATE = 30
NW_LAG_BY_HORIZON = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}


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
    for w in (20, 60, 120, 200):
        ma = g.transform(lambda s: s.rolling(w, min_periods=w).mean())
        df[f"ma_dist_{w}"] = df["close"] / ma - 1.0
    for w in (60, 120, 252):
        hi = g.transform(lambda s: s.rolling(w, min_periods=w).max())
        df[f"dd_from_high_{w}"] = df["close"] / hi - 1.0
    return df


def add_own_forward_returns(df):
    """parquet fwd_* 무결성 교차검증. 주의: parquet fwd는 ticker의 전체 세션 인덱스로
    계산된 반면 이 재계산은 '패널 행 기준 shift'라서, A4 레코드가 결측한 세션(패널 갭)이
    있으면 두 정의가 어긋난다 — 이때 parquet 쪽이 실제 t+거래일 정의에 맞다.
    그래서 maxAbsDiff와 함께 불일치 행 비율·p99를 함께 기록한다."""
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    grp = df.groupby("ticker", sort=False)["close"]
    for h in (20, 60, 120):
        df[f"own_fwd_d{h}"] = grp.transform(lambda s: s.shift(-h) / s - 1)
    checks = {}
    for h in (20, 60, 120):
        a = df[f"own_fwd_d{h}"]
        b = df[f"fwd_d{h}"]
        m = a.notna() & b.notna()
        diff = (a[m] - b[m]).abs()
        checks[f"d{h}"] = {
            "maxAbsDiff": round(float(diff.max()), 8),
            "nCompared": int(m.sum()),
            "shareRowsMismatched": round(float((diff > 1e-9).mean()), 6),
            "p99AbsDiff": round(float(diff.quantile(0.99)), 8),
            "note": "maxAbsDiff comes from panel-gap rows (A4 records missing on some sessions) where row-shift is the wrong definition; parquet fwd (full per-ticker session index) is authoritative.",
        }
    return df, checks


def pit_truncation_check(df, sample=40):
    """'앞 60%만 잘라낸 계열'로 다시 만든 feature가 겹치는 구간에서 전체 계열 값과
    완전히 같아야 한다(rolling backward 연산의 성질). look-ahead가 섞이면 여기서 들킨다."""
    tickers = sorted(df["ticker"].unique())
    step = max(1, len(tickers) // sample)
    chosen = tickers[::step][:sample]
    worst = {}
    for feat in FEATURES:
        worst[feat] = 0.0
    for t in chosen:
        sub = df[df["ticker"] == t].sort_values("date")
        k = int(len(sub) * 0.6)
        if k < 252:
            continue
        trunc = compute_features(sub.iloc[:k].copy())
        for feat in FEATURES:
            full = sub.iloc[:k][feat].to_numpy()
            got = trunc[feat].to_numpy()
            d = float(np.nanmax(np.abs(full - got))) if len(full) else 0.0
            worst[feat] = max(worst[feat], d)
    return worst


def daily_ic_series(df, feature, fwd_col, min_names=30):
    recs = []
    cols = ["date", feature, fwd_col]
    arr = df[cols].dropna()
    for d, g in arr.groupby("date"):
        if len(g) < min_names:
            continue
        r = spearmanr(g[feature].to_numpy(), g[fwd_col].to_numpy())
        if not np.isnan(r.statistic):
            recs.append((d, float(r.statistic)))
    return recs


def summarize_ic(recs):
    if not recs:
        return {"nDays": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean() / (sd / np.sqrt(len(vals)))) if sd > 0 else None
    by_year = {}
    for d, v in recs:
        by_year.setdefault(d[:4], []).append(v)
    yearly = {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())}
    pos_share = round(float((vals > 0).mean()), 4)
    return {"nDays": len(vals), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd, 5), "icT": round(t, 3) if t is not None else None,
            "icPositiveShare": pos_share, "yearlyICMean": yearly}


def monthly_rebalance_dates(dates):
    out, seen = [], set()
    for d in sorted(dates.unique()):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return set(out)


def decile_analysis(df, feature, rebal_dates):
    sub = df[df["date"].isin(rebal_dates)].dropna(subset=[feature]).copy()
    tables = {}
    mono = {}
    panel_rows = len(sub)
    for h in DECILE_HORIZONS:
        s = sub.dropna(subset=[h]).copy()

        def _q(grp):
            if len(grp) < MIN_NAMES_PER_DATE:
                grp["decile"] = np.nan
                return grp
            grp["decile"] = pd.qcut(grp[feature].rank(method="first"), 10, labels=False) + 1
            return grp

        s = s.groupby("date", group_keys=False).apply(_q)
        s = s.dropna(subset=["decile"])
        s["decile"] = s["decile"].astype(int)
        agg = s.groupby("decile")[h].agg(["count", "mean", "median"])
        win = s.groupby("decile")[h].apply(lambda x: float((x > 0).mean()))
        tables[h] = {
            "count": {int(i): int(agg.loc[i, "count"]) for i in agg.index},
            "mean": {int(i): round(float(agg.loc[i, "mean"]), 5) for i in agg.index},
            "median": {int(i): round(float(agg.loc[i, "median"]), 5) for i in agg.index},
            "winrate": {int(i): round(float(win.loc[i]), 4) for i in agg.index},
        }
        sp_pairs = []
        for d, gd in s.groupby("date"):
            top = gd[gd["decile"] == 10][h]
            bot = gd[gd["decile"] == 1][h]
            if len(top) and len(bot):
                sp_pairs.append((d, float(top.mean() - bot.mean())))
        sp = np.array([v for _, v in sp_pairs], dtype=float)
        means = [tables[h]["mean"][i] for i in range(1, 11)]
        rho = spearmanr(means, list(range(1, 11))).statistic
        lag = NW_LAG_BY_HORIZON[h]
        by_year_sp = {}
        for d, v in sp_pairs:
            by_year_sp.setdefault(d[:4], []).append(v)
        mono[h] = {
            "decileReturnSpearman": round(float(rho), 4),
            "pooledD10minusD1": round(float(tables[h]["mean"][10] - tables[h]["mean"][1]), 5),
            "monthlySpreadMean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, lag),
            "nMonths": int(len(sp)),
            "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year_sp.items())},
        }
    return {"panelRows": panel_rows, "decileTables": tables, "monotonicitySpread": mono}


def cross_sectional_context(df, rebal_dates):
    sub = df[df["date"].isin(rebal_dates)]
    out = {}
    out["shareAboveMA20"] = round(float((sub["ma_dist_20"] > 0).mean()), 4)
    out["shareAboveMA200"] = round(float((sub["ma_dist_200"] > 0).mean()), 4)
    for w in (60, 120, 252):
        col = f"dd_from_high_{w}"
        v = sub[col].dropna()
        out[f"medianDD{w}"] = round(float(v.median()), 4)
        out[f"shareAtHigh{w}"] = round(float((v >= -1e-9).mean()), 4)
    out["minNamesPerDateForDecile"] = MIN_NAMES_PER_DATE
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 research dataset (needed columns only)...")
    cols = ["ticker", "date", "close", "fwd_d20", "fwd_d60", "fwd_d120"]
    df = pd.read_parquet(DATA, columns=cols)
    n_dupes = int(df.duplicated(subset=["ticker", "date"]).sum())
    if n_dupes:
        df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    print(f"rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"period={df['date'].min()}~{df['date'].max()}, dupesRemoved={n_dupes}")

    print("Computing own forward returns + integrity check vs parquet...")
    df, integrity = add_own_forward_returns(df)
    print(f"  forward-return recomputation maxAbsDiff: "
          + ", ".join(f"{k}={v['maxAbsDiff']:.2e}" for k, v in integrity.items()))

    print("Computing MA distance / drawdown features...")
    df = compute_features(df)

    print("PIT truncation check (full series vs first-60% recompute)...")
    pit_dev = pit_truncation_check(df)
    for feat, dev in pit_dev.items():
        print(f"  max |{feat}_full - truncated| over sample tickers = {dev:.3e}")
        assert dev < 1e-8, f"PIT violation suspected in {feat}: truncated-series values differ"

    rebal = monthly_rebalance_dates(df["date"])

    report = {
        "question": {
            "drawdown": "Do stocks far below their recent high rebound afterwards? "
                        "(rebound => D1 deepest-drawdown beats D10 near-high => D10-D1 spread < 0)",
            "maDistance": "Do stocks far from their moving averages mean-revert or trend? "
                          "(trend => spread > 0, reversion => spread < 0)",
        },
        "data": {
            "source": "research/strategy-lab/data/a4/a4-research-dataset.parquet",
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "priceBasis": "A2a adjusted close (수정주가)",
            "forwardReturnConvention": "close[t+h]/close[t]-1, signal at t close, return strictly after t",
            "duplicateRowsRemoved": n_dupes,
            "forwardReturnIntegrityRecheck": integrity,
            "pitTruncationMaxDeviation": pit_dev,
            "pitTruncationNote": "features recomputed from first-60% truncated series must equal full-series values exactly; any look-ahead would show up here.",
        },
        "featureDefinitions": FEATURES,
        "caveats": [
            "A4 panel scope = A4 tickers ∩ A2a coverage ≈ currently-listed universe (same survivorship caveat as the Momentum12M A1A_ONLY study; delisted-only-after periods are absent).",
            "Parquet starts 2016-01-04, so MA200/dd_from_high_252 only become non-NaN ~200 sessions in (~2016-10); those features have a shorter effective sample.",
            "Rolling-high window includes day t itself (standard drawdown definition; observable at signal time, hence PIT-safe) - dd <= 0 always and equals 0 at new highs.",
            "dd_from_high_* overlaps mechanically with multi-month price momentum and REV20-style short-term reversal; this study measures raw information content only, no combination tests.",
            "Monthly rebalance at each month's first session, cross-sectional qcut deciles per date (Book3 9.47 convention, same as Momentum12M/MACD studies); D1 = lowest feature value, D10 = highest.",
            "Overlapping forward windows are not independent; monthly spreads use Newey-West with lag=h/21 as a partial correction.",
            "No transaction costs - information content, not a tradable strategy's net P&L.",
        ],
    }

    print("\n=== Daily cross-sectional IC ===")
    ic_block = {}
    for feat in FEATURES:
        for h in DECILE_HORIZONS:
            key = f"{feat}|{h}"
            ic_block[key] = summarize_ic(daily_ic_series(df, feat, h))
            r = ic_block[key]
            if r.get("nDays"):
                print(f"  {feat:16s} vs {h}: IC={r['icMean']:+.5f} (t={r['icT']}, nDays={r['nDays']}, posShare={r['icPositiveShare']})")
    report["dailyIC"] = ic_block

    print("\n=== Monthly-rebalance deciles (Momentum12M convention) ===")
    decile_block = {}
    for feat in FEATURES:
        decile_block[feat] = decile_analysis(df, feat, rebal)
        for h in DECILE_HORIZONS:
            m = decile_block[feat]["monotonicitySpread"][h]
            print(f"  {feat:16s} {h}: D10-D1 pooled={m['pooledD10minusD1']:+.5f}, "
                  f"monthly mean={m['monthlySpreadMean']:+.5f}, naiveT={m['monthlySpreadNaiveT']}, "
                  f"NWT={m['monthlySpreadNWT']}, rho={m['decileReturnSpearman']:+.3f}")
    report["monthlyDeciles"] = decile_block

    print("\n=== Cross-sectional context at monthly dates ===")
    ctx = cross_sectional_context(df, rebal)
    for k, v in ctx.items():
        print(f"  {k}: {v}")
    report["crossSectionalContext"] = ctx

    out_path = os.path.join(OUT_DIR, "ma-drawdown-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
