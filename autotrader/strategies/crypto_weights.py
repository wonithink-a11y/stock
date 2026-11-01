"""크립토 목표 비중 — 업비트 여러 코인을 정한 비중으로 들고 가고, 어긋나면 되맞춘다
(설계 docs/control/크립토-목표비중-전략-설계-2026-11-01.md). **신호가 없고 수익을 주장하지 않는다.**

★ 이 전략이 **직접 체결한 수량만** 센다 — 계좌에 따로 가진 같은 코인은 보지도 팔지도 않는다(`coinbase_premium` 과 같은 방식).
   주문의 원장 행(clientId)을 다음 실행에서 찾아 업비트 체결량을 읽은 뒤에만 보유·현금이 바뀐다.
   dry-run·위험 검사 거부로 주문이 안 나갔으면 원장 행이 없으니 보유도 안 변한다(계획만 기록에 남는다).
★ 비중은 `capital_krw`(이 전략이 쓰는 자본) 기준이다. 계좌 전체 원화가 아니다.

params(프로필):
    weights          {"KRW-BTC": 0.5, "KRW-ETH": 0.3, "KRW-XRP": 0.2} — 합 ≤ 1(나머지는 원화로 둔다)
    capital_krw      이 전략의 자본(원, ≥ 5,000)
    band_pct         목표 대비 허용 오차(%p, 기본 5.0) — 안쪽이면 건드리지 않는다
    max_order_krw    한 주문의 최대 금액(원, 기본 capital_krw 의 20%) — 처음 진입을 며칠에 나눠 들어간다
허용 종목·한도·킬 스위치는 엔진이 강제한다(프로필 symbol_allowlist 에 weights 의 코인이 모두 있어야 주문이 나간다).
"""
from __future__ import annotations

import math
import re
from typing import Dict, List

from ..engine import Ledger
from ..models import Intent
from ..strategy import Strategy

TAG = "cw"
MIN_ORDER_KRW = 5_000
_SYM = re.compile(r"^KRW-[A-Z0-9]{2,10}$")


def _floor8(q: float) -> float:
    return math.floor(q * 1e8) / 1e8


def parse_params(pr: dict) -> dict:
    """설정 검사 — 틀리면 ValueError(엔진이 '전략 오류'로 멈추고 주문은 안 낸다)."""
    w = pr.get("weights")
    if not isinstance(w, dict) or not w:
        raise ValueError("params.weights 가 필요하다 — 예 {\"KRW-BTC\": 0.5}")
    for s, v in w.items():
        if not _SYM.match(str(s)):
            raise ValueError(f"weights 의 종목은 KRW-XXX 형식: {s!r}")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
            raise ValueError(f"weights 의 비중은 0 초과 1 이하 숫자: {s}={v!r}")
    if sum(w.values()) > 1.0 + 1e-9:
        raise ValueError(f"weights 의 합이 1 을 넘는다: {sum(w.values()):.3f}")
    cap = pr.get("capital_krw")
    if isinstance(cap, bool) or not isinstance(cap, (int, float)) or cap < MIN_ORDER_KRW:
        raise ValueError(f"params.capital_krw 가 필요하다(≥ {MIN_ORDER_KRW:,}원)")
    band = float(pr.get("band_pct", 5.0))
    if band < 0:
        raise ValueError("band_pct 는 0 이상")
    mo = float(pr.get("max_order_krw", cap * 0.2))
    if mo < MIN_ORDER_KRW:
        raise ValueError(f"max_order_krw 는 {MIN_ORDER_KRW:,}원 이상")
    return {"weights": {str(s): float(v) for s, v in w.items()}, "capital": float(cap), "band": band, "max_order": mo}


class CryptoWeights(Strategy):
    name = "crypto_weights"
    markets = ["UPBIT"]

    def decide(self, ctx) -> List[Intent]:
        p = parse_params(ctx.params)
        weights, st = p["weights"], ctx.state
        log: List[str] = []
        out: List[Intent] = []

        # 0) 자본 — 처음엔 capital_krw, 나중에 값을 바꾸면 차액만큼 현금이 늘고 준다
        if "cash" not in st:
            st["cash"], st["capital"], st["holdings"] = p["capital"], p["capital"], {}
        elif abs(p["capital"] - st.get("capital", p["capital"])) > 1e-9:
            st["cash"] += p["capital"] - st["capital"]
            log.append(f"자본 {st['capital']:,.0f} → {p['capital']:,.0f}원")
            st["capital"] = p["capital"]
        holdings: Dict[str, float] = st.setdefault("holdings", {})
        pending: Dict[str, dict] = st.setdefault("pending", {})

        # 1) 지난 실행이 낸 주문의 결과 — 원장(clientId)과 업비트 체결량으로 확인
        ours = {r["clientId"]: r for r in Ledger(ctx.state_dir).rows()
                if r.get("kind") == "order" and r.get("executed") and r.get("clientId")}
        for cid, pd_ in list(pending.items()):
            r = ours.get(cid)
            if r is None:
                log.append(f"{cid} 주문 기록 없음(dry-run 또는 거부) — 변화 없음")
                pending.pop(cid)
                continue
            f = ctx.order_fill(r["orderNo"], "UPBIT")
            if f["state"] in ("wait", "watch"):
                log.append(f"{cid} 아직 체결 대기 — 다음 실행에 다시 본다")
                continue
            sym, q, px, fee = pd_["symbol"], float(f["qty"]), float(f["price"] or 0), float(f.get("fee") or 0)
            if q > 0:
                if pd_["side"] == "BUY":
                    holdings[sym] = _floor8(holdings.get(sym, 0.0) + q)
                    st["cash"] -= q * px + fee
                else:
                    holdings[sym] = _floor8(max(0.0, holdings.get(sym, 0.0) - q))
                    st["cash"] += q * px - fee
                log.append(f"{cid} 체결 {q:.8f} @ {px:,.0f}")
            else:
                ctx.notes.append(f"크립토 목표 비중: 주문 {r['orderNo']} 체결 0 — 변화 없음")
            pending.pop(cid)

        # 2) 아직 결과를 못 본 주문이 있으면 이번엔 새 주문을 내지 않는다(겹침 방지)
        if pending:
            log.append("대기 주문 있음 — 이번 실행은 새 주문 없음")
            return self._finish(st, ctx, log, out)

        # 3) 목표와 비교
        prices = {s: ctx.quote(s, "UPBIT") for s in weights}
        base = st["cash"] + sum(holdings.get(s, 0.0) * prices[s] for s in weights)
        if base <= 0:
            return self._finish(st, ctx, log, out)
        acct = ctx.positions("UPBIT")
        acct_cash = ctx.cash("UPBIT")
        sells, buys = [], []
        for s, w in weights.items():
            px, held = prices[s], holdings.get(s, 0.0)
            diff = w * base - held * px
            if abs(diff) / base * 100 < p["band"]:
                continue
            amount = min(abs(diff), p["max_order"])
            if diff < 0:                                              # 초과 → 자기 수량까지만, 계좌에 그만큼 없으면 있는 만큼
                have = acct.get(s).qty if acct.get(s) else 0.0
                qty = _floor8(min(amount / px, held, have))
                if held > have + 1e-12:
                    ctx.notes.append(f"크립토 목표 비중: 기록 {s} {held:.8f} 이 계좌 {have:.8f} 보다 많다 — 수동 확인 필요")
                if qty * px >= MIN_ORDER_KRW:
                    sells.append((s, qty, px, w))
            else:
                buys.append((s, amount, px, w, diff))
        for s, qty, px, w in sells:
            cid = f"{TAG}-{ctx.now:%Y%m%d%H}-{s[4:]}-sell"
            out.append(Intent(s, "SELL", qty, market="UPBIT", order_type="market", client_id=cid,
                              reason=f"목표 {w:.0%} 초과분 정리"))
            pending[cid] = {"symbol": s, "side": "SELL"}
            log.append(f"매도 {s} {qty:.8f} (≈{qty * px:,.0f}원)")
        budget = min(st["cash"], acct_cash)                           # 팔아서 생길 현금은 다음 실행에 쓴다
        for s, amount, px, w, diff in sorted(buys, key=lambda x: -x[4]):
            krw = math.floor(min(amount, budget))
            if krw < MIN_ORDER_KRW:
                continue
            budget -= krw
            cid = f"{TAG}-{ctx.now:%Y%m%d%H}-{s[4:]}-buy"
            out.append(Intent(s, "BUY", krw / px, market="UPBIT", order_type="market", client_id=cid,
                              reason=f"목표 {w:.0%} 미달분 매수"))
            pending[cid] = {"symbol": s, "side": "BUY"}
            log.append(f"매수 {s} {krw:,.0f}원")
        return self._finish(st, ctx, log, out)

    @staticmethod
    def _finish(st, ctx, log, out):
        st.setdefault("log", []).append({"at": ctx.now.isoformat(), "cash": round(st["cash"]), "holdings": dict(st["holdings"]),
                                         "actions": log})
        st["log"] = st["log"][-200:]
        return out


STRATEGY = CryptoWeights
