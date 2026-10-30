"""코인베이스 프리미엄 C24 — 업비트 KRW-BTC 실계좌(설계 docs/control/코인베이스프리미엄-실계좌연결-설계-2026-10-30.md).

규칙은 모의 슬리브와 같다(사전등록 4f6eace): z ≥ +2 이면 시장가 매수, 신호 +24시간 뒤 첫 실행에서 시장가 매도,
사건 뒤 24시간 차단(방향 무관), 숏 사건은 차단만, 신호 +30분 넘게 늦으면 진입 안 함(청산은 늦어도 한다).
신호 계산은 research/strategy-lab/run_coinbase_premium_paper.py 의 함수를 **그대로 불러 쓴다**(복사하지 않는다) —
모의와 실계좌가 같은 사건을 본다. 다른 것은 크기(params.notional_krw)뿐이다.

★ 판정 정본은 모의 원장(cbprem-paper/trades.jsonl)이다. 이 전략의 기록(state 의 trades)은 실제 체결 비용을 재는 기록이다.
★ 포지션은 **체결이 확인된 뒤에만** 생긴다: 매수 주문의 원장 행(clientId)을 다음 실행에서 찾아 업비트 체결량을 읽는다.
   dry-run·위험 검사 거부로 주문이 안 나갔으면 원장 행이 없으니 포지션도 없다.
★ 매도는 이 전략이 산 체결 수량까지만 — 계좌에 따로 가진 같은 코인은 건드리지 않는다.

params: notional_krw(필수, 1회 매수 원 금액) · symbol(기본 KRW-BTC)
"""
from __future__ import annotations

import importlib.util
import math
from datetime import timedelta
from typing import List

from ..config import REPO_ROOT
from ..engine import Ledger
from ..models import Intent
from ..strategy import Strategy

PAPER = REPO_ROOT / "research" / "strategy-lab" / "run_coinbase_premium_paper.py"
TAG = "cbprem"
MIN_ORDER_KRW = 5_000
OVERDUE_H = 26                      # 신호 + 이 시간이 지나도 보유 중이면 알린다(정상은 24시간 뒤 첫 실행에서 매도)
_mod = None


def paper():
    """모의 러너 모듈(신호 함수의 정본). 한 번만 읽는다."""
    global _mod
    if _mod is None:
        spec = importlib.util.spec_from_file_location("cbprem_paper_rules", PAPER)
        _mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_mod)
    return _mod


def _fetch(P, T):
    return P.fetch_coinbase(T), P.fetch_binance(T)


def _floor8(q: float) -> float:
    return math.floor(q * 1e8) / 1e8


class CoinbasePremium(Strategy):
    name = "coinbase_premium"
    markets = ["UPBIT"]
    fetcher = staticmethod(_fetch)            # 회귀가 갈아끼운다(네트워크 없이)

    def decide(self, ctx) -> List[Intent]:
        import pandas as pd
        P = paper()
        notional = float(ctx.params.get("notional_krw") or 0)
        if notional < MIN_ORDER_KRW:
            raise ValueError(f"params.notional_krw 가 필요하다(≥ {MIN_ORDER_KRW:,}원)")
        sym = ctx.params.get("symbol", "KRW-BTC")
        st = ctx.state
        now = pd.Timestamp(ctx.now)
        if now.tzinfo is None:
            raise ValueError("ctx.now 에 시간대가 없다")
        T = now.tz_convert("UTC").floor("h")              # 모의 러너와 같은 UTC 격자(z 계산이 UTC 인덱스)
        kst = lambda t: pd.Timestamp(t).tz_convert("Asia/Seoul")   # noqa: E731 — 사람이 읽는 문구·주문 식별자는 KST
        delay = (now - T).total_seconds() / 60
        log: List[str] = []
        out: List[Intent] = []

        # 0) 지난 실행이 낸 주문의 결과 — 원장(clientId)과 업비트 체결량으로 확인
        ours = {r["clientId"]: r for r in Ledger(ctx.state_dir).rows()
                if r.get("kind") == "order" and r.get("executed") and r.get("clientId")}
        pb = st.get("pendingBuy")
        if pb:
            r = ours.get(pb["clientId"])
            if r is None:
                log.append(f"매수 {pb['clientId']} 주문 기록 없음(dry-run 또는 거부) — 포지션 없음")
                st["pendingBuy"] = None
            else:
                f = ctx.order_fill(r["orderNo"], "UPBIT")
                if f["state"] in ("wait", "watch"):
                    log.append(f"매수 {r['orderNo']} 아직 체결 대기 — 다음 실행에 다시 본다")
                elif f["qty"] > 0:
                    st["position"] = {"signalT": pb["signalT"], "z": pb["z"], "qty": f["qty"], "entryAvg": f["price"],
                                      "entryFee": f["fee"], "orderNo": r["orderNo"], "entryAt": r["ts"]}
                    st["pendingBuy"] = None
                    log.append(f"매수 체결 {f['qty']:.8f} @ {f['price']:,.0f}")
                else:
                    ctx.notes.append(f"코인베이스 프리미엄: 매수 주문 {r['orderNo']} 체결 0 — 포지션 없음")
                    st["pendingBuy"] = None
        ps = st.get("pendingSell")
        pos = st.get("position")
        if ps and pos:
            r = ours.get(ps["clientId"])
            if r is None:
                log.append(f"매도 {ps['clientId']} 주문 기록 없음 — 이번 실행에 다시 낸다")
                st["pendingSell"] = None
            else:
                f = ctx.order_fill(r["orderNo"], "UPBIT")
                if f["state"] in ("wait", "watch"):
                    log.append(f"매도 {r['orderNo']} 아직 체결 대기")
                else:
                    gross = (f["price"] / pos["entryAvg"] - 1) * 1e4 if f["qty"] > 0 and pos["entryAvg"] else None
                    st.setdefault("trades", []).append({**pos, "exitOrderNo": r["orderNo"], "exitAt": r["ts"],
                                                        "exitQty": f["qty"], "exitAvg": f["price"], "exitFee": f["fee"],
                                                        "grossBp": None if gross is None else round(gross, 2)})
                    st["trades"] = st["trades"][-500:]
                    left = pos["qty"] - f["qty"]
                    st["pendingSell"] = None
                    if left * (f["price"] or 1) >= MIN_ORDER_KRW:            # 일부만 팔렸으면 남은 수량을 다음에 판다
                        st["position"] = {**pos, "qty": _floor8(left)}
                        ctx.notes.append(f"코인베이스 프리미엄: 매도 일부 체결 — 남은 {left:.8f} 다시 매도")
                    else:
                        st["position"] = None
                        log.append(f"청산 체결 {f['qty']:.8f} @ {f['price']:,.0f}"
                                   + ("" if gross is None else f" ({gross:+.1f}bp, 수수료 전)"))
        pos = st.get("position")

        # 1) 신호
        cb, bn = self.fetcher(P, T)
        z, p = P.premium_z(cb, bn["close"], T)
        last = pd.Timestamp(st["lastScanned"]) if st.get("lastScanned") else None
        first_run = last is None
        start = z.first_valid_index() if first_run else last + P.H
        blocked = pd.Timestamp(st["blockedUntil"]) if st.get("blockedUntil") else None
        events, blocked = P.scan_events(z, start, blocked) if start is not None else ([], blocked)

        # 2) 청산 — 신호 + 24h 이후 첫 실행. 이 전략이 산 수량까지만(계좌에 그만큼 없으면 있는 만큼)
        if pos and not st.get("pendingSell") and T >= pd.Timestamp(pos["signalT"]) + P.HOLD:
            held = ctx.positions("UPBIT").get(sym)
            qty = _floor8(min(pos["qty"], held.qty if held else 0.0))
            if qty <= 0:
                ctx.notes.append(f"코인베이스 프리미엄: 청산할 {sym} 이 계좌에 없다(기록 {pos['qty']:.8f}) — 수동 확인 필요")
            else:
                n = int(st.get("sellAttempts", 0)) + 1
                st["sellAttempts"] = n
                cid = f"{TAG}-{kst(pos['signalT']):%Y%m%d%H}-sell-{n}"
                out.append(Intent(sym, "SELL", qty, market="UPBIT", order_type="market", client_id=cid,
                                  reason=f"{TAG} 청산(신호 {kst(pos['signalT']):%m-%d %H}시 KST +24h)"))
                st["pendingSell"] = {"clientId": cid, "signalT": pos["signalT"]}
            if T >= pd.Timestamp(pos["signalT"]) + timedelta(hours=OVERDUE_H):
                ctx.notes.append(f"코인베이스 프리미엄: 청산 지연 — 신호 {kst(pos['signalT']):%m-%d %H}시 KST 뒤 {OVERDUE_H}시간 넘게 보유 중")

        # 3) 사건 — 모의 러너와 같은 분기
        for t, v in events:
            kind = "LONG" if v > 0 else "SHORT"
            if first_run and t < T:
                log.append(f"초기 차단 {kst(t):%m-%d %H}시 {kind}")
            elif t < T:
                log.append(f"놓침 {kst(t):%m-%d %H}시 {kind} z={v:+.2f}(차단만)")
            elif kind == "SHORT":
                log.append(f"숏 사건 z={v:+.2f}(거래 안 함, 24h 차단)")
            elif delay > P.MAX_ENTRY_DELAY_MIN:
                log.append(f"롱 사건 z={v:+.2f} — 지연 {delay:.0f}분, 진입 안 함")
                ctx.notes.append(f"코인베이스 프리미엄: 롱 신호 z={v:+.2f} — 실행이 {delay:.0f}분 늦어 매수 안 함")
            elif st.get("position") or st.get("pendingBuy"):
                log.append("롱 사건 — 보유·대기 중, 진입 안 함")
            else:
                px = ctx.quote(sym, "UPBIT")
                cid = f"{TAG}-{kst(t):%Y%m%d%H}-buy"
                out.append(Intent(sym, "BUY", _floor8(notional / px), market="UPBIT", order_type="market",
                                  client_id=cid, reason=f"{TAG} 롱 신호 z={v:+.2f} ({kst(t):%m-%d %H}시 KST)"))
                st["pendingBuy"] = {"clientId": cid, "signalT": str(t), "z": round(float(v), 3)}
                log.append(f"매수 신호 z={v:+.2f} {notional:,.0f}원")

        done = T if not pd.isna(p.get(T)) else T - P.H   # 코인베이스 봉이 늦으면 T 를 다음 실행이 다시 본다
        st["lastScanned"] = str(done)
        st["blockedUntil"] = str(blocked) if blocked is not None else None
        zt = z.get(T)
        st.setdefault("log", []).append({"T": str(T), "z": None if pd.isna(zt) else round(float(zt), 3),
                                         "delayMin": round(delay, 1), "actions": log})
        st["log"] = st["log"][-200:]
        return out


STRATEGY = CoinbasePremium
