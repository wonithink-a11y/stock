#!/usr/bin/env python
"""MACD(12,26,9) 정보력 검증 — A4 research dataset 기반, Momentum12M decile 연구와
동일 관례의 독립 재현.

목적: MACD 전략 채택이 아니라, MACD feature가 향후 주가수익률에 독립 정보를
갖는지 확인한다. production/scoring engine은 일절 건드리지 않고, 새 데이터 수집도
없다.

데이터 구성 (v2):
  - 특징값 계열은 research/strategy-lab/data/a4/a4-research-dataset.parquet(A2a
    adjusted close + PIT 규약의 fwd_d20/d60/d120 내장)의 (ticker, date) 표본이다.
  - 단, v1 실행에서 무결성 대조가 드러낸 사실: parquet의 forward return과 MACD가
    참조해야 할 시계열은 '종목별 전체 가격 세션 캘린더'(data/backfill/price/a2a,
    결측 없는 매 세션)다. A4 패널 행만 세면 가격-패널 갭이 누적돼 h번째 관측이
    h거래일 뒤와 달라진다(max abs diff 22 실측). 그래서 v2는 A2a 원본 gz를
    build_a4_research_dataset.py와 같은 방식으로 스트리밍해 종목별 전체 종가
    계열 위에서 MACD와 모든 forward return을 계산하고, 패널 행에 조인한다.
    parquet fwd_d20/d60/d120와의 재대조는 이제 정의 동일성 검증(~0 수렴)이 된다.

검증 대상 (지시서 1~5):
  1. MACD>0 / <=0 상태 분할 (월간 리밸런스 시점)
  2. zero-line bullish/bearish cross → 5/20/60 거래일 event study
  3. MACD-Signal bullish/bearish cross → 5/20/60 거래일 event study
  4. histogram level(hist_pct) 및 변화량(hist_chg_5d)
  5. MACD slope(macd_slope_5d)

관례 재사용 출처:
  - 월간 리밸런스·날짜별 qcut decile·양/음 분할·decile-return Spearman:
    momentum_decile_analysis.py (Momentum12M)
  - 일별 cross-sectional Spearman IC + t=mean/(std/sqrt(nDays)):
    analyze_a4_research.py
  - forward return 정의 close[t+h]/close[t]-1 (신호는 t 종가, 수익은 t 이후):
    build_a4_research_dataset.py의 PIT 규약과 동일

PIT 설계:
  - EMA는 ewm(span, adjust=False) 순차 재귀 — t값은 t까지 데이터의 함수.
    "앞 60%만 잘라 재계산 == 전체 계열 값" 단언으로 경험적 검증.
  - cross 판정도 t와 t-1 두 값만 사용. 당일 신호를 당일 수익률에 사용 안 함.
  - event study의 유의성은 같은 날짜 전체 횡단면 평균과의 초과수익(excess)을
    날짜 클러스터 단위로 검정한다(시장 drift·국면 혼입 분리).

주가 스케일 문제: macd/hist 절대값은 주가 크기에 비례하므로 횡단면 feature는
전부 /close*100 백분율 정규화(macd_pct, hist_pct, 그 5일 변화량). 원값은
부호 상태·cross 판정에만 사용. MACD divergence는 지시대로 제외.

산출: reports/2026-08-26-macd-information-content/macd-results.json (+stdout).
data/backfill 읽기 전용(CLAUDE.md 규칙 4), production 무변경.
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-macd-information-content")

FAST, SLOW, SIGNAL = 12, 26, 9
SLOPE_WIN = 5
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]  # 1M / 3M / 6M (거래일)
EVENT_HORIZONS = ["fwd_d5", "fwd_d20", "fwd_d60"]     # 5 / 20 / 60 거래일
CONT_FEATURES = ["macd_pct", "hist_pct", "hist_chg_5d", "macd_slope_5d"]
MIN_NAMES_PER_DATE = 30   # momentum_decile_analysis의 N_DECILES*3 가드와 동일
NW_LAG_BY_HORIZON = {"fwd_d5": 1, "fwd_d20": 2, "fwd_d60": 3, "fwd_d120": 6}
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


def load_full_closes(tickers_wanted):
    """A2a 원본에서 종목별 전체 세션 종가 계열(정렬 dict)을 스트리밍 수집."""
    closes = {t: {} for t in tickers_wanted}
    for year in A2A_YEARS:
        path = os.path.join(A2A_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(path):
            continue
        for rec in read_gz_jsonl(path):
            t = rec["ticker"]
            dmap = closes.get(t)
            if dmap is not None and rec["close"] and rec["close"] > 0:
                dmap[rec["date"]] = float(rec["close"])
    return {t: dict(sorted(d.items())) for t, d in closes.items() if d}


def macd_from_close_series(close_series):
    """dict(date->close) 1개 종목 → DataFrame(date, close, macd, signal, hist,
    정규화 feature, 상태/cross 플래그, fwd_d5/20/60/120)."""
    dates = list(close_series.keys())
    close = pd.Series([close_series[d] for d in dates], index=dates, dtype=float)
    ema_fast = close.ewm(span=FAST, adjust=False).mean()
    ema_slow = close.ewm(span=SLOW, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=SIGNAL, adjust=False).mean()
    hist = macd - signal
    out = pd.DataFrame({
        "date": dates,
        "close": close.to_numpy(),
        "macd": macd.to_numpy(),
        "signal": signal.to_numpy(),
        "hist": hist.to_numpy(),
        "fwd_d5": (close.shift(-5) / close - 1).to_numpy(),
        "fwd_d20": (close.shift(-20) / close - 1).to_numpy(),
        "fwd_d60": (close.shift(-60) / close - 1).to_numpy(),
        "fwd_d120": (close.shift(-120) / close - 1).to_numpy(),
    })
    out["macd_pct"] = out["macd"] / out["close"] * 100.0
    out["hist_pct"] = out["hist"] / out["close"] * 100.0
    out["hist_chg_5d"] = out["hist_pct"].diff(SLOPE_WIN)
    out["macd_slope_5d"] = out["macd_pct"].diff(SLOPE_WIN)
    prev_macd = macd.shift(1)
    prev_signal = signal.shift(1)
    out["macd_pos"] = (macd > 0).to_numpy()
    out["zero_cross_up"] = ((macd > 0) & (prev_macd <= 0)).to_numpy()
    out["zero_cross_dn"] = ((macd < 0) & (prev_macd >= 0)).to_numpy()
    out["sig_cross_up"] = ((macd > signal) & (prev_macd <= prev_signal)).to_numpy()
    out["sig_cross_dn"] = ((macd < signal) & (prev_macd >= prev_signal)).to_numpy()
    return out


def pit_truncation_check(full_closes, sample=40):
    """전체 계열로 만든 macd_pct와 '앞 60%만 잘라낸 계열'로 다시 만든 값이 겹치는
    구간에서 완전히 같아야 한다(look-ahead 없음의 경험적 증명)."""
    tickers = sorted(full_closes.keys())
    step = max(1, len(tickers) // sample)
    worst = 0.0
    for t in tickers[::step][:sample]:
        full = macd_from_close_series(full_closes[t])
        k = int(len(full) * 0.6)
        if k < SLOW + SIGNAL:
            continue
        trunc = macd_from_close_series(dict(list(full_closes[t].items())[:k]))
        d = float(np.nanmax(np.abs(
            full["macd_pct"].to_numpy()[:k] - trunc["macd_pct"].to_numpy())))
        worst = max(worst, d)
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
    tables = {}
    spreads = {}
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
        lag = NW_LAG_BY_HORIZON[h]
        mono[h] = {
            "decileReturnSpearman": round(float(rho), 4),
            "pooledD10minusD1": round(float(tables[h]["mean"][10] - tables[h]["mean"][1]), 5),
            "monthlySpreadMean": round(float(np.mean(sp)), 5) if len(sp) else None,
            "monthlySpreadNaiveT": naive_t(sp),
            "monthlySpreadNWT": newey_west_t(sp, lag),
            "nMonths": int(len(sp)),
        }
    return {"panelRows": int(len(sub)), "decileTables": tables, "monotonicitySpread": mono}


def binary_state_split(df, state_col, rebal_dates):
    sub = df[df["date"].isin(rebal_dates)].dropna(subset=[state_col]).copy()
    out = {}
    for h in DECILE_HORIZONS:
        s = sub.dropna(subset=[h])
        pos = s[s[state_col]][h]
        neg = s[~s[state_col]][h]
        diffs = []
        for d, gd in s.groupby("date"):
            p = gd[gd[state_col]][h]
            n_ = gd[~gd[state_col]][h]
            if len(p) >= 5 and len(n_) >= 5:
                diffs.append(float(p.mean() - n_.mean()))
        lag = NW_LAG_BY_HORIZON[h]
        out[h] = {
            "nPos": int(len(pos)), "nNeg": int(len(neg)),
            "meanPos": round(float(pos.mean()), 5), "meanNeg": round(float(neg.mean()), 5),
            "winratePos": round(float((pos > 0).mean()), 4),
            "winrateNeg": round(float((neg > 0).mean()), 4),
            "monthlyDiffMean": round(float(np.mean(diffs)), 5) if diffs else None,
            "monthlyDiffNaiveT": naive_t(diffs), "monthlyDiffNWT": newey_west_t(diffs, lag),
            "nMonths": len(diffs),
        }
    return out


def event_study(df, event_col, horizons):
    """유의성 기준: 같은 날짜 전체 횡단면 평균 대비 초과수익을 날짜별로 묶어 검정.
    raw 평균은 시장 drift를 포함하므로 보조 정보로만 남긴다."""
    ev = df[df[event_col]]
    out = {"nEvents": int(len(ev))}
    for h in horizons:
        e = ev[[h, "date"]].dropna()
        if len(e) == 0:
            continue
        all_day = df[h].groupby(df["date"]).mean()
        day_counts = df.groupby("date").size()
        by_day = e.groupby("date")[h].mean()
        common = [d for d in by_day.index.intersection(all_day.index)
                  if day_counts.get(d, 0) >= MIN_NAMES_PER_DATE]
        excess_daily = (by_day[common] - all_day[common]).to_numpy()
        out[h] = {
            "n": int(len(e)), "nEventDays": int(len(by_day)),
            "rawMean": round(float(e[h].mean()), 5),
            "rawMedian": round(float(e[h].median()), 5),
            "winrate": round(float((e[h] > 0).mean()), 4),
            "unconditionalMeanAllRows": round(float(df[h].mean()), 5),
            "excessVsSameDateCrossSectionMean": round(float(np.mean(excess_daily)), 5) if len(excess_daily) else None,
            "excessDayClusteredT": naive_t(excess_daily),
            "nExcessDays": int(len(excess_daily)),
        }
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("Loading A4 panel (sample definition)...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    dupes = int(panel.duplicated(subset=["ticker", "date"]).sum())
    if dupes:
        panel = panel.drop_duplicates(subset=["ticker", "date"], keep="last")
    wanted = set(panel["ticker"].unique())
    print(f"  panel rows={len(panel)}, tickers={len(wanted)}, dupesRemoved={dupes}")

    print("Streaming full A2a close series per ticker...")
    full_closes = load_full_closes(wanted)
    print(f"  tickers with price series={len(full_closes)}")

    print("Computing MACD + forward returns on full session series...")
    feat_frames = []
    for t, cs in full_closes.items():
        f = macd_from_close_series(cs)
        f.insert(0, "ticker", t)
        feat_frames.append(f)
    feats = pd.concat(feat_frames, ignore_index=True)
    del full_closes, feat_frames

    print(f"  full-series rows={len(feats)}")

    print("PIT truncation check (full vs first-60% recompute)...")
    close_maps = {t: dict(zip(g["date"], g["close"])) for t, g in feats.groupby("ticker")}
    pit_dev = pit_truncation_check(close_maps)
    del close_maps
    print(f"  max |macd_pct full-vs-truncated| = {pit_dev:.3e}")
    assert pit_dev < 1e-8, "PIT violation suspected"

    print("Joining features onto panel + integrity recheck vs parquet fwd...")
    df = panel.merge(feats.drop(columns=["close"]), on=["ticker", "date"], how="inner")
    integrity = {}
    for h in (20, 60, 120):
        m = df[f"fwd_d{h}_x"].notna() & df[f"fwd_d{h}_y"].notna()
        diff = float((df.loc[m, f"fwd_d{h}_x"] - df.loc[m, f"fwd_d{h}_y"]).abs().max())
        integrity[f"d{h}"] = {"maxAbsDiff": round(diff, 12), "nCompared": int(m.sum())}
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])
    print("  " + ", ".join(f"{k}: maxAbsDiff={v['maxAbsDiff']}" for k, v in integrity.items()))

    rebal = monthly_rebalance_dates(df["date"])

    report = {
        "question": "Does standard MACD(12,26,9) carry independent information about future KRX returns?",
        "data": {
            "sampleSource": "research/strategy-lab/data/a4/a4-research-dataset.parquet (A4 panel rows)",
            "featureBasis": "data/backfill/price/a2a/*.jsonl.gz full per-ticker session close series (A2a adjusted)",
            "rows": int(len(df)), "tickers": int(df["ticker"].nunique()),
            "period": [str(df["date"].min()), str(df["date"].max())],
            "priceBasis": "A2a adjusted close (수정주가)",
            "forwardReturnConvention": "close[t+h]/close[t]-1 on the ticker's full session calendar; signal at t close, return strictly after t",
            "duplicatePanelRowsRemoved": dupes,
            "forwardReturnIntegrityRecheckVsParquet": integrity,
            "pitTruncationMaxDeviation": pit_dev,
            "pitTruncationNote": "macd_pct recomputed from a first-60%-truncated series must equal full-series values exactly.",
        },
        "caveats": [
            "Sample scope = A4 panel (A4 ∩ A2a coverage) ≈ currently-listed universe; same survivorship caveat as the Momentum12M A1A_ONLY study.",
            "EMA runs on each ticker's full session sequence (suspensions simply absent, standard daily-bar practice).",
            "Continuous features normalized to % of close because raw MACD scales with price level; raw values drive only state/cross flags.",
            "Overlapping forward windows are not independent; monthly spreads use Newey-West lag=h/21, events use day-clustered t.",
            "No transaction costs - information content, not tradable net P&L.",
            "MACD divergence excluded per instruction.",
        ],
    }

    print("\n=== Daily cross-sectional IC (continuous features) ===")
    ic_block, ic_series_store = {}, {}
    for feat in CONT_FEATURES:
        for h in DECILE_HORIZONS:
            key = f"{feat}|{h}"
            ic_by_date = daily_ic_series(df, feat, h)
            ic_series_store[key] = ic_by_date
            ic_block[key] = ic_summary(ic_by_date)
            r = ic_block[key]
            if r.get("nDays"):
                print(f"  {feat:14s} vs {h}: IC={r['icMean']:+.5f} (t={r['icT']}, nDays={r['nDays']})")
    report["dailyIC"] = ic_block

    print("\n=== Yearly IC stability (vs fwd_d60) ===")
    year_block = {}
    for feat in CONT_FEATURES:
        key = f"{feat}|fwd_d60"
        year_block[key] = yearly_breakdown(ic_series_store[key])
        yb = year_block[key]
        print(f"  {feat}: " + ", ".join(f"{y}:{v['icMean']:+.4f}" for y, v in yb.items()))
    report["yearlyIC_vsD60"] = year_block

    print("\n=== Monthly-rebalance deciles (Momentum12M convention; D10=highest) ===")
    decile_block = {}
    for feat in CONT_FEATURES:
        decile_block[feat] = decile_analysis(df, feat, rebal)
        for h in DECILE_HORIZONS:
            m = decile_block[feat]["monotonicitySpread"][h]
            print(f"  {feat:14s} {h}: D10-D1 pooled={m['pooledD10minusD1']:+.5f}, "
                  f"monthly mean={m['monthlySpreadMean']:+.5f}, naiveT={m['monthlySpreadNaiveT']}, "
                  f"NWT={m['monthlySpreadNWT']}, rho={m['decileReturnSpearman']:+.3f}")
    report["monthlyDeciles"] = decile_block

    print("\n=== Sign-state split at monthly rebalance (MACD>0 vs <=0) ===")
    sign_split = binary_state_split(df, "macd_pos", rebal)
    for h, v in sign_split.items():
        print(f"  {h}: pos mean={v['meanPos']:+.5f}(wr {v['winratePos']}), neg mean={v['meanNeg']:+.5f}(wr {v['winrateNeg']}), "
              f"diff naiveT={v['monthlyDiffNaiveT']}, NWT={v['monthlyDiffNWT']}")
    report["signStateSplit"] = sign_split

    print("\n=== Event studies (5/20/60 trading days after event close) ===")
    events = {
        "zeroCrossUp": "zero_cross_up", "zeroCrossDown": "zero_cross_dn",
        "signalCrossUp": "sig_cross_up", "signalCrossDown": "sig_cross_dn",
    }
    ev_block = {}
    for label, col in events.items():
        ev_block[label] = event_study(df, col, EVENT_HORIZONS)
        v = ev_block[label]
        parts = []
        for h in EVENT_HORIZONS:
            if h in v:
                parts.append(f"{h}: excess={v[h]['excessVsSameDateCrossSectionMean']:+.5f}(t={v[h]['excessDayClusteredT']})")
        print(f"  {label} (n={v['nEvents']}): " + " | ".join(parts))
    report["eventStudies"] = ev_block

    rb = df[df["date"].isin(rebal)]
    report["counts"] = {
        "shareMacdPosAtMonthlyDates": round(float(rb["macd_pos"].mean()), 4),
        "nZeroCrossUp": int(df["zero_cross_up"].sum()),
        "nZeroCrossDown": int(df["zero_cross_dn"].sum()),
        "nSignalCrossUp": int(df["sig_cross_up"].sum()),
        "nSignalCrossDown": int(df["sig_cross_dn"].sum()),
        "minNamesPerDateForDecile": MIN_NAMES_PER_DATE,
    }

    out_path = os.path.join(OUT_DIR, "macd-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
