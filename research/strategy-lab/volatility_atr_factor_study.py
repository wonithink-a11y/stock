#!/usr/bin/env python
"""Volatility / ATR cross-sectional factor 정보력 검증 — A4 research dataset 기반,
Momentum12M·MACD 연구와 동일 관례의 독립 재현.

목적: 고변동 vs 저변동 종목의 미래수익률 차이가 존재하는지, 그것이 단순
size/liquidity 효과인지 확인한다. production 무변경, 새 수집 없음.

기존 연구와의 관계 (중복 실행 회피 확인 완료):
  - 2026-08-17 post-5dc screening README: Volatility·ATR은 "미검증" 잔여 후보로 명시.
  - 2026-08-18 strategy-candidates README: 종가 기반 vol20만 Spearman +0.07 "혼재",
    decile10(고변동)만 fwd120 음(-1.58%). LOWVOL top-30 백테스트 CAGR -6.1%.
    REV20+LOWVOL 조합은 MDD 개선(-35.6%) 효과만 관측.
  - 본 스크립트가 새로 하는 것: (1) ATR/Price(진짜 True Range, A2a OHLC 원본),
    (2) 20D/60D rolling volatility를 종목별 '전체 세션 캘린더'에서 계산,
    (3) PIT 절단 단언 + parquet fwd 무결성 대조, (4) 월별 spread NW t,
    (5) 연도별 안정성, (6) 절대 유동성/가격 버킷 조건부 분해.

feature:
  atr14_pct : Wilder ATR(14)/close*100. TR=max(high-low,|high-prevC|,|low-prevC|)
              (첫 세션 TR=high-low), ewm(alpha=1/14, adjust=False).
  rv20_pct  : 최근 20세션 로그수익률 표준편차 *100 (일간 % 단위)
  rv60_pct  : 동일 60세션

PIT:
  - 모든 feature는 t까지의 세션만 사용(rolling backward, Wilder 순차 재귀).
    "앞 60% 절단 재계산 == 전체 계열 값" 단언으로 경험적 검증.
  - 각 종목 첫 40세션은 warmup으로 feature NaN 처리(ATR/표준편차 시드 편향 제거).
  - forward return close[t+h]/close[t]-1 — 신호는 t 종가, 당일 수익률 미사용.

size/liquidity 단서:
  - 유동성 proxy: total_amount(A4 원자료 거래대금)의 trailing 20 패널행 평균
    (행 기반 근사 — caveat). 절대 임계값 1억원(CLAUDE.md 2026-08-21 관례;
    상대 tercile은 오염 통제변수였던 전례로 사용하지 않음).
  - 가격 버킷: close <5,000원 vs 이상 (REV20 교훈 관례).
  - 버킷 내부에서 재-rank한 D10-D1 spread로 "효과가 버킷 혼성인지" 분리.
  - feature와 log(거래대금)·close의 일별 횡단면 Spearman 평균도 함께 기록.

관례 재사용: momentum_decile_analysis.py(decile), analyze_a4_research.py(IC+t),
build_a4_research_dataset.py(fwd PIT 규약), macd_information_content_study.py v2
(전체 캘린더 스트리밍·무결성 대조·NW t) 구조 재사용.

산출: reports/2026-08-26-volatility-atr-factor/vol-results.json (+stdout 요약).
data/backfill 읽기 전용(규칙 4), production 무변경, 커밋 없음.
"""
import gzip
import json
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-volatility-atr-factor")

ATR_WIN = 14
RV_WINS = (20, 60)
WARMUP = 40
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
CONT_FEATURES = ["atr14_pct", "rv20_pct", "rv60_pct"]
MIN_NAMES_PER_DATE = 30
MIN_NAMES_PER_BUCKET = 30
NW_LAG_BY_HORIZON = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}
LIQ_THRESHOLD = 1e8   # 20행 평균 거래대금 1억원 (절대 임계값 관례)
PRICE_THRESHOLD = 5000.0
A2A_YEARS = [str(y) for y in range(2015, 2027)]


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


def read_gz_jsonl(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_full_ohlc(tickers_wanted):
    """A2a 원본에서 종목별 전체 세션 OHLC 계열을 스트리밍 수집.
    거래정지 아티팩트(close>0이지만 high=low=0) 행은 TR이 무의미하므로 제외하며
    그 수를 센다 — 이 때문에 세션 캘린더가 parquet build(close만 필터)와 미세하게
    달라질 수 있다(무결성 블록에 집계 보고)."""
    out = {t: [] for t in tickers_wanted}
    stats = {"rowsReadTickerMatched": 0, "haltArtifactRowsExcluded": 0}
    for year in A2A_YEARS:
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path):
            continue
        for rec in read_gz_jsonl(path):
            lst = out.get(rec["ticker"])
            if lst is None:
                continue
            if not (rec["close"] and rec["close"] > 0):
                continue
            stats["rowsReadTickerMatched"] += 1
            if not (rec["high"] and rec["high"] > 0 and rec["low"] and rec["low"] > 0):
                stats["haltArtifactRowsExcluded"] += 1
                continue
            lst.append((rec["date"], float(rec["high"]), float(rec["low"]), float(rec["close"])))
    return {t: sorted(v) for t, v in out.items() if v}, stats


def features_from_ohlc(rows):
    """[(date,high,low,close)] 1종목 → DataFrame(date, close, atr14_pct, rv20_pct,
    rv60_pct, fwd_d5/20/60/120). warmup 40세션은 feature NaN."""
    dates = [r[0] for r in rows]
    high = pd.Series([r[1] for r in rows], dtype=float)
    low = pd.Series([r[2] for r in rows], dtype=float)
    close = pd.Series([r[3] for r in rows], dtype=float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    atr = tr.ewm(alpha=1.0 / ATR_WIN, adjust=False).mean()
    logret = np.log(close).diff()
    out = pd.DataFrame({
        "date": dates,
        "close": close.to_numpy(),
        "atr14_pct": (atr / close * 100.0).to_numpy(),
        "rv20_pct": (logret.rolling(RV_WINS[0]).std() * 100.0).to_numpy(),
        "rv60_pct": (logret.rolling(RV_WINS[1]).std() * 100.0).to_numpy(),
        "fwd_d20": (close.shift(-20) / close - 1).to_numpy(),
        "fwd_d60": (close.shift(-60) / close - 1).to_numpy(),
        "fwd_d120": (close.shift(-120) / close - 1).to_numpy(),
    })
    for c in CONT_FEATURES:
        out.loc[: WARMUP - 1, c] = np.nan
    return out


def pit_truncation_check(full_rows_by_ticker, sample=40):
    tickers = sorted(full_rows_by_ticker.keys())
    step = max(1, len(tickers) // sample)
    worst = 0.0
    for t in tickers[::step][:sample]:
        full = features_from_ohlc(full_rows_by_ticker[t])
        k = int(len(full) * 0.6)
        if k < max(WARMUP, RV_WINS[1]) + 5:
            continue
        trunc = features_from_ohlc(full_rows_by_ticker[t][:k])
        for c in CONT_FEATURES:
            d = float(np.nanmax(np.abs(
                full[c].to_numpy()[:k] - trunc[c].to_numpy())))
            if d > worst:
                worst = d
    return worst


def ic_summary(ic_by_date):
    vals = np.array(list(ic_by_date.values()), dtype=float)
    if len(vals) == 0:
        return {"nDays": 0}
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean() / (sd / np.sqrt(len(vals)))) if sd > 0 else None
    return {"nDays": int(len(vals)), "icMean": round(float(vals.mean()), 5),
            "icStd": round(sd, 5), "icT": round(t, 3) if t is not None else None}


def yearly_breakdown(ic_by_date):
    by_year = {}
    for d, v in ic_by_date.items():
        by_year.setdefault(d[:4], []).append(v)
    out = {}
    for y, vals in sorted(by_year.items()):
        arr = np.array(vals, dtype=float)
        sd = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
        t = float(arr.mean() / (sd / np.sqrt(len(arr)))) if sd > 0 else None
        out[y] = {"nDays": len(arr), "icMean": round(float(arr.mean()), 5),
                  "icT": round(t, 3) if t is not None else None}
    return out


def daily_ic_series(df, feature, fwd_col, min_names=MIN_NAMES_PER_DATE):
    ic_by_date = {}
    for d, g in df.groupby("date"):
        gg = g[[feature, fwd_col]].dropna()
        if len(gg) < min_names:
            continue
        r = spearmanr(gg[feature].to_numpy(), gg[fwd_col].to_numpy())
        if not np.isnan(r.statistic):
            ic_by_date[d] = float(r.statistic)
    return ic_by_date


def monthly_rebalance_dates(dates):
    out, seen = [], set()
    for d in sorted(pd.unique(dates)):
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return set(out)


def decile_analysis(df, feature, rebal_dates):
    sub = df[df["date"].isin(rebal_dates)].dropna(subset=[feature]).copy()
    tables, spreads = {}, {}
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
        sp = []
        for d, gd in s.groupby("date"):
            top = gd[gd["decile"] == 10][h]
            bot = gd[gd["decile"] == 1][h]
            if len(top) and len(bot):
                sp.append(float(top.mean() - bot.mean()))
        spreads[h] = np.array(sp, dtype=float)
    mono = {}
    for h in DECILE_HORIZONS:
        means = [tables[h]["mean"][i] for i in range(1, 11)]
        rho = spearmanr(means, list(range(1, 11))).statistic
        sp = spreads[h]
        mono[h] = {
            "decileReturnSpearman": round(float(rho), 4),
            "pooledD10minusD1": round(float(tables[h]["mean"][10] - tables[h]["mean"][1]), 5),
            "monthlySpreadMean": round(float(np.mean(sp)), 5) if len(sp) else None,
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, NW_LAG_BY_HORIZON[h]),
            "nMonths": int(len(sp)),
        }
    return {"panelRows": int(len(sub)), "decileTables": tables, "monotonicitySpread": mono}


def avg_cross_corr(df, feat, other, rebal_dates=None):
    sub = df if rebal_dates is None else df[df["date"].isin(rebal_dates)]
    vals = []
    for d, g in sub[[feat, other, "date"]].dropna().groupby("date"):
        if len(g) < MIN_NAMES_PER_DATE:
            continue
        r = spearmanr(g[feat].to_numpy(), g[other].to_numpy())
        if not np.isnan(r.statistic):
            vals.append(float(r.statistic))
    return {"nDays": len(vals), "meanSpearman": round(float(np.mean(vals)), 4)} if vals else {"nDays": 0}


def conditioned_spread(df, feature, horizon, mask_col, rebal_dates):
    """버킷 내부 재-rank D10-D1 spread. mask_col은 사전 계산된 불리언 컬럼."""
    sub = df[df["date"].isin(rebal_dates)].dropna(subset=[feature, horizon])
    per_bucket = {}
    for d, gd in sub.groupby("date"):
        for b, gb in gd.groupby(mask_col):
            if len(gb) < MIN_NAMES_PER_BUCKET:
                continue
            gg = gb.copy()
            gg["decile"] = pd.qcut(gg[feature].rank(method="first"), 10, labels=False) + 1
            top = gg[gg["decile"] == 10][horizon]
            bot = gg[gg["decile"] == 1][horizon]
            if len(top) and len(bot):
                per_bucket.setdefault(bool(b), []).append(float(top.mean() - bot.mean()))
    out = {}
    for b, sp in per_bucket.items():
        label = "true" if b else "false"
        out[label] = {
            "nMonths": len(sp),
            "monthlySpreadMean": round(float(np.mean(sp)), 5),
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, NW_LAG_BY_HORIZON[horizon]),
        }
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 panel...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "total_amount",
                                           "fwd_d20", "fwd_d60", "fwd_d120"])
    dupes = int(panel.duplicated(subset=["ticker", "date"]).sum())
    if dupes:
        panel = panel.drop_duplicates(subset=["ticker", "date"], keep="last")
    wanted = set(panel["ticker"].unique())
    print(f"  panel rows={len(panel)}, tickers={len(wanted)}, dupesRemoved={dupes}")

    print("Streaming full A2a OHLC series per ticker...")
    full, stream_stats = load_full_ohlc(wanted)
    print(f"  tickers with OHLC series={len(full)}, "
          f"haltArtifactRowsExcluded={stream_stats['haltArtifactRowsExcluded']}"
          f"/{stream_stats['rowsReadTickerMatched']}")

    print("Computing ATR/volatility features on full session series...")
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)
    del frames
    print(f"  full-series rows={len(feats)}")

    print("PIT truncation check (full vs first-60% recompute)...")
    rows_map = {t: full[t] for t in sorted(full)}
    pit_dev = pit_truncation_check(rows_map)
    del rows_map
    print(f"  max |feature full-vs-truncated| = {pit_dev:.3e}")
    assert pit_dev < 1e-8, "PIT violation suspected"

    print("Joining onto panel + integrity check vs parquet fwd...")
    df = panel.merge(feats, on=["ticker", "date"], how="inner")
    integrity = {}
    for h in (20, 60, 120):
        a = df[f"fwd_d{h}_x"]
        b = df[f"fwd_d{h}_y"]
        m = a.notna() & b.notna()
        diff = (a[m] - b[m]).abs()
        integrity[f"d{h}"] = {
            "nCompared": int(m.sum()),
            "exactMatchRate": round(float((diff < 1e-12).mean()), 6),
            "nMismatched": int((diff >= 1e-12).sum()),
            "maxAbsDiff": round(float(diff.max()), 6),
        }
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])
    print("  " + ", ".join(f"{k}: match={v['exactMatchRate']}, mismatched={v['nMismatched']}, "
                           f"maxAbsDiff={v['maxAbsDiff']}" for k, v in integrity.items()))

    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["liq20"] = df.groupby("ticker", sort=False)["total_amount"].transform(
        lambda s: s.rolling(20, min_periods=10).mean())
    df["log_liq20"] = np.log(df["liq20"].clip(lower=1))
    df["liq_hi"] = df["liq20"] >= LIQ_THRESHOLD
    df["price_lo"] = df["close"] < PRICE_THRESHOLD
    rebal = monthly_rebalance_dates(df["date"])

    report = {
        "question": "Do ATR/Price and rolling volatility carry cross-sectional information about future KRX returns, "
                    "and is any effect separable from size/liquidity?",
        "existingEvidenceReviewed": [
            "reports/2026-08-17-post-5dc-factor-screening/README.md §7: Volatility·ATR listed as untested residual candidates.",
            "reports/2026-08-18-strategy-candidates/README.md §3: close-only vol20 Spearman(20D)=+0.07 mixed; only decile10 negative at fwd120.",
            "reports/2026-08-18-strategy-candidates/README.md §4: LOWVOL top-30 backtest CAGR -6.1%, MDD -51.3%; REV20+LOWVOL MDD improved to -35.6%.",
        ],
        "data": {
            "sampleSource": DATA,
            "featureBasis": "data/backfill/price/a2a/*.jsonl.gz full per-ticker session OHLC series",
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "features": {
                "atr14_pct": "Wilder ATR(14)/close*100, TR=gap-aware true range",
                "rv20_pct": "20-session log-return std *100 (daily %)",
                "rv60_pct": "60-session log-return std *100",
            },
            "warmupSessionsMaskedNaN": WARMUP,
            "forwardReturnConvention": "close[t+h]/close[t]-1 on full session calendar; signal at t close",
            "duplicatePanelRowsRemoved": dupes,
            "forwardReturnIntegrityRecheckVsParquet": integrity,
            "integrityNote": "본 스터디의 세션 캘린더는 거래정지 아티팩트 행(close>0, high=low=0)을 "
                             "제외해 만들었다(TR 무의미). parquet build는 close만 필터했으므로 그 행이 "
                             "forward window에 걸치는 소수 행에서 정의 차이가 난다 — exactMatchRate로 "
                             "영향 범위를 보고. feature 계산에는 제외가 필수적.",
            "streamStats": stream_stats,
            "pitTruncationMaxDeviation": pit_dev,
        },
        "caveats": [
            "Sample scope = A4 panel (A4 ∩ A2a coverage) ≈ currently-listed universe; same survivorship caveat as prior factor studies.",
            "Liquidity proxy is a row-based 20-panel-row mean of total_amount (approximation when price/A4 calendars differ); absolute threshold convention per CLAUDE.md 2026-08-21.",
            "Market cap unavailable (documented notComputable in a4-feature-summary.json) - price bucket + turnover proxy are the available size/liquidity clues.",
            "Overlapping forward windows are not independent; monthly spreads use Newey-West lag=h/21.",
            "No transaction costs - information content, not tradable net P&L.",
        ],
    }

    print("\n=== Feature loading on size/liquidity (daily cross-sectional Spearman mean) ===")
    load_block = {}
    for feat in CONT_FEATURES:
        load_block[feat] = {
            "vs_log_liq20": avg_cross_corr(df, feat, "log_liq20"),
            "vs_close": avg_cross_corr(df, feat, "close"),
        }
        lb = load_block[feat]
        print(f"  {feat}: corr(log_liq20)={lb['vs_log_liq20']['meanSpearman']}, "
              f"corr(close)={lb['vs_close']['meanSpearman']} (nDays={lb['vs_log_liq20']['nDays']})")
    report["featureLoading"] = load_block

    print("\n=== Daily cross-sectional IC ===")
    ic_block, ic_store = {}, {}
    for feat in CONT_FEATURES:
        for h in DECILE_HORIZONS:
            key = f"{feat}|{h}"
            ic_by_date = daily_ic_series(df, feat, h)
            ic_store[key] = ic_by_date
            ic_block[key] = ic_summary(ic_by_date)
            r = ic_block[key]
            if r.get("nDays"):
                print(f"  {feat:10s} vs {h}: IC={r['icMean']:+.5f} (t={r['icT']}, nDays={r['nDays']})")
    report["dailyIC"] = ic_block

    print("\n=== Yearly IC stability (vs fwd_d60) ===")
    year_block = {}
    for feat in CONT_FEATURES:
        key = f"{feat}|fwd_d60"
        year_block[key] = yearly_breakdown(ic_store[key])
        print(f"  {feat}: " + ", ".join(f"{y}:{v['icMean']:+.4f}" for y, v in year_block[key].items()))
    report["yearlyIC_vsD60"] = year_block

    print("\n=== Monthly-rebalance deciles (D10=highest vol) ===")
    decile_block = {}
    for feat in CONT_FEATURES:
        decile_block[feat] = decile_analysis(df, feat, rebal)
        for h in DECILE_HORIZONS:
            m = decile_block[feat]["monotonicitySpread"][h]
            print(f"  {feat:10s} {h}: D10-D1 pooled={m['pooledD10minusD1']:+.5f}, "
                  f"monthly mean={m['monthlySpreadMean']:+.5f}, naiveT={m['monthlySpreadNaiveT']}, "
                  f"NWT={m['monthlySpreadNWT']}, rho={m['decileReturnSpearman']:+.3f}")
    report["monthlyDeciles"] = decile_block

    print("\n=== Conditioned within-bucket D10-D1 (rv20_pct / atr14_pct) ===")
    cond_block = {}
    masks = [("liq_hi", "turnover>=1e8"), ("price_lo", "close<5000")]
    for feat in CONT_FEATURES:
        cond_block[feat] = {}
        for col, label in masks:
            cond_block[feat][label] = {}
            gd = df[df[col]]
            gb = df[~df[col]]
            for name, part in (("bucketTrue", gd), ("bucketFalse", gb)):
                res = conditioned_spread(part, feat, "fwd_d60", col, rebal)
                # within a single-mask frame the groupby yields one bucket; normalize keys
                vals = list(res.values())
                cond_block[feat][label][name] = vals[0] if vals else {"nMonths": 0}
                v = cond_block[feat][label][name]
                print(f"  {feat:10s} [{label}] {name}: months={v['nMonths']}, "
                      f"spread={v['monthlySpreadMean']}, NWT={v['monthlySpreadNWT']}")
    report["conditionedSpreads_vsD60"] = cond_block

    report["counts"] = {
        "minNamesPerDateForDecile": MIN_NAMES_PER_DATE,
        "minNamesPerBucket": MIN_NAMES_PER_BUCKET,
        "shareLiqHiAtMonthlyDates": round(float(df[df["date"].isin(rebal)]["liq_hi"].mean()), 4),
        "sharePriceLoAtMonthlyDates": round(float(df[df["date"].isin(rebal)]["price_lo"].mean()), 4),
    }

    out_path = os.path.join(OUT_DIR, "vol-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
