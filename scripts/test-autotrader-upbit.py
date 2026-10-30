#!/usr/bin/env python3
"""autotrader 업비트 경로 회귀 — 코인베이스 프리미엄 C24 실계좌 연결. 키·네트워크 없이 돈다.

핀하는 것:
  설정 — broker upbit 는 UPBIT 시장·live·UPBIT_<접두사> 키만, 조회용 UPBIT_ACCESS_KEY 는 못 고른다, KIS 설정은 그대로
  주문 의도 — UPBIT 만 소수 수량(8자리)·시장가, KR/US 규칙 불변 · 최소 주문 5,000원
  어댑터 — 매수 = 원 금액(price), 매도 = 수량(지수 표기 없음), identifier 전달, dry-run·잠금이면 요청 안 보냄,
          종료 주문 조회는 7일씩 나눠서, 평균가는 체결 목록으로, 주문 생성 '테스트'로만 probe
  전략 — 첫 실행은 차단만 · z ≥ 2 정시 매수 · 체결 확인 뒤에만 포지션 · 24h 뒤 **자기 체결 수량만** 매도(개인 보유 안 건드림) ·
          dry-run 은 포지션을 안 만든다 · 30분 넘게 늦으면 진입 안 하고 알림 · 킬 스위치 · 모의 러너와 같은 진입 시각
  표시 — 소수 수량 손익, 알림 단위 '개', 실행 요약에 알림

    python scripts/test-autotrader-upbit.py
"""
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import cli, notify                                            # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import (ConfigError, GateError, gate_problems, key_names, kill_file, load_env,  # noqa: E402
                               normalize_config)
from autotrader.engine import KST, Ledger, run_once                          # noqa: E402
from autotrader.models import Intent, Position                               # noqa: E402
from autotrader import risk as R                                              # noqa: E402
from autotrader.pnl import new_fills, realized, sync_fills                    # noqa: E402
from autotrader.strategies import coinbase_premium as CPS                     # noqa: E402
from autotrader.upbit import UpbitBroker, _vol                                # noqa: E402

FAILS, COUNT = [], [0]
ENV = {"UPBIT_TRADE_ACCESS_KEY": "a", "UPBIT_TRADE_SECRET_KEY": "s", "AUTOTRADER_ALLOW_LIVE": "I-ACCEPT-REAL-TRADES"}
PX = 100_000_000.0                       # BTC 1억원


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def cfg_for(td, **kw):
    base = {"strategy": "coinbase_premium", "broker": "upbit", "mode": "live", "key_prefix": "UPBIT_TRADE",
            "markets": ["UPBIT"], "symbol_allowlist": ["KRW-BTC"], "params": {"notional_krw": 1_000_000},
            "risk": {"UPBIT": {"max_order_value": 1_100_000, "max_daily_value": 2_500_000, "max_position_value": 200_000_000}},
            "live": {"enabled": True, "tr_ids_reviewed": True}, "state_dir": str(td)}
    return normalize_config({**base, **kw})


# ---------------------------------------------------------------- 합성 시장
class Market:
    """매끈한 프리미엄(사인파, |z| < 1.5 — 사건 없음) + 지정 시각 급등. fetcher 가 T 시점에 보였을 구간만 잘라 준다."""

    def __init__(self, spikes, start, hours=1400, noise=None):
        idx = pd.date_range(start, periods=hours, freq="h", tz="UTC")
        rng = np.random.default_rng(7)
        self.bn = pd.Series(PX / 1400 * np.exp(np.cumsum(rng.normal(0, 0.002, hours))), index=idx)
        prem = 0.0004 * np.sin(np.arange(hours) * 2 * np.pi / 37) if noise is None else noise(hours)
        for s in spikes:                                  # z(s) 는 s−1h 봉의 프리미엄으로 정해진다
            prem[idx.get_loc(pd.Timestamp(s) - pd.Timedelta(hours=1))] += 0.01
        self.cb = self.bn * (1 + prem)

    def fetcher(self, P, T):
        lo = T - P.FETCH_HOURS * P.H
        cb = self.cb[(self.cb.index >= lo) & (self.cb.index < T)]
        bn = self.bn[(self.bn.index >= lo) & (self.bn.index <= T)]
        return cb, pd.DataFrame({"open": bn.shift(1).bfill(), "close": bn})


def kst(ts_utc, minute=2):
    return (pd.Timestamp(ts_utc) + pd.Timedelta(minutes=minute)).tz_convert("Asia/Seoul").to_pydatetime()


def run(cfg, fb, when, execute=True):
    return run_once(cfg, fb, CPS.STRATEGY(), execute=execute, env=ENV, now=when, sleep=lambda s: None)


# ---------------------------------------------------------------- 가짜 업비트 클라이언트
class FakeClient:
    def __init__(self):
        self.calls = []
        self.closed = []
        self.details = {}

    def get_ticker(self, m):
        if m == "KRW-XYZ":
            raise RuntimeError("마켓 없음")
        return PX

    def get_accounts(self):
        return [{"currency": "KRW", "balance": "2500000", "unit_currency": "KRW"},
                {"currency": "BTC", "balance": "0.015", "avg_buy_price": "95000000", "unit_currency": "KRW"},
                {"currency": "XYZ", "balance": "3", "avg_buy_price": "10", "unit_currency": "KRW"},
                {"currency": "ETH", "balance": "0", "avg_buy_price": "0", "unit_currency": "KRW"}]

    def get_open_orders(self, market=None):
        return [{"uuid": "u-open", "market": "KRW-BTC", "side": "bid", "ord_type": "price", "locked": "1000500",
                 "volume": None, "executed_volume": "0", "price": "1000000"}]

    def get_closed_orders(self, start_ms, end_ms, market=None, limit=1000):
        self.calls.append(("closed", start_ms, end_ms))
        return [o for o in self.closed if start_ms <= o["_ms"] < end_ms]

    def get_order(self, u):
        return self.details[u]

    def place_order(self, market, side, ord_type, volume=None, price=None, identifier=None, test=False):
        self.calls.append(("place", market, side, ord_type, volume, price, identifier, test))
        return {"uuid": "u-new"}

    def cancel_order(self, u):
        self.calls.append(("cancel", u))


def main():
    # ------------------------------------------------ 설정
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        ck("업비트 키 이름 = 접두사_ACCESS_KEY/_SECRET_KEY", key_names(c) == ("UPBIT_TRADE_ACCESS_KEY", "UPBIT_TRADE_SECRET_KEY"))
        ck("업비트 한도 기본값에 최소 주문 5,000원", c["risk"]["UPBIT"]["min_order_value"] == 5_000)
        for bad, why in ((dict(markets=["KR"]), "시장"), (dict(mode="paper"), "모의"), (dict(key_prefix="UPBIT"), "조회용 키"),
                         (dict(key_prefix=None), "접두사 없음"), (dict(key_prefix="KIS_LIVE"), "KIS 접두사"),
                         (dict(broker="binance"), "모르는 브로커")):
            try:
                cfg_for(td, **bad)
                ck(f"설정 거부: {why}", False)
            except ConfigError:
                ck(f"설정 거부: {why}", True)
        try:
            normalize_config({"strategy": "x", "mode": "paper", "markets": ["UPBIT"]})
            ck("KIS 브로커에 UPBIT 시장 거부", False)
        except ConfigError:
            ck("KIS 브로커에 UPBIT 시장 거부", True)
        k = normalize_config({"strategy": "x", "mode": "paper", "markets": ["KR"]})
        ck("KIS 설정은 그대로(broker 기본 kis·키 KIS_VTS_*)", k["broker"] == "kis" and key_names(k)[0] == "KIS_VTS_APP_KEY")
        env = load_env(Path(td), {"UPBIT_TRADE_ACCESS_KEY": "a", "UPBIT_TRADE_SECRET_KEY": "s", "UPBIT_ACCESS_KEY": "q"})
        ck("주문 키는 읽고 조회용 UPBIT_ACCESS_KEY 는 안 읽는다", env.get("UPBIT_TRADE_ACCESS_KEY") == "a" and "UPBIT_ACCESS_KEY" not in env)
        g = gate_problems(c, {k_: v for k_, v in ENV.items() if k_ != "AUTOTRADER_ALLOW_LIVE"}, True, Path(td))
        ck("실계좌 주문은 AUTOTRADER_ALLOW_LIVE 없이는 막힌다", any("AUTOTRADER_ALLOW_LIVE" in p for p in g))
        g2 = gate_problems(cfg_for(td, live={"enabled": True, "tr_ids_reviewed": False}), ENV, True, Path(td))
        ck("tr_ids_reviewed 없으면 막히고 업비트 probe 를 안내", any("upbit-probe" in p for p in g2))
        ck("dry-run 은 키만 있으면 통과", gate_problems(c, ENV, False, Path(td)) == [])

    # ------------------------------------------------ 주문 의도·위험 검사
    ck("UPBIT 소수 수량·시장가 통과", Intent("KRW-BTC", "BUY", 0.01, market="UPBIT", order_type="market").validate() is None)
    ck("UPBIT 9자리 소수 거부", Intent("KRW-BTC", "BUY", 0.000000001, market="UPBIT", order_type="market").validate() is not None)
    ck("UPBIT 지정가 거부", Intent("KRW-BTC", "BUY", 0.01, market="UPBIT", order_type="limit", limit_price=1).validate() is not None)
    ck("KR 소수 수량은 여전히 거부", Intent("005930", "BUY", 1.5, market="KR", order_type="market").validate() is not None)
    ck("US 시장가는 여전히 거부", Intent("TQQQ", "BUY", 1, market="US", order_type="market").validate() is not None)
    rk = {**cfg_for(tempfile.gettempdir())["risk"]["UPBIT"]}
    small = R.check_intent(Intent("KRW-BTC", "BUY", 0.00004, market="UPBIT", order_type="market"), risk=rk,
                           allowlist=["KRW-BTC"], last_price=PX, sellable_qty=0, cash=1e9, held_value=0,
                           spent_today=0, spent_run=0, orders_run=0)
    ck("최소 주문 5,000원 미만 거부", small is not None and "최소 주문" in small)
    ck("KR 위험 검사에는 최소 주문 규칙이 없다", "min_order_value" not in normalize_config(
        {"strategy": "x", "mode": "paper", "markets": ["KR"]})["risk"]["KR"])

    # ------------------------------------------------ 어댑터
    fc = FakeClient()
    ub = UpbitBroker(fc, orders_enabled=False)
    buy = Intent("KRW-BTC", "BUY", 0.01, market="UPBIT", order_type="market", client_id="cbprem-x-buy")
    req = ub.order_request(buy)
    ck("매수 = 원 금액 시장가(수량 × 시세, 원 미만 버림) + identifier",
       req == {"market": "KRW-BTC", "side": "bid", "ord_type": "price", "price": 1_000_000, "identifier": "cbprem-x-buy"})
    sreq = ub.order_request(Intent("KRW-BTC", "SELL", 0.00001, market="UPBIT", order_type="market"))
    ck("매도 = 수량 시장가, 지수 표기 없음", sreq["ord_type"] == "market" and sreq["volume"] == "0.00001" and _vol(0.123456789) == "0.12345679")
    ck("dry-run 은 요청을 안 보낸다", ub.place(buy, dry_run=True)["dryRun"] and not [x for x in fc.calls if x[0] == "place"])
    try:
        ub.place(buy, dry_run=False)
        ck("잠금(--execute 아님) 상태의 실주문 거부", False)
    except RuntimeError:
        ck("잠금(--execute 아님) 상태의 실주문 거부", not [x for x in fc.calls if x[0] == "place"])
    ub2 = UpbitBroker(fc, orders_enabled=True)
    res = ub2.place(buy, dry_run=False)
    pl = [x for x in fc.calls if x[0] == "place"]
    ck("실주문은 identifier 를 실어 한 번", res["orderNo"] == "u-new" and len(pl) == 1 and pl[0][6] == "cbprem-x-buy" and pl[0][7] is False)
    pos = ub.positions("UPBIT")
    ck("잔고: 원화·0 수량 제외, 원화 마켓 없는 코인은 현재가 0",
       [(p.symbol, p.qty) for p in pos] == [("KRW-BTC", 0.015), ("KRW-XYZ", 3.0)] and pos[1].price == 0.0 and pos[0].price == PX)
    ck("주문가능 현금 = 원화 잔고", ub.cash("UPBIT") == 2_500_000)
    oo = ub.open_orders("UPBIT")
    ck("원 금액 매수 대기 주문은 잠긴 원화로 센다", oo[0].remaining * oo[0].price == 1_000_500)
    base = pd.Timestamp("2026-10-01", tz="Asia/Seoul")
    for i, (d, ex) in enumerate(((1, "0.01"), (9, "0.02"), (9, "0"))):
        t = base + pd.Timedelta(days=d)
        fc.closed.append({"uuid": f"c{i}", "market": "KRW-BTC", "side": "bid" if i == 0 else "ask", "executed_volume": ex,
                          "created_at": t.isoformat(), "_ms": int(t.timestamp() * 1000)})
        fc.details[f"c{i}"] = {"executed_volume": ex, "paid_fee": "500",
                               "trades": [{"price": "99000000", "volume": str(float(ex) / 2), "funds": str(99e6 * float(ex) / 2)},
                                          {"price": "101000000", "volume": str(float(ex) / 2), "funds": str(101e6 * float(ex) / 2)}]}
    fl = ub.fills("UPBIT", "20261001", "20261012")
    spans = [(b - a) / 86_400_000 for _, a, b in [x for x in fc.calls if x[0] == "closed"]]
    ck("종료 주문 조회는 7일 이하 구간으로 나눈다", len(spans) == 2 and max(spans) <= 7)
    ck("체결 0 은 빼고, 평균가는 체결 목록으로", [(f["orderNo"], f["qty"], round(f["price"])) for f in fl]
       == [("c0", 0.01, 100_000_000), ("c1", 0.02, 100_000_000)] and fl[1]["side"] == "SELL")
    fc.calls.clear()
    pr = ub.probe()
    ck("probe 는 주문 생성 '테스트'만 쓴다", pr == {"자산조회": "ok", "주문조회": "ok", "주문하기(테스트)": "ok"}
       and all(x[7] is True for x in fc.calls if x[0] == "place"))
    fc.place_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("{'error': {'name': 'insufficient_funds_bid'}}"))
    ck("원화 부족 거절은 권한·IP 통과로 읽는다", ub.probe()["주문하기(테스트)"].startswith("ok"))
    fc.place_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("{'error': {'name': 'out_of_scope'}}"))
    ck("권한 없음은 실패로 남는다", not ub.probe()["주문하기(테스트)"].startswith("ok"))

    # ------------------------------------------------ 전략 + 엔진(가짜 브로커)
    S = pd.Timestamp("2026-11-03 01:00", tz="UTC")                   # 롱 사건 시각(KST 10시)
    mk = Market([S], S - pd.Timedelta(hours=1000))
    CPS.CoinbasePremium.fetcher = staticmethod(mk.fetcher)
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": [Position("KRW-BTC", "UPBIT", 0.5, 90e6, PX)]}, cash={"UPBIT": 5_000_000},
                        quotes={"KRW-BTC": PX})
        r0 = run(c, fb, kst(S - pd.Timedelta(hours=3)))
        ck("첫 실행: 주문 없음", not r0["placed"] and r0["status"] == "ok")
        run(c, fb, kst(S - pd.Timedelta(hours=1)))
        r1 = run(c, fb, kst(S))
        ck("z ≥ 2 정시: 1,000,000원 매수 1건", len(r1["placed"]) == 1 and r1["placed"][0]["side"] == "BUY"
           and abs(r1["placed"][0]["value"] - 1_000_000) < 1)
        row = [r for r in Ledger(td).rows() if r.get("kind") == "order"][-1]
        ck("원장에 주문 식별자(KST 시각)", row.get("clientId") == "cbprem-2026110310-buy")
        q = 0.01
        fb.fill_rows.append({"orderNo": row["orderNo"], "symbol": "KRW-BTC", "side": "BUY", "qty": q, "price": PX * 1.001, "fee": 500, "state": "done"})
        fb._pos["UPBIT"] = [Position("KRW-BTC", "UPBIT", 0.5 + q, 90e6, PX)]
        run(c, fb, kst(S + pd.Timedelta(hours=1)))
        st = json.loads((Path(td) / "strategy_coinbase_premium.json").read_text("utf-8"))
        ck("체결 확인 뒤 포지션 = 체결 수량·평균가", st["position"]["qty"] == q and st["position"]["entryAvg"] == PX * 1.001)
        r23 = run(c, fb, kst(S + pd.Timedelta(hours=23)))
        ck("24시간 전에는 매도 없음", not r23["placed"])
        r24 = run(c, fb, kst(S + pd.Timedelta(hours=24)))
        sells = [x for x in r24["placed"] if x["side"] == "SELL"]
        ck("24시간 뒤 자기 체결 수량만 매도(개인 보유 0.5 는 그대로)", len(sells) == 1 and sells[0]["qty"] == q)
        srow = [r for r in Ledger(td).rows() if r.get("kind") == "order"][-1]
        fb.fill_rows.append({"orderNo": srow["orderNo"], "symbol": "KRW-BTC", "side": "SELL", "qty": q, "price": PX * 1.006, "fee": 500, "state": "done"})
        fb._pos["UPBIT"] = [Position("KRW-BTC", "UPBIT", 0.5, 90e6, PX)]
        r25 = run(c, fb, kst(S + pd.Timedelta(hours=25)))
        st = json.loads((Path(td) / "strategy_coinbase_premium.json").read_text("utf-8"))
        ck("청산 체결 뒤 포지션 없음·거래 기록(수수료 전 bp)", st["position"] is None and len(st["trades"]) == 1
           and abs(st["trades"][0]["grossBp"] - (1.006 / 1.001 - 1) * 1e4) < 0.01 and not r25["placed"])

    with tempfile.TemporaryDirectory() as td:          # dry-run 은 포지션을 만들지 않는다
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={"KRW-BTC": PX})
        run(c, fb, kst(S - pd.Timedelta(hours=1)), execute=False)
        rd = run(c, fb, kst(S), execute=False)
        run(c, fb, kst(S + pd.Timedelta(hours=1)), execute=False)
        st = json.loads((Path(td) / "strategy_coinbase_premium.json").read_text("utf-8"))
        ck("dry-run: 매수 계획만, 원장·포지션 없음", len(rd["planned"]) == 1 and not rd["placed"]
           and st.get("position") is None and st.get("pendingBuy") is None and not Ledger(td).rows())

    with tempfile.TemporaryDirectory() as td:          # 늦은 실행
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={"KRW-BTC": PX})
        run(c, fb, kst(S - pd.Timedelta(hours=1)))
        rl = run(c, fb, kst(S, minute=40))
        ck("30분 넘게 늦으면 진입 안 하고 알림", not rl["placed"] and any("늦어" in n for n in rl.get("notes", [])))
        ck("실행 요약에 알림 줄", "알림 코인베이스 프리미엄" in cli.run_summary("cbprem", rl))

    with tempfile.TemporaryDirectory() as td:          # 킬 스위치
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={"KRW-BTC": PX})
        run(c, fb, kst(S - pd.Timedelta(hours=1)))
        kill_file(c).parent.mkdir(parents=True, exist_ok=True)
        kill_file(c).write_text("test", encoding="utf-8")
        try:
            run(c, fb, kst(S))
            ck("킬 스위치면 실행 거부", False)
        except GateError:
            ck("킬 스위치면 실행 거부", not fb.placed)

    # ------------------------------------------------ 모의 러너와 같은 진입 시각(잡음 많은 프리미엄, 사건 여러 번)
    P = CPS.paper()
    start = pd.Timestamp("2026-06-01", tz="UTC")
    mk2 = Market([], start, hours=1300, noise=lambda n: np.random.default_rng(11).standard_t(3, n) * 0.0004)
    CPS.CoinbasePremium.fetcher = staticmethod(mk2.fetcher)
    hours = pd.date_range(start + pd.Timedelta(hours=900), periods=300, freq="h")
    with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as pd_dir:
        c = cfg_for(td)
        fb = FakeBroker(positions={"UPBIT": []}, cash={"UPBIT": 5_000_000}, quotes={"KRW-BTC": PX})

        class PB:
            def current_price(self, m):
                return PX
        mine, theirs = [], []
        for h in hours:
            when = kst(h)
            r = run(c, fb, when, execute=False)
            mine += [h for x in r["planned"] if x["side"] == "BUY"]
            cb, bn = mk2.fetcher(P, h)
            res = P.run(pd.Timestamp(when).tz_convert("UTC").to_pydatetime(), cb, bn, PB(), Path(pd_dir), execute=True, log=lambda s: None)
            theirs += [h for a in res["rec"]["actions"] if a.startswith("매수")]
        ck(f"모의 러너와 같은 진입 시각({len(theirs)}건)", len(theirs) >= 2 and mine == theirs)

    # ------------------------------------------------ 표시
    book = {"opening": {}, "fills": {
        "b": {"orderNo": "b", "market": "UPBIT", "symbol": "KRW-BTC", "side": "BUY", "qty": 0.01, "price": 100e6, "day": "2026-11-03"},
        "s": {"orderNo": "s", "market": "UPBIT", "symbol": "KRW-BTC", "side": "SELL", "qty": 0.01, "price": 101e6, "day": "2026-11-04"}}}
    rz = realized(book)["UPBIT"]
    ck("소수 수량 실현손익(0.01 × 100만원 = 1만원)", abs(rz["realized"] - 10_000) < 1e-6 and not rz["incomplete"])
    nf = new_fills({"fills": {}}, {"fills": {"b": book["fills"]["b"]}})
    ck("새 체결 증가분이 소수로", nf[0]["delta"] == 0.01)
    ck("업비트 체결 알림 단위 '개'·원", "KRW-BTC 매수 0.01개 @ 100,000,000원" in notify.fill_message("cbprem", "live", nf[0]))
    with tempfile.TemporaryDirectory() as td:
        snap = {"markets": {"UPBIT": {"positions": [{"symbol": "KRW-BTC", "qty": 0.5, "avgPrice": 90e6}]}}}
        bk = sync_fills(cfg_for(td), FakeBroker(), snap, kst(S))
        ck("업비트 개인 보유는 시작 원가에 안 넣는다(전략 손익에 개인 평단이 안 섞임)", "UPBIT" not in bk["opening"])

    print(f"\ntest-autotrader-upbit {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
