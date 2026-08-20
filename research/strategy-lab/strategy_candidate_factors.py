#!/usr/bin/env python
"""전략 후보 팩터 검증 - 2016~현재 KOSPI/KOSDAQ 개별주식 전략 후보 탐색.

A2a(A1A_ONLY) 가격·거래량만 사용. 엔진(execution/portfolio)은 cross-sectional
팩터 검증에 부적합하므로(기존 momentum_decile_analysis.py의 판단과 동일) decile /
forward-return 방식으로 검증한다. A4 투자자별 수급은 data/backfill/supplyDemand/a4
미존재(본수집 대기) → 수급 결합 전략은 여기서 실증 불가(설계만 보고).

검증 대상 팩터(전략군 대표):
  MOM-20D     단기 모멘텀          : Close[t]/Close[t-20]-1
  MOM-60D     중기 모멘텀          : Close[t]/Close[t-60]-1
  MOM-12-1    12개월-1개월 모멘텀  : Close[t-21]/Close[t-252]-1 (기존 역전 재현 포함)
  REV-20D     단기 평균회귀        : -(Close[t]/Close[t-20]-1) (역방향: 급락 후 반등?)
  VOL-20D     변동성              : 20D 로그수익률 표준편차 (저변동성 프리미엄?)
  LIQ-SURGE   거래량 급증         : 5D 평균거래량/60D 평균거래량 (이벤트 시그널)
  VOLUME-20D  20D 거래량 레벨      : 20D 평균거래량 (유동성 필터용)

방법: 월별 리밸런스일마다 cross-sectional decile → forward 20D/60D/120D 수익률
→ decile monotonicity(Spearman) + decile10-decile1 스프레드.

survivorship: A1A_ONLY(현재 상장 종목)로 한정 — 2016 이전 상장폐지 종목은 제외.
PIT: 팩터는 리밸런스일 t 종가까지의 backward 데이터만 사용, forward는 t 이후.
look-ahead: 없음(백테스트 아님). 거래비용: 미반영(팩터 raw 검증 단계).

read-only: data/backfill/ 미기록. 출력은 reports/2026-08-18-strategy-candidates/.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HORIZONS = (20, 60, 120)
N_DECILES = 10
START = "2016-01-01"  # A4 계약과 동일 기준, 2014-2015 상장 종목은 웜업으로만
END = "2026-08-14"  # A2a 마지막 데이터 근처
MIN_TICKERS_PER_DATE = 50  # decile 10개로 나누기 위한 최소 종목 수

FACTORS = {
    "mom20": lambda df: df["close"] / df["close"].shift(20) - 1,
    "mom60": lambda df: df["close"] / df["close"].shift(60) - 1,
    "mom12_1": lambda df: df["close"].shift(21) / df["close"].shift(252) - 1,
    "rev20": lambda df: -(df["close"] / df["close"].shift(20) - 1),
    "vol20": lambda df: np.log(df["close"]).diff().rolling(20).std(),
    "liq_surge": lambda df: df["volume"].rolling(5).mean() / df["volume"].rolling(60).mean(),
    "volume20": lambda df: df["volume"].rolling(20).mean(),
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


def build_factor_panel(bars_by_ticker, rebalance_dates):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close = bars["close"]
        fwd = {h: close.shift(-h) / close - 1 for h in HORIZONS}
        factor_series = {name: fn(bars) for name, fn in FACTORS.items()}
        idx = close.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        for d in rebalance_dates:
            i = pos.get(d)
            if i is None:
                continue
            row = {"ticker": ticker, "date": d}
            ok = True
            for name, s in factor_series.items():
                v = s.iloc[i]
                if pd.isna(v):
                    ok = False
                    break
                row[name] = float(v)
            if not ok:
                continue
            for h in HORIZONS:
                v = fwd[h].iloc[i]
                if pd.isna(v):
                    ok = False
                    break
                row[f"fwd{h}"] = float(v)
            if ok:
                rows.append(row)
    return pd.DataFrame(rows)


def decile_analysis(panel, factor):
    def _assign(group):
        if len(group) < MIN_TICKERS_PER_DATE:
            group["decile"] = np.nan
            return group
        group["decile"] = pd.qcut(group[factor], N_DECILES, labels=False, duplicates="drop") + 1
        return group

    panel = panel.groupby("date", group_keys=False).apply(_assign)
    panel = panel.dropna(subset=["decile"])
    panel["decile"] = panel["decile"].astype(int)

    agg = {}
    for h in HORIZONS:
        col = f"fwd{h}"
        g = panel.groupby("decile")[col]
        agg[f"mean_fwd{h}"] = g.mean()
        agg[f"winrate_fwd{h}"] = g.apply(lambda s: float((s > 0).mean()))
    agg["n"] = panel.groupby("decile").size()
    table = pd.DataFrame(agg).sort_index()

    mono = {}
    for h in HORIZONS:
        col = f"mean_fwd{h}"
        sp = table[col].corr(pd.Series(table.index, index=table.index), method="spearman")
        mono[f"fwd{h}_spearman"] = None if pd.isna(sp) else round(float(sp), 4)
        mono[f"fwd{h}_d10minusd1"] = round(float(table[col].iloc[-1] - table[col].iloc[0]), 5)
    return table, mono


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    price_provider = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = price_provider.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"universe={universe.mode} tickers={len(bars_by_ticker)}")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    print(f"rebalance_dates={len(rebalance_dates)}")

    panel = build_factor_panel(bars_by_ticker, rebalance_dates)
    print(f"panel rows={len(panel)}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-18-strategy-candidates")
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "title": "전략 후보 팩터 검증 (2016-2026, A1A_ONLY)",
        "universeMode": universe.mode,
        "tickersScanned": len(bars_by_ticker),
        "rebalanceDates": len(rebalance_dates),
        "panelRows": len(panel),
        "horizonsDays": list(HORIZONS),
        "start": START,
        "end": END,
        "factorDefinitions": {
            "mom20": "Close[t]/Close[t-20]-1 (단기 모멘텀)",
            "mom60": "Close[t]/Close[t-60]-1 (중기 모멘텀)",
            "mom12_1": "Close[t-21]/Close[t-252]-1 (12-1 모멘텀, 기존 역전 재현)",
            "rev20": "-(Close[t]/Close[t-20]-1) (단기 평균회귀 — 급락 후 반등)",
            "vol20": "20D 로그수익률 표준편차 (변동성)",
            "liq_surge": "5D 평균거래량/60D 평균거래량 (거래량 급증)",
            "volume20": "20D 평균거래량 (유동성)",
        },
        "results": {},
        "caveats": [
            "A1A_ONLY 유니버스(현재 상장 종목만) — survivorship bias 있음. 2016 이전 상장폐지 종목 제외.",
            "월별 리밸런스, cross-sectional decile, 팩터는 t까지 backward, forward는 t 이후 (PIT 준수).",
            "거래비용·슬리피지·포지션사이징 미반영 — raw 팩터 검증이다. tradable 전략 P&L 아님.",
            "20D/60D/120D 겹치는 수익률 창은 독립 관측치 아님 — 통계적 유의성 한계.",
            "A4 투자자별 수급은 저장소에 없음(data/backfill/supplyDemand/a4 부재) → 수급 결합 전략 실증 불가.",
        ],
    }

    for factor in FACTORS:
        table, mono = decile_analysis(panel, factor)
        report["results"][factor] = {
            "decileTable": table.round(5).to_dict(orient="index"),
            "monotonicity": mono,
        }
        print(f"\n=== {factor} ===")
        print(table[[f"mean_fwd{h}" for h in HORIZONS] + ["n"]].round(4))
        print("monotonicity:", mono)

    out_path = os.path.join(out_dir, "factor_deciles.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
