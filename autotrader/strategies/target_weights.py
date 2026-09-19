"""예시 전략 — 목표 비중 리밸런싱. **수익을 주장하지 않는다**(플러그인 구조를 보여주는 예시일 뿐).

사용자가 정한 목표 비중 파일(JSON)에 맞춰, 비중이 허용 밴드를 벗어난 종목만 사고판다.

params(설정 파일):
    targets_file     목표 비중 JSON 경로(저장소 루트 기준 또는 절대경로). 예: {"KR": {"005930": 0.4}}
    band_pct         목표 대비 허용 오차(기본 2.0 = 포트폴리오 가치의 2%p 이내면 건드리지 않음)
    kr_order_type    "market"(기본) | "limit"
    us_order_type    "limit"(기본, 모의는 지정가만)
    limit_offset_bps 지정가를 시세에서 얼마나 공격적으로 잡을지(기본 10bp: 매수는 위, 매도는 아래)

기준 가치 = 주문가능 현금 + **목표에 적힌 종목의** 보유 평가금액. 목표에 없는 보유 종목은 건드리지 않는다.
비중의 합이 1 을 넘으면 실행하지 않는다. 매수는 현재 주문가능 현금 안에서만(매도 대금은 다음 실행에 반영).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List

from autotrader.config import REPO_ROOT
from autotrader.models import Intent
from autotrader.strategy import Context, Strategy


def load_targets(path) -> Dict[str, Dict[str, float]]:
    p = Path(path)
    p = p if p.is_absolute() else REPO_ROOT / p
    t = json.loads(p.read_text(encoding="utf-8"))
    for m, w in t.items():
        if m not in ("KR", "US"):
            raise ValueError(f"목표 비중 파일의 시장은 KR|US: {m}")
        if any((not isinstance(v, (int, float))) or v < 0 for v in w.values()):
            raise ValueError(f"비중은 0 이상의 숫자: {m}")
        if sum(w.values()) > 1.0 + 1e-9:
            raise ValueError(f"{m} 비중의 합이 1 을 넘는다: {sum(w.values()):.3f}")
    return t


class TargetWeights(Strategy):
    name = "target_weights"
    markets = ["KR", "US"]

    def decide(self, ctx: Context) -> List[Intent]:
        pr = ctx.params
        targets = load_targets(pr["targets_file"])
        band = float(pr.get("band_pct", 2.0))
        off = float(pr.get("limit_offset_bps", 10.0)) / 1e4
        out: List[Intent] = []
        for market, weights in targets.items():
            if market not in self.markets or not weights:
                continue
            pos = ctx.positions(market)
            ref = next(iter(weights)) if market == "US" else None
            cash = ctx.cash(market, ref)
            prices = {s: ctx.quote(s, market) for s in weights}
            held = {s: (pos[s].qty if s in pos else 0) for s in weights}
            base = cash + sum(held[s] * prices[s] for s in weights)
            if base <= 0:
                continue
            otype = pr.get("kr_order_type", "market") if market == "KR" else pr.get("us_order_type", "limit")
            sells, buys = [], []
            for s, w in weights.items():
                px = prices[s]
                diff = w * base - held[s] * px
                if abs(diff) / base * 100 < band:
                    continue
                qty = int(math.floor(abs(diff) / px))
                if qty <= 0:
                    continue
                side = "SELL" if diff < 0 else "BUY"
                qty = min(qty, held[s]) if side == "SELL" else qty
                if qty <= 0:
                    continue
                limit = None
                if otype == "limit":
                    limit = round(px * (1 - off if side == "SELL" else 1 + off), 2)
                (sells if side == "SELL" else buys).append((s, side, qty, px, limit))
            budget = cash
            for s, side, qty, px, limit in sells:
                out.append(Intent(s, side, qty, market=market, order_type=otype, limit_price=limit,
                                  reason=f"목표비중 {weights[s]:.1%} 초과분 정리"))
            for s, side, qty, px, limit in buys:
                unit = limit if limit else px
                qty = min(qty, int(budget // unit))
                if qty <= 0:
                    continue
                budget -= qty * unit
                out.append(Intent(s, side, qty, market=market, order_type=otype, limit_price=limit,
                                  reason=f"목표비중 {weights[s]:.1%} 미달분 매수"))
        return out


STRATEGY = TargetWeights
