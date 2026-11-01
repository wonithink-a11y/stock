"""빗썸 브로커 — autotrader 엔진이 빗썸 원화 마켓(KRW-BTC 등)에 주문을 낼 때 쓰는 어댑터.

설계: docs/control/빗썸-autotrader-어댑터-설계-2026-11-01.md (§6 = 공식 문서 확인 결과).
HTTP·서명은 기존 research/strategy-lab/engine/live/bithumbClient.py 를 쓴다(HS256 JWT·v1/v2 경로가 섞여 있어 다시 쓰지 않는다).

★ 빗썸에도 모의투자가 없다 — 이 브로커의 주문은 언제나 실계좌다. 설정은 mode live 만 받고, 실주문은 엔진의 실계좌 게이트
   (live.enabled · tr_ids_reviewed · AUTOTRADER_ALLOW_LIVE · --execute)를 전부 지나야 나간다.
★ 키는 주문 전용 `<key_prefix>_ACCESS_KEY` / `_SECRET_KEY`(예: BITHUMB_TRADE_*). 조회용 BITHUMB_ACCESS_KEY 와 섞지 않는다.
   발급할 때 출금·입금 권한은 주지 않는다.
★ 시장가만: 매수는 원 금액(order_type=price, 총액), 매도는 수량(order_type=market) — 업비트와 같은 비대칭(문서 확인).
★ Intent.client_id 를 빗썸 client_order_id 로 보낸다(영문·숫자·-·_ 1~36자). 보내기 전에 같은 client_order_id 의 주문이 이미 있으면
   보내지 않는다(거래소가 같은 값을 거절하는지는 문서에 명시가 없다 — 소액 실검증 P2 에서 확인).
★ 빗썸에는 주문 생성 '테스트'가 없다 — probe 는 잔고·대기 주문 조회만 확인하고 주문 경로는 소액 실검증으로 확인한다.
"""
from __future__ import annotations

import math
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .broker import Broker
from .config import REPO_ROOT, key_names
from .models import Intent, OpenOrder, Position

KST = timezone(timedelta(hours=9))
MARKET = "BITHUMB"
WINDOW_DAYS = 7                 # 종료 주문 목록의 최대 조회 구간(문서)
_CID = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


def _client_module():
    sl = str(REPO_ROOT / "research" / "strategy-lab")
    if sl not in sys.path:
        sys.path.insert(0, sl)
    from engine.live import bithumbClient          # noqa: E402 — 연구 쪽 클라이언트(서명·요청 한 곳)
    return bithumbClient


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _vol(q: float) -> str:
    """코인 수량 문자열(소수 8자리, 끝 0 제거) — 지수 표기가 나가지 않게."""
    s = f"{q:.8f}".rstrip("0").rstrip(".")
    return s or "0"


def _rows(body) -> list:
    """목록 응답이 {data:[...]} 이든 배열이든 받는다."""
    return list(body.get("data") or []) if isinstance(body, dict) else list(body or [])


def _avg(d: dict) -> float:
    """주문 상세의 평균 체결가: 체결 목록(trades)이 있으면 그것으로, 없으면 체결 금액 ÷ 체결 수량."""
    tr = d.get("trades") or []
    vol = sum(_f(t.get("volume")) for t in tr)
    funds = sum(_f(t.get("funds")) or _f(t.get("price")) * _f(t.get("volume")) for t in tr)
    if vol > 0:
        return funds / vol
    ev = _f(d.get("executed_volume"))
    return _f(d.get("executed_funds")) / ev if ev > 0 else 0.0


class BithumbBroker(Broker):
    name = "bithumb"
    mode = "live"

    def __init__(self, client, orders_enabled: bool = False):
        self.client = client
        self.orders_enabled = orders_enabled        # --execute 일 때만 True — 아니면 place/cancel 이 실제 요청을 못 보낸다

    @staticmethod
    def _check_market(market: str) -> None:
        if market != MARKET:
            raise ValueError(f"빗썸 브로커는 {MARKET} 시장만: {market}")

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
            except Exception:                           # noqa: BLE001 — 원화 마켓이 없는 코인은 현재가 모름
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
        for o in _rows(self.client.get_pending_orders()):
            side = "BUY" if o.get("side") == "bid" else "SELL"
            oid = o.get("order_id") or o.get("uuid") or ""
            if o.get("order_type", o.get("ord_type")) == "price":   # 원 금액 시장가 매수: 수량이 없다 → 잠긴 원화를 '1 × 금액'으로 둔다
                qty, filled, price = 1.0, 0.0, _f(o.get("locked"))
            else:
                qty = _f(o.get("volume"))
                filled = qty - _f(o.get("remaining_volume")) if o.get("remaining_volume") is not None else _f(o.get("executed_volume"))
                price = _f(o.get("price"))
            out.append(OpenOrder(oid, o.get("market", ""), MARKET, side, qty, filled, price))
        return out

    def fills(self, market: str, start: str, end: str) -> List[dict]:
        """start~end(YYYYMMDD, KST, 양끝 포함)에 생성된 종료 주문 중 체결이 있는 것. 종료 주문 목록(7일 창)에 체결 금액이 있어 평균가를 바로 낸다."""
        self._check_market(market)
        t0 = datetime.strptime(start, "%Y%m%d").replace(tzinfo=KST)
        t1 = min(datetime.strptime(end, "%Y%m%d").replace(tzinfo=KST) + timedelta(days=1), datetime.now(KST))
        rows, seen = [], set()
        a = t0
        while a < t1:
            b = min(a + timedelta(days=WINDOW_DAYS), t1)
            key = None
            while True:
                body = self.client.get_orders_history(start_ms=int(a.timestamp() * 1000), end_ms=int(b.timestamp() * 1000), next_key=key)
                for o in _rows(body):
                    oid = o.get("order_id") or o.get("uuid")
                    ev = _f(o.get("executed_volume"))
                    if not oid or oid in seen or ev <= 0:
                        continue
                    seen.add(oid)
                    rows.append({"orderNo": oid, "symbol": o.get("market", ""), "side": "BUY" if o.get("side") == "bid" else "SELL",
                                 "qty": ev, "price": _f(o.get("executed_funds")) / ev, "fee": _f(o.get("paid_fee")),
                                 "day": str(o.get("created_at", ""))[:10]})
                if isinstance(body, dict) and body.get("has_next") and body.get("next_key"):
                    key = body["next_key"]
                    continue
                break
            a = b
        return rows

    def quote(self, symbol: str, market: str) -> float:
        self._check_market(market)
        return float(self.client.get_ticker(symbol))

    def market_info(self, market: str, symbols: List[str]) -> Dict[str, dict]:
        """공개 API(키 불필요) — 24시간 거래대금(acc_trade_price_24h)과 경보 여부(마켓 목록 market_warning · 경보제 조회).
        마켓 목록에 없는 종목은 빠진다."""
        self._check_market(market)
        mod = _client_module()
        syms = list(symbols)
        if not syms:
            return {}
        mk = mod._request("GET", mod.BASE_URL + "/v1/market/all", params={"isDetails": "true"}, timeout=10)
        mk.raise_for_status()
        warn = {m["market"]: m.get("market_warning", "NONE") not in ("NONE", None, "") for m in mk.json()}
        try:                                            # 경보제(가격 급등락 등) 중인 코인도 유의로 본다
            wr = mod._request("GET", mod.BASE_URL + "/v1/market/virtual_asset_warning", timeout=10)
            wr.raise_for_status()
            for w in wr.json():
                warn[w.get("market")] = True
        except Exception:                               # noqa: BLE001 — 경보제 조회가 실패하면 마켓 목록의 표시만으로
            pass
        tk = mod._request("GET", mod.BASE_URL + "/v1/ticker", params={"markets": ",".join(syms)}, timeout=10)
        tk.raise_for_status()
        return {t["market"]: {"value24h": _f(t.get("acc_trade_price_24h")), "warning": bool(warn.get(t["market"], True))}
                for t in tk.json() if t["market"] in warn}

    def order_request(self, intent: Intent) -> dict:
        """보낼 주문 본문(서명 전). dry-run 리포트와 실제 주문이 같은 함수로 만든다."""
        if intent.market != MARKET or intent.order_type != "market":
            raise ValueError("빗썸은 BITHUMB 시장가 주문만")
        if intent.side == "BUY":
            krw = int(math.floor(float(intent.qty) * self.quote(intent.symbol, MARKET)))
            req = {"market": intent.symbol, "side": "bid", "order_type": "price", "price": str(krw)}
        else:
            req = {"market": intent.symbol, "side": "ask", "order_type": "market", "volume": _vol(float(intent.qty))}
        if intent.client_id:
            if not _CID.match(intent.client_id):
                raise ValueError(f"client_order_id 는 영문·숫자·-·_ 1~36자: {intent.client_id!r}")
            req["client_order_id"] = intent.client_id
        return req

    def _exists(self, client_order_id: str) -> bool:
        """같은 client_order_id 의 주문이 이미 있나(중복 전송 방지) — 조회 실패(없음·오류)는 '없음'으로 읽고 보낸다."""
        try:
            d = self.client.get_order_v1(client_order_id=client_order_id)
        except Exception:                               # noqa: BLE001
            return False
        return bool(isinstance(d, dict) and (d.get("uuid") or d.get("order_id")))

    def place(self, intent: Intent, dry_run: bool = True) -> dict:
        req = self.order_request(intent)
        if dry_run:
            return {"dryRun": True, **req}
        if not self.orders_enabled:
            raise RuntimeError("주문 잠금 상태(--execute 가 아닌 실행) — 빗썸 주문을 보내지 않는다")
        cid = req.get("client_order_id")
        if cid and self._exists(cid):
            raise RuntimeError(f"같은 client_order_id({cid}) 주문이 이미 있다 — 중복 전송을 막았다")
        resp = self.client.place_order(req["market"], req["side"], req["order_type"], volume=req.get("volume"),
                                       price=req.get("price"), client_order_id=cid)
        return {"dryRun": False, "orderNo": resp.get("order_id") or resp.get("uuid"), "symbol": intent.symbol,
                "side": intent.side, "qty": intent.qty, "price": None, "market": MARKET}

    def cancel(self, order: OpenOrder, dry_run: bool = True) -> dict:
        if dry_run:
            return {"dryRun": True, "orderNo": order.order_no}
        if not self.orders_enabled:
            raise RuntimeError("주문 잠금 상태 — 취소를 보내지 않는다")
        self.client.cancel_order(order.order_no)
        return {"dryRun": False, "orderNo": order.order_no}

    def order_fill(self, order_no: str, market: str) -> dict:
        self._check_market(market)
        d = self.client.get_order_v1(uuid=order_no)
        return {"qty": _f(d.get("executed_volume")), "price": _avg(d), "fee": _f(d.get("paid_fee")), "state": d.get("state", "")}

    def probe(self, symbol: str = "KRW-BTC", krw: int = 5_000) -> Dict[str, str]:
        """주문 없이 키·권한·허용 IP 를 확인한다: 잔고(자산조회) · 대기 주문(주문조회). 빗썸에는 주문 생성 테스트가 없다 —
        주문 경로는 소액 실검증(설계 §3 P2)으로 사용자가 확인한다."""
        out: Dict[str, str] = {}
        for label, fn in (("자산조회", lambda: self.client.get_accounts()),
                          ("주문조회", lambda: self.client.get_pending_orders())):
            try:
                fn()
                out[label] = "ok"
            except Exception as e:                      # noqa: BLE001
                out[label] = f"실패: {type(e).__name__}: {str(e)[:120]}"
        out["주문하기(테스트)"] = "해당 없음 — 빗썸은 주문 테스트가 없다: 소액 실검증 주문은 사용자가 직접(설계 §3 P2)"
        return out


def make_broker(cfg: dict, env: Dict[str, str], execute: bool, client=None) -> BithumbBroker:
    """프로필의 key_prefix 로 주문 전용 키를 골라 브로커를 만든다. 주문 잠금 해제는 --execute 일 때만."""
    if client is None:
        ak, sk = key_names(cfg)
        client = _client_module().BithumbClient(env[ak], env[sk])
    return BithumbBroker(client, orders_enabled=execute)
