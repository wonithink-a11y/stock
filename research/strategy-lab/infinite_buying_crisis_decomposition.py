#!/usr/bin/env python3
"""V4.0 Crisis Path Decomposition — 2022위기 구간 일별 상태 로그 + 요약 통계.

    python research/strategy-lab/infinite_buying_crisis_decomposition.py

★ 이 분석은 현재 엔진의 리버스 해석(후보A, infinite_buying_reverse_sensitivity.py
  참고)을 전제로 한다. 원문 규칙 확정 전 절대 성과값은 잠정치다.

목적: "CAGR이 얼마인가"가 아니라 "어떤 가격 경로에서 매수/매도 메커니즘이 어떻게
갈리는가"를 날짜별로 보는 것. `infinite_buying_hybrid_v1.py`의 결과(후반전 매도비중
확대가 SOXL 2022는 개선, TQQQ 2022는 악화)를 설명하는 게 1차 목표다.
"""
import argparse
from pathlib import Path

import pandas as pd

from infinite_buying_engine import Rules, backtest

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
WINDOW = ("2021-11-01", "2022-12-30")


def load_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    candles = [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
               for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]
    return [c for c in candles if WINDOW[0] <= c["date"] <= WINDOW[1]]


def reverse_episodes(trace: list[dict]) -> list[dict]:
    """reverse=True 로 이어지는 연속 구간을 사이클처럼 묶는다."""
    episodes = []
    cur = None
    for row in trace:
        if row["reverse"]:
            if cur is None:
                cur = {"start": row["date"], "end": row["date"], "days": 0,
                       "sell_fills": 0, "buy_fills": 0,
                       "start_price": row["close"], "min_price": row["close"]}
            cur["end"] = row["date"]
            cur["days"] += 1
            cur["sell_fills"] += 1 if row["sell_qty"] > 0 else 0
            cur["buy_fills"] += 1 if row["buy_qty"] > 0 else 0
            cur["min_price"] = min(cur["min_price"], row["close"])
        else:
            if cur is not None:
                cur["end_price"] = row["close"]
                episodes.append(cur)
                cur = None
    if cur is not None:
        cur["end_price"] = trace[-1]["close"]
        episodes.append(cur)
    return episodes


def summarize(ticker: str, trace: list[dict]) -> dict:
    df = pd.DataFrame(trace)
    max_dd_row = df.loc[df["price_drawdown_pct"].idxmax()]
    max_eq_dd_row = df.loc[df["drawdown_pct"].idxmax()]
    episodes = reverse_episodes(trace)
    return {
        "ticker": ticker,
        "days": len(df),
        "price_max_dd_pct": max_dd_row["price_drawdown_pct"],
        "price_max_dd_date": max_dd_row["date"],
        "days_since_peak_at_max_dd": int(max_dd_row["days_since_price_peak"]),
        "eq_max_dd_pct": max_eq_dd_row["drawdown_pct"],
        "eq_max_dd_date": max_eq_dd_row["date"],
        "window_end_price_dd_pct": df.iloc[-1]["price_drawdown_pct"],
        "reverse_days_total": int(df["reverse"].sum()),
        "reverse_episode_count": len(episodes),
        "reverse_episodes": episodes,
        "sell_fill_days_total": int((df["sell_qty"] > 0).sum()),
        "sell_fill_days_in_reverse": sum(e["sell_fills"] for e in episodes),
        "sell_fill_days_general": int((df["sell_qty"] > 0).sum()) - sum(e["sell_fills"] for e in episodes),
        "buy_fill_days_total": int((df["buy_qty"] > 0).sum()),
        "final_qty": int(df.iloc[-1]["qty"]),
        "final_cash": df.iloc[-1]["cash"],
        "final_equity_est": df.iloc[-1]["equity"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv-out", type=Path, default=None,
                    help="일별 로그를 CSV로 저장할 디렉터리(기본: 저장 안 함)")
    a = ap.parse_args()

    print(f"★ 리버스 해석은 후보A(현재 엔진) 전제 — infinite_buying_reverse_sensitivity.py 참고\n")

    summaries = {}
    for ticker in ["TQQQ", "SOXL"]:
        r = Rules.load(RULES, ticker, 40)
        candles = load_candles(ticker)
        trace: list = []
        res = backtest(candles, r, trace=trace)
        summ = summarize(ticker, trace)
        summaries[ticker] = summ

        print(f"===== {ticker} 2022위기 ({WINDOW[0]}~{WINDOW[1]}, {summ['days']}일) =====")
        print(f"  최종 CAGR {res.cagr:.2f}%  최종 MDD(자본) {res.mdd:.1f}%")
        print(f"  가격 기준 최대낙폭 {summ['price_max_dd_pct']:.1f}%"
              f"({summ['price_max_dd_date']}, 고점 후 {summ['days_since_peak_at_max_dd']}일)"
              f"  창 종료 시점 낙폭 {summ['window_end_price_dd_pct']:.1f}%")
        print(f"  자본 기준 최대낙폭 {summ['eq_max_dd_pct']:.1f}%({summ['eq_max_dd_date']})")
        print(f"  역전모드 총 {summ['reverse_days_total']}일 / {summ['reverse_episode_count']}회 진입")
        for e in summ["reverse_episodes"]:
            print(f"    - {e['start']}~{e['end']} ({e['days']}일) 매도체결 {e['sell_fills']}일"
                  f" 매수체결 {e['buy_fills']}일  가격 {e['start_price']:.2f}→{e.get('end_price', e['min_price']):.2f}"
                  f"(구간최저 {e['min_price']:.2f})")
        print(f"  매도체결일 총 {summ['sell_fill_days_total']}일"
              f"(역전중 {summ['sell_fill_days_in_reverse']} / 일반중 {summ['sell_fill_days_general']})"
              f"  매수체결일 총 {summ['buy_fill_days_total']}일")
        print(f"  창 종료 시점: 보유 {summ['final_qty']}주  현금 ${summ['final_cash']:,.0f}"
              f"  평가금 ${summ['final_equity_est']:,.0f}\n")

        if a.csv_out:
            a.csv_out.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(trace).to_csv(a.csv_out / f"{ticker}_2022crisis_trace.csv", index=False)

    t, s = summaries["TQQQ"], summaries["SOXL"]
    print("===== TQQQ vs SOXL 대조 =====")
    print(f"  가격 최대낙폭   TQQQ {t['price_max_dd_pct']:.1f}%  vs  SOXL {s['price_max_dd_pct']:.1f}%")
    print(f"  창 종료 시점 낙폭(회복 정도)  TQQQ {t['window_end_price_dd_pct']:.1f}%"
          f"  vs  SOXL {s['window_end_price_dd_pct']:.1f}%")
    print(f"  역전 총 체류일   TQQQ {t['reverse_days_total']}일  vs  SOXL {s['reverse_days_total']}일")
    print(f"  역전 진입 횟수   TQQQ {t['reverse_episode_count']}회  vs  SOXL {s['reverse_episode_count']}회")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
