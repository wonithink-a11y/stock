#!/usr/bin/env python
"""섹터중립 PBR - "업종당 최저 1종목"(pbr_sector_neutral_check.py) 대신 업종
내부 PBR rank로 하위 decile(디폴트 10%, 최소 1종목) 전체를 pool해 포트폴리오를
구성 - 업종 크기와 무관하게 1개만 뽑던 이전 방식보다 분산되고 노이즈가 적다.
IC는 within-sector rank 기준으로 이미 계산돼 있고(포트폴리오 구성과 무관한
순수 통계량) 재사용 - 이번엔 스프레드/CAGR만 새로 본다.

같은 3구간(전체 2016-2026 / 2022 단독 / OOS 2023-2026)에서 원본 top-30 ·
섹터중립 top-1 · 섹터중립 decile 셋을 나란히 비교한다. 새 엔진/전략 생성 없음
- 기존 캐시된 가격데이터·valuation panel만 사용. 애매하면 여기서 종료(추가
스윕 없음, 사용자 지시).

  python pbr_sector_decile_check.py
"""
import json
import math
import os
import sys
import time

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
LOAD_START, LOAD_END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
COST_RT_BPS = 30.0
DECILE_FRACTION = 0.10  # bottom/top 10% within each sector, min 1 stock
MIN_SECTOR_SIZE = 3  # below this, within-sector rank is too noisy to slice further
WINDOWS = {
    "full_2016_2026": ("2016-01-01", "2026-08-14"),
    "y2022_only": ("2022-01-01", "2022-12-31"),
    "oos_2023_2026_pooled": ("2023-01-01", "2026-08-14"),
}

# already-computed within-sector rank IC (pbr_sector_neutral_check.py, 2026-08-22)
# - IC is a pure rank statistic independent of how the resulting portfolio is
# built, so it's unchanged whether we pick top-1/sector or a decile/sector.
PRIOR_IC = {
    "full_2016_2026": {"crossSectional": {"meanMonthlyIC": 0.0703, "icTstat": 6.30},
                        "withinSectorRank": {"meanMonthlyIC": 0.0365, "icTstat": 3.55}},
    "y2022_only": {"crossSectional": {"meanMonthlyIC": 0.1191, "icTstat": 3.60},
                   "withinSectorRank": {"meanMonthlyIC": 0.0857, "icTstat": 3.15}},
    "oos_2023_2026_pooled": {"crossSectional": {"meanMonthlyIC": 0.0787, "icTstat": 4.02},
                              "withinSectorRank": {"meanMonthlyIC": 0.0394, "icTstat": 1.94}},
}
PRIOR_SPREAD = {
    "full_2016_2026": {"original_top30": {"cagr": 0.1492, "sharpe": 0.8146},
                        "sectorNeutral_top1": {"cagr": 0.0675, "sharpe": 1.081}},
    "y2022_only": {"original_top30": {"cagr": 0.7518, "sharpe": 3.6586},
                   "sectorNeutral_top1": {"cagr": 0.1558, "sharpe": 3.0387}},
    "oos_2023_2026_pooled": {"original_top30": {"cagr": 0.0907, "sharpe": 0.5281},
                              "sectorNeutral_top1": {"cagr": 0.0488, "sharpe": 0.7333}},
}


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


def build_panel(bars_by_ticker, rebalance_dates, pbr_lookup, sector_lookup):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        turnover20 = (close * vol).rolling(20).mean()
        sector = sector_lookup.get(ticker, "UNKNOWN")
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
            rows.append({"ticker": ticker, "entry_date": t, "pbr": float(pbr), "sector": sector,
                         "ret": exit_price / entry_price - 1,
                         "turnover20": float(tv) if not pd.isna(tv) else 0.0})
    return pd.DataFrame(rows)


def curve_from_monthly_rets(month_rets):
    if not month_rets:
        return {"cagr": None, "sharpe": None, "maxDD": None, "monthsUsed": 0}
    s = pd.Series([r for _, r in month_rets])
    eq, peak, maxdd = 1.0, 1.0, 0.0
    for r in s:
        eq *= (1 + r)
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1)
    n_years = len(s) / 12.0
    cagr = eq ** (1 / n_years) - 1 if n_years > 0 else None
    std_r = s.std(ddof=1) if len(s) > 1 else 0.0
    sharpe = (s.mean() / std_r * np.sqrt(12)) if std_r and std_r > 0 else None
    return {"cagr": round(float(cagr), 4) if cagr is not None else None,
            "sharpe": round(float(sharpe), 4) if sharpe is not None else None,
            "maxDD": round(float(maxdd), 4), "monthsUsed": len(s)}


def sector_decile_returns(sub, low_side):
    """Pool the bottom (or top) DECILE_FRACTION of each sector by within-sector
    PBR rank, every month - proportional to sector size (min 1/sector), equal-
    weighted across the pooled names."""
    out = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        picks = []
        for sector, grp in g.groupby("sector"):
            n = len(grp)
            if n < MIN_SECTOR_SIZE:
                continue
            k = max(1, math.ceil(n * DECILE_FRACTION))
            picks.append(grp.sort_values("pbr", ascending=low_side).head(k))
        if not picks:
            continue
        pooled = pd.concat(picks)
        out.append((m, float((pooled["ret"] - COST_RT_BPS / 1e4).mean()), len(pooled)))
    return [(m, r) for m, r, _ in out], (round(float(np.mean([n for _, _, n in out])), 1) if out else None)


def spread_curve(low_rets, high_rets):
    low_by_m, high_by_m = dict(low_rets), dict(high_rets)
    common = sorted(set(low_by_m) & set(high_by_m))
    if not common:
        return {"cagr": None, "sharpe": None}
    spread = [(m, low_by_m[m] - high_by_m[m]) for m in common]
    return curve_from_monthly_rets(spread)


def main():
    t0 = time.time()
    pbr_lookup = load_valuation_panel()
    sector_lookup = load_sector_lookup()
    tickers = sorted({t for t, _ in pbr_lookup.keys()})
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, LOAD_START, LOAD_END, universe_hash="pbr-sector-neutral-check")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, LOAD_START, LOAD_END)
    panel = build_panel(bars_by_ticker, rebalance_dates, pbr_lookup, sector_lookup)
    panel_hi = panel[panel["turnover20"] >= MIN_TURNOVER]
    print(f"panel high-liquidity rows={len(panel_hi)} ({time.time()-t0:.0f}s)")

    results = {}
    for window_name, (ws, we) in WINDOWS.items():
        sub = panel_hi[(panel_hi["entry_date"] >= ws) & (panel_hi["entry_date"] <= we)]

        low_rets, low_avgn = sector_decile_returns(sub, low_side=True)
        high_rets, high_avgn = sector_decile_returns(sub, low_side=False)

        block = {
            "period": f"{ws} ~ {we}",
            "sectorDecile_bottom10pctPerSector": {
                "avgStocksPerMonth": low_avgn,
                "lowPBR": curve_from_monthly_rets(low_rets),
                "spread": spread_curve(low_rets, high_rets),
            },
            "comparison": {
                "ic_crossSectional_original": PRIOR_IC[window_name]["crossSectional"],
                "ic_withinSectorRank_unchanged": PRIOR_IC[window_name]["withinSectorRank"],
                "spread_original_top30": PRIOR_SPREAD[window_name]["original_top30"],
                "spread_sectorNeutral_top1PerSector": PRIOR_SPREAD[window_name]["sectorNeutral_top1"],
            },
        }
        results[window_name] = block
        print(f"\n=== {window_name} ({ws}~{we}) ===")
        print(json.dumps(block, ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-22-pbr-sector-decile-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-sector-decile-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "섹터중립 PBR - 업종당 1종목 대신 업종 내부 하위 10%(최소 1종목) "
                       "pool로 포트폴리오 구성. IC는 within-sector rank 기준 기존값 재사용"
                       "(포트폴리오 구성과 무관한 통계량). pbr_sector_neutral_check.py 후속.",
            "decileFraction": DECILE_FRACTION, "minSectorSize": MIN_SECTOR_SIZE,
            "minTurnover": MIN_TURNOVER, "costBps": COST_RT_BPS,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
