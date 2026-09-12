#!/usr/bin/env python3
"""Phase 1 — LOC 체결 현실성 검증 (read-only 분석, 엔진 코드 불변).

무한매수 V4.0 백테스트의 체결 가정은 `daily close <= limit → 체결`
(`infinite_buying_engine.fill`)이다. 이게 실제 Nasdaq/NYSE Arca 종가 경매
(Closing Cross)와 어긋날 수 있는 지점을 TQQQ/SOXL 기존 일별 OHLCV 데이터만으로
정량화한다.

`infinite_buying_engine.py`는 전혀 수정하지 않는다 — 이 스크립트 안에서 실행 중에만
`eng.fill`을 대체 함수로 바꿔치기(monkeypatch)하고 finally 에서 원복한다. 전략
로직·파라미터(splits·base_pct 등)는 그대로, 체결 가정만 바꾼다.

두 축으로 스트레스를 준다(각각 왜 이 값인지는 §0 참고):
  1. 슬리피지 — 벤더가 보고하는 종가가 실제 경매 체결가와 정확히 같지 않을 수
     있다는 불확실성. 매수는 불리하게(더 비싸게), 매도는 불리하게(더 싸게) 조정한
     "실제 종가"로 체결 판정 자체를 다시 한다 — limit보다 나쁜 값에 체결되는 일은
     없다(실제 지정가 주문의 성질 그대로).
  2. 극단 교란 — 그날의 (고가-저가)/종가 가 해당 티커 전체 역사에서 상위 K% 안에
     들면, 그날 LOC/MOC 자체가 체결 안 됐다고 가정한다(경매 메커니즘이 정상
     작동하지 못했다는 최악의 가정 — 변동성/거래량 데이터만으로 구성했다).

    python research/strategy-lab/loc_fill_realism_check.py
    python research/strategy-lab/loc_fill_realism_check.py --selftest
"""
import argparse
from pathlib import Path

import pandas as pd

import infinite_buying_engine as eng
from infinite_buying_drawdown_episodes import detect_episodes, load_candles as load_price_candles

ROOT = Path(__file__).resolve().parent
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"
THRESHOLD = 0.25
TICKERS = {"TQQQ": 15.0, "SOXL": 20.0}  # base_pct 는 Rules.load 가 JSON 에서 읽는다 — 여기 숫자는 참고용 라벨일 뿐 사용 안 함
SPLITS = 40


def load_engine_candles(ticker: str) -> list[dict]:
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
            for d, o, h, lo, c in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def _row_at_or_before(df: pd.DataFrame, date: str) -> pd.Series:
    sub = df[df["date"] <= date]
    return sub.iloc[-1] if len(sub) else df.iloc[0]


def disrupted_dates(engine_candles: list[dict], pct: float) -> frozenset:
    """그 티커 전체 역사에서 (고가-저가)/종가 상위 pct 안에 드는 날짜 집합."""
    if pct <= 0:
        return frozenset()
    ranges = [(c["high"] - c["low"]) / c["close"] for c in engine_candles]
    thresh = sorted(ranges)[int(len(ranges) * (1 - pct))]
    return frozenset(c["date"] for c, rr in zip(engine_candles, ranges) if rr >= thresh)


def make_fill(slip_bps: float = 0.0, disrupted: frozenset = frozenset(), counters: dict | None = None):
    """slip_bps=0, disrupted=공집합이면 원본 fill()과 완전히 동치(selftest가 확인)."""

    def _fill(o, c):
        side, kind, limit, qty = o
        if qty <= 0:
            return None
        if kind == "LIMIT":
            hit = c["low"] <= limit if side == "buy" else c["high"] >= limit
            return (limit, qty) if hit else None
        # 이 아래(LOC·MOC)만 이 검증의 대상 — 실제 종가 경매를 거치는 주문
        if counters is not None:
            counters["attempted"] = counters.get("attempted", 0) + 1
        if c["date"] in disrupted:
            if counters is not None:
                counters["blocked_disruption"] = counters.get("blocked_disruption", 0) + 1
            return None
        adj = c["close"] * (1 + slip_bps / 10000) if side == "buy" else c["close"] * (1 - slip_bps / 10000)
        if kind == "MOC":
            return (adj, qty)
        if limit is None:
            raise ValueError(f"{kind} 주문에 지정가가 없다")
        hit = adj <= limit if side == "buy" else adj >= limit
        if not hit:
            if counters is not None:
                counters["blocked_slippage"] = counters.get("blocked_slippage", 0) + 1
            return None
        return (adj, qty)

    return _fill


def run_variant(r: eng.Rules, engine_candles: list[dict], episodes: list, fill_fn) -> dict:
    orig_fill = eng.fill
    eng.fill = fill_fn
    try:
        continuous_trace: list = []
        res_full = eng.backtest(engine_candles, r, plan_fn=eng.plan_orders, trace=continuous_trace)
        cdf = pd.DataFrame(continuous_trace)

        rows = []
        for e in episodes:
            end = e.recovery_date or e.end_date
            window = [c for c in engine_candles if e.peak_date <= c["date"] <= end]
            res = eng.backtest(window, r, plan_fn=eng.plan_orders)
            trough_row = _row_at_or_before(cdf, e.trough_date)
            cash_ratio = trough_row["cash"] / trough_row["equity"] if trough_row["equity"] > 0 else float("nan")
            rows.append({
                "peak_date": e.peak_date,
                "cagr": res.cagr, "mdd": res.mdd, "final_eq": res.final_equity,
                "cash_at_trough": cash_ratio, "strategy_fail": res.final_equity < r.seed,
            })
        R = pd.DataFrame(rows)
        return {
            "full_cagr": res_full.cagr, "full_mdd": res_full.mdd,
            "episode_avg_cagr": R["cagr"].mean(), "episode_worst_cagr": R["cagr"].min(),
            "episode_worst_mdd": R["mdd"].max(), "recovery_fail": int(R["strategy_fail"].sum()),
            "n_episodes": len(R), "worst_cash_at_trough": R["cash_at_trough"].min(),
        }
    finally:
        eng.fill = orig_fill


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    c = {"date": "2020-01-06", "open": 100.0, "high": 120.0, "low": 90.0, "close": 100.0}
    base = make_fill()
    ck("slip=0·교란없음이면 LOC 매수 원본과 동치",
       base(("buy", "LOC", 100.0, 1), c) == eng.fill(("buy", "LOC", 100.0, 1), c))
    ck("slip=0·교란없음이면 LOC 매도 원본과 동치",
       base(("sell", "LOC", 100.0, 1), c) == eng.fill(("sell", "LOC", 100.0, 1), c))
    ck("slip=0·교란없음이면 LIMIT 원본과 동치",
       base(("sell", "LIMIT", 115.0, 1), c) == eng.fill(("sell", "LIMIT", 115.0, 1), c))
    ck("slip=0·교란없음이면 MOC 원본과 동치",
       base(("sell", "MOC", None, 1), c) == eng.fill(("sell", "MOC", None, 1), c))

    slip = make_fill(slip_bps=100.0)  # 1% — 극단값으로 방향성만 확인
    buy = slip(("buy", "LOC", 100.0, 1), c)
    ck("매수 슬리피지는 종가보다 비싸게(불리하게) 조정", buy is None or buy[0] > c["close"])
    ck("종가*1.01=101 > 지정가 100 이라 매수 미체결", buy is None)
    sell = slip(("sell", "LOC", 99.0, 1), c)
    ck("매도 슬리피지는 종가보다 싸게(불리하게) 조정되고 그래도 지정가 넘으면 체결",
       sell is not None and sell[0] < c["close"])

    counters: dict = {}
    disrupted = frozenset({"2020-01-06"})
    dis = make_fill(disrupted=disrupted, counters=counters)
    ck("교란일이면 LOC 미체결", dis(("buy", "LOC", 100.0, 1), c) is None)
    ck("교란일이면 MOC도 미체결", dis(("sell", "MOC", None, 1), c) is None)
    ck("교란일 카운터가 늘어난다", counters.get("blocked_disruption", 0) == 2)

    ranges_c = [{"date": f"d{i}", "high": 100 + (10 if i == 5 else 1), "low": 100, "close": 100}
                for i in range(10)]
    dd = disrupted_dates(ranges_c, 0.1)
    ck("상위 10% 변동성 하루만 교란일로 잡힌다", dd == frozenset({"d5"}))

    total = 9
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    variants = [
        ("baseline(원본)", 0.0, 0.0),
        ("slip10bp", 10.0, 0.0),
        ("slip50bp", 50.0, 0.0),
        ("disrupt상위1%", 0.0, 0.01),
        ("최악(slip50bp+disrupt상위1%)", 50.0, 0.01),
    ]

    for ticker in TICKERS:
        r = eng.Rules.load(RULES, ticker, SPLITS)
        engine_candles = load_engine_candles(ticker)
        price_candles = load_price_candles(ticker)
        episodes = detect_episodes(price_candles, THRESHOLD)

        print(f"\n===== {ticker} (splits={SPLITS}, base_pct={r.base_pct:g}, "
              f"episode {len(episodes)}건) =====")
        results = {}
        for label, slip, dpct in variants:
            dset = disrupted_dates(engine_candles, dpct)
            counters: dict = {}
            fill_fn = make_fill(slip_bps=slip, disrupted=dset, counters=counters)
            res = run_variant(r, engine_candles, episodes, fill_fn)
            res["attempted"] = counters.get("attempted", 0)
            res["blocked_slippage"] = counters.get("blocked_slippage", 0)
            res["blocked_disruption"] = counters.get("blocked_disruption", 0)
            results[label] = res

        base = results["baseline(원본)"]
        print(f"{'변형':32} {'전체CAGR':>9} {'전체MDD':>8} {'ep평균CAGR':>10} "
              f"{'ep최악CAGR':>10} {'ep최악MDD':>9} {'회복실패':>7} {'저점현금최소':>10} "
              f"{'미체결(슬리피지/교란)':>16}")
        for label, res in results.items():
            print(f"{label:32} {res['full_cagr']:8.2f}% {res['full_mdd']:7.1f}% "
                  f"{res['episode_avg_cagr']:+9.2f}%p {res['episode_worst_cagr']:+9.2f}% "
                  f"{res['episode_worst_mdd']:8.1f}% {res['recovery_fail']:3d}/{res['n_episodes']:<3d} "
                  f"{res['worst_cash_at_trough']*100:9.1f}% "
                  f"{res['blocked_slippage']:6d}/{res['blocked_disruption']:<6d}")

        worst = results["최악(slip50bp+disrupt상위1%)"]
        print(f"\n  [{ticker}] 최악변형 대비 원본:")
        print(f"    전체CAGR  {base['full_cagr']:+.2f}% -> {worst['full_cagr']:+.2f}%"
              f" (차 {worst['full_cagr']-base['full_cagr']:+.2f}%p)")
        print(f"    전체MDD   {base['full_mdd']:.1f}% -> {worst['full_mdd']:.1f}%"
              f" (차 {worst['full_mdd']-base['full_mdd']:+.1f}%p)")
        print(f"    회복실패  {base['recovery_fail']}/{base['n_episodes']} -> "
              f"{worst['recovery_fail']}/{worst['n_episodes']}")
        print(f"    시도한 LOC/MOC 주문 {worst['attempted']}건 중 슬리피지로 미체결 "
              f"{worst['blocked_slippage']}건 + 교란일로 미체결 {worst['blocked_disruption']}건")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
