#!/usr/bin/env python
"""Offline builder for selection.json - foreign_flow5d_v1.

pbr_value_v1/lowmom60_v1과 같은 이유(engine의 Strategy 계약이 종목 하나씩만
본다, strategies/base.py)로 횡단면 랭킹을 오프라인에서 한 번에 계산한다.
다른 점: 월별이 아니라 **매 거래일** 랭킹하고, holdSessions는 전부 고정 5
(원본 finding이 검증한 T+5 정의 그대로 - lowmom60_v1처럼 "다음 리밸런싱일까지"
가변 계산이 필요 없다).

foreign_net 정의는 findings/kr-foreign-flow-5d-independent-verification-
2026-08.md에서 실측 대조로 확정한 것 그대로 재사용한다: A4의 "외국인" 카테고리
하나가 아니라 "외국인"+"기타외국인" 합산.

  python build_selection.py
"""
import glob
import gzip
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/foreign_flow5d_v1
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # .../research/strategy-lab
sys.path.insert(0, _STRATEGY_LAB_DIR)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
A4_DIR = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")
START = "2016-01-01"
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-03"
TOP_N = 6
MIN_TURNOVER = 100_000_000.0
HOLD_SESSIONS = 5


def load_a4_flow():
    frames = []
    for path in sorted(glob.glob(os.path.join(A4_DIR, "*.jsonl.gz"))):
        recs = []
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                ba, sa = o["buyAmount"], o["sellAmount"]
                foreign_net = (ba.get("외국인", 0) + ba.get("기타외국인", 0)
                               - sa.get("외국인", 0) - sa.get("기타외국인", 0))
                recs.append({"ticker": o["ticker"], "date": o["date"],
                             "foreign_net": foreign_net, "total_amount": ba.get("전체", np.nan)})
        frames.append(pd.DataFrame(recs))
    df = pd.concat(frames, ignore_index=True)
    df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce")
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    return df


def main():
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash="foreign-flow5d-v1-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    flow = load_a4_flow()
    print(f"A4 flow rows: {len(flow)}")
    flow_by_ticker = {t: g.set_index("date") for t, g in flow.groupby("ticker")}

    all_sessions = calendar.sessions_between(START, END)
    print(f"sessions: {len(all_sessions)}")

    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        fl = flow_by_ticker.get(ticker)
        if fl is None:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        turnover20 = (close * vol).rolling(20).mean()
        pos = {d: i for i, d in enumerate(idx)}
        for t in all_sessions:
            i = pos.get(t)
            if i is None or t not in fl.index:
                continue
            tv = turnover20.iloc[i]
            fn, ta = fl.at[t, "foreign_net"], fl.at[t, "total_amount"]
            if pd.isna(tv) or pd.isna(fn) or pd.isna(ta) or ta == 0:
                continue
            rows.append({"ticker": ticker, "asOf": t, "ffr": fn / ta, "turnover20": float(tv)})
    panel = pd.DataFrame(rows)
    print(f"panel rows={len(panel)}")

    eligible = panel[panel["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (turnover20>={MIN_TURNOVER:,.0f}) rows={len(eligible)}")

    selection = {}
    daily_counts = {}
    for asOf, g in eligible.groupby("asOf"):
        # 고수급 우선 - descending on foreign_flow_ratio
        top = g.sort_values("ffr", ascending=False).head(TOP_N)
        daily_counts[asOf] = len(top)
        for ticker in top["ticker"]:
            selection.setdefault(ticker, []).append({"date": asOf, "holdSessions": HOLD_SESSIONS})

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection.py",
            "sourcePanel": "A2a bars(turnover20) + A4 raw(foreign_net/total_amount) - no external panel file",
            "period": f"{START} ~ {END}",
            "holdSessions": HOLD_SESSIONS,
            "topN": TOP_N,
            "minTurnover": MIN_TURNOVER,
            "rebalanceDays": len(daily_counts),
            "avgSelectedPerDay": round(sum(daily_counts.values()) / len(daily_counts), 1) if daily_counts else None,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(daily_counts)} days)")


if __name__ == "__main__":
    main()
