#!/usr/bin/env python
"""Breakout/Pullback 이벤트 기반 forward-return 검증 — 2016-2026, A1A_ONLY.

전략군 대표 이벤트 (backward-only, PIT 준수):
  BREAKOUT55 : Close[t] > Donchian55_high[t-1] 且 Close[t-1] <= Donchian55_high[t-1]
               (55일 고가 상향 돌파 엣지) — TREND-BREAKOUT-v1과 같은 신호 계열
  PULLBACK   : mom60[t] >= +5% (추세) 且 rev20[t] >= +5% (20일간 5% 하락 = 되돌림)
               — 5DC-v1A-P(추세+CCI 풀백)와 같은 계열의 단순화
  MOMBREAK   : mom60[t] >= +10% (강한 상승 추세) — 추세추종 대조군

이벤트 발생일 t 이후 forward return 20/60/120D (평균/중앙/승률/횟수).
비용·슬리피지 미반영 — 신호의 raw 예측력만. 거래로 만들면 갭·비용이 더해짐.
"""
import json
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402
from engine.indicators.donchian import donchian_channel  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START = "2016-01-01"
END = "2026-08-14"
HORIZONS = (20, 60, 120)


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"tickers={len(bars_by_ticker)}")

    events = defaultdict(list)
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < 260:
            continue
        close = bars["close"]
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        dc = donchian_channel(bars["high"], bars["low"], period=55)
        dc_high = dc["donchian_high"]
        mom60 = close / close.shift(60) - 1
        ret20 = close / close.shift(20) - 1
        fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}

        for i, d in enumerate(idx):
            if i < 2 or i + 1 >= len(idx):
                continue
            c = close.iloc[i]
            prev = close.iloc[i - 1]
            dh = dc_high.iloc[i - 1]
            if pd.isna(dh):
                continue
            m60 = mom60.iloc[i]
            r20 = ret20.iloc[i]
            # BREAKOUT55: 현재가 > 직전 55일 고가, 직전가는 <= (엣지)
            is_breakout = (c > dh) and (prev <= dh)
            # PULLBACK: 추세(+) 중 20일 5% 되돌림
            is_pullback = (m60 >= 0.05) and (r20 <= -0.05)
            # MOMBREAK: 강한 60일 추세
            is_mombreak = (m60 >= 0.10)
            for name, flag in (("BREAKOUT55", is_breakout), ("PULLBACK", is_pullback), ("MOMBREAK", is_mombreak)):
                if not flag:
                    continue
                row = {"ticker": ticker, "date": d}
                ok = True
                for h in HORIZONS:
                    v = fwd[h].iloc[i]
                    if pd.isna(v):
                        ok = False
                        break
                    row[f"fwd{h}"] = float(v)
                if ok:
                    events[name].append(row)

    report = {}
    for name, rows in events.items():
        df = pd.DataFrame(rows)
        print(f"\n=== {name}: {len(df)} events ===")
        agg = {"n": len(df)}
        for h in HORIZONS:
            col = f"fwd{h}"
            agg[f"mean_fwd{h}"] = round(float(df[col].mean()), 5)
            agg[f"median_fwd{h}"] = round(float(df[col].median()), 5)
            agg[f"winrate_fwd{h}"] = round(float((df[col] > 0).mean()), 4)
            print(f"  fwd{h}: mean={agg[f'mean_fwd{h}']:.4f} median={agg[f'median_fwd{h}']:.4f} winrate={agg[f'winrate_fwd{h}']:.3f}")
        # 연도별 이벤트 분포 + fwd60 평균
        df["year"] = df["date"].str[:4]
        yr = df.groupby("year").agg(n=("fwd60", "size"), mean60=("fwd60", "mean"))
        agg["byYear"] = {y: {"n": int(r.n), "mean_fwd60": round(float(r.mean60), 4)} for y, r in yr.iterrows()}
        report[name] = agg

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-18-strategy-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "breakout_pullback_events.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()