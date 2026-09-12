#!/usr/bin/env python3
"""분할매수 사이클 전략 엔진 — 규칙 상수는 코드가 아니라 JSON 이 갖는다.

    python research/strategy-lab/infinite_buying_engine.py --selftest
    python research/strategy-lab/infinite_buying_engine.py --rules <파일> --ticker TQQQ

★ 이 파일에 매직넘버를 두지 않는다. `Rules` 의 모든 값은 외부 JSON 에서 온다.
  특정 방법론의 수치는 원작자가 재배포를 금지해 저장소에 두지 않는다 —
  기전(코드)은 공개하고 값(규칙)은 로컬에 둔다. `--selftest` 는 합성 규칙으로 돌아
  규칙 파일 없이도 이 엔진이 맞게 도는지 검증된다.

기전: 매일 (1) 기준선 = 평단 x (1 + pct/100), pct 는 회차 T 에 선형 감소해
T = N/2 에서 0 — 그 뒤로 기준선이 평단 아래다. (2) 기준선 아래에서 분할매수, 위에서
분할매도. (3) 보유 0 이면 한 사이클 종료. (4) 원금 소진이면 역전 국면으로 전환해
보유를 쪼개 판 현금으로 더 싸게 되산다.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

Order = tuple[str, str, "float | None", int]  # side, kind(LOC|LIMIT|MOC), limit, qty


@dataclass(frozen=True)
class Rules:
    """모든 수치의 단일 출처. 코드에 기본값을 숨기지 않는다."""

    ticker: str
    splits: int
    base_pct: float
    tick: float
    star_slope: float          # pct = base * (1 - slope*T/N)
    quarter_frac: float        # 부분매도 비율
    reverse_enter_t: float     # T > N - this 면 역전 국면
    reverse_sell_div: float    # 역전 매도 비율 = this / N
    reverse_buy_frac: float    # 역전 매수 = 잔금 * this
    reverse_star_window: int
    ladder_tiers: int = 0      # 하단 사다리 단수(0=끔). 출처가 엇갈리는 항목
    ladder_qty: int = 1
    seed: float = 10_000.0
    compound: bool = True
    commission: float = 0.0    # 편도 비율
    tax: float = 0.0           # 사이클 실현이익 과세율

    @staticmethod
    def load(path: Path, ticker: str, splits: int, **over: object) -> "Rules":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        r = Rules(
            ticker=ticker,
            splits=splits,
            base_pct=d["basePct"][ticker],
            tick=d["tick"],
            star_slope=d["starSlope"],
            quarter_frac=d["quarterFrac"],
            reverse_enter_t=d["reverseEnterT"],
            reverse_sell_div=d["reverseSellDiv"],
            reverse_buy_frac=d["reverseBuyFrac"],
            reverse_star_window=d["reverseStarWindow"],
            ladder_tiers=d.get("ladderTiers", 0),
            ladder_qty=d.get("ladderQty", 1),
        )
        return replace(r, **over) if over else r


@dataclass
class State:
    t: float = 0.0
    cash: float = 0.0
    qty: int = 0
    cost: float = 0.0
    realized: float = 0.0
    reverse_day: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0
    fills: int = 0
    commission_paid: float = 0.0
    tax_paid: float = 0.0


def avg(s: State) -> float:
    return s.cost / s.qty if s.qty else 0.0


def star_pct(t: float, r: Rules) -> float:
    return r.base_pct * (1 - r.star_slope * t / r.splits)


def star_price(s: State, r: Rules) -> float:
    return round(avg(s) * (1 + star_pct(s.t, r) / 100), 2)


def unit_amount(s: State, r: Rules) -> float:
    left = r.splits - s.t
    return s.cash / left if left > 0 else 0.0


def in_reverse(s: State) -> bool:
    return s.reverse_day > 0


def exhausted(s: State, r: Rules) -> bool:
    return s.t > r.splits - r.reverse_enter_t


def _buy(orders: list[Order], amount: float, limit: float) -> None:
    if limit > 0:
        q = int(amount // limit)
        if q > 0:
            orders.append(("buy", "LOC", limit, q))


def _ladder(orders: list[Order], amount: float, top: float, r: Rules) -> None:
    """하단 보험 사다리. tierPrice = amount/(baseQty+k). tiers=0 이면 없다."""
    if r.ladder_tiers <= 0 or top <= 0:
        return
    base_qty = int(amount // top)
    for k in range(1, r.ladder_tiers + 1):
        denom = base_qty + k
        price = round(amount / denom, 2) if denom > 0 else 0.0
        if 0 < price < top:
            orders.append(("buy", "LOC", price, r.ladder_qty))


def plan_orders(s: State, r: Rules, recent_closes: list[float]) -> list[Order]:
    if in_reverse(s):
        return _plan_reverse(s, r, recent_closes)

    orders: list[Order] = []
    if s.qty > 0:
        q = int(s.qty * r.quarter_frac)
        if q > 0:
            orders.append(("sell", "LOC", star_price(s, r), q))
        rest = s.qty - q
        if rest > 0:
            orders.append(("sell", "LIMIT", round(avg(s) * (1 + r.base_pct / 100), 2), rest))

    if exhausted(s, r):
        return orders
    unit = unit_amount(s, r)
    if unit <= 0:
        return orders

    if s.qty == 0:
        prev = recent_closes[-1] if recent_closes else 0.0
        top = round(prev * (1 + r.base_pct / 100), 2)
        _buy(orders, unit, top)
        _ladder(orders, unit, top, r)
    elif s.t < r.splits / 2:
        _buy(orders, unit / 2, round(star_price(s, r) - r.tick, 2))
        _buy(orders, unit / 2, round(avg(s), 2))
        _ladder(orders, unit / 2, round(avg(s), 2), r)
    else:
        top = round(star_price(s, r) - r.tick, 2)
        _buy(orders, unit, top)
        _ladder(orders, unit, top, r)
    return orders


def _plan_reverse(s: State, r: Rules, recent_closes: list[float]) -> list[Order]:
    orders: list[Order] = []
    sell_qty = int(s.qty * r.reverse_sell_div / r.splits)
    if s.reverse_day == 1:
        if sell_qty > 0:
            orders.append(("sell", "MOC", None, sell_qty))
        return orders

    win = recent_closes[-r.reverse_star_window:]
    star = round(sum(win) / len(win), 2) if win else 0.0
    if star <= 0:
        return orders
    if sell_qty > 0:
        orders.append(("sell", "LOC", star, sell_qty))
    _buy(orders, s.cash * r.reverse_buy_frac, round(star - r.tick, 2))
    return orders


def fill(o: Order, c: dict) -> "tuple[float, int] | None":
    side, kind, limit, qty = o
    if qty <= 0:
        return None
    if kind == "MOC":
        return (c["close"], qty)
    if limit is None:
        raise ValueError(f"{kind} 주문에 지정가가 없다")
    if kind == "LOC":
        hit = c["close"] <= limit if side == "buy" else c["close"] >= limit
        return (c["close"], qty) if hit else None
    hit = c["low"] <= limit if side == "buy" else c["high"] >= limit
    return (limit, qty) if hit else None


def step(s: State, r: Rules, c: dict, orders: list[Order], daybook: dict | None = None) -> bool:
    """하루치를 반영하고 사이클 종료 여부를 돌려준다. 매도를 먼저 본다.

    daybook 이 주어지면 그날의 실제 체결 수량(buy_qty/sell_qty)을 채워 넣는다 —
    상태 로그(위기 경로 해부용)를 위한 부가 출력일 뿐 기존 동작은 안 바뀐다."""
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
    qty_after_sell = s.qty
    if s.qty != qty_before:
        # 남은 수량 비율만큼 회차를 줄인다 — 부분매도 계수들이 전부 여기서 파생된다.
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
    if reverse and bought > 0:
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
        s.reverse_day = _next_reverse_day(s, r, c)
    if daybook is not None:
        daybook["buy_qty"] = s.qty - qty_after_sell
        daybook["sell_qty"] = qty_before - qty_after_sell
    return closed


def _next_reverse_day(s: State, r: Rules, c: dict) -> int:
    if not in_reverse(s):
        return 1 if exhausted(s, r) else 0
    if c["close"] > avg(s) * (1 - r.base_pct / 100):
        return 0
    return s.reverse_day + 1


@dataclass
class Result:
    cycles: list[dict] = field(default_factory=list)
    final_equity: float = 0.0
    cagr: float = 0.0
    mdd: float = 0.0
    reverse_days: int = 0
    state: "State | None" = None


def backtest(candles: list[dict], r: Rules, plan_fn=plan_orders, trace: list | None = None) -> Result:
    s = State(cash=r.seed)
    closes: list[float] = []
    res = Result()
    peak = r.seed
    price_peak, price_peak_i = (candles[0]["close"], 0) if candles else (0.0, 0)
    cycle_start_eq, cycle_start_i = r.seed, 0

    for i, c in enumerate(candles):
        orders = plan_fn(s, r, closes)
        buy_before, sell_before = s.buy_notional, s.sell_notional
        daybook: dict = {} if trace is not None else None
        closed = step(s, r, c, orders, daybook)
        traded = (s.buy_notional - buy_before) + (s.sell_notional - sell_before)
        if traded and r.commission:
            fee = traded * r.commission
            s.cash -= fee
            s.commission_paid += fee
        closes.append(c["close"])

        if closed:
            profit = s.cash + s.realized - cycle_start_eq
            if profit > 0 and r.tax:
                s.cash -= profit * r.tax
                s.tax_paid += profit * r.tax
                profit *= 1 - r.tax
            res.cycles.append({
                "start": candles[cycle_start_i]["date"], "end": c["date"],
                "days": i - cycle_start_i + 1, "profit": profit,
            })
            cycle_start_eq = s.cash + s.realized
            cycle_start_i = i + 1

        eq = s.cash + s.qty * c["close"] + s.realized
        peak = max(peak, eq)
        if peak > 0:
            res.mdd = max(res.mdd, (peak - eq) / peak * 100)
        if s.reverse_day > 0:
            res.reverse_days += 1
        if c["close"] >= price_peak:
            price_peak, price_peak_i = c["close"], i

        if trace is not None:
            trace.append({
                "date": c["date"], "close": c["close"], "t": s.t, "avg": avg(s),
                "star": star_price(s, r) if s.qty > 0 else None,
                "cash": s.cash, "qty": s.qty,
                "buy_qty": daybook["buy_qty"], "sell_qty": daybook["sell_qty"],
                "reverse": in_reverse(s), "reverse_day": s.reverse_day,
                "cycle_id": len(res.cycles), "cycle_elapsed_days": i - cycle_start_i + 1,
                "exhausted": exhausted(s, r), "realized_pnl": s.realized,
                "equity": eq, "peak_equity": peak,
                "drawdown_pct": (peak - eq) / peak * 100 if peak > 0 else 0.0,
                "price_drawdown_pct": (price_peak - c["close"]) / price_peak * 100 if price_peak > 0 else 0.0,
                "days_since_price_peak": i - price_peak_i,
            })

    res.final_equity = s.cash + s.qty * candles[-1]["close"] + s.realized
    yrs = (_ordinal(candles[-1]["date"]) - _ordinal(candles[0]["date"])) / 365.25
    res.cagr = ((res.final_equity / r.seed) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    res.state = s
    return res


def _ordinal(iso: str) -> int:
    from datetime import date

    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).toordinal()


def _synth() -> Rules:
    """합성 규칙 — 특정 방법론의 값이 아니다. 기전만 검증한다."""
    return Rules(ticker="X", splits=10, base_pct=10.0, tick=0.01, star_slope=2.0,
                 quarter_frac=0.25, reverse_enter_t=1.0, reverse_sell_div=2.0,
                 reverse_buy_frac=0.25, reverse_star_window=5, seed=1000.0)


def selftest() -> int:
    r = _synth()
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ck("기준선 pct 가 T=0 에서 base", abs(star_pct(0, r) - 10.0) < 1e-9)
    ck("기준선 pct 가 T=N/2 에서 0", abs(star_pct(r.splits / 2, r)) < 1e-9)
    ck("기준선 pct 가 후반전에 음수", star_pct(r.splits * 0.75, r) < 0)
    ck("1회매수금 = 잔금/(N-T)", abs(unit_amount(State(cash=900.0, t=1.0), r) - 100.0) < 1e-9)

    s = State(cash=10_000.0, t=1.0, qty=10, cost=1000.0)
    s2 = State(cash=10_000.0, t=8.0, qty=10, cost=1000.0)
    pre = [o for o in plan_orders(s, r, [100.0]) if o[0] == "buy"]
    post = [o for o in plan_orders(s2, r, [100.0]) if o[0] == "buy"]
    ck("전반전 매수주문 2개", len(pre) == 2)
    ck("후반전 매수주문 1개", len(post) == 1)
    ck("후반전 매수가 < 평단", post[0][2] < avg(s2))

    sells = [o for o in plan_orders(s, r, [100.0]) if o[0] == "sell"]
    ck("매도주문 2개(부분+나머지)", len(sells) == 2)
    ck("부분매도 수량 = quarter_frac", sells[0][3] == int(10 * r.quarter_frac))
    ck("나머지 매도가 = 평단*(1+base%)", abs(sells[1][2] - 110.0) < 1e-9)

    s3 = State(cash=0.0, t=4.0, qty=8, cost=800.0)
    step(s3, r, {"date": "2020-01-02", "open": 110.0, "high": 120.0, "low": 109.0,
                 "close": 115.0}, [("sell", "LOC", 110.0, 2)])
    ck("부분매도 후 T = T*(남은/이전)", abs(s3.t - 3.0) < 1e-9)
    ck("부분매도가 평단을 안 바꾼다", abs(avg(s3) - 100.0) < 1e-9)

    s4 = State(cash=0.0, t=4.0, qty=2, cost=200.0)
    closed = step(s4, r, {"date": "2020-01-03", "open": 110.0, "high": 120.0, "low": 109.0,
                          "close": 115.0}, [("sell", "MOC", None, 2)])
    ck("보유 0 -> 사이클 종료 + 리셋", closed and s4.t == 0.0 and s4.cost == 0.0)

    s5 = State(cash=0.0, t=9.5, qty=20, cost=2000.0)
    ck("T > N - enterT 면 소진", exhausted(s5, r))
    s5.reverse_day = 1
    rev = plan_orders(s5, r, [100.0])
    ck("역전 첫날은 MOC 매도만", len(rev) == 1 and rev[0][1] == "MOC")
    ck("역전 매도수량 = 보유*div/N", rev[0][3] == 4)

    s6 = State(cash=400.0, t=9.5, qty=18, cost=1800.0, reverse_day=2)
    rev2 = plan_orders(s6, r, [90.0, 95.0, 100.0, 105.0, 110.0])
    ck("역전 기준선 = 직전 5일 평균", any(abs((o[2] or 0) - 100.0) < 1e-9 for o in rev2))
    ck("역전 둘째날은 매수·매도 양쪽", {o[0] for o in rev2} == {"buy", "sell"})

    c = {"date": "2020-01-06", "open": 100.0, "high": 120.0, "low": 90.0, "close": 100.0}
    ck("LOC 매수는 종가<=지정가", fill(("buy", "LOC", 100.0, 1), c) == (100.0, 1))
    ck("LOC 매수는 종가>지정가면 미체결", fill(("buy", "LOC", 99.0, 1), c) is None)
    ck("LIMIT 매도는 고가 도달 시 지정가 체결", fill(("sell", "LIMIT", 115.0, 1), c) == (115.0, 1))

    s7 = State(cash=10_000.0, t=8.0, qty=10, cost=1000.0)
    on = replace(r, ladder_tiers=3)
    ck("사다리 기본 꺼짐", len(plan_orders(s7, on, [100.0])) == len(plan_orders(s7, r, [100.0])) + 3)
    tops = [o[2] for o in plan_orders(s7, on, [100.0]) if o[0] == "buy"]
    ck("사다리는 본덩이보다 아래", all(t <= tops[0] for t in tops[1:]))

    tiny = State(cash=50.0, t=1.0, qty=10, cost=1000.0)
    ck("1회매수금이 1주 값보다 작으면 매수주문이 없다",
       not [o for o in plan_orders(tiny, r, [100.0]) if o[0] == "buy"])

    flat = [{"date": f"2020-01-{d:02d}", "open": 100.0, "high": 100.0, "low": 100.0,
             "close": 100.0} for d in range(1, 21)]
    big = replace(r, seed=10_000.0)
    a = backtest(flat, big)
    b = backtest(flat, replace(big, commission=0.001))
    ck("횡보에 비용 0 이면 평가금 = 시드", abs(a.final_equity - big.seed) < 1e-6)
    ck("수수료가 있으면 평가금이 준다", b.final_equity < a.final_equity)

    total = 23
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--ticker", default="TQQQ")
    ap.add_argument("--splits", type=int, default=40)
    ap.add_argument("--base", type=float, default=None)
    ap.add_argument("--ladder", type=int, default=None)
    ap.add_argument("--commission", type=float, default=0.0)
    ap.add_argument("--tax", type=float, default=0.0)
    ap.add_argument("--seed", type=float, default=None)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--data", type=Path,
                    default=Path(__file__).resolve().parent / "data" / "leveraged-etf")
    a = ap.parse_args()

    if a.selftest or not a.rules:
        return selftest()

    import pandas as pd

    over: dict = {"commission": a.commission, "tax": a.tax}
    if a.seed is not None:
        over["seed"] = a.seed
    if a.ladder is not None:
        over["ladder_tiers"] = a.ladder
    if a.base is not None:
        over["base_pct"] = a.base
    r = Rules.load(a.rules, a.ticker, a.splits, **over)

    df = pd.read_parquet(a.data / f"{a.ticker}.parquet")
    candles = [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
               for d, o, h, lo, c in
               df[["date", "open", "high", "low", "close"]].itertuples(index=False)]
    if a.start:
        candles = [c for c in candles if c["date"] >= a.start]
    if a.end:
        candles = [c for c in candles if c["date"] <= a.end]

    res = backtest(candles, r)
    st = res.state
    assert st is not None
    print(f"{a.ticker} {a.splits}분할 base={r.base_pct:g} 사다리={r.ladder_tiers}  "
          f"{candles[0]['date']}~{candles[-1]['date']} ({len(candles)}일)")
    print(f"  사이클 {len(res.cycles)}  역전 {res.reverse_days}일  체결 {st.fills}  "
          f"회전 {st.buy_notional / r.seed:.0f}x")
    print(f"  평가금 ${res.final_equity:,.0f}  CAGR {res.cagr:.2f}%  MDD {res.mdd:.1f}%  "
          f"수수료 ${st.commission_paid:,.0f}  세금 ${st.tax_paid:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
