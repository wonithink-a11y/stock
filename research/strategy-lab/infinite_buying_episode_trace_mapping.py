#!/usr/bin/env python3
"""3B — 3A에서 확정한 episode 목록에 V4.0 trace 를 매핑한다.

원칙(3A → 3B 순서 고정, selection bias 방지):
  가격 데이터 -> episode 확정(infinite_buying_drawdown_episodes.py, 이미 커밋됨, 안 건드림)
  -> 그 episode 를 그대로 V4.0 trace 에 매핑 -> 전략 결과 관찰
전략 성과를 보고 episode 를 다시 고르지 않는다 — 이 스크립트는 3A 의 detect_episodes()
결과를 그대로 가져다 쓴다(재구현 안 함).

상태 연속성: episode 마다 새 backtest 를 시작하지 않는다. 실제 라이브가 그렇게 안
돌기 때문 — 한 번의 연속 backtest(2010~2026 전체)를 돌리고 trace 를 episode 날짜로
잘라서 쓴다.

    python research/strategy-lab/infinite_buying_episode_trace_mapping.py
"""
from pathlib import Path

import pandas as pd

from infinite_buying_engine import Rules, backtest
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
THRESHOLD = 0.25  # 3A 에서 확정한 값 그대로


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _row_at_or_before(df: pd.DataFrame, date: str) -> pd.Series:
    sub = df[df["date"] <= date]
    return sub.iloc[-1] if len(sub) else df.iloc[0]


def _days_between(d1: str, d2: str) -> int:
    from datetime import date
    y1, m1, dd1 = (int(x) for x in d1.split("-"))
    y2, m2, dd2 = (int(x) for x in d2.split("-"))
    return (date(y2, m2, dd2) - date(y1, m1, dd1)).days


def map_episode(df: pd.DataFrame, ep, splits: int) -> dict:
    end = ep.recovery_date or ep.end_date
    window = df[(df["date"] >= ep.peak_date) & (df["date"] <= end)]

    late_general = window[(~window["reverse"]) & (window["t"] > splits / 2) & (window["sell_qty"] > 0)]
    last_late_sell = late_general["date"].max() if len(late_general) else None
    if last_late_sell is not None:
        runway_days = _days_between(last_late_sell, end)
    else:
        runway_days = None

    trough_row = _row_at_or_before(window, ep.trough_date)
    cash_frac_at_trough = trough_row["cash"] / trough_row["equity"] if trough_row["equity"] > 0 else None

    return {
        "peak_date": ep.peak_date, "trough_date": ep.trough_date,
        "end_date": end, "recovered": ep.recovery_date is not None,
        "dd_pct": (ep.peak_price - ep.trough_price) / ep.peak_price * 100,
        "recovery_days": _days_between(ep.trough_date, end),
        "late_general_sell_days": int(len(late_general)),
        "last_late_sell_date": last_late_sell,
        "runway_after_last_late_sell_days": runway_days,
        "cash_frac_at_trough": cash_frac_at_trough,
        "entered_reverse": bool(window["reverse"].any()),
        "reverse_days_in_ep": int(window["reverse"].sum()),
        "cycles_touched": int(window["cycle_id"].nunique()),
    }


def main() -> int:
    print(f"★ 리버스 해석은 후보A(현재 엔진) 전제. episode 는 3A 확정 목록(threshold {THRESHOLD:.0%}) 그대로.\n")
    for ticker in ["TQQQ", "SOXL"]:
        r = Rules.load(RULES, ticker, 40)
        price_candles = load_price_candles(ticker)
        episodes = detect_episodes(price_candles, THRESHOLD)

        engine_candles = load_engine_candles(ticker)
        trace: list = []
        backtest(engine_candles, r, trace=trace)
        df = pd.DataFrame(trace)

        print(f"===== {ticker} — episode 별 V4.0 매핑 =====")
        print(f"{'고점일':11} {'낙폭%':>6} {'상태':6} {'회복까지':>8} {'후반전매도일':>10} "
              f"{'마지막매도후 남은기간':>18} {'저점현금비중':>10} {'역전여부':6}")
        for ep in episodes:
            m = map_episode(df, ep, splits=40)
            runway = m["runway_after_last_late_sell_days"]
            runway_str = f"{runway}일" if runway is not None else "해당없음"
            cash_str = f"{m['cash_frac_at_trough']*100:.0f}%" if m["cash_frac_at_trough"] is not None else "-"
            print(f"{m['peak_date']:11} {m['dd_pct']:6.1f} {'회복' if m['recovered'] else '미회복':6} "
                  f"{m['recovery_days']:8d} {m['late_general_sell_days']:10d} "
                  f"{runway_str:>18} {cash_str:>10} {'Y' if m['entered_reverse'] else 'N':6}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
