"""업비트 브로커 — autotrader 엔진이 업비트 원화 마켓(KRW-BTC 등)에 주문을 낼 때 쓰는 어댑터.

설계: docs/control/코인베이스프리미엄-실계좌연결-설계-2026-10-30.md §4-2.
HTTP·서명은 기존 research/strategy-lab/engine/live/upbitClient.py 를 그대로 쓴다(다시 쓰지 않는다).

★ 업비트에는 모의투자가 없다 — 이 브로커의 주문은 언제나 실계좌다. 그래서 설정은 mode live 만 받고,
   실주문은 엔진의 실계좌 게이트(live.enabled · tr_ids_reviewed · AUTOTRADER_ALLOW_LIVE · --execute)를 전부 지나야 나간다.
★ 키는 주문 전용 `<key_prefix>_ACCESS_KEY` / `_SECRET_KEY`(예: UPBIT_TRADE_*). 잔고 조회용 UPBIT_ACCESS_KEY 와 섞지 않는다.
   발급할 때 출금·입금 권한은 주지 않는다(키가 새어도 자산을 빼 갈 수 없게).
★ 시장가만: 매수는 원 금액(ord_type=price, 금액 = 수량 × 직전 시세), 매도는 수량(ord_type=market). 업비트 API 자체가 비대칭이다.
★ Intent.client_id 를 업비트 identifier 로 보낸다 — 계정 전체에서 한 번만 쓸 수 있어 같은 주문이 두 번 나가지 않는다.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .broker import Broker
from .config import REPO_ROOT, key_names
from .models import Intent, OpenOrder, Position

KST = timezone(timedelta(hours=9))
MARKET = "UPBIT"
WINDOW_DAYS = 7                 # 종료 주문 조회 한 번의 최대 구간(업비트 문서)


def _client_module():
    sl = str(REPO_ROOT / "research" / "strategy-lab")
    if sl not in sys.path:
        sys.path.insert(0, sl)
    from engine.live import upbitClient           # noqa: E402 — 연구 쪽 클라이언트(서명·요청 한 곳)
    return upbitClient


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _vol(q: float) -> str:
    """코인 수량 문자열(소수 8자리, 끝 0 제거) — 지수 표기(1e-05)가 나가지 않게."""
    s = f"{q:.8f}".rstrip("0").rstrip(".")
    return s or "0"


def _avg(order: dict) -> float:
    """주문 상세의 체결 목록(trades)으로 평균 체결가. 체결이 없으면 0."""
    tr = order.get("trades") or []
    vol = sum(_f(t.get("volume")) for t in tr)
    funds = sum(_f(t.get("funds")) or _f(t.get("price")) * _f(t.get("volume")) for t in tr)
    return funds / vol if vol > 0 else 0.0


class UpbitBroker(Broker):
    name = "upbit"
    mode = "live"

    def __init__(self, client, orders_enabled: bool = False):
        self.client = client
        self.orders_enabled = orders_enabled        # --execute 일 때만 True — 아니면 place/cancel 이 실제 요청을 못 보낸다

    @staticmethod
    def _check_market(market: str) -> None:
        if market != MARKET:
            raise ValueError(f"업비트 브로커는 {MARKET} 시장만: {market}")

    def positions(self, market: str) -> List[Position]:
        if market != MARKET:
            return []
        out = []
        for a in self.client.get_accounts():
            cur, unit = a.get("currency"), a.get("unit_currency", "KRW")
            qty = _f(a.get("balance"))                  # 주문에 잠긴(locked) 수량은 뺀다 — 팔 수 있는 수량
            if cur == "KRW" or unit != "KRW" or qty <= 0:
                continue
            sym = f"KRW-{cur}"
            try:
                price = self.client.get_ticker(sym)
            except Exception:                           # noqa: BLE001 — 원화 마켓이 없는 코인(에어드랍 등)은 현재가 모름
                price = 0.0
            out.append(Position(sym, MARKET, qty, _f(a.get("avg_buy_price")), price, cur))
        return out

    def cash(self, market: str, ref_symbol: Optional[str] = None) -> float:
        self._check_market(market)
        return sum(_f(a.get("balance")) for a in self.client.get_accounts() if a.get("currency") == "KRW")

    def open_orders(self, market: str) -> List[OpenOrder]:
        if market != MARKET:
            return []
        out = []
        for o in self.client.get_open_orders():
            side = "BUY" if o.get("side") == "bid" else "SELL"
            if o.get("ord_type") == "price":            # 원 금액 시장가 매수: 수량이 없다 → 잠긴 원화를 '1 × 금액'으로 둔다(한도 교차 확인용)
                qty, filled, price = 1.0, 0.0, _f(o.get("locked"))
            else:
                qty, filled, price = _f(o.get("volume")), _f(o.get("executed_volume")), _f(o.get("price"))
            out.append(OpenOrder(o["uuid"], o.get("market", ""), MARKET, side, qty, filled, price))
        return out

    def fills(self, market: str, start: str, end: str) -> List[dict]:
        """start~end(YYYYMMDD, KST, 양끝 포함)에 생성된 종료 주문 중 체결이 있는 것. 평균가는 주문 상세(trades)로 계산한다."""
        self._check_market(market)
        t0 = datetime.strptime(start, "%Y%m%d").replace(tzinfo=KST)
        t1 = min(datetime.strptime(end, "%Y%m%d").replace(tzinfo=KST) + timedelta(days=1), datetime.now(KST))
        rows, seen = [], set()
        a = t0
        while a < t1:
            b = min(a + timedelta(days=WINDOW_DAYS), t1)
            for o in self.client.get_closed_orders(int(a.timestamp() * 1000), int(b.timestamp() * 1000)):
                if o["uuid"] in seen or _f(o.get("executed_volume")) <= 0:
                    continue
                seen.add(o["uuid"])
                d = self.client.get_order(o["uuid"])
                rows.append({"orderNo": o["uuid"], "symbol": o.get("market", ""),
                             "side": "BUY" if o.get("side") == "bid" else "SELL",
                             "qty": _f(d.get("executed_volume")), "price": _avg(d),
                             "fee": _f(d.get("paid_fee")), "day": str(o.get("created_at", ""))[:10]})
            a = b
        return rows

    def quote(self, symbol: str, market: str) -> float:
        self._check_market(market)
        return float(self.client.get_ticker(symbol))

    def order_request(self, intent: Intent) -> dict:
        """보낼 주문 본문(서명 전). dry-run 리포트와 실제 주문이 같은 함수로 만든다."""
        if intent.market != MARKET or intent.order_type != "market":
            raise ValueError("업비트는 UPBIT 시장가 주문만")
        if intent.side == "BUY":
            krw = int(math.floor(float(intent.qty) * self.quote(intent.symbol, MARKET)))
            req = {"market": intent.symbol, "side": "bid", "ord_type": "price", "price": krw}
        else:
            req = {"market": intent.symbol, "side": "ask", "ord_type": "market", "volume": _vol(float(intent.qty))}
        if intent.client_id:
            req["identifier"] = intent.client_id
        return req

    def place(self, intent: Intent, dry_run: bool = True) -> dict:
        req = self.order_request(intent)
        if dry_run:
            return {"dryRun": True, **req}
        if not self.orders_enabled:
            raise RuntimeError("주문 잠금 상태(--execute 가 아닌 실행) — 업비트 주문을 보내지 않는다")
        resp = self.client.place_order(req["market"], req["side"], req["ord_type"], volume=req.get("volume"),
                                       price=req.get("price"), identifier=req.get("identifier"))
        return {"dryRun": False, "orderNo": resp["uuid"], "symbol": intent.symbol, "side": intent.side,
                "qty": intent.qty, "price": None, "market": MARKET}

    def cancel(self, order: OpenOrder, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dryRun": True, "orderNo": order.order_no}
        if not self.orders_enabled:
            raise RuntimeError("주문 잠금 상태 — 취소를 보내지 않는다")
        self.client.cancel_order(order.order_no)
        return {"dryRun": False, "orderNo": order.order_no}

    def order_fill(self, order_no: str, market: str) -> dict:
        self._check_market(market)
        d = self.client.get_order(order_no)
        return {"qty": _f(d.get("executed_volume")), "price": _avg(d), "fee": _f(d.get("paid_fee")),
                "state": d.get("state", "")}

    def probe(self, symbol: str = "KRW-BTC", krw: int = 5_000) -> Dict[str, str]:
        """주문 없이 키·권한·허용 IP 를 확인한다: 잔고(자산조회) · 대기 주문(주문조회) · 주문 생성 **테스트**(주문하기 — 업비트
        /v1/orders/test 는 검증만 하고 주문을 만들지 않는다). 항목별 'ok' 또는 오류 문구."""
        out = {}
        for name, fn in (("자산조회", self.client.get_accounts), ("주문조회", self.client.get_open_orders),
                         ("주문하기(테스트)", lambda: self.client.place_order(symbol, "bid", "price", price=krw, test=True))):
            try:
                fn()
                out[name] = "ok"
            except Exception as e:                      # noqa: BLE001 — 키 원문은 예외에 없다(업비트 오류 본문만)
                if "insufficient_funds" in str(e):      # 권한·허용 IP 검사를 지난 뒤의 거절 — 경로는 통과(원화만 부족)
                    out[name] = "ok(권한·IP 통과 — 원화 잔고 부족)"
                else:
                    out[name] = f"{type(e).__name__}: {e}"[:200]
        return out


def make_broker(cfg: dict, env: Dict[str, str], execute: bool, client=None) -> UpbitBroker:
    """프로필의 key_prefix 로 주문 전용 키를 골라 브로커를 만든다. 주문 잠금 해제는 --execute 일 때만."""
    if client is None:
        ak, sk = key_names(cfg)
        client = _client_module().UpbitClient(env[ak], env[sk])
    return UpbitBroker(client, orders_enabled=execute)
