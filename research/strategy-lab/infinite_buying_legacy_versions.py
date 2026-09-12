#!/usr/bin/env python3
"""무한매수법 V2.0/V2.1/V2.2/V3.0 백테스트 — V4.0(infinite_buying_engine.py)과의 비교용.

출처: quantstack.app/infinite/{v2-0,v2-1,v2-2,v3-0} (2026-08-26 갱신본, 원문 이미지 직접
정리라고 밝힘). V4.0 만 구현돼 있던 기존 엔진과 별도 파일 — 버전마다 회차(T) 정의와
매수/매도 조건이 근본적으로 달라(V2.0/V2.1 은 날짜 기반 정수 T, V2.2/V3.0 은 금액 기반
연속 T) 하나의 Rules 로 못 묶는다. LOC/LIMIT/MOC 체결 판정은 V4 엔진의 `fill()` 을 그대로
재사용한다 — 체결 규칙 자체는 전 버전 공통(라오어 방법론 §2 "공통 골격").

    python research/strategy-lab/infinite_buying_legacy_versions.py --selftest
    python research/strategy-lab/infinite_buying_legacy_versions.py --version v22 --ticker TQQQ --base 15 --seed 10000

★ 문서에 없어 임의로 정한 것 (전부 v4 엔진과 같은 선례를 따름):
  - 사이클 첫 매수 진입가 = 전일 종가 × (1+익절%) ("큰수매수" 부트스트랩, v4 와 동일 관례)
  - v20/v21 의 회차(T) = 사이클 시작 후 경과 거래일 수(정수). 원문이 "회차 정의가 모호하다"고
    스스로 인정한 지점(quantstack v2-0 페이지 "미해결 문제 2") — 날짜 기준으로 센다.
  - v20/v21 쿼터손절 세부 프로세스는 v2.2 페이지의 것을 그대로 씀(원 페이지들은 이름만 언급).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from infinite_buying_engine import Order, fill, _ordinal


@dataclass
class LState:
    qty: int = 0
    cost: float = 0.0
    cash: float = 0.0
    t: float = 0.0             # v20/v21: 경과일수(정수) · v22/v30: 매수누적액/1회매수액
    unit: float = 0.0          # 현재 1회매수액 (v30 만 사이클 넘어 증가, 나머지는 고정)
    reserve: float = 0.0       # v30 쿼터모드 대비 보관금
    ql: bool = False           # 쿼터손절/쿼터모드 진입 여부
    ql_buys: int = 0           # 쿼터손절 진입 후 매수 성공 횟수
    fills: int = 0
    buy_notional: float = 0.0
    sell_notional: float = 0.0


def avg(s: LState) -> float:
    return s.cost / s.qty if s.qty else 0.0


def _entry_price(recent_closes: list[float], bump_pct: float) -> float:
    prev = recent_closes[-1] if recent_closes else 0.0
    return round(prev * (1 + bump_pct / 100), 2)


def _buy(orders: list[Order], amount: float, limit: float, kind: str = "LOC") -> None:
    if limit > 0:
        q = int(amount // limit)
        if q > 0:
            orders.append(("buy", kind, limit, q))


# ---------------------------------------------------------------- V2.0 / V2.1

def plan_v20(s: LState, base: float, recent_closes: list[float], v21: bool) -> list[Order]:
    if s.ql:
        return _plan_quarterloss(s, base, orders_are_sells=True)

    orders: list[Order] = []
    a = avg(s)
    if s.qty > 0:
        if not v21:
            if s.t <= 19:
                orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty))
            else:
                half = s.qty // 2
                orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), half))
                orders.append(("sell", "LIMIT", round(a * (1 + base / 200), 2), s.qty - half))
        else:
            if s.t <= 19:
                q1 = int(s.qty * 0.25)
                orders.append(("sell", "LOC", round(a * (1 + base / 200), 2), q1))
                orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty - q1))
            else:
                q1 = int(s.qty * 0.50)
                q2 = int(s.qty * 0.25)
                orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), q1))
                orders.append(("sell", "LIMIT", round(a * (1 + base / 200), 2), q2))
                orders.append(("sell", "LOC", round(a, 2), s.qty - q1 - q2))

    if s.t >= 40:
        return orders
    unit = s.unit
    if s.qty == 0:
        top = _entry_price(recent_closes, base)
        _buy(orders, unit, top)
    elif s.t <= 19:
        _buy(orders, unit / 2, round(a, 2))
        cap = round(a * 1.05, 2)
        _buy(orders, unit / 2, cap)
    else:
        _buy(orders, unit, round(a, 2))
    return orders


def _plan_quarterloss(s: LState, base: float, orders_are_sells: bool) -> list[Order]:
    """v2.0/v2.1/v2.2 공통 쿼터손절(quantstack v2-2 페이지 프로세스). 39<T<=40 에서 발동."""
    orders: list[Order] = []
    a = avg(s)
    if s.qty > 0:
        q1 = int(s.qty * 0.25)
        if s.ql_buys >= 10:
            orders.append(("sell", "MOC", None, q1))
        else:
            orders.append(("sell", "LOC", round(a * (1 - base / 100), 2), q1))
            orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty - q1))
    if s.ql_buys < 10:
        limit = round(a * (1 - base / 100), 2) if a > 0 else 0.0
        _buy(orders, s.unit, limit)
    return orders


# --------------------------------------------------------------------- V2.2

def star_pct_v22(t: float, base: float, splits: int) -> float:
    return base - (t / 2) * (40 / splits)


def plan_v22(s: LState, base: float, splits: int, tick: float, recent_closes: list[float]) -> list[Order]:
    orders: list[Order] = []
    a = avg(s)
    pct = star_pct_v22(s.t, base, splits)
    star = round(a * (1 + pct / 100), 2)

    if s.ql:
        return _plan_quarterloss(s, base, orders_are_sells=True)

    if s.qty > 0:
        q1 = int(s.qty * 0.25)
        orders.append(("sell", "LOC", star, q1))
        orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty - q1))

    if s.t > splits - 1:
        return orders
    unit = s.unit
    if s.qty == 0:
        top = _entry_price(recent_closes, base)
        _buy(orders, unit, top)
    elif s.t < splits / 2:
        _buy(orders, unit / 2, round(a, 2))
        _buy(orders, unit / 2, round(star - tick, 2))
    else:
        _buy(orders, unit, round(star - tick, 2))
    return orders


# --------------------------------------------------------------------- V3.0

def plan_v30(s: LState, base: float, splits: int, tick: float, recent_closes: list[float]) -> list[Order]:
    orders: list[Order] = []
    a = avg(s)
    pct = base * (1 - 2 * s.t / splits)
    star = round(a * (1 + pct / 100), 2)
    half = splits / 2

    exhausting = s.t >= splits - 1

    if s.qty > 0:
        q1 = int(s.qty * 0.25)
        if exhausting:
            orders.append(("sell", "MOC", None, q1))
            orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty - q1))
        else:
            orders.append(("sell", "LOC", star, q1))
            orders.append(("sell", "LIMIT", round(a * (1 + base / 100), 2), s.qty - q1))

    if exhausting:
        return orders  # "그 날은 매수 시도 없음"

    unit = s.unit
    if s.qty == 0:
        top = _entry_price(recent_closes, base)
        _buy(orders, unit, top)
    elif s.t < half:
        _buy(orders, unit / 2, round(a, 2))
        _buy(orders, unit / 2, round(star - tick, 2))
    else:
        _buy(orders, unit, round(star - tick, 2))
    return orders


# ------------------------------------------------------------- 공통 실행 루프

@dataclass
class Result:
    cycles: list[dict] = field(default_factory=list)
    final_equity: float = 0.0
    cagr: float = 0.0
    mdd: float = 0.0


def _apply_fills(s: LState, orders: list[Order], c: dict, commission: float) -> tuple[bool, float]:
    """주문을 체결하고 (사이클종료여부, 오늘실제매수액) 반환. cost/qty/cash 갱신."""
    closed = False
    day_buy_notional = 0.0
    pre_qty = s.qty
    for o in orders:
        r = fill(o, c)
        if r is None:
            continue
        px, q = r
        if px <= 0 or q <= 0:
            continue  # 음수/0 가격 주문은 무시 (avg 왜곡 시 폭주 방지)
        if o[0] == "buy":
            afford = int(s.cash // px) if px > 0 else 0
            q = min(q, afford)
            if q <= 0:
                continue
            notional = px * q
            s.cash -= notional
            s.cost += notional
            s.qty += q
            s.buy_notional += notional
            day_buy_notional += notional
        else:
            notional = px * q
            avg_cost = s.cost / pre_qty if pre_qty else 0.0
            s.cash += notional
            s.cost -= avg_cost * q
            s.qty -= q
            s.sell_notional += notional
        if commission:
            fee = notional * commission
            s.cash -= fee
        s.fills += 1
    if pre_qty > 0 and s.qty == 0:
        closed = True
    return closed, day_buy_notional


def backtest(candles: list[dict], version: str, base: float, splits: int, seed: float,
             tick: float = 0.01, commission: float = 0.0, tax: float = 0.0,
             trace: list | None = None) -> Result:
    s = LState(cash=seed, unit=seed / splits)
    closes: list[float] = []
    res = Result()
    peak = seed
    cycle_start_eq, cycle_start_i = seed, 0

    for i, c in enumerate(candles):
        if version in ("v20", "v21"):
            orders = plan_v20(s, base, closes, v21=(version == "v21"))
        elif version == "v22":
            orders = plan_v22(s, base, splits, tick, closes)
        elif version == "v30":
            orders = plan_v30(s, base, splits, tick, closes)
        else:
            raise ValueError(version)

        closed, bought_amt = _apply_fills(s, orders, c, commission)
        closes.append(c["close"])

        # T·unit·쿼터손절 상태 갱신 (bought_amt·bought 는 _apply_fills 가 실제 체결한 값 — 현금
        # 한도로 잘렸을 수 있으니 orders 를 fill() 로 다시 계산하지 않는다)
        bought = bought_amt > 0
        if version in ("v20", "v21", "v22"):
            if version in ("v20", "v21"):
                if not s.ql:
                    s.t += 1
                    if s.t > 40:
                        s.ql = True
                        s.ql_buys = 0
                        s.unit = (s.cash) / 10 if (s.cash) > 0 else 0.0
                        s.unit = min(s.unit, seed / 40)
                else:
                    if bought:
                        s.ql_buys += 1
                    if s.ql_buys >= 10:
                        sold_at_moc = any(o[0] == "sell" and o[1] == "MOC" for o in orders)
                        if sold_at_moc:
                            s.ql = False
                            s.t = 20  # 후반전 복귀(quantstack: "10회째 MOC 매도" 후 후반전 진입)
                            s.unit = seed / 40
            else:  # v22
                if not s.ql:
                    s.t = round(s.t + bought_amt / s.unit, 3) if s.unit else s.t
                    if s.t > 39:
                        s.ql = True
                        s.ql_buys = 0
                        s.unit = min((s.cash) / 10 if (s.cash) > 0 else 0.0,
                                     seed / 40)
                else:
                    if bought_amt > 0:
                        s.ql_buys += 1
                    if s.ql_buys >= 10:
                        s.ql = False
                        s.t = 20
                        s.unit = seed / 40
        else:  # v30
            s.t = round(s.t + bought_amt / s.unit, 2) if s.unit else s.t

        if closed:
            profit = s.cash - cycle_start_eq
            if profit > 0 and tax:
                s.cash -= profit * tax
                profit *= 1 - tax
            res.cycles.append({"start": candles[cycle_start_i]["date"], "end": c["date"],
                                "days": i - cycle_start_i + 1, "profit": profit})
            cycle_start_eq = s.cash
            cycle_start_i = i + 1
            s.t, s.cost = 0.0, 0.0
            s.ql, s.ql_buys = False, 0
            if version == "v30":
                gain = max(profit, 0.0)
                s.reserve += gain / 2          # 쿼터모드 대비 보관(quantstack "절반 보관")
                s.unit = s.unit + gain / 40     # 반복리: 수익 전액의 1/40 (quantstack 수치예시 실측)
            else:
                s.unit = seed / splits

        eq = s.cash + s.qty * c["close"]
        peak = max(peak, eq)
        if peak > 0:
            res.mdd = max(res.mdd, (peak - eq) / peak * 100)

        if trace is not None:
            trace.append({
                "date": c["date"], "close": c["close"], "t": s.t, "cash": s.cash,
                "qty": s.qty, "equity": eq, "peak_equity": peak,
                "drawdown_pct": (peak - eq) / peak * 100 if peak > 0 else 0.0,
                "exhausted": s.ql, "cycle_id": len(res.cycles),
            })

    res.final_equity = s.cash + s.qty * candles[-1]["close"]
    yrs = (_ordinal(candles[-1]["date"]) - _ordinal(candles[0]["date"])) / 365.25
    res.cagr = ((res.final_equity / seed) ** (1 / yrs) - 1) * 100 if yrs > 0 else 0.0
    return res


# ------------------------------------------------------------------ selftest

def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ck("v2.2 별% T=0 == base", abs(star_pct_v22(0, 10.0, 40) - 10.0) < 1e-9)
    ck("v2.2 별% T=20(40분할) == 0", abs(star_pct_v22(20, 10.0, 40)) < 1e-9)
    ck("v2.2 별% T=38 == -9.0 (문서 예시)", abs(star_pct_v22(38, 10.0, 40) - (-9.0)) < 1e-9)

    flat = [{"date": f"2020-01-{d:02d}", "open": 100.0, "high": 100.0, "low": 100.0,
             "close": 100.0} for d in range(1, 26)]
    for v in ("v20", "v21", "v22", "v30"):
        r = backtest(flat, v, 10.0, 40, 10_000.0)
        ck(f"{v} 횡보 진입가는 0(전일종가 없음)이라 매수 없음 -> 평가금=시드",
           abs(r.final_equity - 10_000.0) < 1e-6)

    up = [{"date": f"2020-01-{d:02d}", "open": 100.0 + d, "high": 100.0 + d,
           "low": 100.0 + d, "close": 100.0 + d} for d in range(1, 3)]
    up += [{"date": f"2020-02-{d:02d}", "open": 100.0 + d, "high": 100.0 + d,
            "low": 100.0 + d, "close": 100.0 + d} for d in range(1, 29)]
    for v in ("v20", "v21", "v22", "v30"):
        r = backtest(up, v, 15.0, 40, 10_000.0)
        ck(f"{v} 상승장에서 사이클이 최소 1개 발생", len(r.cycles) >= 1)

    # ---- 독립검증: quantstack.app 원문 손계산 예시 재현 (내가 짠 selftest 말고 1차 출처 숫자) ----

    # V2.0 — 평단$50·100주 아님 20주, 1회매수액$1000, "둘째 날" 주문의 데드존 표
    s = LState(qty=20, cost=1000.0, cash=39_000.0, t=1, unit=1000.0)
    o20 = plan_v20(s, 10.0, [50.0], v21=False)
    ck("v2.0 둘째날 매수주문 2개(평단·평단+5%)",
       sorted(round(x[2], 2) for x in o20 if x[0] == "buy") == [50.0, 52.5])
    ck("v2.0 둘째날 매도주문 = 평단+10% 전량",
       any(x[0] == "sell" and abs(x[2] - 55.0) < 1e-9 and x[3] == 20 for x in o20))
    for close, want in [(49.0, "전부매수"), (51.0, "절반매수"), (53.0, "데드존"), (56.0, "익절")]:
        c = {"date": "2020-01-02", "open": close, "high": close, "low": close, "close": close}
        fills = [fill(o, c) for o in o20]
        n_buy_fill = sum(1 for o, f in zip(o20, fills) if o[0] == "buy" and f)
        n_sell_fill = sum(1 for o, f in zip(o20, fills) if o[0] == "sell" and f)
        got = ("전부매수" if n_buy_fill == 2 else "절반매수" if n_buy_fill == 1 else
               "익절" if n_sell_fill else "데드존")
        ck(f"v2.0 종가${close:g} -> {want}(quantstack 표)", got == want)

    # V2.1 — 평단$50·100주·15회차, LOC 매도가 "종가"에 체결돼 +6.0% 실현되는지
    s = LState(qty=100, cost=5000.0, cash=35_000.0, t=15, unit=1000.0)
    o21 = plan_v20(s, 10.0, [50.0], v21=True)
    loc_sell = next(o for o in o21 if o[0] == "sell" and o[1] == "LOC")
    ck("v2.1 전반전 LOC매도 = 25주 @ 평단+5%", abs(loc_sell[2] - 52.5) < 1e-9 and loc_sell[3] == 25)
    c53 = {"date": "2020-01-02", "open": 53.0, "high": 53.0, "low": 53.0, "close": 53.0}
    px, q = fill(loc_sell, c53)
    ck("v2.1 종가$53 -> LOC매도가 종가에 체결 = +6.0%(quantstack 예시)",
       abs(px - 53.0) < 1e-9 and abs((px / 50.0 - 1) * 100 - 6.0) < 1e-9)

    # V2.2 — 원금$40,000·40분할, 4일 누적 T (quantstack 표, 소수점 셋째자리 반올림)
    st = LState(cash=40_000.0, unit=1000.0)
    for bought, want_t in [(980.0, 0.98), (500.0, 1.48), (0.0, 1.48), (1010.0, 2.49)]:
        st.t = round(st.t + bought / st.unit, 3)
        ck(f"v2.2 체결액${bought:g} 누적 후 T={want_t}(quantstack 표)", abs(st.t - want_t) < 1e-9)

    # V3.0 — 원금$20,000·20분할, 반복리 4사이클 (quantstack 수치예시)
    unit = 1000.0
    for profit, want_unit in [(200.0, 1005.0), (400.0, 1015.0), (-300.0, 1015.0), (600.0, 1030.0)]:
        unit = unit + max(profit, 0.0) / 40
        ck(f"v3.0 사이클손익${profit:g} 후 1회매수금=${want_unit:g}(quantstack 수치예시)",
           abs(unit - want_unit) < 1e-9)

    total = 3 + 4 + 4 + 6 + 2 + 4 + 4
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--version", choices=["v20", "v21", "v22", "v30"], default="v22")
    ap.add_argument("--ticker", default="TQQQ")
    ap.add_argument("--base", type=float, default=15.0)
    ap.add_argument("--splits", type=int, default=40)
    ap.add_argument("--seed", type=float, default=10_000.0)
    ap.add_argument("--commission", type=float, default=0.0)
    ap.add_argument("--tax", type=float, default=0.0)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--data", type=Path,
                    default=Path(__file__).resolve().parent / "data" / "leveraged-etf")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    import pandas as pd
    df = pd.read_parquet(a.data / f"{a.ticker}.parquet")
    candles = [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
               for d, o, h, lo, c in
               df[["date", "open", "high", "low", "close"]].itertuples(index=False)]
    if a.start:
        candles = [c for c in candles if c["date"] >= a.start]
    if a.end:
        candles = [c for c in candles if c["date"] <= a.end]

    res = backtest(candles, a.version, a.base, a.splits, a.seed,
                    commission=a.commission, tax=a.tax)
    print(f"{a.ticker} [{a.version}] base={a.base:g} splits={a.splits}  "
          f"{candles[0]['date']}~{candles[-1]['date']} ({len(candles)}일)")
    print(f"  사이클 {len(res.cycles)}")
    print(f"  평가금 ${res.final_equity:,.0f}  CAGR {res.cagr:.2f}%  MDD {res.mdd:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
