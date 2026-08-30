#!/usr/bin/env python
"""2022년 PBR-EW 초과성과(로그초과수익의 ~98.6%가 이 한 해에서 나옴, 2026-08-22
확인)의 원인분해 - 세 가설을 가른다:
  (a) 저PBR-고PBR이 Value-Growth 로테이션과 거의 동일한 현상인가
  (b) PBR 자체의 독립적 효과인가
  (c) 특정 업종/소수 종목의 표본 효과인가

두 가지를 본다:
  1. decile 단조성 - 2022년만 따로 PBR decile 1~10 평균수익률·IC. 소수 극단
     종목이 아니라 분포 전체가 단조적으로 움직였다면 (b)를 지지.
  2. 고PBR/저PBR 버킷의 업종 구성·손실 집중도 - data/backfill/universe/a1a/
     current.jsonl의 sector 필드로 두 버킷의 업종이 뚜렷이 갈리면 (a)/(c)를,
     고PBR 버킷 손실이 소수 종목에 집중되면 (c)를 지지.

기존 파일 미변경, 새 진단 스크립트+report만 생성.

  python pbr_2022_decomposition.py
"""
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
START, END = "2022-01-01", "2022-12-31"
# build_panel requires >=260 bars of history per ticker (warmup for turnover20
# rolling + a sane minimum listing history) - a bars load scoped to exactly
# 2022 never satisfies that. Load a wide window (matches every other script
# in this session) and filter down to 2022 entry_dates only after building.
LOAD_START, LOAD_END = "2016-01-01", "2023-01-31"
MIN_TURNOVER = 100_000_000.0
TOP_N = 30
N_DECILES = 10


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_valuation_panel():
    rows = [json.loads(line) for line in open(PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["pbr"])
    df = df[df["pbr"] > 0]
    return df.set_index(["ticker", "asOf"])["pbr"].to_dict()


def load_sector_lookup():
    lookup = {}
    with open(UNIVERSE_PATH, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            lookup[row["ticker"]] = row.get("sector", "UNKNOWN")
    return lookup


def build_panel(bars_by_ticker, rebalance_dates, pbr_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        for k, t in enumerate(rebalance_dates[:-1]):
            pbr = pbr_lookup.get((ticker, t))
            if pbr is None:
                continue
            i = pos.get(t)
            if i is None or i + 1 >= len(idx):
                continue
            entry_date = idx[i + 1]
            exit_date = rebalance_dates[k + 1]
            j = pos.get(exit_date)
            if j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[i + 1]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            tv = turnover20.iloc[i]
            rows.append({"ticker": ticker, "entry_date": t, "pbr": float(pbr),
                         "ret": exit_price / entry_price - 1,
                         "turnover20": float(tv) if not pd.isna(tv) else 0.0})
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    return float(np.corrcoef(pd.Series(factor_vals).rank(), pd.Series(fwd_rets).rank())[0, 1])


def decile_analysis_2022(sub):
    months = sorted(sub["entry_date"].unique())
    decile_rets = {d: [] for d in range(1, N_DECILES + 1)}
    monthly_ics = []
    for m in months:
        g = sub[sub["entry_date"] == m]
        if len(g) < N_DECILES * 3:
            continue
        ranks = g["pbr"].rank(ascending=True, method="first")  # low pbr = decile 1
        deciles = pd.qcut(ranks, N_DECILES, labels=False, duplicates="drop") + 1
        for d in range(1, int(deciles.max()) + 1 if len(deciles) else 1):
            sel = g.loc[deciles == d, "ret"]
            if len(sel):
                decile_rets[d].append(float(sel.mean()))
        ic = rank_ic((-g["pbr"]).values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    decile_avg = {d: (round(float(np.mean(v)), 4) if v else None) for d, v in decile_rets.items()}
    ic_mean = round(float(np.mean(monthly_ics)), 4) if monthly_ics else None
    return {"decileAvgMonthlyReturn": decile_avg, "meanMonthlyIC": ic_mean, "monthsUsed": len(monthly_ics)}


def bucket_concentration_and_sectors(sub, sector_lookup, ascending, label):
    months = sorted(sub["entry_date"].unique())
    all_stock_rets = []
    sector_counts = Counter()
    for m in months:
        g = sub[sub["entry_date"] == m].sort_values("pbr", ascending=ascending).head(TOP_N)
        for _, row in g.iterrows():
            all_stock_rets.append((row["ticker"], m, row["ret"]))
            sector_counts[sector_lookup.get(row["ticker"], "UNKNOWN")] += 1

    rets = [r for _, _, r in all_stock_rets]
    rets_sorted = sorted(all_stock_rets, key=lambda x: x[2])  # worst first
    worst5_sum = sum(r for _, _, r in rets_sorted[:5])
    total_sum = sum(rets)
    worst5_share = round(worst5_sum / total_sum, 3) if total_sum != 0 else None

    top_sectors = sector_counts.most_common(8)
    return {
        "label": label, "stockMonthObservations": len(all_stock_rets),
        "meanReturn": round(float(np.mean(rets)), 4) if rets else None,
        "stdReturn": round(float(np.std(rets)), 4) if rets else None,
        "worst5of_allStockMonths_pnlShareOfTotal": worst5_share,
        "worst5Examples": [{"ticker": t, "month": m, "ret": round(r, 4)} for t, m, r in rets_sorted[:5]],
        "topSectorsByCount": [{"sector": s, "count": c} for s, c in top_sectors],
        "sectorCount": len(sector_counts),
    }


def main():
    t0 = time.time()
    pbr_lookup = load_valuation_panel()
    sector_lookup = load_sector_lookup()
    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, LOAD_START, LOAD_END, universe_hash="pbr-2022-decomposition")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, LOAD_START, LOAD_END)
    panel = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup)
    panel = panel[(panel["entry_date"] >= START) & (panel["entry_date"] <= END)]
    panel_hi = panel[panel["turnover20"] >= MIN_TURNOVER]
    print(f"2022 high-liquidity rows={len(panel_hi)}, months={panel_hi['entry_date'].nunique()}")

    decile = decile_analysis_2022(panel_hi)
    print("\ndecile:", json.dumps(decile, ensure_ascii=False))

    low_bucket = bucket_concentration_and_sectors(panel_hi, sector_lookup, ascending=True, label="저PBR top30 (2022)")
    high_bucket = bucket_concentration_and_sectors(panel_hi, sector_lookup, ascending=False, label="고PBR top30 (2022)")
    print("\nlow bucket:", json.dumps(low_bucket, ensure_ascii=False, default=str))
    print("\nhigh bucket:", json.dumps(high_bucket, ensure_ascii=False, default=str))

    result = {"period": f"{START} ~ {END}", "decile": decile,
              "lowPBRbucket": low_bucket, "highPBRbucket": high_bucket}

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-22-pbr-2022-decomposition")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-2022-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "2022년 PBR-EW 초과성과(전체 로그초과수익의 ~98.6%)의 원인분해 - "
                       "decile 단조성 + 고/저PBR 버킷 업종구성·손실집중도.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
