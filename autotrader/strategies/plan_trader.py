"""직접매매 계획 카드 실행 — 웹에서 적은 계획(진입 구간·손절·목표)대로 **모의투자 계좌에서** 사고판다.

설계: docs/control/직접매매-계획카드-설계-2026-09-27.md §10. 상태 전이는 autotrader/plans.py 의 step().

★ 모의투자 전용이다. 실계좌(mode=live)면 주문 없이 오류로 끝난다 — 실계좌 전환은 별도 결정(코드 변경 + 사용자 GO).
★ 국내(KR)만. 주문은 시장가(진입·손절·목표 모두) — 체결이 확실한 대신 5분 점검 간격만큼 늦고, 갭은 못 막는다.
   ponytail: 서버 쪽 스톱 주문이 없어서 5분 폴링으로 흉내 낸다. 스톱 체결가가 계획보다 얼마나 밀리는지를 모의에서 잰 뒤 판단.
★ 장중(09:05~15:15 KST)에만 움직인다. 예약은 프로필 run_at 에 "09:05-15:15/5" 처럼 둔다.

params(프로필 파일):
    capital   자본(원) — 1회 손실 한도(riskPct)로 수량을 계산하는 기준. 없으면 웹이 계획을 안 받는다.
"""
from __future__ import annotations

from datetime import time as dtime
from typing import List

from autotrader.models import Intent
from autotrader.plans import load_plans, reason_tag, step
from autotrader.strategy import Context, Strategy

OPEN, CLOSE = dtime(9, 5), dtime(15, 15)


class PlanTrader(Strategy):
    name = "plan_trader"
    markets = ["KR"]

    def decide(self, ctx: Context) -> List[Intent]:
        if ctx.mode != "paper":
            raise RuntimeError("plan_trader 는 모의투자 전용이다 — 실계좌 전환은 별도 결정")
        if not (OPEN <= ctx.now.time() < CLOSE):
            return []
        today = ctx.now.strftime("%Y-%m-%d")
        st = ctx.state.setdefault("plans", {})
        pos = ctx.positions("KR")
        out: List[Intent] = []
        for p in load_plans(ctx.state_dir):
            if p.get("market", "KR") != "KR":
                continue
            s = st.setdefault(p["id"], {"status": "wait"})
            if s["status"] in ("done", "expired", "cancelled"):
                continue
            try:
                last = ctx.quote(p["symbol"], "KR")
            except Exception:                           # noqa: BLE001 — 시세를 모르면 그 계획은 이번에 건너뛴다
                continue
            if last <= 0:
                continue
            held = pos[p["symbol"]].qty if p["symbol"] in pos else 0
            act = step(p, s, held, last, today)
            if act:
                side, qty, why = act
                out.append(Intent(p["symbol"], side, qty, market="KR", order_type="market",
                                  reason=reason_tag(p["id"], why)))
        return out


STRATEGY = PlanTrader
