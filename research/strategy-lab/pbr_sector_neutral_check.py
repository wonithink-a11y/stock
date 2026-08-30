#!/usr/bin/env python
"""섹터중립 PBR precheck (panel-naive, 실제 엔진 아님) - 매달 업종별로 PBR
순위를 매겨 업종당 최저PBR 1종목만 선별(사실상 "업종별 동일비중 합산" -
업종 하나당 정확히 1종목이므로), 기존 횡단면 top-30(전체 유니버스에서 그냥
저PBR 30개)과 나란히 비교한다. 2022년의 초과성과가 Value-Growth 업종
로테이션과 크게 겹친다는 걸 확인한 뒤(2026-08-22, pbr_2022_decomposition.py),
업종을 통제해도 PBR 신호가 남는지 보는 다음 단계.

세 구간: 전체 2016-2026 / 2022 단독 / OOS 2023-2026(풀링) - 다른 스윕(비용·
topN·유동성)은 이미 반복 검증됐다고 판단해 반복하지 않는다(사용자 승인).

IC는 "섹터내부 순위"(그 달 같은 업종 안에서의 PBR 순위)로 계산해 업종간
평균 PBR 차이가 IC에 기여하는 걸 원천 제거한다 - 순수 within-sector 신호.

기존 파일 미변경 - 새 진단 스크립트+report만 생성. 실제 엔진(run_smoke)
안 씀 - 필요하면 이 결과 확인 후 별도로 진행.

  python pbr_sector_neutral_check.py
"""
import json
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
TOP_N = 30  # for the original (non-sector-neutral) comparison arm
WINDOWS = {
    "full_2016_2026": ("2016-01-01", "2026-08-14"),
    "y2022_only": ("2022-01-01", "2022-12-31"),
    "oos_2023_2026_pooled": ("2023-01-01", "2026-08-14"),
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


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    return float(np.corrcoef(pd.Series(factor_vals).rank(), pd.Series(fwd_rets).rank())[0, 1])


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


def cross_sectional_ic(sub):
    """Original (non-sector-neutral) IC: raw pbr rank vs return, whole cross-section."""
    monthly_ics = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        if len(g) < 15:
            continue
        ic = rank_ic((-g["pbr"]).values, g["ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    if not monthly_ics:
        return {"meanMonthlyIC": None, "icTstat": None}
    m_, s_ = float(np.mean(monthly_ics)), float(np.std(monthly_ics))
    t_ = (m_ / (s_ / np.sqrt(len(monthly_ics)))) if s_ > 0 else None
    return {"meanMonthlyIC": round(m_, 4), "icTstat": round(t_, 2) if t_ is not None else None,
            "icMonthsUsed": len(monthly_ics)}


def sector_neutral_ic(sub):
    """Within-sector rank vs return, pooled across sectors each month - removes
    any between-sector average-PBR difference from contributing to IC."""
    monthly_ics = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        if len(g) < 15:
            continue
        within_rank = g.groupby("sector")["pbr"].rank(ascending=True)
        sector_size = g.groupby("sector")["pbr"].transform("size")
        eligible = sector_size >= 3  # within-sector rank is noisy for tiny sectors
        if eligible.sum() < 15:
            continue
        ic = rank_ic((-within_rank[eligible]).values, g.loc[eligible, "ret"].values)
        if ic is not None:
            monthly_ics.append(ic)
    if not monthly_ics:
        return {"meanMonthlyIC": None, "icTstat": None}
    m_, s_ = float(np.mean(monthly_ics)), float(np.std(monthly_ics))
    t_ = (m_ / (s_ / np.sqrt(len(monthly_ics)))) if s_ > 0 else None
    return {"meanMonthlyIC": round(m_, 4), "icTstat": round(t_, 2) if t_ is not None else None,
            "icMonthsUsed": len(monthly_ics)}


def original_topN_returns(sub, ascending):
    out = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m].sort_values("pbr", ascending=ascending).head(TOP_N)
        if g.empty:
            continue
        out.append((m, float((g["ret"] - COST_RT_BPS / 1e4).mean())))
    return out


def sector_neutral_returns(sub, ascending):
    """One stock per sector - the sector's single lowest (or highest) PBR name."""
    out = []
    for m in sorted(sub["entry_date"].unique()):
        g = sub[sub["entry_date"] == m]
        picks = g.sort_values("pbr", ascending=ascending).groupby("sector").head(1)
        if picks.empty:
            continue
        out.append((m, float((picks["ret"] - COST_RT_BPS / 1e4).mean()), len(picks)))
    return [(m, r) for m, r, _ in out], (out[-1][2] if out else None), \
           round(float(np.mean([n for _, _, n in out])), 1) if out else None


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

        orig_low = original_topN_returns(sub, ascending=True)
        orig_high = original_topN_returns(sub, ascending=False)
        sn_low, sn_low_n, sn_low_avgn = sector_neutral_returns(sub, ascending=True)
        sn_high, sn_high_n, sn_high_avgn = sector_neutral_returns(sub, ascending=False)

        results[window_name] = {
            "period": f"{ws} ~ {we}",
            "original_top30": {
                "lowPBR": curve_from_monthly_rets(orig_low),
                "spread": spread_curve(orig_low, orig_high),
                "ic_crossSectional": cross_sectional_ic(sub),
            },
            "sectorNeutral_top1PerSector": {
                "avgStocksPerMonth": sn_low_avgn,
                "lowPBR": curve_from_monthly_rets(sn_low),
                "spread": spread_curve(sn_low, sn_high),
                "ic_withinSectorRank": sector_neutral_ic(sub),
            },
        }
        print(f"\n=== {window_name} ({ws}~{we}) ===")
        print(json.dumps(results[window_name], ensure_ascii=False, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-22-pbr-sector-neutral-check")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-sector-neutral-check.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "섹터중립 PBR(업종당 최저PBR 1종목, 업종별 동일비중) vs 기존 "
                       "횡단면 top-30 - panel-naive precheck(실제 엔진 아님). 2022년의 "
                       "PBR-EW 초과성과가 Value-Growth 업종 로테이션과 겹친다는 발견 "
                       "(pbr_2022_decomposition.py) 이후, 업종 통제 시 신호가 남는지 확인.",
            "minTurnover": MIN_TURNOVER, "costBps": COST_RT_BPS, "originalTopN": TOP_N,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
