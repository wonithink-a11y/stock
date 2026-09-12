"""리버스모드 T 전이식 민감도 — READ ONLY, 저장소 코드는 안 건드린다.

후보 A(현재 엔진 = toss/Uni 변형판 추정): 리버스 기준선=5일평균, T 는 매수/매도마다 계속 갱신
후보 B(bottomup32 스펙 §14 가 "순정"이라 암시하는 쪽): 리버스 기준선=일반모드와 같은 별지점(평단
  기반), T 는 리버스 진입 시점 값에서 동결(진행 중 안 바뀜) — 복귀 시 "그 값 그대로 이어간다"(§11)
  는 문장을 T 고정으로 해석한 것.

목적: 어느 쪽이 돈을 더 버는지가 아니라, 2022 위기 결론이 이 해석 차이에 얼마나 흔들리는지 재는 것.
"""
import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\User\projects\stock\research\strategy-lab")
import pandas as pd
from dataclasses import replace

from infinite_buying_engine import (
    Rules, State, avg, star_pct, star_price, unit_amount, in_reverse, exhausted,
    _buy, _ladder, fill, plan_orders as plan_orders_a, _ordinal, Result,
    backtest as engine_backtest,
)

ROOT = Path(r"C:\Users\User\projects\stock\research\strategy-lab")
RULES = ROOT / "data" / "leveraged-etf" / "_rules.local.json"


def plan_orders_b(s: State, r: Rules, recent_closes):
    """후보B: 리버스 기준선을 일반모드 별지점으로. 매수/매도 구조 자체는 A와 동일."""
    if in_reverse(s):
        orders = []
        sell_qty = int(s.qty * r.reverse_sell_div / r.splits)
        if s.reverse_day == 1:
            if sell_qty > 0:
                orders.append(("sell", "MOC", None, sell_qty))
            return orders
        star = star_price(s, r)  # <- 5일평균 대신 별지점(순정 추정)
        if star <= 0:
            return orders
        if sell_qty > 0:
            orders.append(("sell", "LOC", star, sell_qty))
        _buy(orders, s.cash * r.reverse_buy_frac, round(star - r.tick, 2))
        return orders
    return plan_orders_a(s, r, recent_closes)


def step_generic(s: State, r: Rules, c: dict, orders, freeze_t_in_reverse: bool) -> bool:
    reverse = in_reverse(s)
    qty_before, avg_before = s.qty, avg(s)

    for o in [o for o in orders if o[0] == "sell"]:
        f = fill(o, c)
        if f is None:
            continue
        price, q = f
        s.cost -= avg_before * q
        s.qty -= q
        s.cash += price * q
        s.sell_notional += price * q
        s.fills += 1
    if s.qty != qty_before:
        if not (reverse and freeze_t_in_reverse):
            s.t = s.t * (s.qty / qty_before) if qty_before else 0.0

    unit = s.cash * r.reverse_buy_frac if reverse else unit_amount(s, r)
    bought = 0.0
    for o in [o for o in orders if o[0] == "buy"]:
        f = fill(o, c)
        if f is None:
            continue
        price, q = f
        amt = price * q
        if amt > s.cash:
            continue
        s.qty += q
        s.cost += amt
        s.cash -= amt
        s.buy_notional += amt
        s.fills += 1
        bought += amt
        if not reverse and unit > 0:
            s.t += amt / unit
    if reverse and bought > 0 and not freeze_t_in_reverse:
        s.t += (r.splits - s.t) * r.reverse_buy_frac

    closed = qty_before > 0 and s.qty == 0
    if closed:
        s.t = 0.0
        s.cost = 0.0
        s.reverse_day = 0
        if not r.compound:
            s.realized += s.cash - r.seed
            s.cash = r.seed
    else:
        was_reverse = reverse
        s.reverse_day = _next_reverse_day_generic(s, r, c)
        if freeze_t_in_reverse and not was_reverse and s.reverse_day > 0:
            pass  # T 는 진입 시점 값 그대로 자연히 유지됨(별도 처리 불필요)
    return closed


def _next_reverse_day_generic(s, r, c):
    if not in_reverse(s):
        return 1 if exhausted(s, r) else 0
    if c["close"] > avg(s) * (1 - r.base_pct / 100):
        return 0
    return s.reverse_day + 1


def backtest_variant(candles, r: Rules, plan_fn, freeze_t_in_reverse: bool):
    s = State(cash=r.seed)
    closes = []
    res = Result()
    peak = r.seed
    cycle_start_eq, cycle_start_i = r.seed, 0
    reverse_entries = 0
    buys_in_reverse = sells_in_reverse = 0

    for i, c in enumerate(candles):
        was_reverse = in_reverse(s)
        orders = plan_fn(s, r, closes)
        closed = step_generic(s, r, c, orders, freeze_t_in_reverse)
        if in_reverse(s) and not was_reverse:
            reverse_entries += 1
        if in_reverse(s) or was_reverse:
            for o in orders:
                f = fill(o, c)
                if f is None:
                    continue
                if o[0] == "buy":
                    buys_in_reverse += 1
                else:
                    sells_in_reverse += 1
        closes.append(c["close"])

        if closed:
            profit = s.cash + s.realized - cycle_start_eq
            res.cycles.append({"start": candles[cycle_start_i]["date"], "end": c["date"],
                                "days": i - cycle_start_i + 1, "profit": profit})
            cycle_start_eq = s.cash + s.realized
            cycle_start_i = i + 1

        eq = s.cash + s.qty * c["close"] + s.realized
        peak = max(peak, eq)
        if peak > 0:
            res.mdd = max(res.mdd, (peak - eq) / peak * 100)
        if s.reverse_day > 0:
            res.reverse_days += 1

    res.final_equity = s.cash + s.qty * candles[-1]["close"] + s.realized
    yrs = (_ordinal(candles[-1]["date"]) - _ordinal(candles[0]["date"])) / 365.25
    res.cagr = ((res.final_equity / r.seed) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    res.state = s
    return res, reverse_entries, buys_in_reverse, sells_in_reverse


def load_candles(ticker):
    df = pd.read_parquet(ROOT / "data" / "leveraged-etf" / f"{ticker}.parquet")
    return [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": cl}
            for d, o, h, lo, cl in df[["date", "open", "high", "low", "close"]].itertuples(index=False)]


def slice_candles(candles, start, end):
    out = candles
    if start:
        out = [c for c in out if c["date"] >= start]
    if end:
        out = [c for c in out if c["date"] <= end]
    return out


WINDOWS = {"2022crisis": ("2021-11-01", "2022-12-30")}


def _synth_declining_candles(n: int = 120):
    """리버스모드까지 확실히 몰아넣는 합성 하락 경로 — 실제 티커 데이터 불필요."""
    from datetime import date, timedelta
    d0 = date(2020, 1, 1)
    out = []
    price = 100.0
    for i in range(n):
        price *= 0.985  # 꾸준한 하락 -> 소진 -> 리버스 진입을 강제
        d = d0 + timedelta(days=i)
        out.append({"date": d.isoformat(), "open": price, "high": price * 1.01,
                    "low": price * 0.99, "close": price})
    return out


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    synth = Rules(ticker="X", splits=10, base_pct=10.0, tick=0.01, star_slope=2.0,
                  quarter_frac=0.25, reverse_enter_t=1.0, reverse_sell_div=2.0,
                  reverse_buy_frac=0.25, reverse_star_window=5, seed=10_000.0)
    candles = _synth_declining_candles()

    ref = engine_backtest(candles, synth)
    got, _, _, _ = backtest_variant(candles, synth, plan_orders_a, freeze_t_in_reverse=False)

    ck("합성 하락 경로가 실제로 리버스모드까지 간다(전제조건)", ref.reverse_days > 0)
    ck("후보A == 원본 엔진 CAGR", abs(got.cagr - ref.cagr) < 1e-9)
    ck("후보A == 원본 엔진 MDD", abs(got.mdd - ref.mdd) < 1e-9)
    ck("후보A == 원본 엔진 최종자산", abs(got.final_equity - ref.final_equity) < 1e-6)
    ck("후보A == 원본 엔진 역전체류일", got.reverse_days == ref.reverse_days)
    ck("후보A == 원본 엔진 사이클수", len(got.cycles) == len(ref.cycles))

    got_b, _, _, sb = backtest_variant(candles, synth, plan_orders_b, freeze_t_in_reverse=True)
    ck("후보B 는 T 를 얼리므로 후보A 와 다른 결과가 나온다(회귀 아님 확인)",
       abs(got_b.cagr - ref.cagr) > 1e-6 or got_b.reverse_days != ref.reverse_days)

    total = 7
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    for ticker in ["TQQQ", "SOXL"]:
        r = Rules.load(RULES, ticker, 40)
        full = load_candles(ticker)
        for wname, (start, end) in WINDOWS.items():
            candles = slice_candles(full, start, end)
            res_a, re_a, ba, sa = backtest_variant(candles, r, plan_orders_a, freeze_t_in_reverse=False)
            res_b, re_b, bb, sb = backtest_variant(candles, r, plan_orders_b, freeze_t_in_reverse=True)
            print(f"\n===== {ticker} {wname} =====")
            print(f"{'':14}{'후보A(현재)':>16}{'후보B(순정추정)':>18}")
            print(f"{'CAGR%':14}{res_a.cagr:16.2f}{res_b.cagr:18.2f}")
            print(f"{'MDD%':14}{res_a.mdd:16.1f}{res_b.mdd:18.1f}")
            print(f"{'최종자산$':14}{res_a.final_equity:16,.0f}{res_b.final_equity:18,.0f}")
            print(f"{'사이클수':14}{len(res_a.cycles):16d}{len(res_b.cycles):18d}")
            print(f"{'역전진입횟수':14}{re_a:16d}{re_b:18d}")
            print(f"{'역전체류일':14}{res_a.reverse_days:16d}{res_b.reverse_days:18d}")
            print(f"{'역전중매수':14}{ba:16d}{bb:18d}")
            print(f"{'역전중매도':14}{sa:16d}{sb:18d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
