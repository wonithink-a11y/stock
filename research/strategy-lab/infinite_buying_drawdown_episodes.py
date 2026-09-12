#!/usr/bin/env python3
"""3A — 실제 가격 경로에서 고점→낙폭→저점→회복 episode 를 순수 알고리즘으로 탐지.

전략 코드(엔진)는 전혀 참조하지 않는다 — 종가만 본다. 임계값(threshold)은 결과를
보기 전에 먼저 정한다: 레버리지 3배 ETF 의 일상적 변동성 노이즈를 걸러내되 2022
같은 사례를 놓치지 않을 라운드 넘버로 25%를 쓴다(20%~30% 어디를 잡아도 큰 사례
목록은 안 바뀐다는 걸 --threshold 로 직접 확인 가능).

    python research/strategy-lab/infinite_buying_drawdown_episodes.py
    python research/strategy-lab/infinite_buying_drawdown_episodes.py --ticker SOXL --threshold 0.30
"""
import argparse
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent


@dataclass
class Episode:
    peak_date: str
    peak_price: float
    trough_date: str = ""
    trough_price: float = 0.0
    recovery_date: str | None = None
    recovery_price: float | None = None
    end_date: str = ""  # 미회복이면 데이터 마지막 날
    end_price: float = 0.0


def detect_episodes(candles: list[dict], threshold: float) -> list[Episode]:
    """candles: [{"date","close"}, ...] 날짜순 정렬 가정."""
    episodes: list[Episode] = []
    peak_price, peak_date = candles[0]["close"], candles[0]["date"]
    cur: Episode | None = None

    for c in candles:
        price, date = c["close"], c["date"]
        if price >= peak_price:
            if cur is not None:
                cur.recovery_date, cur.recovery_price = date, price
                episodes.append(cur)
                cur = None
            peak_price, peak_date = price, date
            continue

        dd = (peak_price - price) / peak_price
        if cur is None:
            if dd >= threshold:
                cur = Episode(peak_date=peak_date, peak_price=peak_price,
                               trough_date=date, trough_price=price)
        else:
            if price < cur.trough_price:
                cur.trough_date, cur.trough_price = date, price

    if cur is not None:
        cur.end_date, cur.end_price = candles[-1]["date"], candles[-1]["close"]
        episodes.append(cur)
    return episodes


def load_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "close": c}
            for d, c in df[["date", "close"]].itertuples(index=False)]


def _days_between(d1: str, d2: str) -> int:
    from datetime import date
    y1, m1, dd1 = (int(x) for x in d1.split("-"))
    y2, m2, dd2 = (int(x) for x in d2.split("-"))
    return (date(y2, m2, dd2) - date(y1, m1, dd1)).days


def print_episodes(ticker: str, episodes: list[Episode]) -> None:
    print(f"\n===== {ticker} — 고점 대비 낙폭 episode =====")
    print(f"{'고점일':11} {'고점가':>9} {'저점일':11} {'저점가':>9} {'낙폭%':>7} "
          f"{'고점~저점일':>11} {'회복일':11} {'저점~회복일':>11} {'상태':6}")
    for e in episodes:
        dd_pct = (e.peak_price - e.trough_price) / e.peak_price * 100
        p2t = _days_between(e.peak_date, e.trough_date)
        if e.recovery_date:
            t2r = _days_between(e.trough_date, e.recovery_date)
            status, rec_str = "회복", e.recovery_date
        else:
            t2r = _days_between(e.trough_date, e.end_date)
            status, rec_str = "미회복", "-"
        print(f"{e.peak_date:11} {e.peak_price:9.2f} {e.trough_date:11} {e.trough_price:9.2f} "
              f"{dd_pct:7.1f} {p2t:11d} {rec_str:11} {t2r:11d} {status:6}")


def _no_overlap(episodes: list[Episode]) -> bool:
    """episode 가 날짜순으로 서로 안 겹치는 구간인지 — 장기 하락 중 중간반등을 별도
    episode 로 중복 집계하지 않는다는 걸 실측으로 확인한다(구조상 peak_price 를
    episode 진행 중에는 안 바꾸므로 안 겹치는 게 당연하지만, 회귀로 못 박아둔다)."""
    for prev, nxt in zip(episodes, episodes[1:]):
        prev_end = prev.recovery_date or prev.end_date
        if nxt.peak_date < prev_end:
            return False
    return True


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    # 고점100 -> 하락(-40%,60) -> 중간반등(80, 원고점 미달) -> 재하락(-70%,30, 더 깊은 저점)
    # -> 완전회복(101). 원 고점(100)에 못 미치는 반등은 별개 episode 를 만들면 안 되고,
    # 최종 trough 는 더 깊은 30이어야 한다.
    synth = [
        {"date": "2020-01-01", "close": 100.0},
        {"date": "2020-01-02", "close": 60.0},   # -40% 진입(임계 25% 넘음)
        {"date": "2020-01-03", "close": 80.0},   # 반등하지만 원고점(100) 미달
        {"date": "2020-01-04", "close": 30.0},   # 재하락, 더 깊은 저점
        {"date": "2020-01-05", "close": 101.0},  # 원고점 초과 -> 회복
    ]
    eps = detect_episodes(synth, threshold=0.25)
    ck("중간반등이 원고점 미달이면 별도 episode 를 안 만든다(episode 1개)", len(eps) == 1)
    if eps:
        ck("최종 trough 는 중간반등 이후 더 깊은 저점(30)이다", eps[0].trough_price == 30.0)
        ck("trough 가 중간반등(80)으로 되돌아가지 않는다", eps[0].trough_price != 80.0)
        ck("회복가는 원고점을 넘은 101이다", eps[0].recovery_price == 101.0)

    ck("실제 TQQQ episode 들이 서로 안 겹친다(25% 임계)",
       _no_overlap(detect_episodes(load_candles("TQQQ"), 0.25)))
    ck("실제 SOXL episode 들이 서로 안 겹친다(25% 임계)",
       _no_overlap(detect_episodes(load_candles("SOXL"), 0.25)))

    total = 6
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    import sys
    if "--selftest" in sys.argv:
        return selftest()
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default=None, help="지정 안 하면 TQQQ·SOXL 둘 다")
    ap.add_argument("--threshold", type=float, default=0.25)
    a = ap.parse_args()

    tickers = [a.ticker] if a.ticker else ["TQQQ", "SOXL"]
    for ticker in tickers:
        candles = load_candles(ticker)
        episodes = detect_episodes(candles, a.threshold)
        print_episodes(ticker, episodes)
        recovered = sum(1 for e in episodes if e.recovery_date)
        print(f"  총 {len(episodes)}건 (회복 {recovered} / 미회복 {len(episodes)-recovered}), "
              f"임계값 {a.threshold:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
