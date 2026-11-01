#!/usr/bin/env python3
"""autotrader 빗썸 경로 회귀 — 키·네트워크 없이 돈다(가짜 클라이언트). 설계 docs/control/빗썸-autotrader-어댑터-설계-2026-11-01.md.

핀하는 것: 설정(broker bithumb 는 BITHUMB 시장·live·BITHUMB_<접두사> 키만, 조회용 BITHUMB_ACCESS_KEY 는 못 고른다) · 주문 본문(시장가 매수 = order_type price 총액,
매도 = market 수량, client_order_id) · dry-run·잠금이면 요청 안 보냄 · 같은 client_order_id 가 이미 있으면 안 보냄 · 잔고·대기 주문·종료 주문(7일 창)·
체결 확인 · 공개 market_info(거래대금·경고) · probe 는 주문 안 만듦 · crypto_weights 가 BITHUMB 시장으로 돈다 · 웹이 빗썸을 크립토로 센다.

    python scripts/test-autotrader-bithumb.py
"""
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import bithumb as BT                                          # noqa: E402
from autotrader import web                                                    # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import ConfigError, gate_problems, key_names, load_env, normalize_config  # noqa: E402
from autotrader.engine import KST, run_once                                  # noqa: E402
from autotrader.models import Intent                                          # noqa: E402
from autotrader.strategies import crypto_weights as CW                        # noqa: E402

FAILS, COUNT = [], [0]
BTC = 100_000_000.0


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.exist = set()

    def get_accounts(self):
        self.calls.append(("accounts",))
        return [{"currency": "KRW", "balance": "2500000", "unit_currency": "KRW"},
                {"currency": "BTC", "balance": "0.015", "avg_buy_price": "95000000", "unit_currency": "KRW"},
                {"currency": "XYZ", "balance": "3", "avg_buy_price": "10", "unit_currency": "KRW"},
                {"currency": "ETH", "balance": "0", "unit_currency": "KRW"}]

    def get_ticker(self, m):
        if m == "KRW-XYZ":
            raise RuntimeError("마켓 없음")
        return BTC

    def get_pending_orders(self, market=None):
        self.calls.append(("pending",))
        return {"data": [{"order_id": "o-buy", "market": "KRW-BTC", "side": "bid", "order_type": "price", "locked": "1000500"},
                         {"order_id": "o-lim", "market": "KRW-BTC", "side": "ask", "order_type": "limit", "price": "101000000",
                          "volume": "0.02", "remaining_volume": "0.005"}]}

    def get_orders_history(self, market=None, start_ms=None, end_ms=None, limit=1000, next_key=None):
        self.calls.append(("history", start_ms, end_ms, next_key))
        if next_key is None and len([c for c in self.calls if c[0] == "history"]) == 1:
            return {"data": [{"order_id": "h1", "market": "KRW-BTC", "side": "bid", "executed_volume": "0.01", "executed_funds": "1000000",
                              "paid_fee": "400", "created_at": "2026-10-02T10:00:00+09:00"},
                             {"order_id": "h0", "market": "KRW-BTC", "side": "bid", "executed_volume": "0", "executed_funds": "0",
                              "paid_fee": "0", "created_at": "2026-10-02T11:00:00+09:00"}], "has_next": True, "next_key": "k2"}
        return {"data": [{"order_id": "h2", "market": "KRW-BTC", "side": "ask", "executed_volume": "0.01", "executed_funds": "1010000",
                          "paid_fee": "404", "created_at": "2026-10-03T10:00:00+09:00"}], "has_next": False, "next_key": None}

    def get_order_v1(self, uuid=None, client_order_id=None):
        self.calls.append(("order", uuid, client_order_id))
        if client_order_id is not None:
            if client_order_id in self.exist:
                return {"uuid": "u-exist", "client_order_id": client_order_id}
            raise RuntimeError("not found")
        return {"uuid": uuid, "state": "done", "executed_volume": "0.02", "executed_funds": "2000000", "paid_fee": "800",
                "trades": [{"price": "99000000", "volume": "0.01", "funds": "990000"}, {"price": "101000000", "volume": "0.01", "funds": "1010000"}]}

    def place_order(self, market, side, order_type, volume=None, price=None, client_order_id=None):
        self.calls.append(("place", market, side, order_type, volume, price, client_order_id))
        return {"order_id": "u-new", "client_order_id": client_order_id}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {}


def cfg_for(td, **kw):
    base = {"strategy": "crypto_weights", "broker": "bithumb", "mode": "live", "key_prefix": "BITHUMB_TRADE", "markets": ["BITHUMB"],
            "symbol_allowlist": ["KRW-BTC", "KRW-ETH"],
            "params": {"market": "BITHUMB", "weights": {"KRW-BTC": 0.5, "KRW-ETH": 0.3}, "capital_krw": 1_000_000, "max_order_krw": 200_000},
            "risk": {"BITHUMB": {"max_order_value": 3_000_000, "max_daily_value": 9_000_000, "max_orders_per_run": 5,
                                 "max_position_value": 900_000_000}},
            "live": {"enabled": True, "tr_ids_reviewed": True}, "state_dir": str(td)}
    return normalize_config({**base, **kw})


def placed(fc):
    return [c for c in fc.calls if c[0] == "place"]


def main():
    # ---- 설정
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        ck("빗썸 프로필 정상(BITHUMB 시장·live·BITHUMB_TRADE)", c["broker"] == "bithumb" and c["risk"]["BITHUMB"]["min_order_value"] == 5_000)
        bad = [dict(markets=["UPBIT"]), dict(mode="paper"), dict(key_prefix="BITHUMB"), dict(key_prefix="UPBIT_TRADE"), dict(key_prefix=None)]
        n = 0
        for kw in bad:
            try:
                cfg_for(td, **kw)
            except ConfigError:
                n += 1
        ck("빗썸 설정 오류 5가지 거부(시장·모의·접미사 없음·업비트 접두사·접두사 없음)", n == len(bad))
        ck("키 이름 = <접두사>_ACCESS_KEY/_SECRET_KEY", key_names(c) == ("BITHUMB_TRADE_ACCESS_KEY", "BITHUMB_TRADE_SECRET_KEY"))
        env = load_env(environ={"BITHUMB_TRADE_ACCESS_KEY": "a", "BITHUMB_TRADE_SECRET_KEY": "s", "BITHUMB_ACCESS_KEY": "no"})
        ck("환경에서 주문 전용 키만 읽는다(조회용 BITHUMB_ACCESS_KEY 는 안 읽음)", env.get("BITHUMB_TRADE_ACCESS_KEY") == "a" and "BITHUMB_ACCESS_KEY" not in env)
        c2 = cfg_for(td, live={"enabled": True, "tr_ids_reviewed": False})
        pr = gate_problems(c2, {"AUTOTRADER_ALLOW_LIVE": "I-ACCEPT-REAL-TRADES"}, True)
        ck("tr_ids_reviewed 미표시면 '소액 실검증' 안내로 막힌다", any("소액 실검증" in x for x in pr))
        ck("Intent: BITHUMB 소수 수량·시장가만", Intent("KRW-BTC", "BUY", 0.001, market="BITHUMB", order_type="market").validate() is None
           and Intent("KRW-BTC", "BUY", 0.001, market="BITHUMB", order_type="limit").validate() is not None
           and Intent("KRW-BTC", "BUY", 0.0000000001, market="BITHUMB", order_type="market").validate() is not None)

    # ---- 어댑터
    fc = FakeClient()
    bb = BT.BithumbBroker(fc, orders_enabled=False)
    buy = Intent("KRW-BTC", "BUY", 0.01, market="BITHUMB", order_type="market", client_id="cw-2026110209-BTC-buy")
    sell = Intent("KRW-BTC", "SELL", 0.00001, market="BITHUMB", order_type="market", client_id="cw-2026110209-BTC-sell")
    rb, rs = bb.order_request(buy), bb.order_request(sell)
    ck("매수 = order_type price · 총액 문자열(수량 × 시세, 원 내림)", rb == {"market": "KRW-BTC", "side": "bid", "order_type": "price",
                                                                          "price": "1000000", "client_order_id": "cw-2026110209-BTC-buy"})
    ck("매도 = order_type market · 수량 문자열(지수 표기 없음)", rs == {"market": "KRW-BTC", "side": "ask", "order_type": "market",
                                                                  "volume": "0.00001", "client_order_id": "cw-2026110209-BTC-sell"})
    try:
        bb.order_request(Intent("KRW-BTC", "BUY", 0.01, market="BITHUMB", order_type="market", client_id="나쁜/아이디"))
        ck("client_order_id 형식 검사", False)
    except ValueError:
        ck("client_order_id 는 영문·숫자·-·_ 1~36자만", True)
    ck("dry-run 은 요청을 안 보낸다", bb.place(buy, True)["dryRun"] is True and not placed(fc))
    try:
        bb.place(buy, False)
        ck("--execute 가 아니면 주문 잠금", False)
    except RuntimeError:
        ck("--execute 가 아니면 주문 잠금(요청 안 감)", not placed(fc))
    live = BT.BithumbBroker(fc, orders_enabled=True)
    res = live.place(buy, False)
    ck("실주문: order_id 를 orderNo 로, client_order_id 를 실어 한 번", res["orderNo"] == "u-new" and len(placed(fc)) == 1
       and placed(fc)[0] == ("place", "KRW-BTC", "bid", "price", None, "1000000", "cw-2026110209-BTC-buy"))
    fc.exist.add("cw-2026110209-BTC-buy")
    try:
        live.place(buy, False)
        ck("같은 client_order_id 가 이미 있으면 안 보낸다", False)
    except RuntimeError as e:
        ck("같은 client_order_id 가 이미 있으면 안 보낸다(중복 전송 방지)", "이미 있다" in str(e) and len(placed(fc)) == 1)
    pos = bb.positions("BITHUMB")
    ck("잔고: 원화·0 수량 제외, 마켓 없는 코인은 현재가 0", [(p.symbol, p.qty) for p in pos] == [("KRW-BTC", 0.015), ("KRW-XYZ", 3.0)] and pos[1].price == 0.0)
    ck("주문가능 현금 = 원화 잔고", bb.cash("BITHUMB") == 2_500_000)
    oo = bb.open_orders("BITHUMB")
    ck("대기 주문: 원 금액 매수는 잠긴 원화, 지정가는 남은 수량", oo[0].remaining * oo[0].price == 1_000_500 and abs(oo[1].remaining - 0.005) < 1e-12)
    fl = bb.fills("BITHUMB", "20261001", "20261012")
    spans = [(c[2] - c[1]) / 86_400_000 for c in fc.calls if c[0] == "history"]
    ck("종료 주문: 체결 0 제외·평균가=체결금액÷수량·next_key 페이지 이어받기·7일 이하 창",
       [(f["orderNo"], f["qty"], round(f["price"])) for f in fl] == [("h1", 0.01, 100_000_000), ("h2", 0.01, 101_000_000)]
       and max(spans) <= 7 and any(c[3] == "k2" for c in fc.calls if c[0] == "history"))
    of = bb.order_fill("u-1", "BITHUMB")
    ck("체결 확인: trades 로 평균가·수수료·상태(v1 개별 조회 uuid)", of["qty"] == 0.02 and round(of["price"]) == 100_000_000 and of["fee"] == 800
       and of["state"] == "done" and ("order", "u-1", None) in fc.calls)
    n_before = len(placed(fc))
    pr = bb.probe()
    ck("probe 는 잔고·대기 주문 조회만, 주문 테스트는 '해당 없음'(주문 안 만듦)", pr["자산조회"] == "ok" and pr["주문조회"] == "ok"
       and pr["주문하기(테스트)"].startswith("해당 없음") and len(placed(fc)) == n_before)

    # ---- 공개 market_info (거래대금·경고)
    mod = BT._client_module()

    class Resp:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            pass

        def json(self):
            return self.d
    seen = []

    def fake_request(method, url, **kw):
        seen.append(url.rsplit("/", 1)[-1])
        if url.endswith("/market/all"):
            return Resp([{"market": "KRW-XRP", "market_warning": "NONE"}, {"market": "KRW-JUNK", "market_warning": "CAUTION"},
                         {"market": "KRW-SOL", "market_warning": "NONE"}])
        if url.endswith("virtual_asset_warning"):
            return Resp([{"market": "KRW-SOL", "warning_type": "PRICE_SUDDEN_FLUCTUATION", "warning_step": "CAUTION"}])
        return Resp([{"market": "KRW-XRP", "acc_trade_price_24h": 9e11}, {"market": "KRW-JUNK", "acc_trade_price_24h": 1e12},
                     {"market": "KRW-SOL", "acc_trade_price_24h": 5e11}, {"market": "KRW-GONE", "acc_trade_price_24h": 1e9}])
    orig = mod._request
    mod._request = fake_request
    try:
        mi = BT.BithumbBroker(object()).market_info("BITHUMB", ["KRW-XRP", "KRW-JUNK", "KRW-SOL", "KRW-GONE"])
    finally:
        mod._request = orig
    ck("market_info: 거래대금·경고(market_warning·경보제), 마켓 목록에 없는 코인은 빠진다",
       mi == {"KRW-XRP": {"value24h": 9e11, "warning": False}, "KRW-JUNK": {"value24h": 1e12, "warning": True},
              "KRW-SOL": {"value24h": 5e11, "warning": True}} and seen == ["all", "virtual_asset_warning", "ticker"])

    # ---- crypto_weights 가 BITHUMB 시장으로 돈다(엔진 + 가짜 브로커)
    with tempfile.TemporaryDirectory() as td:
        c = cfg_for(td)
        fb = FakeBroker(positions={"BITHUMB": []}, cash={"BITHUMB": 5_000_000}, quotes={"KRW-BTC": BTC, "KRW-ETH": 5_000_000.0})
        env = {"BITHUMB_TRADE_ACCESS_KEY": "a", "BITHUMB_TRADE_SECRET_KEY": "s", "AUTOTRADER_ALLOW_LIVE": "I-ACCEPT-REAL-TRADES"}
        r = run_once(c, fb, CW.STRATEGY(), execute=True, env=env, now=datetime(2026, 11, 2, 9, 5, tzinfo=KST), sleep=lambda s: None)
        ck("crypto_weights(market BITHUMB): 코인마다 슬라이스 매수 2건, 시장 BITHUMB", len(r["placed"]) == 2
           and all(x["side"] == "BUY" for x in r["placed"]) and all(p["market"] == "BITHUMB" for p in fb.placed))
    try:
        CW.parse_params({"weights": {"KRW-BTC": 1}, "capital_krw": 1e6, "market": "KRAKEN"})
        ck("market 값 검사", False)
    except ValueError:
        ck("market 은 UPBIT|BITHUMB 만", True)

    # ---- 웹
    ck("웹: 빗썸 프로필도 크립토로 센다", web.is_crypto({"broker": "bithumb", "markets": ["BITHUMB"]})
       and web.is_crypto({"broker": "upbit", "markets": ["UPBIT"]}) and not web.is_crypto({"broker": "kis", "markets": ["KR"]}))
    print(f"\ntest-autotrader-bithumb {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
