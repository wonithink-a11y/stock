#!/usr/bin/env python3
"""분할매수 사이클 슬리브 일별 실행 - 두 모드를 한 진입점에서 돌린다.

    # 1번 - 자체 페이퍼. 주문을 안 낸다. 규칙대로(LOC) 돈다 = 전략 판정용 정본
    python research/strategy-lab/run_infinite_buying_daily.py --mode paper

    # 2번 - KIS 모의투자 배선. 기본이 dry-run 이라 --execute 없이는 주문이 안 나간다
    python research/strategy-lab/run_infinite_buying_daily.py --mode vts
    python research/strategy-lab/run_infinite_buying_daily.py --mode vts --execute

    python research/strategy-lab/run_infinite_buying_daily.py --selftest   # 네트워크 없음

★ 왜 두 모드인가 (findings/infinite-buying-rule-spec-2026-09.md §7.11)
  KIS 모의투자는 **지정가(00)만** 받는다 - LOC(34)는 실전 전용이다. 지정가로 흉내 내면
  사이클이 45% 줄고 MDD 가 6~9%p 나빠진다(실측). 그래서 모의투자에서 나오는 숫자는
  이 전략의 숫자가 아니다. `paper` 가 전략 판정용 정본이고, `vts` 는 **주문 경로
  검증용**이다. 둘을 같은 상태로 섞지 않는다 - 상태 파일이 모드별로 따로 있다.

★ 규칙 값은 이 파일에 없다. 로컬 JSON(`--rules`)에서만 온다(엔진과 같은 원칙).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import infinite_buying_engine as E  # noqa: E402

KST = timezone(timedelta(hours=9))
DATA = _HERE / "data" / "leveraged-etf"
# VM 은 git pull 을 하므로 저장소 안의 추적 파일(state/*.json)을 거기서 고치면 다음
# pull 이 막힌다. VM 은 이 환경변수로 상태를 저장소 밖에 둔다.
STATE_DIR = Path(os.environ.get("INFBUY_STATE_DIR") or DATA / "state")
DEFAULT_RULES = DATA / "_rules.local.json"
SLEEVES = ("TQQQ", "SOXL")


# ---------------------------------------------------------------- 상태 입출력


def state_path(ticker: str, mode: str) -> Path:
    return STATE_DIR / f"{ticker}_{mode}.json"


def load_state(ticker: str, mode: str, seed: float,
               splits: int | None = None) -> tuple[E.State, dict]:
    """저장된 상태를 읽는다. ★ 분할수가 바뀌면 이어가지 않고 막는다.

    T 는 '분할수 분의 몇 회차'라 분모가 바뀌면 같은 T 가 다른 뜻이 된다. 조용히
    이어가면 후반전 경계(T = N/2)와 소진 판정이 통째로 어긋난다 - 잴 수 없는 상태로
    넘어가느니 시끄럽게 막는다(교훈57).
    """
    p = state_path(ticker, mode)
    if not p.exists():
        return E.State(cash=seed), {"lastDate": None, "log": [], "lastUnit": None,
                                    "splits": splits}
    d = json.loads(p.read_text(encoding="utf-8"))
    prev = d.get("splits")
    if splits is not None and prev is not None and prev != splits and d["state"]["qty"] > 0:
        raise SystemExit(
            f"{ticker}/{mode}: 분할수가 {prev} -> {splits} 로 바뀌었는데 보유가 남아 있다"
            f"(T {d['state']['t']:.2f}). T 의 분모가 바뀌면 같은 값이 다른 뜻이 된다. "
            f"사이클을 끝내고 바꾸거나, 상태 파일을 지우고 새로 시작한다.")
    s = E.State(**{k: v for k, v in d["state"].items()
                   if k in E.State.__dataclass_fields__})
    return s, {"lastDate": d.get("lastDate"), "log": d.get("log", []),
               "lastUnit": d.get("lastUnit"), "splits": splits if splits is not None else prev}


def save_state(ticker: str, mode: str, s: E.State, meta: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path(ticker, mode).write_text(json.dumps({
        "ticker": ticker, "mode": mode,
        "updatedAtKst": datetime.now(KST).isoformat(),
        "lastDate": meta["lastDate"],
        "lastUnit": meta.get("lastUnit"),
        "splits": meta.get("splits"),
        "state": asdict(s),
        "log": meta["log"][-400:],   # 최근 400건만 - 무한히 자라지 않게
    }, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 시세


def recent_bars(ticker: str, days: int = 30) -> list[dict]:
    """최근 일봉. 파일이 있으면 그걸 쓰고, 모자라면 yfinance 로 이어 받는다."""
    import pandas as pd

    p = DATA / f"{ticker}.parquet"
    df = pd.read_parquet(p) if p.exists() else None
    need = df is None or (datetime.now(KST).date()
                          - df["date"].iloc[-1].date()).days > 1
    if need:
        import yfinance as yf

        fresh = yf.Ticker(ticker).history(period="3mo", auto_adjust=False, actions=False)
        fresh = fresh.reset_index().rename(columns=str.lower)
        fresh["date"] = pd.to_datetime(fresh["date"]).dt.tz_localize(None).dt.normalize()
        df = fresh if df is None else (
            pd.concat([df, fresh])[["date", "open", "high", "low", "close"]]
            .drop_duplicates("date", keep="last").sort_values("date"))
    tail = df.tail(days)
    return [{"date": d.strftime("%Y-%m-%d"), "open": float(o), "high": float(h),
             "low": float(lo), "close": float(c)}
            for d, o, h, lo, c in
            tail[["date", "open", "high", "low", "close"]].itertuples(index=False)]


# ---------------------------------------------------------------- 모드


def run_paper(ticker: str, rules_path: Path, seed: float, splits: int,
              verbose: bool) -> dict:
    """규칙대로(LOC) 하루를 진행한다. 주문 없음. 마지막 처리일 이후만 따라잡는다."""
    r = E.Rules.load(rules_path, ticker, splits, seed=seed)
    s, meta = load_state(ticker, "paper", seed, splits)
    bars = recent_bars(ticker)
    closes = [b["close"] for b in bars]

    idx = [i for i, b in enumerate(bars)
           if meta["lastDate"] is None or b["date"] > meta["lastDate"]]
    if meta["lastDate"] is None:
        idx = idx[-1:]              # 첫 실행은 오늘부터. 과거를 몰래 소급하지 않는다
    fresh = [bars[i] for i in idx]
    if not fresh:
        return {"ticker": ticker, "mode": "paper", "advanced": 0,
                "date": meta["lastDate"], "state": s}

    for i in idx:
        b = bars[i]
        # ★ 종가 값이 아니라 **위치**로 자른다. 같은 종가가 두 번 나오면 index() 가
        # 첫 번째를 집어 과거를 다시 보게 된다(조용히 틀리는 자리).
        orders = E.plan_orders(s, r, closes[:i])
        before = s.qty
        closed = E.step(s, r, b, orders)
        meta["log"].append({"date": b["date"], "close": b["close"],
                            "orders": len(orders), "qtyFrom": before, "qtyTo": s.qty,
                            "t": round(s.t, 3), "cycleClosed": closed})
        if verbose:
            print(f"  {b['date']} 종가 {b['close']:.2f}  주문 {len(orders)}  "
                  f"보유 {before}->{s.qty}  T {s.t:.2f}" + ("  [사이클 종료]" if closed else ""))
    meta["lastDate"] = fresh[-1]["date"]
    save_state(ticker, "paper", s, meta)
    return {"ticker": ticker, "mode": "paper", "advanced": len(fresh),
            "date": meta["lastDate"], "state": s}


def cancel_open_orders(c, ticker: str, execute: bool, verbose: bool = True,
                       sleep=time.sleep, tries: int = 3) -> dict:
    """이 종목의 잔존 미체결을 취소하고, 0 이 될 때까지 확인한다.

    ★ 새 주문은 이 함수가 `blocked=False` 를 돌려줬을 때만 낸다. 취소가 실패했거나
    미체결이 남았는데 재접수하면 같은 주문이 쌓인다(중복 매수). 하루 건너뛰는 게 낫다.
    부분체결은 계좌 보유로 이미 반영되므로(run_vts 가 브로커를 읽는다) 여기서는
    **취소 후 계좌를 다시 읽는 순서**만 지키면 된다 - 호출부가 그 순서를 지킨다.
    dry-run 이면 조회만 하고 취소하지 않는다(`blocked` 도 False - 아무것도 안 냈다).
    """
    def mine():
        return [o for o in c.open_orders() if o["symbol"] == ticker]

    found = mine()
    out = {"found": len(found), "cancelled": 0, "remaining": len(found), "blocked": False}
    if not found:
        return out
    if verbose:
        print(f"  잔존 미체결 {len(found)}건: "
              + ", ".join(f"{o['side']} {o['qty'] - o['filledQty']}주@{o['price']:.2f}"
                          for o in found))
    if not execute:
        if verbose:
            print("  DRY  취소하지 않음(--execute 아님)")
        return out
    for o in found:
        left = o["qty"] - o["filledQty"]
        if left <= 0:
            continue
        try:
            c.cancel(ticker, o["orderNo"], left, dry_run=False)
            out["cancelled"] += 1
        except Exception as e:  # noqa: BLE001 - 실패는 아래 재조회가 판정한다
            print(f"  취소 실패 {o['orderNo']}: {e}", file=sys.stderr)
    for k in range(tries):
        rem = mine()
        if not rem:
            break
        if k < tries - 1:
            sleep(1.0)
    out["remaining"] = len(rem)
    out["blocked"] = bool(rem)
    return out


def run_vts(ticker: str, rules_path: Path, seed: float, splits: int,
            execute: bool, verbose: bool) -> dict:
    """모의투자 계좌에 그날 주문을 낸다. **지정가만** - LOC 가 아니다(모듈 docstring)."""
    from engine.live.kisVtsOverseasClient import KisVtsOverseasClient

    c = KisVtsOverseasClient()
    r = E.Rules.load(rules_path, ticker, splits, seed=seed)
    s, meta = load_state(ticker, "vts", seed, splits)

    # ★ 순서가 계약이다: 잔존 주문 취소 -> (그 뒤에) 계좌 조회 -> 재계획 -> 재접수.
    # 취소 전에 계좌를 읽으면 그 사이 체결된 분이 T 에 안 잡힌다.
    co = cancel_open_orders(c, ticker, execute, verbose)
    if co["blocked"]:
        print(f"  ★ 미체결 {co['remaining']}건이 안 없어져서 {ticker} 는 오늘 주문을 내지 않는다",
              file=sys.stderr)
        return {"ticker": ticker, "mode": "vts", "planned": 0, "placed": 0,
                "skippedMOC": 0, "executed": execute, "blocked": True,
                "cancel": co, "state": s}

    bars = recent_bars(ticker)
    last = bars[-1]

    # 브로커가 정본이다 - 보유/평단을 로컬 장부로 추측하지 않고 계좌에서 읽는다(교훈75).
    held = {h["symbol"]: h for h in c.holdings()}
    h = held.get(ticker)
    qty_before, cost_before = s.qty, s.cost
    s.qty = h["qty"] if h else 0
    s.cost = (h["qty"] * h["avgPrice"]) if h else 0.0

    # ★ 회차(T)는 브로커가 안 준다 - 보유수량만으로는 복원되지 않으므로 여기서 잇는다.
    # 엔진과 **같은 규칙**을 쓴다: 매수는 T += 체결금액/1회매수금, 매도는 남은 수량 비율.
    # 처음엔 감소분만 반영해서 T 가 영원히 0 에 머물렀다 - 그러면 후반전·소진 판정이
    # 아예 오지 않는다(2026-09-12 첫 실주문 직후 발견). 조용히 틀리는 자리라 회귀로 핀한다.
    last_unit = float(meta.get("lastUnit") or 0.0)
    if s.qty > qty_before and last_unit > 0:
        s.t += max(0.0, s.cost - cost_before) / last_unit
    elif qty_before and s.qty < qty_before:
        s.t = s.t * (s.qty / qty_before)

    bp = c.buying_power(ticker, last["close"])
    # 이 슬리브의 잔금 = 배정액에서 **이미 투입된 원가**를 뺀 것. 그리고 계좌에 실제로
    # 있는 돈을 넘지 않는다. min(seed, orderable) 로만 두면 이미 쓴 만큼을 또 남은 것으로
    # 세어 1회매수금이 계속 부풀고, 그 오차는 T 가 오를수록 커진다(2026-09-12 첫 실주문
    # 직후 발견 - $1,071 을 쓰고도 잔금이 $50,000 으로 찍혔다).
    # ★ 두 슬리브가 **하나의 외화 예수금을 공유**한다. 각 슬리브를 자기 배정액으로
    # 묶어 두는 것이 교차 초과를 막는 장치이고, 합이 예수금을 넘으면 브로커가 거절한다
    # (여기서 배분기를 새로 짜지 않는다 - 필요해지면 그때).
    s.cash = max(0.0, min(seed - s.cost, bp["orderableCash"]))

    # ★ 여기서 내는 주문은 **다음 세션**의 것이다. 그러니 기준이 되는 "직전 종가"는
    # 마지막 완료 세션이다. 끝에서 하나를 잘라내면 한 세션 옛 종가로 큰수를 잡는다
    # (2026-09-12 dry-run 에서 $79.59 로 드러났다 - 71.57x1.15 = $82.31 이어야 한다).
    # 역전모드의 5일 평균도 같은 이유로 전부 넘긴다. 아래 selftest 가 이 자리를 핀한다.
    orders = E.plan_orders(s, r, [b["close"] for b in bars])
    meta["lastUnit"] = E.unit_amount(s, r)   # 다음 실행이 T 를 이을 때 쓴다
    placed = []
    for side, kind, limit, q in orders:
        if limit is None or q <= 0:
            continue                       # MOC 는 모의투자에 없다 - 건너뛰고 기록만 한다
        res = c.place(side, ticker, q, limit, dry_run=not execute)
        placed.append(res)
        if verbose:
            tag = "DRY " if res["dryRun"] else "접수"
            print(f"  {tag} {side:4} {q:>4}주 @ ${limit:.2f}"
                  + ("" if res["dryRun"] else f"  주문번호 {res.get('orderNo')}"))

    skipped = [o for o in orders if o[2] is None]
    meta["log"].append({"date": last["date"], "close": last["close"],
                        "planned": len(orders), "placed": len(placed),
                        "skippedMOC": len(skipped), "executed": execute,
                        "cancelled": co["cancelled"], "qty": s.qty, "t": round(s.t, 3),
                        "orderableCash": bp["orderableCash"], "fx": bp["fxRate"]})
    meta["lastDate"] = last["date"]
    save_state(ticker, "vts", s, meta)
    return {"ticker": ticker, "mode": "vts", "planned": len(orders),
            "placed": len(placed), "skippedMOC": len(skipped),
            "executed": execute, "buyingPower": bp, "cancel": co, "state": s}


# ---------------------------------------------------------------- selftest


def _frag(*parts: str) -> str:
    """소스 검사용 바늘을 조각에서 조립한다.

    ★ 소스를 훑는 검사는 **자기 자신이 바늘**이 되어 영원히 참/거짓이 된다.
    이 세션에서 같은 실수를 세 번 했다(교훈72 의 거울상 - 통과가 아니라 실패가
    구성상 보장됐다). 검사 줄에는 조각만 두고 여기서 합친다.
    """
    return "".join(parts)


def selftest() -> int:
    """네트워크·규칙파일 없이 도는 검사. 조용히 틀릴 수 있는 자리만 본다."""
    import tempfile

    fails: list[str] = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    global STATE_DIR
    with tempfile.TemporaryDirectory() as td:
        saved, STATE_DIR = STATE_DIR, Path(td)

        ck("모드별 상태파일이 분리된다",
           state_path("TQQQ", "paper") != state_path("TQQQ", "vts"))
        ck("슬리브별 상태파일이 분리된다",
           state_path("TQQQ", "paper") != state_path("SOXL", "paper"))

        s0, m0 = load_state("TQQQ", "paper", 1000.0)
        ck("상태가 없으면 시드로 시작한다", s0.cash == 1000.0 and s0.qty == 0)
        ck("첫 실행은 lastDate 가 없다", m0["lastDate"] is None)

        s0.qty, s0.t, s0.cash = 7, 2.5, 400.0
        m0["lastDate"] = "2026-09-11"
        m0["log"] = [{"date": "2026-09-11"}]
        save_state("TQQQ", "paper", s0, m0)
        s1, m1 = load_state("TQQQ", "paper", 1000.0)
        ck("상태가 왕복한다", (s1.qty, s1.t, s1.cash) == (7, 2.5, 400.0))
        ck("lastDate 가 왕복한다", m1["lastDate"] == "2026-09-11")
        ck("다른 모드는 그 상태를 안 본다",
           load_state("TQQQ", "vts", 1000.0)[1]["lastDate"] is None)

        m0["log"] = [{"i": i} for i in range(900)]
        save_state("TQQQ", "paper", s0, m0)
        ck("로그가 무한히 자라지 않는다", len(load_state("TQQQ", "paper", 1000.0)[1]["log"]) == 400)

        # 분할수가 바뀌면 조용히 이어가지 않는다 - T 의 분모가 달라지기 때문이다
        s2, m2 = load_state("SOXL", "paper", 1000.0, 40)
        s2.qty, s2.t = 5, 3.0
        m2["splits"] = 40
        save_state("SOXL", "paper", s2, m2)
        ck("같은 분할수면 이어간다", load_state("SOXL", "paper", 1000.0, 40)[0].t == 3.0)
        try:
            load_state("SOXL", "paper", 1000.0, 20)
            ck("분할수가 바뀌고 보유가 있으면 막는다", False)
        except SystemExit:
            ck("분할수가 바뀌고 보유가 있으면 막는다", True)
        s2.qty = 0
        save_state("SOXL", "paper", s2, m2)
        ck("보유가 0 이면 분할수를 바꿔도 된다",
           load_state("SOXL", "paper", 1000.0, 20)[1]["splits"] == 20)

        STATE_DIR = saved

    # 계획 기준일 - 같은 종가가 반복돼도 위치로 잘라야 한다
    bars = [{"date": f"2026-09-0{d}", "open": 10.0, "high": 10.0, "low": 10.0,
             "close": 10.0} for d in (1, 2, 3)]
    closes = [b["close"] for b in bars]
    ck("반복 종가에서도 위치로 자른다", closes[:2] == [10.0, 10.0] and len(closes[:0]) == 0)
    ck("_frag 이 조각을 합친다", _frag("ab", "cd") == "abcd")

    # 규칙 값이 이 파일에 새지 않았는지
    src = Path(__file__).read_text(encoding="utf-8")
    # 바늘을 조각으로 만든다 - 통짜로 쓰면 이 검사 줄 자체가 바늘이라 영원히 실패한다.
    ck("이 파일에 별% 기준값이 하드코딩돼 있지 않다",
       not any(n in src for n in (_frag("base", "Pct"), _frag("base", "_pct"))))
    ck("주문 기본이 dry-run 이다 (--execute 를 명시해야 나간다)",
       "dry_run=not execute" in src and "--execute" in src)
    ck("vts 계획이 마지막 완료 세션을 기준으로 삼는다 (한 세션 뒤처지지 않는다)",
       _frag('[b["close"] ', 'for b in bars]') in src
       and _frag("bars[", ":-1]") not in src)

    src_vts = src[src.index("def run_vts"):src.index("# ---", src.index("def run_vts"))]
    ck("vts 가 매수에서도 T 를 올린다 (감소분만 반영하면 T 가 영원히 0 이다)",
       "s.t +=" in src_vts and "lastUnit" in src_vts)
    ck("vts 의 T 증가가 엔진과 같은 규칙(체결금액/1회매수금)이다", "/ last_unit" in src_vts)
    # 취소-후-재접수 계약 - 가짜 브로커로 실제 동작을 본다(문자열 검사가 아니다)
    class _Fake:
        def __init__(self, stuck=False, fail=False):
            self.book = [{"orderNo": "1", "symbol": "TQQQ", "side": "BUY", "qty": 4,
                          "filledQty": 1, "price": 71.0},
                         {"orderNo": "2", "symbol": "SOXL", "side": "BUY", "qty": 2,
                          "filledQty": 0, "price": 120.0}]
            self.stuck, self.fail, self.calls = stuck, fail, []

        def open_orders(self):
            return list(self.book)

        def cancel(self, sym, no, qty, dry_run=True):
            self.calls.append((sym, no, qty, dry_run))
            if self.fail:
                raise RuntimeError("거절")
            if not self.stuck:
                self.book = [o for o in self.book if o["orderNo"] != no]

    nosleep = lambda _s: None  # noqa: E731
    f = _Fake()
    o = cancel_open_orders(f, "TQQQ", True, False, sleep=nosleep)
    ck("잔량(원수량-체결분)만 취소한다", f.calls == [("TQQQ", "1", 3, False)])
    ck("다른 종목 주문은 안 건드린다", all(c_[0] == "TQQQ" for c_ in f.calls))
    ck("취소가 확인되면 blocked 가 아니다", o["cancelled"] == 1 and not o["blocked"])
    f = _Fake()
    o = cancel_open_orders(f, "TQQQ", False, False, sleep=nosleep)
    ck("dry-run 은 취소를 부르지 않는다", f.calls == [] and o["found"] == 1 and not o["blocked"])
    f = _Fake(stuck=True)
    o = cancel_open_orders(f, "TQQQ", True, False, sleep=nosleep)
    ck("취소했는데 남아 있으면 blocked (재접수 금지)", o["blocked"] and o["remaining"] == 1)
    f = _Fake(fail=True)
    o = cancel_open_orders(f, "TQQQ", True, False, sleep=nosleep)
    ck("취소가 실패하면 blocked (재접수 금지)", o["blocked"])
    f = _Fake()
    ck("미체결이 없으면 아무것도 안 한다",
       cancel_open_orders(f, "QQQQ", True, False, sleep=nosleep)["found"] == 0 and f.calls == [])
    ck("run_vts 가 blocked 면 주문 전에 돌아간다",
       src_vts.index('co["blocked"]') < src_vts.index("c.place("))
    ck("run_vts 가 취소를 계좌 조회보다 먼저 한다",
       src_vts.index("cancel_open_orders(") < src_vts.index("c.holdings()"))
    ck("vts 잔금이 이미 투입한 원가를 뺀 값이다 (배정액 전부로 세지 않는다)",
       _frag("min(seed ", "- s.cost") in src_vts)

    # ★ selftest 가 main() 을 안 불러서 CLI 배선 오류를 놓쳤다(2026-09-12, --splits 추가
    # 직후 TypeError). 인자 수가 맞는지 서명으로 직접 본다 - 문자열 검사보다 정확하다.
    import inspect as _insp
    main_src = src[src.index("def main("):]
    ck("main 이 run_paper/run_vts 에 splits 를 넘긴다",
       "a.splits, verbose" in main_src and "a.splits, a.execute" in main_src)
    ck("run_paper 서명에 splits 가 있다", "splits" in _insp.signature(run_paper).parameters)
    ck("run_vts 서명에 splits 가 있다", "splits" in _insp.signature(run_vts).parameters)

    total = 31
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("paper", "vts"), default="paper")
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--tickers", nargs="+", default=list(SLEEVES))
    ap.add_argument("--seed-usd", type=float, default=50000.0, help="슬리브당 배정")
    ap.add_argument("--splits", type=int, default=40, choices=(20, 30, 40),
                    help="분할수. 작을수록 공격적 - 자금 소진이 빠르고 MDD 가 커진다")
    ap.add_argument("--execute", action="store_true",
                    help="vts 모드에서 실제로 주문을 접수한다. 없으면 dry-run")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if not a.rules.exists():
        print(f"규칙 파일이 없다: {a.rules}", file=sys.stderr)
        return 1

    verbose = not a.quiet
    print(f"모드 {a.mode}"
          + (f"  (dry-run - 주문 안 나감)" if a.mode == "vts" and not a.execute else "")
          + f"  슬리브당 ${a.seed_usd:,.0f}  {a.splits}분할")
    for t in a.tickers:
        print(f"\n[{t}]")
        res = (run_paper(t, a.rules, a.seed_usd, a.splits, verbose) if a.mode == "paper"
               else run_vts(t, a.rules, a.seed_usd, a.splits, a.execute, verbose))
        s = res["state"]
        eq = s.cash + s.qty * (s.cost / s.qty if s.qty else 0.0)
        print(f"  -> 보유 {s.qty}주  평단 ${(s.cost / s.qty if s.qty else 0):.2f}  "
              f"T {s.t:.2f}  잔금 ${s.cash:,.0f}  (원가기준 ${eq:,.0f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
