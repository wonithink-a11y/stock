#!/usr/bin/env python
"""DD252(skip-1m) survivorship 재검증 — A1A_ONLY vs A1A_A1B_MERGED.

질문: A4 current universe에서 발견된 dd_from_high_252 효과(6M, 고점근접 프리미엄)가
survivorship bias 때문인가? lowmom60_survivorship.py와 동일한 패널 구축 방식
(UniverseProvider include_delisted 플래그 + A2a/A2b 병합, A2b는
quality-excluded·delisted-exit 파일 제외)으로 두 유니버스를 만들고, 같은 분석
기계(월초 리밸런스, 날짜별 qcut decile, daily Spearman IC, NW t)로 비교한다.

feature (dd_factor_followup_study.py 권장 정의 그대로):
  dd_252_skip1m = close[t-21] / max(close[t-252..t-21]) - 1   (신호 창은 t-21까지,
                  forward return은 t 종가 대비 — JT skip 관례)
  mom252        = close[t]/close[t-252] - 1 (raw12m, 독립성 재확인용 control)

horizon: fwd_d20/d60/d80/d120 (1M/3M/4M/6M — 직전 연구에서 효과가 d80~d120에
나타났으므로 4M을 추가). 조합 전략·백테스트 없음, production 무변경.

PIT: feature는 전부 trailing(shift+rolling), 앞 60% 절단 재계산 일치 단언.
forward return은 t 이후 close만 사용. 상장폐지 종목은 시계열이 끝기 전 구간에서만
자연스럽게 표본에 들어온다(미래 NaN → 해당 horizon에서 drop).

산출: reports/2026-08-26-dd252-survivorship/dd252-survivorship-results.json
"""
import gzip
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-04", "2026-08-03"
HORIZONS = {"fwd_d20": 20, "fwd_d60": 60, "fwd_d80": 80, "fwd_d120": 120}
NW_LAG = {"fwd_d20": 2, "fwd_d60": 3, "fwd_d80": 4, "fwd_d120": 6}
MIN_NAMES_PER_DATE = 30
FEATURES = ("dd_252_skip1m", "mom252")
A2B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2b")
A2B_SCHEMA = ("ticker", "date", "open", "high", "low", "close", "volume")
A2B_SKIP_FILES = {"price-quality-excluded.jsonl.gz", "delisted-exit.jsonl.gz"}
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-dd252-survivorship")


def load_a2b(a1b_tickers):
    """lowmom60_survivorship.py와 동일: A2b 연도별 jsonl.gz에서 A1B 종목만."""
    a1b_tickers = set(a1b_tickers)
    buffers = {t: [] for t in a1b_tickers}
    files = [f for f in os.listdir(A2B_DIR) if f.endswith(".jsonl.gz") and f not in A2B_SKIP_FILES]
    for fn in sorted(files):
        with gzip.open(os.path.join(A2B_DIR, fn), "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row["ticker"] not in buffers:
                    continue
                missing = [k for k in A2B_SCHEMA if k not in row]
                if missing:
                    raise ValueError(f"A2b schema violation: missing {missing}")
                buffers[row["ticker"]].append(row)
    result = {}
    for t, rows in buffers.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").set_index("date")
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype("float64")
        result[t] = df[["open", "high", "low", "close"]]
    return result


def build_panel(bars_by_ticker):
    frames = []
    for t, bars in bars_by_ticker.items():
        if bars.empty or "close" not in bars:
            continue
        s = bars["close"]
        s = s[s > 0].dropna()
        if s.empty:
            continue
        frames.append(pd.DataFrame({"ticker": t, "date": s.index.astype(str),
                                    "close": s.to_numpy(dtype=float)}))
    return pd.concat(frames, ignore_index=True)


def add_features(df):
    """ticker별 정렬 후 dd_252_skip1m / mom252 부착. 전부 trailing."""
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)

    def per_ticker(s):
        lag = s.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        mom = s / s.shift(252) - 1.0
        out = pd.DataFrame({"dd_252_skip1m": dd, "mom252": mom})
        for h in HORIZONS.values():
            out[f"fwd_d{h}"] = s.shift(-h) / s - 1.0
        return out

    res = df.groupby("ticker", sort=False)["close"].apply(per_ticker).reset_index(level=0, drop=True)
    for col in res.columns:
        df[col] = res[col]
    return df


def pit_truncation_check(df, sample=40):
    tickers = sorted(df["ticker"].unique())
    step = max(1, len(tickers) // sample)
    chosen = tickers[::step][:sample]
    worst = {f: 0.0 for f in FEATURES}
    for t in chosen:
        sub = df[df["ticker"] == t].sort_values("date")
        k = int(len(sub) * 0.6)
        if k < 273:
            continue
        trunc = add_features(sub.iloc[:k].copy())
        for f in FEATURES:
            full = sub.iloc[:k][f].to_numpy()
            got = trunc[f].to_numpy()
            m = ~np.isnan(full) & ~np.isnan(got)
            if m.any():
                worst[f] = max(worst[f], float(np.abs(full[m] - got[m]).max()))
    return worst


def summarize(recs):
    if not recs:
        return {"n": 0}
    vals = np.array([v for _, v in recs], dtype=float)
    sd = float(vals.std(ddof=1)) if len(vals) > 1 else 0.0
    t = float(vals.mean() / (sd / np.sqrt(len(vals)))) if sd > 0 else None
    by_year = {}
    for d, v in recs:
        by_year.setdefault(d[:4], []).append(v)
    return {"n": len(vals), "mean": round(float(vals.mean()), 5), "std": round(sd, 5),
            "tNaive": round(t, 3) if t is not None else None,
            "sharePositive": round(float((vals > 0).mean()), 4),
            "yearlyMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())}}


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


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return set(out)


def daily_ic(df, feat, h):
    arr = df[["date", feat, h]].dropna()
    recs = []
    for d, gd in arr.groupby("date"):
        if len(gd) < MIN_NAMES_PER_DATE:
            continue
        r = spearmanr(gd[feat].to_numpy(), gd[h].to_numpy())
        if not np.isnan(r.statistic):
            recs.append((d, float(r.statistic)))
    return summarize(recs)


def orth_ic(df, feat, ctrl, h):
    arr = df[["date", feat, ctrl, h]].dropna(subset=[feat, ctrl])
    recs = []
    for d, gd in arr.groupby("date"):
        gg = gd[[feat, ctrl, h]].dropna()
        if len(gg) < 50:
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
    return summarize(recs)


def decile_analysis(df, feat, rebal):
    sub = df[df["date"].isin(rebal)].dropna(subset=[feat]).copy()
    out = {}
    for h in HORIZONS:
        s = sub.dropna(subset=[h]).copy()

        def _q(grp):
            if len(grp) < MIN_NAMES_PER_DATE:
                grp["decile"] = np.nan
                return grp
            grp["decile"] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp

        s = s.groupby("date", group_keys=False).apply(_q)
        s = s.dropna(subset=["decile"])
        s["decile"] = s["decile"].astype(int)
        agg = s.groupby("decile")[h].agg(["count", "mean", "median"])
        win = s.groupby("decile")[h].apply(lambda x: float((x > 0).mean()))
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
        means = [float(agg.loc[i, "mean"]) if i in agg.index else None for i in range(1, 11)]
        rho = None
        if all(m is not None for m in means):
            r = spearmanr(means, list(range(1, 11)))
            rho = round(float(r.statistic), 4) if not np.isnan(r.statistic) else None
        out[h] = {
            "panelRows": int(len(s)),
            "nMonths": int(len(sp)),
            "decileMeanD1toD10": [round(m, 5) for m in means],
            "decileWinrateD1toD10": [round(float(win.loc[i]), 4) if i in win.index else None for i in range(1, 11)],
            "countsPerDecile": {int(i): int(agg.loc[i, "count"]) for i in agg.index},
            "monotonicityRho": round(float(rho), 4) if rho is not None and not np.isnan(rho) else None,
            "pooledD10minusD1": round(float(means[-1] - means[0]), 5),
            "monthlySpreadMean": round(float(np.nanmean(sp)), 5) if len(sp) else None,
            "monthlySpreadNWT": newey_west_t(sp, NW_LAG[h]),
            "yearlySpreadMean": {y: round(float(np.mean(v)), 5) for y, v in sorted(by_year.items())},
        }
    return out


def analyze_panel(df, rebal, label):
    print(f"\n--- panel[{label}]: rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"period={df['date'].min()}~{df['date'].max()} ---")
    df = add_features(df)
    dev = pit_truncation_check(df)
    for f, v in dev.items():
        print(f"  PIT truncation max dev [{f}] = {v:.3e}")
        assert v < 1e-8, f"PIT violation in {f}"
    block = {
        "rows": int(len(df)),
        "tickers": int(df["ticker"].nunique()),
        "period": [str(df["date"].min()), str(df["date"].max())],
        "pitTruncationMaxDeviation": {f: float(v) for f, v in dev.items()},
        "dailyIC": {}, "monthlyDeciles": {}, "orthogonalIC": {},
    }
    for feat in FEATURES:
        for h in HORIZONS:
            ic = daily_ic(df, feat, h)
            block["dailyIC"][f"{feat}|{h}"] = ic
            print(f"  IC {feat:14s} {h}: mean={ic.get('mean'):+.5f} (t={ic.get('tNaive')}, n={ic.get('n')})")
        block["monthlyDeciles"][feat] = decile_analysis(df, feat, rebal)
        for h in HORIZONS:
            m = block["monthlyDeciles"][feat][h]
            print(f"  DEC {feat:14s} {h}: D10-D1 pooled={m['pooledD10minusD1']:+.5f}, "
                  f"monthly={m['monthlySpreadMean']:+.5f}, NWT={m['monthlySpreadNWT']}, "
                  f"rho={m['monotonicityRho']}, months={m['nMonths']}")
    for h in HORIZONS:
        o = orth_ic(df, "dd_252_skip1m", "mom252", h)
        block["orthogonalIC"][f"dd_252_skip1m|mom252|{h}"] = o
        print(f"  ORTH dd_252_skip1m|mom252 {h}: mean={o.get('mean'):+.5f} (t={o.get('tNaive')})")
    return block


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    rebal = monthly_rebalance_dates(calendar, START, END)
    print(f"rebalance dates: {len(rebal)} ({min(rebal)}~{max(rebal)})")

    universe_a1a = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    print(f"A1A tickers={len(universe_a1a.tickers)}; loading A2a prices...")
    bars_a1a = a2a.load(set(universe_a1a.tickers), START, END, universe_hash=universe_a1a.universe_hash)
    bars_a1a = {t: _drop_suspension_rows(dfx) for t, dfx in bars_a1a.items()}
    panel_a1a = build_panel(bars_a1a)
    del bars_a1a
    res_a1a = analyze_panel(panel_a1a, rebal, "A1A_ONLY(current)")
    del panel_a1a

    universe_merged = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    a1b_tickers = {e.ticker for e in universe_merged.entries if e.source == "A1B"}
    print(f"\nLoading A2b (delisted) bars for {len(a1b_tickers)} A1B tickers...")
    bars_a1b = load_a2b(a1b_tickers)
    bars_a1b = {t: _drop_suspension_rows(dfx) for t, dfx in bars_a1b.items()}
    print(f"A2b loaded={len(bars_a1b)} tickers")
    a2a2 = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_mrg = a2a2.load(set(universe_merged.tickers), START, END, universe_hash=universe_merged.universe_hash)
    bars_mrg = {t: _drop_suspension_rows(dfx) for t, dfx in bars_mrg.items()}
    merged = dict(bars_mrg)
    merged.update(bars_a1b)
    panel_mrg = build_panel(merged)
    del bars_mrg, merged, bars_a1b
    res_mrg = analyze_panel(panel_mrg, rebal, "A1A_A1B_MERGED")
    del panel_mrg

    report = {
        "question": ("Does the DD252 (skip-1m) effect survive adding delisted stocks? "
                     "A1A_ONLY vs A1A_A1B_MERGED, identical machinery."),
        "featureDefinition": {
            "dd_252_skip1m": "close[t-21]/max(close[t-252..t-21]) - 1",
            "mom252": "close[t]/close[t-252] - 1",
        },
        "config": {
            "start": START, "end": END, "horizonsDays": list(HORIZONS.values()),
            "rebalanceDates": len(rebal), "minNamesPerDate": MIN_NAMES_PER_DATE,
            "panelConstruction": "lowmom60_survivorship.py 방식: UniverseProvider(include_delisted) + A2a + A2b(quality-excluded/delisted-exit 제외)",
        },
        "panels": {"A1A_ONLY": res_a1a, "A1A_A1B_MERGED": res_mrg},
        "referencePriorResults": {
            "note": "이전 A4-parquet 기반 연구(dd_factor_followup_study)의 dd_252_skip1m 참고값 — 패널 구성이 달라 수치는 근사 비교용",
            "fwd_d120_dailyIC_mean": 0.06566, "fwd_d120_dailyIC_t": 32.821,
            "fwd_d120_spreadMonthlyMean": 0.04253, "fwd_d120_spreadNWT": 2.631,
        },
        "caveats": [
            "Forward returns are row-shifted within each ticker's post-suspension-filter session sequence; long-halted tickers can slightly differ from a calendar-session definition.",
            "A2b coverage is whatever has been collected so far (same caveat as lowmom60_survivorship); some A1B tickers may lack price history.",
            "Survivorship direction note: delisted names enter the panel only up to their last session; forward returns near the end of a delisted ticker's series are NaN and drop out of that horizon.",
            "Overlapping windows; monthly spreads use Newey-West lag=h/21. No costs, no strategy backtest.",
        ],
    }
    out_path = os.path.join(OUT_DIR, "dd252-survivorship-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
