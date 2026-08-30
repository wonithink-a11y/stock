#!/usr/bin/env python
"""Liquidity / Trading Value cross-sectional factor ?뺣낫??寃利???A4 dataset 湲곕컲,
Momentum12M쨌MACD쨌Volatility ?곌뎄? ?숈씪 愿濡???낅┰ ?ы쁽.

紐⑹쟻: ?좊룞??嫄곕옒?湲댟룰굅?섎웾)??誘몃옒?섏씡瑜좎뿉 ?낅┰ ?뺣낫瑜?媛뽯뒗吏, ?덈떎硫?洹멸쾬???욎꽑 Volatility/ATR 寃곌낵???ы몴?꾩씤吏 ?먮퀎?쒕떎. production 臾대?寃? ???섏쭛 ?놁쓬,
而ㅻ컠 ?놁쓬.

湲곗〈 ?곌뎄 ?뺤씤 (以묐났 ?뚰뵾):
  - absolute_liquidity_decile_check.py: ?덈??꾧퀎媛?turnover20>=1?????듭젣蹂??    以묐┰??寃利???liquidity ?먯껜???⑺꽣 IC ?곌뎄 ?꾨떂.
  - strategy_candidate_factors.py liq_surge(5D/60D 嫄곕옒??鍮꾩쑉): "+0.32 ?쏀븿,
    ?좎쓽 援щ텇 ????(?⑤꼸??湲곕컲, NW t쨌議곌굔遺 遺꾪빐 ?놁쓬).
  - Trading Value ?덈꺼쨌嫄곕옒??湲곕컲 ?좊룞?깆쓽 IC 諛고꽣由щ뒗 湲곗〈???놁쓬 ???좉퇋.

feature (?꾨? 醫낅ぉ蹂?'?꾩껜 ?몄뀡 罹섎┛???먯꽌 怨꾩궛, warmup 40?몄뀡 NaN):
  dv20_log : log(理쒓렐 20?몄뀡 ?됯퇏 dollar volume = volume횞close). KRX 嫄곕옒?湲덉쓽
             close 洹쇱궗 ??parquet total_amount? ?쇰퀎 ?〓떒硫??곴??쇰줈 異⑹떎??蹂닿퀬.
  vv20_log : log(理쒓렐 20?몄뀡 ?됯퇏 嫄곕옒??二쇱떇??.
  surge_5_60 : mean(dollar vol, 5?몄뀡) / mean(dollar vol, 60?몄뀡) ???좊룞???쒖?.
  蹂댁“(議곌굔 遺꾪빐?? ?댁쟾 ?ㅽ꽣?붿? ?숈씪 ?뺤쓽): rv20_pct, atr14_pct,
  mom20/mom60(?⑥닚 ?섏씡瑜???REV20쨌LOWMOM60 ?뚰뙆 ?꾩튂 ?뺤씤??.

percentile 愿???뺤쭅 鍮꾧퀬: Spearman IC? decile? ?⑥“ 蹂?뺤뿉 遺덈??대?濡?"Trading Value percentile"? ?덈꺼怨??쒖쐞媛 ?꾩쟾 ?숈씪 ??蹂꾨룄 怨꾩궛?섏? ?딄퀬 臾몄꽌??
吏꾩쭨 turnover??TV/?쒖킑)? ?쒖킑 誘몄닔吏?notComputable)?대씪 遺덇?.

PIT: rolling backward留? ?덈떒 ?ш퀎???⑥뼵, ?뱀씪 ?좏샇?믩떦???섏씡 誘몄궗??
嫄곕옒?뺤? ?꾪떚?⑺듃(close>0쨌high=low=0) ???쒖쇅 ??vol ?ㅽ꽣?붿? ?숈씪, ?곹뼢?
exactMatchRate濡?蹂닿퀬.

?곗텧: reports/2026-08-26-liquidity-factor/liq-results.json (+stdout). 而ㅻ컠 ?놁쓬.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-liquidity-factor")

WARMUP = 40
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
LIQ_FEATURES = ["dv20_log", "vv20_log", "surge_5_60"]
MIN_NAMES_PER_DATE = 30
NW_LAG_BY_HORIZON = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}
LIQ_THRESHOLD = 1e8
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
            lst.append((rec["date"], float(rec["high"]), float(rec["low"]),
                        float(rec["close"]), float(rec["volume"])))
    return {t: sorted(v) for t, v in out.items() if v}, stats


def features_from_ohlc(rows):
    dates = [r[0] for r in rows]
    high = pd.Series([r[1] for r in rows], dtype=float)
    low = pd.Series([r[2] for r in rows], dtype=float)
    close = pd.Series([r[3] for r in rows], dtype=float)
    volume = pd.Series([r[4] for r in rows], dtype=float)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    atr = tr.ewm(alpha=1.0 / 14, adjust=False).mean()
    logret = np.log(close).diff()
    dollar_vol = volume * close
    dv20 = dollar_vol.rolling(20, min_periods=10).mean()
    dv5 = dollar_vol.rolling(5, min_periods=3).mean()
    out = pd.DataFrame({
        "date": dates,
        "close": close.to_numpy(),
        "rv20_pct": (logret.rolling(20).std() * 100.0).to_numpy(),
        "atr14_pct": (atr / close * 100.0).to_numpy(),
        "mom20": (close / close.shift(20) - 1).to_numpy(),
        "mom60": (close / close.shift(60) - 1).to_numpy(),
        "dv20_log": np.log(dv20.clip(lower=1)).to_numpy(),
        "vv20_log": np.log(volume.rolling(20, min_periods=10).mean().clip(lower=1)).to_numpy(),
        "surge_5_60": (dv5 / dollar_vol.rolling(60, min_periods=30).mean()).to_numpy(),
        "fwd_d20": (close.shift(-20) / close - 1).to_numpy(),
        "fwd_d60": (close.shift(-60) / close - 1).to_numpy(),
        "fwd_d120": (close.shift(-120) / close - 1).to_numpy(),
    })
    for c in ("rv20_pct", "atr14_pct", "dv20_log", "vv20_log", "surge_5_60"):
        out.loc[: WARMUP - 1, c] = np.nan
    return out


def pit_truncation_check(full_rows_by_ticker, sample=40):
    tickers = sorted(full_rows_by_ticker.keys())
    step = max(1, len(tickers) // sample)
    worst = 0.0
    for t in tickers[::step][:sample]:
        full = features_from_ohlc(full_rows_by_ticker[t])
        k = int(len(full) * 0.6)
        if k < WARMUP + 65:
            continue
        trunc = features_from_ohlc(full_rows_by_ticker[t][:k])
        for c in ("dv20_log", "vv20_log", "surge_5_60"):
            d = float(np.nanmax(np.abs(full[c].to_numpy()[:k] - trunc[c].to_numpy())))
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


def within_bucket_spread(part_df, feature, horizon, direction, rebal_dates,
                         min_names=MIN_NAMES_PER_DATE):
    """part_df???대? 踰꾪궥?쇰줈 ?꾪꽣???꾨젅?? '?붽컙 由щ갭?곗뒪 ?쒖젏'?쇰줈 ?쒖젙????    ?좎쭨蹂?decile hi-lo(?먮뒗 lo-hi) spread ?쒓퀎???듦퀎."""
    part_df = part_df[part_df["date"].isin(rebal_dates)]
    sp = []
    for d, gd in part_df.groupby("date"):
        gg = gd[[feature, horizon]].dropna()
        if len(gg) < min_names:
            continue
        dec = pd.qcut(gg[feature].rank(method="first"), 10, labels=False).to_numpy() + 1
        vals = gg[horizon].to_numpy()
        top = vals[dec == 10]
        bot = vals[dec == 1]
        if len(top) and len(bot):
            v = (top.mean() - bot.mean()) if direction == "high_minus_low" else (bot.mean() - top.mean())
            sp.append(float(v))
    lag = NW_LAG_BY_HORIZON[horizon]
    return {"nMonths": len(sp),
            "monthlySpreadMean": round(float(np.mean(sp)), 5) if sp else None,
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, lag)}


def conditional_both_buckets(df, mask_col, feature, horizon, direction, rebal_dates):
    out = {}
    m = df[mask_col].notna()
    for name, flag in (("bucketTrue", True), ("bucketFalse", False)):
        part = df[m & (df[mask_col] == flag)]
        out[name] = within_bucket_spread(part, feature, horizon, direction, rebal_dates)
    return out


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

    print("Streaming full A2a OHLCV series...")
    full, stream_stats = load_full_ohlc(wanted)
    print(f"  tickers={len(full)}, haltArtifactRowsExcluded="
          f"{stream_stats['haltArtifactRowsExcluded']}/{stream_stats['rowsReadTickerMatched']}")

    print("Computing liquidity + auxiliary features on full session series...")
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)
    del frames

    print("PIT truncation check...")
    rows_map = dict(full)
    pit_dev = pit_truncation_check(rows_map)
    del rows_map, full
    print(f"  max |feature full-vs-truncated| = {pit_dev:.3e}")
    assert pit_dev < 1e-8, "PIT violation suspected"

    print("Joining onto panel + integrity + proxy fidelity...")
    df = panel.merge(feats, on=["ticker", "date"], how="inner")
    integrity = {}
    for h in (20, 60, 120):
        a, b = df[f"fwd_d{h}_x"], df[f"fwd_d{h}_y"]
        m = a.notna() & b.notna()
        diff = (a[m] - b[m]).abs()
        integrity[f"d{h}"] = {"nCompared": int(m.sum()),
                              "exactMatchRate": round(float((diff < 1e-12).mean()), 6),
                              "nMismatched": int((diff >= 1e-12).sum()),
                              "maxAbsDiff": round(float(diff.max()), 6)}
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])
    print("  " + ", ".join(f"{k}: match={v['exactMatchRate']}" for k, v in integrity.items()))

    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    pa_tv20 = df.groupby("ticker", sort=False)["total_amount"].transform(
        lambda s: s.rolling(20, min_periods=10).mean())
    df["pa_tv20_log"] = np.log(pa_tv20.clip(lower=1))
    df["liq20"] = pa_tv20
    df["liq20_log"] = df["pa_tv20_log"]

    def nullable_mask(col, expr):
        base = df[col]
        out = pd.Series(pd.NA, index=df.index, dtype="object")
        mm = base.notna()
        out.loc[mm] = expr(mm)
        return out

    med_rv = df.groupby("date")["rv20_pct"].transform("median")
    df["rv_hi"] = nullable_mask("rv20_pct", lambda mm: df.loc[mm, "rv20_pct"] > med_rv[mm])
    df["liq_hi"] = nullable_mask("liq20", lambda mm: df.loc[mm, "liq20"] >= LIQ_THRESHOLD)
    rebal = monthly_rebalance_dates(df["date"])

    report = {
        "question": "Does liquidity (trading value / volume) carry independent cross-sectional information "
                    "about future KRX returns, or is it a re-expression of the volatility effect?",
        "existingEvidenceReviewed": [
            "absolute_liquidity_decile_check.py: absolute-threshold neutrality as CONTROL variable, not a factor IC study.",
            "strategy_candidate_factors.py liq_surge (volume 5d/60d): screened weak (+0.32 mixed), row-based, no NW-t.",
            "volatility-atr-factor-a4-2026-08.md: corr(rv20, log_turnover)=+0.56; low-vol effect survives within liquid bucket; illiquid bucket reverses (+8~9%p/month).",
        ],
        "data": {
            "sampleSource": DATA,
            "featureBasis": "data/backfill/price/a2a/*.jsonl.gz full session OHLCV; dollar volume = volume*close (KRX 嫄곕옒?湲?close 洹쇱궗)",
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "features": {
                "dv20_log": "log(20-session mean volume*close)",
                "vv20_log": "log(20-session mean share volume)",
                "surge_5_60": "mean($vol,5)/mean($vol,60)",
            },
            "percentileNote": "Rank-based IC/deciles are invariant to monotone percentile transforms - TV percentile == TV level under this battery; true turnover ratio impossible without shares outstanding (notComputable).",
            "warmupSessionsMaskedNaN": WARMUP,
            "haltArtifactRowsExcluded": stream_stats,
            "forwardReturnIntegrityRecheckVsParquet": integrity,
            "pitTruncationMaxDeviation": pit_dev,
        },
        "caveats": [
            "Sample scope = A4 panel ??currently-listed universe (same survivorship caveat as prior studies).",
            "dollar volume uses close as price proxy for KRX 嫄곕옒?湲? fidelity vs parquet total_amount reported below.",
            "Market cap unavailable -> no true turnover ratio; liquidity buckets via absolute threshold 1?듭썝 (established convention).",
            "Overlapping windows; Newey-West lag=h/21. No transaction costs.",
        ],
    }

    print("\n=== Proxy fidelity + loading correlations ===")
    fid = avg_cross_corr(df, "dv20_log", "pa_tv20_log")
    report["proxyFidelity"] = {"dv20_log_vs_parquetTotalAmount20": fid}
    load_block = {}
    for pair in (("dv20_log", "rv20_pct"), ("dv20_log", "atr14_pct"), ("vv20_log", "rv20_pct"),
                 ("surge_5_60", "rv20_pct")):
        load_block[f"{pair[0]}|{pair[1]}"] = avg_cross_corr(df, pair[0], pair[1])
        r = load_block[f"{pair[0]}|{pair[1]}"]
        print(f"  corr({pair[0]}, {pair[1]}) = {r.get('meanSpearman')} (nDays={r['nDays']})")
    report["loadingCorrelations"] = load_block

    print("\n=== Daily cross-sectional IC ===")
    ic_block, ic_store = {}, {}
    for feat in LIQ_FEATURES:
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
    for feat in LIQ_FEATURES:
        year_block[f"{feat}|fwd_d60"] = yearly_breakdown(ic_store[f"{feat}|fwd_d60"])
        print(f"  {feat}: " + ", ".join(f"{y}:{v['icMean']:+.4f}" for y, v in year_block[f"{feat}|fwd_d60"].items()))
    report["yearlyIC_vsD60"] = year_block

    print("\n=== Monthly-rebalance deciles ===")
    decile_block = {}
    for feat in LIQ_FEATURES:
        decile_block[feat] = decile_analysis(df, feat, rebal)
        for h in DECILE_HORIZONS:
            m = decile_block[feat]["monotonicitySpread"][h]
            print(f"  {feat:10s} {h}: D10-D1 pooled={m['pooledD10minusD1']:+.5f}, "
                  f"monthly={m['monthlySpreadMean']:+.5f}, NWT={m['monthlySpreadNWT']}, rho={m['decileReturnSpearman']:+.3f}")
    report["monthlyDeciles"] = decile_block

    print("\n=== Independence test 1: volatility effect within liquidity buckets (d60) ===")
    indep1 = {}
    for h in DECILE_HORIZONS:
        indep1[h] = conditional_both_buckets(df, "liq_hi", "rv20_pct", h, "low_minus_high", rebal)
        for bk, v in indep1[h].items():
            print(f"  {h} [{bk}]: low-vol-minus-high = {v['monthlySpreadMean']:+.5f}, NWT={v['monthlySpreadNWT']} (months={v['nMonths']})")
    report["volEffectWithinLiqBuckets"] = indep1

    print("\n=== Independence test 2: liquidity effect within volatility halves (median split) ===")
    indep2 = {}
    for h in DECILE_HORIZONS:
        indep2[h] = conditional_both_buckets(df, "rv_hi", "dv20_log", h, "high_minus_low", rebal)
        for bk, v in indep2[h].items():
            print(f"  {h} [{bk}]: high-TV-minus-low-TV = {v['monthlySpreadMean']:+.5f}, NWT={v['monthlySpreadNWT']} (months={v['nMonths']})")
    report["tvEffectWithinVolHalves"] = indep2

    print("\n=== Prior-signal alpha location: reversal/momentum within liquidity buckets ===")
    sigloc = {}
    for label, feat, direction, hs in (
            ("mom60_lowPremium(LOWMOM60)", "mom60", "low_minus_high", ("fwd_d60", "fwd_d120")),
            ("mom20_reversal(REV20)", "mom20", "low_minus_high", ("fwd_d20", "fwd_d60"))):
        sigloc[label] = {}
        for h in hs:
            sigloc[label][h] = conditional_both_buckets(df, "liq_hi", feat, h, direction, rebal)
            for bk, v in sigloc[label][h].items():
                print(f"  {label} {h} [{bk}]: {v['monthlySpreadMean']:+.5f}, NWT={v['monthlySpreadNWT']} (months={v['nMonths']})")
    report["priorSignalAlphaLocation"] = sigloc

    rb = df[df["date"].isin(rebal)]
    report["counts"] = {
        "shareLiqHiAtMonthlyDates": round(float(rb["liq_hi"].dropna().astype(bool).mean()), 4),
        "shareRvHiAtMonthlyDates": round(float(rb["rv_hi"].dropna().astype(bool).mean()), 4),
    }

    out_path = os.path.join(OUT_DIR, "liq-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()

